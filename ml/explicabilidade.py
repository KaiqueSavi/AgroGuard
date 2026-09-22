"""
AgroGuard IA — Explicabilidade do score (Sprint 3-4 / v0.3)
=============================================================

Explicação por contrafactual (delta-vs-baseline), sem dependências externas
(sem SHAP): para cada feature, substitui o valor da linha pelo valor "típico"
(mediana/moda do treino) e mede o quanto o score previsto muda. Quanto maior a
queda ao neutralizar uma feature, maior sua contribuição para o score da linha.

Usado por `ml/inferencia.py` (preenche `fatores_principais` em `prever`).
"""
from __future__ import annotations

import pandas as pd

from ml.features import CATEGORICAL_FEATURES, FEATURE_COLUMNS, NUMERIC_FEATURES


def baseline_de_treino(df: pd.DataFrame) -> dict:
    """Mediana (numéricas) / moda (categóricas) do treino — usado como
    referência 'neutra' em `fatores_principais` e persistido em
    `baseline_features.json`."""
    baseline: dict = {}
    for col in NUMERIC_FEATURES:
        if col in df.columns:
            baseline[col] = float(df[col].median())
    for col in CATEGORICAL_FEATURES:
        if col in df.columns:
            baseline[col] = str(df[col].mode(dropna=True).iloc[0])
    return baseline


def fatores_principais(regressor, X_row: pd.DataFrame, baseline: dict, top_n: int = 3) -> list[dict]:
    """
    Explica a previsão de UMA linha (`X_row`, 1 linha × FEATURE_COLUMNS) por
    contrafactual: para cada feature, substitui pelo valor de `baseline` e
    reprediz. `contribuicao_pts = score_original - score_com_feature_neutra`
    (positivo = a feature aumentou o score acima do "típico").

    Todas as previsões (linha original + contrafactuais) são feitas em UMA
    única chamada a `regressor.predict` (determinístico e rápido).

    Retorna até `top_n` fatores, ordenados por |contribuicao_pts| (maior
    primeiro), com empates desempatados a favor da contribuição positiva.
    """
    if X_row is None or X_row.empty or not baseline:
        return []

    linha = X_row.iloc[[0]][FEATURE_COLUMNS].reset_index(drop=True)
    features = [f for f in FEATURE_COLUMNS if f in baseline]
    if not features:
        return []

    lote = [linha]
    for feat in features:
        contrafactual = linha.copy()
        contrafactual[feat] = baseline[feat]
        lote.append(contrafactual)

    entrada = pd.concat(lote, ignore_index=True)
    scores = regressor.predict(entrada)

    score_original = float(scores[0])
    candidatos = []
    for i, feat in enumerate(features, start=1):
        score_neutro = float(scores[i])
        contribuicao = round(score_original - score_neutro, 1)
        valor_bruto = linha.iloc[0][feat]
        valor = str(valor_bruto) if feat in CATEGORICAL_FEATURES else float(valor_bruto)
        candidatos.append({"fator": feat, "valor": valor, "contribuicao_pts": contribuicao})

    candidatos.sort(key=lambda c: (-abs(c["contribuicao_pts"]), 0 if c["contribuicao_pts"] >= 0 else 1))
    return candidatos[:top_n]
