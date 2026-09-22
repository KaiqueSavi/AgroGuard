"""
AgroGuard IA — Treino e Validação dos Modelos Preditivos (Sprint 3-4 / v0.3)
==============================================================================

Treina e avalia os modelos supervisionados do AgroGuard IA a partir do dataset
simulado (agora passado pelo pipeline de preparação de dados, `ml/preparacao.py`)
e produz todos os artefatos de validação estatística da Sprint 4.

Mudanças em relação à v0.2 (ver `docs/model-card.md` §"v0.3" para a justificativa
completa):
  1. Preparação de dados (duplicidades, faltantes, fora-de-faixa) ANTES do split.
  2. Regressor de score: busca em grade na VALIDAÇÃO (não mais parâmetros
     default), seleção por MAE, avaliação única no teste.
  3. Classe de risco: derivada do score previsto (faixas de negócio) em vez de
     um classificador direto — compara as duas abordagens lado a lado
     (`comparacao_classe`), pois a classe "Critico" é rara demais (43/10.000)
     para um classificador direto aprender bem.
  4. Validação cruzada corrigida: 5 folds em TREINO+VALIDAÇÃO (a v0.2 rodava,
     por engano, a CV só no split de teste de 1.500 linhas).
  5. Análise do limiar de alerta (score >= 80): precision/recall/F1 contra o
     score real e contra a classe Crítico real, e tabela de limiares
     alternativos para justificar a escolha de 80.

  Modelos:
    1. Regressor de score        → alvo `risco_score` (0-100)  [GradientBoosting, grid em val]
    2. Classe de risco           → faixas do score previsto (principal, v0.3)
                                    + classificador direto (mantido p/ comparação e compat., clf_classe.joblib)
    3. Classificador de sinistro → alvo `sinistro` (0/1)  [RandomForest balanced, análise complementar]

  Saídas:
    ml/models/reg_score.joblib, clf_classe.joblib, clf_sinistro.joblib,
    ml/models/baseline_features.json, ml/models/model_meta.json
    reports/figures/*.png   (matriz de confusão, importâncias, heatmap, dispersão)
    reports/metrics.json    (todas as métricas, consumidas pelo relatório/model card)
    reports/data_quality.json (relatório da preparação de dados)

Uso:
    python -m ml.train [--csv data/synthetic_dataset.csv] [--seed 42] [--rapido]

Sem vazamento de rótulo: ver ml/features.py (alvos e derivadas fora de X).
"""
from __future__ import annotations

import argparse
import itertools
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")  # backend headless (sem display)
import matplotlib.pyplot as plt
import seaborn as sns
import joblib

from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.pipeline import Pipeline
from sklearn.ensemble import (
    RandomForestClassifier,
    GradientBoostingClassifier,
    GradientBoostingRegressor,
)
from sklearn.model_selection import train_test_split, cross_val_score, StratifiedKFold, KFold
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    recall_score,
    precision_score,
    classification_report,
    confusion_matrix,
    ConfusionMatrixDisplay,
    mean_squared_error,
    mean_absolute_error,
    r2_score,
    roc_auc_score,
    roc_curve,
)

from ml.features import (
    NUMERIC_FEATURES,
    CATEGORICAL_FEATURES,
    FEATURE_COLUMNS,
    TARGET_CLASSE,
    TARGET_SCORE,
    TARGET_SINISTRO,
    CLASSES_ORDER,
    MODEL_VERSION,
)
from ml.preparacao import preparar
from ml.inferencia import classe_por_score
from ml.explicabilidade import baseline_de_treino

# ---------------------------------------------------------------------------
# Caminhos
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT / "ml" / "models"
FIG_DIR = ROOT / "reports" / "figures"
REPORTS_DIR = ROOT / "reports"
for d in (MODELS_DIR, FIG_DIR):
    d.mkdir(parents=True, exist_ok=True)

sns.set_theme(style="whitegrid")

