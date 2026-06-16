"""
AgroGuard IA — Análise Exploratória de Dados (Sprint 2)
=======================================================

Exploração estatística do dataset: estatísticas descritivas, correlações
(Pearson e Spearman) e comparações por grupo — material da seção de validação
estatística (identificação de fatores que elevam o risco/sinistro).

Gera:
    reports/eda_summary.txt              (resumo textual)
    reports/figures/eda_score_by_distagua.png
    reports/figures/eda_sinistro_rate.png

Uso:
    python ml/eda.py [--csv data/synthetic_dataset.csv]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

from features import NUMERIC_FEATURES, TARGET_SCORE, TARGET_SINISTRO

ROOT = Path(__file__).resolve().parents[1]
FIG_DIR = ROOT / "reports" / "figures"
REPORTS_DIR = ROOT / "reports"
FIG_DIR.mkdir(parents=True, exist_ok=True)
sns.set_theme(style="whitegrid")


def faixa_dist_agua(m: float) -> str:
    if m < 50:
        return "0-50 m (crítico)"
    if m < 200:
        return "50-200 m (alto)"
    if m < 500:
        return "200-500 m (médio)"
    return "> 500 m (baixo)"


def main() -> None:
    parser = argparse.ArgumentParser(description="EDA AgroGuard IA")
    parser.add_argument("--csv", default=str(ROOT / "data" / "synthetic_dataset.csv"))
    args = parser.parse_args()

    df = pd.read_csv(args.csv)
    linhas = []

    def log(msg: str = ""):
        print(msg)
        linhas.append(msg)

    log("=" * 70)
    log("AgroGuard IA — Análise Exploratória de Dados (EDA)")
    log("=" * 70)
    log(f"Registros: {len(df):,} | Colunas: {len(df.columns)}")
    log(f"Período: {df['data_hora'].min()} → {df['data_hora'].max()}")
    log(f"Equipamentos distintos: {df['equip_id'].nunique()}")
    log(f"Taxa global de sinistro: {df[TARGET_SINISTRO].mean() * 100:.2f}%")
    log("")
    log("Distribuição por classe de risco:")
    log(df["classe_risco"].value_counts().to_string())
    log("")

    # --- Correlações com o score ---
    log("-" * 70)
    log("Correlação das features com risco_score (Pearson | Spearman):")
    log("-" * 70)
    pear = df[NUMERIC_FEATURES + [TARGET_SCORE]].corr("pearson")[TARGET_SCORE].drop(TARGET_SCORE)
    spear = df[NUMERIC_FEATURES + [TARGET_SCORE]].corr("spearman")[TARGET_SCORE].drop(TARGET_SCORE)
    corr_tbl = pd.DataFrame({"pearson": pear, "spearman": spear}).sort_values(
        "pearson", key=abs, ascending=False
    )
    log(corr_tbl.round(3).to_string())
    log("")

    # --- Correlação com sinistro (point-biserial ~ Pearson com 0/1) ---
    log("-" * 70)
    log("Correlação das features com ocorrência de sinistro (0/1):")
    log("-" * 70)
    cs = df[NUMERIC_FEATURES + [TARGET_SINISTRO]].corr("pearson")[TARGET_SINISTRO].drop(
        TARGET_SINISTRO
    ).sort_values(key=abs, ascending=False)
    log(cs.round(3).to_string())
    log("")

    # --- Score médio e taxa de sinistro por faixa de distância de água ---
    df["faixa_agua"] = df["dist_corpo_dagua_m"].apply(faixa_dist_agua)
    ordem_faixa = ["0-50 m (crítico)", "50-200 m (alto)", "200-500 m (médio)", "> 500 m (baixo)"]
    grp = df.groupby("faixa_agua").agg(
        leituras=("id", "count"),
        score_medio=(TARGET_SCORE, "mean"),
        taxa_sinistro_pct=(TARGET_SINISTRO, lambda s: 100 * s.mean()),
    ).reindex(ordem_faixa)
    log("-" * 70)
    log("Risco por faixa de proximidade de corpo d'água:")
    log("-" * 70)
    log(grp.round(2).to_string())

    # --- Figura 1: boxplot score por faixa de água ---
    fig, ax = plt.subplots(figsize=(9, 5))
    sns.boxplot(data=df, x="faixa_agua", y=TARGET_SCORE, order=ordem_faixa,
                hue="faixa_agua", palette="YlOrRd_r", legend=False, ax=ax)
    ax.set_title("Distribuição do risco_score por proximidade de corpo d'água")
    ax.set_xlabel("Faixa de distância")
    ax.set_ylabel("risco_score")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "eda_score_by_distagua.png", dpi=130)
    plt.close(fig)

    # --- Figura 2: taxa de sinistro por classe de risco ---
    taxa = df.groupby("classe_risco")[TARGET_SINISTRO].mean().mul(100)
    taxa = taxa.reindex([c for c in ["Baixo", "Medio", "Alto", "Critico"] if c in taxa.index])
    fig, ax = plt.subplots(figsize=(7, 5))
    taxa.plot(kind="bar", ax=ax, color="#c62828")
    ax.set_title("Taxa de sinistro (%) por classe de risco")
    ax.set_ylabel("% de leituras com sinistro")
    ax.set_xlabel("classe_risco")
    for i, v in enumerate(taxa.values):
        ax.annotate(f"{v:.1f}%", (i, v), ha="center", va="bottom", fontsize=9)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "eda_sinistro_rate.png", dpi=130)
    plt.close(fig)

    (REPORTS_DIR / "eda_summary.txt").write_text("\n".join(linhas), encoding="utf-8")
    log("")
    log(f"✅ Resumo salvo em {REPORTS_DIR / 'eda_summary.txt'}")
    log(f"✅ Figuras em {FIG_DIR}")


if __name__ == "__main__":
    main()
