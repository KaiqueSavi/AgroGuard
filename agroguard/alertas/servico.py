"""
AgroGuard IA — Serviço de alertas (Sprint 3/4)
================================================

Decide se um score de risco vira um alerta, monta a mensagem e as
recomendações de ação, e mantém o ciclo de vida do alerta (aberto →
reconhecido). Critério de alerta e tabela de recomendações vivem aqui —
nenhuma outra camada decide isso.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from sqlalchemy import text
from sqlalchemy.engine import Connection

from agroguard.erros import ErroAgroGuard
from ml.features import ALERT_THRESHOLD

CRITERIO_ALERTA = f"risco_score >= {ALERT_THRESHOLD}"

# Tabela de regras de recomendação: (ação, critério legível, predicado, prioridade).
# `MONITORAR` é o fallback quando nada mais disparou mas o score já preocupa.
REGRAS: list[tuple[str, str, Callable[[dict[str, Any], int], bool], str]] = [
    (
        "ADIAR_OPERACAO",
        "umidade_solo > 0.7 e dist_corpo_dagua_m < 100",
        lambda l, s: l["umidade_solo"] > 0.7 and l["dist_corpo_dagua_m"] < 100,
        "alta",
    ),
    (
        "REDUZIR_VELOCIDADE",
        "declividade_pct > 5 ou inclinacao_graus > 6",
        lambda l, s: l["declividade_pct"] > 5 or l["inclinacao_graus"] > 6,
        "alta",
    ),
    (
        "ATENCAO_CHUVA",
        "precip_24h_mm > 30 ou precip_prev_6h_mm > 10",
        lambda l, s: l["precip_24h_mm"] > 30 or l["precip_prev_6h_mm"] > 10,
        "media",
    ),
    (
        "INSPECAO_MECANICA",
        "dias_desde_manutencao > 40 ou vibracao_g > 1.5",
        lambda l, s: l["dias_desde_manutencao"] > 40 or l["vibracao_g"] > 1.5,
        "media",
    ),
    (
        "PAUSA_JORNADA",
        "jornada_acumulada_h > 10",
        lambda l, s: l["jornada_acumulada_h"] > 10,
        "media",
    ),
    (
        "ROTA_ALTERNATIVA",
        "tipo_operacao == 'transporte' e precip_24h_mm > 10",
        lambda l, s: l["tipo_operacao"] == "transporte" and l["precip_24h_mm"] > 10,
        "media",
    ),
]


def recomendar(leitura: dict[str, Any], score: int, fatores: list[Any]) -> list[dict[str, str]]:
    """Aplica a tabela `REGRAS` e devolve as recomendações que dispararam."""
    recomendacoes = [
        {"acao": acao, "criterio": criterio, "prioridade": prioridade}
        for acao, criterio, predicado, prioridade in REGRAS
        if predicado(leitura, score)
    ]
    if not recomendacoes and score >= 60:
        recomendacoes.append(
            {
                "acao": "MONITORAR",
                "criterio": "risco_score >= 60 sem nenhum outro critério específico",
                "prioridade": "baixa",
            }
        )
    return recomendacoes


def avaliar(conn: Connection, score: dict[str, Any], request_id: str) -> dict[str, Any] | None:
    """Cria o alerta quando `score['alerta']` é verdadeiro. Devolve None caso contrário."""
    if not score["alerta"]:
        return None

    nivel = "Critico" if score["classe_risco"] == "Critico" else "Alto"
    mensagem = (
        f"Risco {nivel.lower()} detectado no equipamento {score['equip_id']} "
        f"(score {score['risco_score']}/100). Critério: {CRITERIO_ALERTA}."
    )

    linha = conn.execute(
        text(
            """
            INSERT INTO alertas (
                score_id, leitura_id, equip_id, nivel, criterio, mensagem,
                recomendacoes, request_id
            ) VALUES (
                :score_id, :leitura_id, :equip_id, :nivel, :criterio, :mensagem,
                :recomendacoes, :request_id
            )
            RETURNING id, status, criado_em
            """
        ),
        {
            "score_id": score["id"],
            "leitura_id": score["leitura_id"],
            "equip_id": score["equip_id"],
            "nivel": nivel,
            "criterio": CRITERIO_ALERTA,
            "mensagem": mensagem,
            "recomendacoes": json.dumps(score["recomendacoes"], ensure_ascii=False),
            "request_id": request_id,
        },
    ).mappings().first()

    return {
        "id": linha["id"],
        "score_id": score["id"],
        "leitura_id": score["leitura_id"],
        "equip_id": score["equip_id"],
        "nivel": nivel,
        "criterio": CRITERIO_ALERTA,
        "mensagem": mensagem,
        "recomendacoes": score["recomendacoes"],
        "status": linha["status"],
        "request_id": request_id,
        "criado_em": linha["criado_em"],
    }


def listar(conn: Connection, status: str | None, limite: int) -> list[dict[str, Any]]:
    """Lista alertas, do mais recente para o mais antigo, opcionalmente filtrando por status."""
    if status:
        linhas = conn.execute(
            text(
                "SELECT * FROM alertas WHERE status = :status "
                "ORDER BY criado_em DESC LIMIT :limite"
            ),
            {"status": status, "limite": limite},
        ).mappings().all()
    else:
        linhas = conn.execute(
            text("SELECT * FROM alertas ORDER BY criado_em DESC LIMIT :limite"),
            {"limite": limite},
        ).mappings().all()
    return [dict(linha) for linha in linhas]


def reconhecer(conn: Connection, id_alerta: int) -> dict[str, Any]:
    """Marca o alerta como reconhecido. Levanta 404 se o id não existir."""
    linha = conn.execute(
        text(
            "UPDATE alertas SET status = 'reconhecido' WHERE id = :id "
            "RETURNING *"
        ),
        {"id": id_alerta},
    ).mappings().first()
    if linha is None:
        raise ErroAgroGuard("nao_encontrado", f"Alerta {id_alerta} não encontrado.", 404)
    return dict(linha)