# Números v0.2 (hardcoded de reports/metrics.json antes desta mudança — usados
# apenas para o bloco `comparacao_v02_v03`; nunca recalculados).
V02_METRICAS = {
    "r2_test": 0.9361,
    "rmse_test": 3.39,
    "mae_test": 2.66,
    "f1_macro_test": 0.6632,
    "recall_critico_test": 0.1667,
}

# Grade de busca do regressor (avaliada na validação, seleção por MAE).
GRID_N_ESTIMATORS = [200, 400]
GRID_LEARNING_RATE = [0.05, 0.1]
GRID_MAX_DEPTH = [2, 3, 4]
GRID_SUBSAMPLE = [0.8, 1.0]

ALERT_LIMIARES = [70, 75, 80, 85]
ALERT_LIMIAR_PRINCIPAL = 80
FAIXA_CRITICA = (70, 90)  # faixa de score real usada para o MAE "faixa crítica"


# ---------------------------------------------------------------------------
# Pré-processamento
# ---------------------------------------------------------------------------
def build_preprocessor() -> ColumnTransformer:
    """OneHot nas categóricas, numéricas passam direto (árvores não exigem escala)."""
    return ColumnTransformer(
        transformers=[
            ("num", "passthrough", NUMERIC_FEATURES),
            (
                "cat",
                OneHotEncoder(handle_unknown="ignore"),
                CATEGORICAL_FEATURES,
            ),
        ]
    )


def get_feature_names(preprocessor: ColumnTransformer) -> list[str]:
    """Nomes das features após o OneHot (para o gráfico de importância)."""
    cat_names = (
        preprocessor.named_transformers_["cat"]
        .get_feature_names_out(CATEGORICAL_FEATURES)
        .tolist()
    )
    return NUMERIC_FEATURES + cat_names


def _score_para_classe(pred_score: np.ndarray) -> list[str]:
    """Aplica a MESMA regra de `ml.inferencia.prever` (clip 0-100, arredonda,
    mapeia pelas faixas) para derivar a classe a partir do score previsto."""
    score_int = np.clip(pred_score, 0, 100).round().astype(int)
    return [classe_por_score(s) for s in score_int]


# ---------------------------------------------------------------------------
# 1) Regressor de score — grid em validação, avaliação única em teste
# ---------------------------------------------------------------------------
def buscar_melhor_regressor(Xtr, y_tr, Xval, y_val, seed, rapido: bool):
    """Varre a grade (ou 1 config, em modo --rapido) treinando em `Xtr`/`y_tr`
    e avaliando MAE em `Xval`/`y_val`. Retorna (melhor_config, grid_resultados)."""
    if rapido:
        melhor_config = {"n_estimators": 100, "learning_rate": 0.1, "max_depth": 3, "subsample": 1.0}
        return melhor_config, [{**melhor_config, "mae_val": None}]

    combinacoes = list(itertools.product(
        GRID_N_ESTIMATORS, GRID_LEARNING_RATE, GRID_MAX_DEPTH, GRID_SUBSAMPLE
    ))
    grid_resultados = []
    melhor_config, melhor_mae = None, float("inf")
    for n_est, lr, depth, sub in combinacoes:
        config = {"n_estimators": n_est, "learning_rate": lr, "max_depth": depth, "subsample": sub}
        pipe = Pipeline([
            ("prep", build_preprocessor()),
            ("model", GradientBoostingRegressor(random_state=seed, **config)),
        ])
        pipe.fit(Xtr, y_tr)
        pred_val = pipe.predict(Xval)
        mae_val = float(mean_absolute_error(y_val, pred_val))
        grid_resultados.append({**config, "mae_val": round(mae_val, 4)})
        print(f"   • n_estimators={n_est:<4} lr={lr:<5} max_depth={depth} subsample={sub}  MAE(val)={mae_val:.4f}")
        if mae_val < melhor_mae:
            melhor_mae, melhor_config = mae_val, config

    print(f"   → Melhor config: {melhor_config}  MAE(val)={melhor_mae:.4f}")
    return melhor_config, grid_resultados


