"""
AgroGuard IA — Serviço de risco (Sprint 3/4)
=============================================

Ponte entre a leitura recém-gravada e o motor de inferência congelado em
`ml.inferencia`. Monta a linha de features, chama `prever`, calcula as
recomendações e grava o score em `scores_risco`.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from agroguard.alertas import servico as alertas_servico
from agroguard.erros import EquipamentoDesconhecido
from ml.features import FEATURE_COLUMNS
from ml.inferencia import Modelos, prever

CRITERIO_ALERTA = alertas_servico.CRITERIO_ALERTA

ROOT = Path(__file__).resolve().parents[2]
METRICS_PATH = ROOT / "reports" / "metrics.json"


def _linha_features(conn: Connection, leitura: dict[str, Any]) -> pd.DataFrame:
    """Monta a linha de features exigida por `ml.features.FEATURE_COLUMNS`."""
    equipamento = conn.execute(
        text("SELECT tipo_equip, idade_equipamento_anos FROM equipamentos WHERE equip_id = :id"),
        {"id": leitura["equip_id"]},
    ).mappings().first()
    if equipamento is None:  # já validado em telemetria.servico.receber — defesa extra
        raise EquipamentoDesconhecido(f"Equipamento {leitura['equip_id']} não cadastrado.")

    linha = {
        "idade_equipamento_anos": equipamento["idade_equipamento_anos"],
        "velocidade_kmh": leitura["velocidade_kmh"],
        "inclinacao_graus": leitura["inclinacao_graus"],
        "vibracao_g": leitura["vibracao_g"],
        "precip_24h_mm": leitura["precip_24h_mm"],
        "precip_prev_6h_mm": leitura["precip_prev_6h_mm"],
        "umidade_solo": leitura["umidade_solo"],
        "vento_max_kmh": leitura["vento_max_kmh"],
        "dist_corpo_dagua_m": leitura["dist_corpo_dagua_m"],
        "declividade_pct": leitura["declividade_pct"],
        "jornada_acumulada_h": leitura["jornada_acumulada_h"],
        "dias_desde_manutencao": leitura["dias_desde_manutencao"],
        "experiencia_operador_anos": leitura["experiencia_operador_anos"],
        "tipo_equip": equipamento["tipo_equip"],
        "tipo_operacao": leitura["tipo_operacao"],
        "turno": leitura["turno"],
    }
    return pd.DataFrame([linha], columns=FEATURE_COLUMNS)


def avaliar(
    conn: Connection,
    modelos: Modelos,
    leitura: dict[str, Any],
    request_id: str,
    inicio_pipeline: float | None = None,
) -> dict[str, Any]:
    """Pontua `leitura`, calcula recomendações/regras e grava em `scores_risco`."""
    marca_inicio = inicio_pipeline if inicio_pipeline is not None else time.perf_counter()

    df = _linha_features(conn, leitura)
    resultado = prever(modelos, df).iloc[0]

    risco_score = int(resultado["risco_score"])
    classe_risco = str(resultado["classe_risco"])
    alerta = bool(resultado["alerta"])
    fatores_principais = list(resultado["fatores_principais"])

    recomendacoes = alertas_servico.recomendar(leitura, risco_score, fatores_principais)
    regras_aplicadas = [CRITERIO_ALERTA] if alerta else []

    latencia_ms = int(round((time.perf_counter() - marca_inicio) * 1000))

    linha = conn.execute(
        text(
            """
            INSERT INTO scores_risco (
                leitura_id, risco_score, classe_risco, alerta,
                fatores_principais, regras_aplicadas, recomendacoes,
                request_id, latencia_ms, modelo_versao
            ) VALUES (
                :leitura_id, :risco_score, :classe_risco, :alerta,
                :fatores_principais, :regras_aplicadas, :recomendacoes,
                :request_id, :latencia_ms, :modelo_versao
            )
            RETURNING id, gerado_em
            """
        ),
        {
            "leitura_id": leitura["id"],
            "risco_score": risco_score,
            "classe_risco": classe_risco,
            "alerta": alerta,
            "fatores_principais": _para_jsonb(fatores_principais),
            "regras_aplicadas": _para_jsonb(regras_aplicadas),
            "recomendacoes": _para_jsonb(recomendacoes),
            "request_id": request_id,
            "latencia_ms": latencia_ms,
            "modelo_versao": modelos.versao,
        },
    ).mappings().first()

    return {
        "id": linha["id"],
        "leitura_id": leitura["id"],
        "equip_id": leitura["equip_id"],
        "risco_score": risco_score,
        "classe_risco": classe_risco,
        "alerta": alerta,
        "fatores_principais": fatores_principais,
        "regras_aplicadas": regras_aplicadas,
        "recomendacoes": recomendacoes,
        "modelo_versao": modelos.versao,
        "request_id": request_id,
        "latencia_ms": latencia_ms,
        "gerado_em": linha["gerado_em"],
    }


def _para_jsonb(valor: Any) -> str:
    return json.dumps(valor, ensure_ascii=False, default=str)


def historico_scores(engine: Engine, equip_id: str, limite: int) -> list[dict[str, Any]]:
    """Histórico de scores de UM equipamento, do mais antigo ao mais recente — US07."""
    query = text(
        """
        SELECT
            id AS leitura_id, equip_id, data_hora, risco_score, classe_risco,
            alerta, fatores_principais, recomendacoes, modelo_versao
        FROM vw_risco_completo
        WHERE equip_id = :equip_id AND risco_score IS NOT NULL
        ORDER BY data_hora
        LIMIT :limite
        """
    )
    with engine.connect() as conn:
        linhas = conn.execute(query, {"equip_id": equip_id, "limite": limite}).mappings().all()
    return [dict(linha) for linha in linhas]


def info_modelo(modelos: Modelos | None, erro: str | None) -> dict[str, Any]:
    """Resumo do estado do modelo carregado — usado por `GET /modelo/info`."""
    if modelos is None:
        return {"carregado": False, "erro": erro, "modelo_versao": None, "pasta": None, "metricas": None}

    metricas: dict[str, Any] | None = None
    if METRICS_PATH.exists():
        try:
            bruto = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
            metricas = {
                "modelo_versao": bruto.get("modelo_versao"),
                "linhas_dataset": bruto.get("dataset", {}).get("linhas"),
                "accuracy_classificador": bruto.get("classificador_classe", {}).get("accuracy_test"),
            }
        except (OSError, ValueError):
            metricas = None

    return {
        "carregado": True,
        "erro": None,
        "modelo_versao": modelos.versao,
        "pasta": str(modelos.origem) if modelos.origem else None,
        "metricas": metricas,
    }
