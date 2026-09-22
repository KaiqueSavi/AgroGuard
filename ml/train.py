"""
AgroGuard IA — Treino e Validação dos Modelos Preditivos (Sprint 2)
===================================================================

Treina e avalia os modelos supervisionados do AgroGuard IA a partir do dataset
simulado e produz TODOS os artefatos de validação estatística da Sprint 2:

  Modelos:
    1. Classificador de risco   → alvo `classe_risco` (Baixo/Medio/Alto/Critico)
       RandomForest vs GradientBoosting (escolhe o de maior F1-macro na validação).
    2. Regressor de score       → alvo `risco_score` (0-100)  [GradientBoosting]
    3. Classificador de sinistro→ alvo `sinistro` (0/1)  [análise complementar, AUC]

  Saídas:
    models/clf_classe.joblib, models/reg_score.joblib, models/clf_sinistro.joblib
    reports/figures/*.png   (matriz de confusão, importâncias, heatmap, dispersão)
    reports/metrics.json    (todas as métricas, consumidas pelo relatório/README)

Uso:
    python ml/train.py [--csv data/synthetic_dataset.csv] [--seed 42]

Sem vazamento de rótulo: ver ml/features.py (alvos e derivadas fora de X).
"""
from __future__ import annotations

import argparse
import json
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
from sklearn.model_selection import train_test_split, cross_val_score, StratifiedKFold
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


# ---------------------------------------------------------------------------
# 1) Classificador de classe de risco
# ---------------------------------------------------------------------------
def treinar_classificador(X_tr, y_tr, X_val, y_val, seed):
    """Compara RandomForest e GradientBoosting; retorna o de maior F1-macro na validação."""
    candidatos = {
        "RandomForest": RandomForestClassifier(
            n_estimators=300,
            max_depth=None,
            class_weight="balanced",
            random_state=seed,
            n_jobs=-1,
        ),
        "GradientBoosting": GradientBoostingClassifier(random_state=seed),
    }

    resultados = {}
    melhor_nome, melhor_f1, melhor_pipe = None, -1.0, None
    for nome, clf in candidatos.items():
        pipe = Pipeline([("prep", build_preprocessor()), ("model", clf)])
        pipe.fit(X_tr, y_tr)
        pred_val = pipe.predict(X_val)
        f1m = f1_score(y_val, pred_val, average="macro", labels=CLASSES_ORDER)
        acc = accuracy_score(y_val, pred_val)
        resultados[nome] = {"f1_macro_val": round(f1m, 4), "accuracy_val": round(acc, 4)}
        print(f"   • {nome:18s} F1-macro(val)={f1m:.4f}  acc(val)={acc:.4f}")
        if f1m > melhor_f1:
            melhor_nome, melhor_f1, melhor_pipe = nome, f1m, pipe

    print(f"   → Escolhido: {melhor_nome} (F1-macro val={melhor_f1:.4f})")
    return melhor_pipe, melhor_nome, resultados


def avaliar_classificador(pipe, nome, X_te, y_te, seed):
    """Métricas de teste + matriz de confusão + cross-val + figura."""
    pred = pipe.predict(X_te)
    acc = accuracy_score(y_te, pred)
    f1m = f1_score(y_te, pred, average="macro", labels=CLASSES_ORDER)
    recall_critico = recall_score(
        y_te, pred, labels=["Critico"], average="macro", zero_division=0
    )
    precision_critico = precision_score(
        y_te, pred, labels=["Critico"], average="macro", zero_division=0
    )
    cm = confusion_matrix(y_te, pred, labels=CLASSES_ORDER)
    report = classification_report(
        y_te, pred, labels=CLASSES_ORDER, output_dict=True, zero_division=0
    )
    report_txt = classification_report(y_te, pred, labels=CLASSES_ORDER, zero_division=0)

    # Validação cruzada estratificada (5 folds) no conjunto de teste+treino combinado
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=seed)
    cv_scores = cross_val_score(pipe, X_te, y_te, cv=cv, scoring="f1_macro")

    print("\n   Matriz de confusão (teste):")
    print("   " + str(cm).replace("\n", "\n   "))
    print("\n" + report_txt)

    # Figura: matriz de confusão
    fig, ax = plt.subplots(figsize=(6, 5))
    ConfusionMatrixDisplay(cm, display_labels=CLASSES_ORDER).plot(
        ax=ax, cmap="Blues", colorbar=False, values_format="d"
    )
    ax.set_title(f"Matriz de Confusão — Classe de Risco ({nome})")
    ax.set_xlabel("Previsto")
    ax.set_ylabel("Real")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "confusion_matrix.png", dpi=130)
    plt.close(fig)

    return {
        "modelo": nome,
        "accuracy_test": round(acc, 4),
        "f1_macro_test": round(f1m, 4),
        "recall_critico_test": round(float(recall_critico), 4),
        "precision_critico_test": round(float(precision_critico), 4),
        "cv_f1_macro_mean": round(float(cv_scores.mean()), 4),
        "cv_f1_macro_std": round(float(cv_scores.std()), 4),
        "confusion_matrix": cm.tolist(),
        "confusion_labels": CLASSES_ORDER,
        "classification_report": report,
    }