def avaliar_regressor_teste(pipe, Xte, y_te) -> dict:
    pred = pipe.predict(Xte)
    rmse = float(np.sqrt(mean_squared_error(y_te, pred)))
    mae = float(mean_absolute_error(y_te, pred))
    r2 = float(r2_score(y_te, pred))

    lo, hi = FAIXA_CRITICA
    mask_fc = (y_te >= lo) & (y_te <= hi)
    mae_faixa_critica = float(mean_absolute_error(y_te[mask_fc], pred[mask_fc])) if mask_fc.any() else None

    print(f"   RMSE={rmse:.2f}  MAE={mae:.2f}  R²={r2:.4f}  MAE(faixa {lo}-{hi})={mae_faixa_critica}")

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(y_te, pred, alpha=0.25, s=12, color="#1565c0")
    lims = [0, 100]
    ax.plot(lims, lims, "r--", lw=1.5, label="ideal (y=x)")
    ax.set_xlim(lims)
    ax.set_ylim(lims)
    ax.set_xlabel("Score real")
    ax.set_ylabel("Score previsto")
    ax.set_title(f"Regressor de Score v0.3 — previsto vs real\nRMSE={rmse:.2f} · MAE={mae:.2f} · R²={r2:.3f}")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIG_DIR / "regression_pred_vs_real.png", dpi=130)
    plt.close(fig)

    return {
        "rmse_test": round(rmse, 3),
        "mae_test": round(mae, 3),
        "r2_test": round(r2, 4),
        "mae_test_faixa_critica_70_90": round(mae_faixa_critica, 3) if mae_faixa_critica is not None else None,
        "predicoes": pred,
    }


# ---------------------------------------------------------------------------
# 2) Classe de risco — comparação: classificador direto (v0.2) vs faixas do score (v0.3)
# ---------------------------------------------------------------------------
def avaliar_classe(y_real, y_pred, y_score_real) -> dict:
    """Métricas de classificação de `classe_risco`, comuns às duas abordagens
    (classificador direto e regressão+faixas), para permitir comparação justa."""
    y_real = list(y_real)
    y_pred = list(y_pred)
    acc = accuracy_score(y_real, y_pred)
    f1m = f1_score(y_real, y_pred, average="macro", labels=CLASSES_ORDER)
    recall_critico = recall_score(y_real, y_pred, labels=["Critico"], average="macro", zero_division=0)
    precision_critico = precision_score(y_real, y_pred, labels=["Critico"], average="macro", zero_division=0)

    real_alto_critico = (np.asarray(y_score_real) > 60)
    pred_alto_critico = np.isin(np.asarray(y_pred), ["Alto", "Critico"])
    recall_alto_critico = recall_score(real_alto_critico, pred_alto_critico, zero_division=0)

    cm = confusion_matrix(y_real, y_pred, labels=CLASSES_ORDER)
    report = classification_report(y_real, y_pred, labels=CLASSES_ORDER, output_dict=True, zero_division=0)

    return {
        "accuracy": round(float(acc), 4),
        "f1_macro": round(float(f1m), 4),
        "recall_critico": round(float(recall_critico), 4),
        "precision_critico": round(float(precision_critico), 4),
        "recall_alto_critico_score_gt_60": round(float(recall_alto_critico), 4),
        "confusion_matrix": cm.tolist(),
        "confusion_labels": CLASSES_ORDER,
        "classification_report": report,
    }


def plot_confusion(cm: list, labels: list, titulo: str, arquivo: str) -> None:
    fig, ax = plt.subplots(figsize=(6, 5))
    ConfusionMatrixDisplay(np.array(cm), display_labels=labels).plot(
        ax=ax, cmap="Blues", colorbar=False, values_format="d"
    )
    ax.set_title(titulo)
    ax.set_xlabel("Previsto")
    ax.set_ylabel("Real")
    fig.tight_layout()
    fig.savefig(FIG_DIR / arquivo, dpi=130)
    plt.close(fig)


