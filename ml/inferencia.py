"""
AgroGuard IA — Interface de inferência (contrato entre API e modelo)
====================================================================

Fonte ÚNICA de inferência do score de risco. A API (`agroguard/risco`), o
scoring em lote (`ml/predict.py`) e os testes chamam SOMENTE estas funções.

Regras de negócio fixadas aqui (uma vez, para todos os consumidores):
  - classe_risco = faixa do score  ->  (-1,30] Baixo · (30,60] Medio · (60,80] Alto · (80,100] Critico
    (mesmas faixas do gerador do dataset: pd.cut(score, [-1, 30, 60, 80, 101]))
  - alerta       = risco_score >= ALERT_THRESHOLD (80)
    Observação: score == 80 é classe "Alto" com alerta ligado (borda documentada).

Assinaturas CONGELADAS (não renomear, não mudar tipos de retorno):
    carregar_modelos(models_dir=None) -> Modelos
    classe_por_score(score) -> str
    prever(modelos, df) -> pd.DataFrame[risco_score, classe_risco, alerta, fatores_principais, modelo_versao]
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from ml.features import ALERT_THRESHOLD, CLASSES_ORDER, FEATURE_COLUMNS, MODEL_VERSION

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODELS_DIR = ROOT / "ml" / "models"

# Limites superiores (inclusivos) de cada faixa, na ordem de CLASSES_ORDER.
SCORE_BINS: list[tuple[int, str]] = [(30, "Baixo"), (60, "Medio"), (80, "Alto"), (100, "Critico")]


class ModeloIndisponivel(RuntimeError):
    """Artefatos do modelo não encontrados — rode `python -m ml.train`."""


@dataclass
class Modelos:
    """Artefatos carregados em memória."""
    regressor: Any
    versao: str = MODEL_VERSION
    baseline: dict[str, Any] = field(default_factory=dict)   # medianas/modas (explicabilidade)
    classificador: Any = None                                # baseline v0.2, opcional
    origem: Path | None = None


def resolver_models_dir(models_dir: Path | None = None) -> Path:
    """Ordem: argumento > env AGROGUARD_MODELS_DIR > ml/models."""
    if models_dir is not None:
        return Path(models_dir)
    env = os.getenv("AGROGUARD_MODELS_DIR")
    return Path(env) if env else DEFAULT_MODELS_DIR


def carregar_modelos(models_dir: Path | None = None) -> Modelos:
    """Carrega o regressor (obrigatório) e os artefatos opcionais."""
    pasta = resolver_models_dir(models_dir)
    caminho = pasta / "reg_score.joblib"
    if not caminho.exists():
        raise ModeloIndisponivel(f"Modelo não encontrado em {caminho}. Rode `python -m ml.train`.")
    regressor = joblib.load(caminho)

    baseline: dict[str, Any] = {}
    baseline_path = pasta / "baseline_features.json"
    if baseline_path.exists():
        import json
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))

    classificador = None
    clf_path = pasta / "clf_classe.joblib"
    if clf_path.exists():
        classificador = joblib.load(clf_path)

    versao = MODEL_VERSION
    meta_path = pasta / "model_meta.json"
    if meta_path.exists():
        import json
        versao = json.loads(meta_path.read_text(encoding="utf-8")).get("modelo_versao", MODEL_VERSION)

    return Modelos(regressor=regressor, versao=versao, baseline=baseline,
                   classificador=classificador, origem=pasta)


def classe_por_score(score: int) -> str:
    """Mapeia o score (0-100) para a classe pelas faixas do negócio."""
    s = int(score)
    for limite, classe in SCORE_BINS:
        if s <= limite:
            return classe
    return CLASSES_ORDER[-1]


def prever(modelos: Modelos, df: pd.DataFrame) -> pd.DataFrame:
    """
    Gera score, classe, alerta e fatores para cada linha de `df`.
    `df` deve conter FEATURE_COLUMNS; colunas extras são ignoradas.
    Retorna DataFrame com o MESMO índice de `df`.
    """
    faltantes = [c for c in FEATURE_COLUMNS if c not in df.columns]
    if faltantes:
        raise ValueError(f"Colunas de features ausentes: {faltantes}")

    X = df[FEATURE_COLUMNS].copy()
    score = modelos.regressor.predict(X).clip(0, 100).round().astype(int)

    return pd.DataFrame(
        {
            "risco_score": score,
            "classe_risco": [classe_por_score(s) for s in score],
            "alerta": score >= ALERT_THRESHOLD,
            "fatores_principais": [[] for _ in range(len(X))],   # preenchido pela v0.3 (ml/explicabilidade.py)
            "modelo_versao": modelos.versao,
        },
        index=df.index,
    )