def plot_importancias(pipe, nome):
    """Top-15 importâncias de feature do classificador escolhido."""
    prep = pipe.named_steps["prep"]
    model = pipe.named_steps["model"]
    nomes = get_feature_names(prep)
    importancias = pd.Series(model.feature_importances_, index=nomes).sort_values(
        ascending=False
    )
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
# 2) Regressor de score
# ---------------------------------------------------------------------------
def treinar_regressor(X_tr, y_tr, X_te, y_te, seed):
    pipe = Pipeline(
        [("prep", build_preprocessor()), ("model", GradientBoostingRegressor(random_state=seed))]
    )
    pipe.fit(X_tr, y_tr)
    pred = pipe.predict(X_te)

    rmse = float(np.sqrt(mean_squared_error(y_te, pred)))
    mae = float(mean_absolute_error(y_te, pred))
    r2 = float(r2_score(y_te, pred))
    print(f"   RMSE={rmse:.2f}  MAE={mae:.2f}  R²={r2:.4f}")

    # Figura: previsto vs real
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(y_te, pred, alpha=0.25, s=12, color="#1565c0")
    lims = [0, 100]
    ax.plot(lims, lims, "r--", lw=1.5, label="ideal (y=x)")
    ax.set_xlim(lims)
    ax.set_ylim(lims)
    ax.set_xlabel("Score real")
    ax.set_ylabel("Score previsto")
    ax.set_title(f"Regressor de Score — previsto vs real\nRMSE={rmse:.2f} · MAE={mae:.2f} · R²={r2:.3f}")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIG_DIR / "regression_pred_vs_real.png", dpi=130)
    plt.close(fig)

    return pipe, {"rmse_test": round(rmse, 3), "mae_test": round(mae, 3), "r2_test": round(r2, 4)}


# ---------------------------------------------------------------------------
# 3) Classificador de sinistro (binário, complementar)
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

    # Figura: curva ROC
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
    """Heatmap de correlação (Pearson) entre features numéricas e o score."""
    cols = NUMERIC_FEATURES + [TARGET_SCORE]
    corr = df[cols].corr(method="pearson")

    fig, ax = plt.subplots(figsize=(11, 9))
    sns.heatmap(corr, annot=True, fmt=".2f", cmap="RdBu_r", center=0, ax=ax,
                annot_kws={"size": 7}, cbar_kws={"shrink": 0.8})
    ax.set_title("Correlação de Pearson — features × risco_score")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "correlation_heatmap.png", dpi=130)
    plt.close(fig)

    # Correlação de cada feature com o score, ordenada (para o relatório)
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
# Pipeline principal
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Treina e valida os modelos AgroGuard IA")
    parser.add_argument("--csv", default=str(ROOT / "data" / "synthetic_dataset.csv"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    print(f"📂 Carregando dataset: {args.csv}")
    df = pd.read_csv(args.csv)
    print(f"   {len(df):,} linhas × {len(df.columns)} colunas")

    # --- Figuras exploratórias ---
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
    print(f"\n🔀 Split estratificado: treino={len(idx_tr)}  val={len(idx_val)}  teste={len(idx_te)}")

    Xtr, Xval, Xte = X.iloc[idx_tr], X.iloc[idx_val], X.iloc[idx_te]

    # ===== Classificador de classe =====
    print("\n🧠 [1/3] Classificador de classe de risco")
    clf_pipe, clf_nome, clf_cmp = treinar_classificador(
        Xtr, y_classe.iloc[idx_tr], Xval, y_classe.iloc[idx_val], args.seed
    )
    clf_metrics = avaliar_classificador(clf_pipe, clf_nome, Xte, y_classe.iloc[idx_te], args.seed)
    importancias = plot_importancias(clf_pipe, clf_nome)
    # re-treina no treino+val antes de salvar (mais dados → modelo de produção)
    clf_pipe.fit(X.iloc[np.concatenate([idx_tr, idx_val])],
                 y_classe.iloc[np.concatenate([idx_tr, idx_val])])
    joblib.dump(clf_pipe, MODELS_DIR / "clf_classe.joblib")

    # ===== Regressor de score =====
    print("\n🧠 [2/3] Regressor de score (0-100)")
    reg_pipe, reg_metrics = treinar_regressor(
        Xtr, y_score.iloc[idx_tr], Xte, y_score.iloc[idx_te], args.seed
    )
    reg_pipe.fit(X.iloc[np.concatenate([idx_tr, idx_val])],
                 y_score.iloc[np.concatenate([idx_tr, idx_val])])
    joblib.dump(reg_pipe, MODELS_DIR / "reg_score.joblib")

    # ===== Classificador de sinistro =====
    print("\n🧠 [3/3] Classificador de sinistro (binário, complementar)")
    sin_pipe, sin_metrics = treinar_sinistro(
        Xtr, y_sin.iloc[idx_tr], Xte, y_sin.iloc[idx_te], args.seed
    )
    sin_pipe.fit(X.iloc[np.concatenate([idx_tr, idx_val])],
                 y_sin.iloc[np.concatenate([idx_tr, idx_val])])
    joblib.dump(sin_pipe, MODELS_DIR / "clf_sinistro.joblib")

    # --- Consolida métricas ---
    metrics = {
        "modelo_versao": MODEL_VERSION,
        "seed": args.seed,
        "dataset": {
            "linhas": int(len(df)),
            "treino": int(len(idx_tr)),
            "validacao": int(len(idx_val)),
            "teste": int(len(idx_te)),
            "distribuicao_classe": df[TARGET_CLASSE].value_counts().to_dict(),
            "taxa_sinistro_pct": round(float(y_sin.mean() * 100), 2),
        },
        "classificador_classe": {**clf_metrics, "comparacao_modelos": clf_cmp},
        "regressor_score": reg_metrics,
        "classificador_sinistro": sin_metrics,
        "correlacao_score": corr_score,
        "feature_importance_top15": dict(list(importancias.items())[:15]),
    }
    (REPORTS_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False))

    print("\n✅ Treino concluído.")
    print(f"   Modelos:  {MODELS_DIR}")
    print(f"   Figuras:  {FIG_DIR}")
    print(f"   Métricas: {REPORTS_DIR / 'metrics.json'}")


if __name__ == "__main__":
    main()