def plot_importancias(pipe, nome: str) -> dict:
    """Top-15 importâncias de feature do regressor de score (motor do produto)."""
    prep = pipe.named_steps["prep"]
    model = pipe.named_steps["model"]
    nomes = get_feature_names(prep)
    importancias = pd.Series(model.feature_importances_, index=nomes).sort_values(ascending=False)
    top = importancias.head(15)[::-1]

    fig, ax = plt.subplots(figsize=(8, 6))
    top.plot(kind="barh", ax=ax, color="#2e7d32")
    ax.set_title(f"Top 15 variáveis mais importantes — {nome}")
    ax.set_xlabel("Importância (Gini / ganho)")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "feature_importance.png", dpi=130)
    plt.close(fig)
    return importancias.round(4).to_dict()


# ---------------------------------------------------------------------------
# 3) Classificador de sinistro (binário, complementar) — inalterado
# ---------------------------------------------------------------------------
def treinar_sinistro(X_tr, y_tr, X_te, y_te, seed):
    clf = RandomForestClassifier(
        n_estimators=300, class_weight="balanced", random_state=seed, n_jobs=-1
    )
    pipe = Pipeline([("prep", build_preprocessor()), ("model", clf)])
    pipe.fit(X_tr, y_tr)
    proba = pipe.predict_proba(X_te)[:, 1]
    pred = pipe.predict(X_te)

    auc = float(roc_auc_score(y_te, proba))
    f1 = float(f1_score(y_te, pred, zero_division=0))
    recall = float(recall_score(y_te, pred, zero_division=0))
    print(f"   AUC={auc:.4f}  F1={f1:.4f}  recall={recall:.4f}")

    fpr, tpr, _ = roc_curve(y_te, proba)
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.plot(fpr, tpr, color="#6a1b9a", lw=2, label=f"AUC = {auc:.3f}")
    ax.plot([0, 1], [0, 1], "k--", lw=1, label="aleatório")
    ax.set_xlabel("Falso Positivo (FPR)")
    ax.set_ylabel("Verdadeiro Positivo (TPR)")
    ax.set_title("Curva ROC — Previsão de Sinistro (0/1)")
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "roc_sinistro.png", dpi=130)
    plt.close(fig)

    return pipe, {"auc_test": round(auc, 4), "f1_test": round(f1, 4), "recall_test": round(recall, 4)}


# ---------------------------------------------------------------------------
# Análise exploratória mínima embutida (correlação + distribuição)
# ---------------------------------------------------------------------------
def plot_correlacoes(df: pd.DataFrame):
    cols = NUMERIC_FEATURES + [TARGET_SCORE]
    corr = df[cols].corr(method="pearson")

    fig, ax = plt.subplots(figsize=(11, 9))
    sns.heatmap(corr, annot=True, fmt=".2f", cmap="RdBu_r", center=0, ax=ax,
                annot_kws={"size": 7}, cbar_kws={"shrink": 0.8})
    ax.set_title("Correlação de Pearson — features × risco_score")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "correlation_heatmap.png", dpi=130)
    plt.close(fig)

    corr_score = corr[TARGET_SCORE].drop(TARGET_SCORE).sort_values(ascending=False)
    return corr_score.round(3).to_dict()


def plot_distribuicao_score(df: pd.DataFrame):
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    sns.histplot(df[TARGET_SCORE], bins=40, kde=True, ax=axes[0], color="#ef6c00")
    axes[0].set_title("Distribuição do risco_score (0-100)")
    axes[0].set_xlabel("risco_score")

    ordem = [c for c in CLASSES_ORDER if c in df[TARGET_CLASSE].unique()]
    sns.countplot(data=df, x=TARGET_CLASSE, order=ordem, ax=axes[1],
                  hue=TARGET_CLASSE, palette="YlOrRd", legend=False)
    axes[1].set_title("Frequência por classe de risco")
    axes[1].set_xlabel("classe_risco")
    for p in axes[1].patches:
        axes[1].annotate(int(p.get_height()), (p.get_x() + p.get_width() / 2, p.get_height()),
                         ha="center", va="bottom", fontsize=9)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "score_distribution.png", dpi=130)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Estimativa estável (validação cruzada em TREINO+VALIDAÇÃO — corrige a v0.2,
# que rodava a CV por engano só no split de teste de 1.500 linhas)
# ---------------------------------------------------------------------------
def cv_regressor_e_classe(X_trainval, y_score_trainval, y_classe_trainval, melhor_config, seed):
    kf = KFold(n_splits=5, shuffle=True, random_state=seed)
    pipe_cv = Pipeline([
        ("prep", build_preprocessor()),
        ("model", GradientBoostingRegressor(random_state=seed, **melhor_config)),
    ])
    neg_rmse = cross_val_score(pipe_cv, X_trainval, y_score_trainval, cv=kf, scoring="neg_root_mean_squared_error")
    rmse_cv_mean = float((-neg_rmse).mean())
    rmse_cv_std = float((-neg_rmse).std())

    # F1-macro da classe DERIVADA do score previsto: treina em 4 folds, prediz
    # o score no 5º fold, converte para classe pelas faixas de negócio.
    Xr = X_trainval.reset_index(drop=True)
    yscore_r = y_score_trainval.reset_index(drop=True)
    yclasse_r = y_classe_trainval.reset_index(drop=True)
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=seed)
    f1_scores = []
    for idx_tr, idx_te in skf.split(Xr, yclasse_r):
        fold_pipe = Pipeline([
            ("prep", build_preprocessor()),
            ("model", GradientBoostingRegressor(random_state=seed, **melhor_config)),
        ])
        fold_pipe.fit(Xr.iloc[idx_tr], yscore_r.iloc[idx_tr])
        pred_fold = fold_pipe.predict(Xr.iloc[idx_te])
        classe_fold = _score_para_classe(pred_fold)
        f1_scores.append(f1_score(yclasse_r.iloc[idx_te], classe_fold, average="macro", labels=CLASSES_ORDER))

    f1_cv_mean = float(np.mean(f1_scores))
    f1_cv_std = float(np.std(f1_scores))
    print(f"   CV(5) RMSE={rmse_cv_mean:.3f}±{rmse_cv_std:.3f}   CV(5) F1-macro(classe derivada)={f1_cv_mean:.4f}±{f1_cv_std:.4f}")
    return rmse_cv_mean, rmse_cv_std, f1_cv_mean, f1_cv_std


# ---------------------------------------------------------------------------
# Análise do limiar de alerta (score >= 80)
# ---------------------------------------------------------------------------
def analisar_alerta(score_pred_int: np.ndarray, y_score_te: pd.Series, y_classe_te: pd.Series, y_sin_te: pd.Series) -> dict:
    y_score_te_np = np.asarray(y_score_te)
    y_sin_te_np = np.asarray(y_sin_te)
    critico_real = (np.asarray(y_classe_te) == "Critico")

    def _metricas(pred_bin, real_bin):
        return {
            "precision": round(float(precision_score(real_bin, pred_bin, zero_division=0)), 4),
            "recall": round(float(recall_score(real_bin, pred_bin, zero_division=0)), 4),
            "f1": round(float(f1_score(real_bin, pred_bin, zero_division=0)), 4),
        }

    pred_bin_principal = score_pred_int >= ALERT_LIMIAR_PRINCIPAL
    real_bin_principal = y_score_te_np >= ALERT_LIMIAR_PRINCIPAL

    acima = y_sin_te_np[pred_bin_principal]
    abaixo = y_sin_te_np[~pred_bin_principal]
    taxa_acima = float(acima.mean() * 100) if len(acima) else None
    taxa_abaixo = float(abaixo.mean() * 100) if len(abaixo) else None

    tabela_limiares = []
    for lim in ALERT_LIMIARES:
        pred_bin = score_pred_int >= lim
        real_bin = y_score_te_np >= lim
        tabela_limiares.append({"limiar": lim, **_metricas(pred_bin, real_bin)})

    return {
        "limiar_escolhido": ALERT_LIMIAR_PRINCIPAL,
        "vs_score_real": _metricas(pred_bin_principal, real_bin_principal),
        "vs_classe_critico_real": _metricas(pred_bin_principal, critico_real),
        "taxa_sinistro_acima_limiar_pct": round(taxa_acima, 2) if taxa_acima is not None else None,
        "taxa_sinistro_abaixo_limiar_pct": round(taxa_abaixo, 2) if taxa_abaixo is not None else None,
        "tabela_limiares_alternativos": tabela_limiares,
    }


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Treina e valida os modelos AgroGuard IA (v0.3)")
    parser.add_argument("--csv", default=str(ROOT / "data" / "synthetic_dataset.csv"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--rapido", action="store_true", help="pula a grade e a CV (uso em testes)")
    args = parser.parse_args()

    print(f"📂 Carregando dataset: {args.csv}")
    df_bruto = pd.read_csv(args.csv)
    print(f"   {len(df_bruto):,} linhas × {len(df_bruto.columns)} colunas")

    print("\n🧹 Preparando dados (duplicidades, faltantes, fora de faixa)...")
    df, relatorio_qualidade = preparar(df_bruto)
    (REPORTS_DIR / "data_quality.json").write_text(
        json.dumps(relatorio_qualidade, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"   linhas: {relatorio_qualidade['linhas_entrada']} → {relatorio_qualidade['linhas_saida']}"
          f"  (rejeitadas={relatorio_qualidade['rejeitadas']},"
          f" dup_exatas={relatorio_qualidade['duplicatas_exatas']},"
          f" dup_chave={relatorio_qualidade['duplicatas_chave']})")

    print("\n📊 Gerando figuras exploratórias (correlação, distribuição)...")
    corr_score = plot_correlacoes(df)
    plot_distribuicao_score(df)

    X = df[FEATURE_COLUMNS].copy()
    y_classe = df[TARGET_CLASSE].astype(str)
    y_score = df[TARGET_SCORE].astype(float)
    y_sin = df[TARGET_SINISTRO].astype(int)

    # --- Split estratificado 70/15/15 por classe de risco ---
    idx = np.arange(len(df))
    idx_tr, idx_tmp = train_test_split(
        idx, test_size=0.30, random_state=args.seed, stratify=y_classe
    )
    idx_val, idx_te = train_test_split(
        idx_tmp, test_size=0.50, random_state=args.seed, stratify=y_classe.iloc[idx_tmp]
    )
    idx_trainval = np.concatenate([idx_tr, idx_val])
    print(f"\n🔀 Split estratificado: treino={len(idx_tr)}  val={len(idx_val)}  teste={len(idx_te)}")

    Xtr, Xval, Xte = X.iloc[idx_tr], X.iloc[idx_val], X.iloc[idx_te]
    X_trainval = X.iloc[idx_trainval]
    y_score_tr, y_score_val, y_score_te = y_score.iloc[idx_tr], y_score.iloc[idx_val], y_score.iloc[idx_te]
    y_score_trainval = y_score.iloc[idx_trainval]
    y_classe_tr, y_classe_te = y_classe.iloc[idx_tr], y_classe.iloc[idx_te]
    y_classe_trainval = y_classe.iloc[idx_trainval]
    y_sin_tr, y_sin_te = y_sin.iloc[idx_tr], y_sin.iloc[idx_te]
    y_sin_trainval = y_sin.iloc[idx_trainval]

    # ===== 1) Regressor de score: grid em validação =====
    print("\n🧠 [1/3] Regressor de score (0-100) — grid em validação")
    melhor_config, grid_resultados = buscar_melhor_regressor(Xtr, y_score_tr, Xval, y_score_val, args.seed, args.rapido)

    reg_pipe = Pipeline([
        ("prep", build_preprocessor()),
        ("model", GradientBoostingRegressor(random_state=args.seed, **melhor_config)),
    ])
    reg_pipe.fit(X_trainval, y_score_trainval)  # refit em treino+val (produção)
    reg_metrics = avaliar_regressor_teste(reg_pipe, Xte, y_score_te)
    score_pred_test = reg_metrics.pop("predicoes")
    score_pred_test_int = np.clip(score_pred_test, 0, 100).round().astype(int)
    joblib.dump(reg_pipe, MODELS_DIR / "reg_score.joblib")
    importancias = plot_importancias(reg_pipe, "Regressor de score v0.3")

    # ===== 2) Classe de risco: direto (v0.2) vs faixas do score (v0.3) =====
    print("\n🧠 [2/3] Classe de risco — classificador direto vs regressão+faixas")
    clf_direto_pipe = Pipeline([("prep", build_preprocessor()), ("model", GradientBoostingClassifier(random_state=args.seed))])
    clf_direto_pipe.fit(Xtr, y_classe_tr)
    pred_classe_direto = clf_direto_pipe.predict(Xte)
    metrics_direto = avaliar_classe(y_classe_te, pred_classe_direto, y_score_te)
    plot_confusion(metrics_direto["confusion_matrix"], CLASSES_ORDER,
                    "Matriz de Confusão — Classe (classificador direto v0.2)", "confusion_matrix_clf_v02.png")

    classe_pred_regfaixas = _score_para_classe(score_pred_test)
    metrics_regfaixas = avaliar_classe(y_classe_te, classe_pred_regfaixas, y_score_te)
    plot_confusion(metrics_regfaixas["confusion_matrix"], CLASSES_ORDER,
                    "Matriz de Confusão — Classe (regressão + faixas v0.3)", "confusion_matrix.png")

    print(f"   classificador_direto_v02:  acc={metrics_direto['accuracy']}  F1-macro={metrics_direto['f1_macro']}  recall_critico={metrics_direto['recall_critico']}")
    print(f"   regressao_faixas_v03:      acc={metrics_regfaixas['accuracy']}  F1-macro={metrics_regfaixas['f1_macro']}  recall_critico={metrics_regfaixas['recall_critico']}")

    # refit do classificador direto em treino+val (mantido só por compatibilidade — clf_classe.joblib)
    clf_direto_pipe.fit(X_trainval, y_classe_trainval)
    joblib.dump(clf_direto_pipe, MODELS_DIR / "clf_classe.joblib")

    # ===== Validação cruzada estável (corrige a CV errada da v0.2) =====
    if not args.rapido:
        print("\n🔁 Validação cruzada (5 folds, treino+validação)...")
        rmse_cv_mean, rmse_cv_std, f1_cv_mean, f1_cv_std = cv_regressor_e_classe(
            X_trainval, y_score_trainval, y_classe_trainval, melhor_config, args.seed
        )
    else:
        rmse_cv_mean = rmse_cv_std = f1_cv_mean = f1_cv_std = None

    # ===== Análise do limiar de alerta =====
    alerta_analise = analisar_alerta(score_pred_test_int, y_score_te, y_classe_te, y_sin_te)
    print(f"\n🚨 Alerta (score>=80): precision={alerta_analise['vs_score_real']['precision']}"
          f" recall={alerta_analise['vs_score_real']['recall']}"
          f" | sinistro acima={alerta_analise['taxa_sinistro_acima_limiar_pct']}%"
          f" abaixo={alerta_analise['taxa_sinistro_abaixo_limiar_pct']}%")

    # ===== 3) Classificador de sinistro (binário, complementar) — inalterado =====
    print("\n🧠 [3/3] Classificador de sinistro (binário, complementar)")
    sin_pipe, sin_metrics = treinar_sinistro(Xtr, y_sin_tr, Xte, y_sin_te, args.seed)
    sin_pipe.fit(X_trainval, y_sin_trainval)
    joblib.dump(sin_pipe, MODELS_DIR / "clf_sinistro.joblib")

    # ===== Baseline de explicabilidade (treino+val) e artefatos =====
    baseline = baseline_de_treino(df.iloc[idx_trainval])
    (MODELS_DIR / "baseline_features.json").write_text(
        json.dumps(baseline, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    resumo_metricas = {
        "regressor_score": {"rmse_test": reg_metrics["rmse_test"], "mae_test": reg_metrics["mae_test"], "r2_test": reg_metrics["r2_test"]},
        "classe_regressao_faixas": {"f1_macro": metrics_regfaixas["f1_macro"], "recall_critico": metrics_regfaixas["recall_critico"]},
        "classe_direto_v02": {"f1_macro": metrics_direto["f1_macro"], "recall_critico": metrics_direto["recall_critico"]},
        "sinistro": sin_metrics,
    }
    model_meta = {
        "modelo_versao": MODEL_VERSION,
        "treinado_em": datetime.now(timezone.utc).isoformat(),
        "seed": args.seed,
        "melhor_config": melhor_config,
        "resumo_metricas": resumo_metricas,
    }
    (MODELS_DIR / "model_meta.json").write_text(
        json.dumps(model_meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # --- Consolida métricas (SEM `treinado_em` — precisa ser byte-idêntico entre runs) ---
    v03_metricas = {
        "r2_test": reg_metrics["r2_test"],
        "rmse_test": reg_metrics["rmse_test"],
        "mae_test": reg_metrics["mae_test"],
        "f1_macro_test": metrics_regfaixas["f1_macro"],
        "recall_critico_test": metrics_regfaixas["recall_critico"],
    }
    comparacao_v02_v03 = {
        "v0.2": V02_METRICAS,
        "v0.3": v03_metricas,
        "delta": {k: round(v03_metricas[k] - V02_METRICAS[k], 4) for k in V02_METRICAS},
    }

    metrics = {
        "modelo_versao": MODEL_VERSION,
        "seed": args.seed,
        "rapido": bool(args.rapido),
        "dataset": {
            "linhas": int(len(df)),
            "treino": int(len(idx_tr)),
            "validacao": int(len(idx_val)),
            "teste": int(len(idx_te)),
            "distribuicao_classe": df[TARGET_CLASSE].value_counts().to_dict(),
            "taxa_sinistro_pct": round(float(y_sin.mean() * 100), 2),
        },
        "qualidade_dados": relatorio_qualidade,
        "regressor_score": {
            "grid_busca": grid_resultados,
            "melhor_config": melhor_config,
            **reg_metrics,
            "cv_rmse_mean": round(rmse_cv_mean, 4) if rmse_cv_mean is not None else None,
            "cv_rmse_std": round(rmse_cv_std, 4) if rmse_cv_std is not None else None,
        },
        "classificador_classe": {
            "comparacao_classe": {
                "classificador_direto_v02": metrics_direto,
                "regressao_faixas_v03": metrics_regfaixas,
            },
            "cv_f1_macro_regressao_faixas_mean": round(f1_cv_mean, 4) if f1_cv_mean is not None else None,
            "cv_f1_macro_regressao_faixas_std": round(f1_cv_std, 4) if f1_cv_std is not None else None,
        },
        "classificador_sinistro": sin_metrics,
        "alerta_analise": alerta_analise,
        "correlacao_score": corr_score,
        "feature_importance_top15": dict(list(importancias.items())[:15]),
        "comparacao_v02_v03": comparacao_v02_v03,
    }
    (REPORTS_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n✅ Treino concluído.")
    print(f"   Modelos:  {MODELS_DIR}")
    print(f"   Figuras:  {FIG_DIR}")
    print(f"   Métricas: {REPORTS_DIR / 'metrics.json'}")


if __name__ == "__main__":
    main()
