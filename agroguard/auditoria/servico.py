"""
AgroGuard IA — Serviço de auditoria (Sprint 3/4)
==================================================

Trilha de uso e de decisões da API: uma linha em `logs_uso` por requisição,
o histórico de leituras rejeitadas e o encadeamento completo de um
`request_id` (log → leitura → score → alerta), para rastreabilidade
ponta a ponta (US Sprint 4: "rastreabilidade de entradas, saídas e decisões").
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from agroguard.erros import ErroAgroGuard


def registrar_uso(
    engine: Engine,
    request_id: str,
    kid: str | None,
    papel: str | None,
    metodo: str,
    rota: str,
    status_http: int,
    duracao_ms: int,
    ip: str | None,
    detalhe: dict[str, Any] | None = None,
) -> None:
    """Grava uma linha de uso. Chamado pelo middleware — nunca deve derrubar a resposta."""
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO logs_uso
                    (request_id, kid, papel, metodo, rota, status_http, duracao_ms, ip, detalhe)
                VALUES
                    (:request_id, :kid, :papel, :metodo, :rota, :status_http, :duracao_ms, :ip, :detalhe)
                """
            ),
            {
                "request_id": request_id,
                "kid": kid,
                "papel": papel,
                "metodo": metodo,
                "rota": rota,
                "status_http": status_http,
                "duracao_ms": duracao_ms,
                "ip": ip,
                "detalhe": json.dumps(detalhe, ensure_ascii=False) if detalhe is not None else None,
            },
        )


def listar_logs(engine: Engine, limite: int) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        linhas = conn.execute(
            text("SELECT * FROM logs_uso ORDER BY ocorrido_em DESC LIMIT :limite"),
            {"limite": limite},
        ).mappings().all()
    return [dict(linha) for linha in linhas]


def listar_rejeitadas(engine: Engine, limite: int) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        linhas = conn.execute(
            text("SELECT * FROM leituras_rejeitadas ORDER BY recebido_em DESC LIMIT :limite"),
            {"limite": limite},
        ).mappings().all()
    return [dict(linha) for linha in linhas]


def rastrear(engine: Engine, request_id: str) -> dict[str, Any]:
    """Encadeia tudo que aconteceu para um `request_id`: log, leitura, score e alerta."""
    with engine.connect() as conn:
        log = conn.execute(
            text("SELECT * FROM logs_uso WHERE request_id = :rid ORDER BY ocorrido_em LIMIT 1"),
            {"rid": request_id},
        ).mappings().first()
        leitura = conn.execute(
            text("SELECT * FROM leituras_telemetria WHERE request_id = :rid"),
            {"rid": request_id},
        ).mappings().first()
        rejeitada = conn.execute(
            text("SELECT * FROM leituras_rejeitadas WHERE request_id = :rid"),
            {"rid": request_id},
        ).mappings().first()
        score = conn.execute(
            text("SELECT * FROM scores_risco WHERE request_id = :rid"),
            {"rid": request_id},
        ).mappings().first()
        alerta = conn.execute(
            text("SELECT * FROM alertas WHERE request_id = :rid"),
            {"rid": request_id},
        ).mappings().first()

    if not any([log, leitura, rejeitada, score, alerta]):
        raise ErroAgroGuard("nao_encontrado", f"Nenhum registro para request_id={request_id}.", 404)

    return {
        "log": dict(log) if log else None,
        "leitura": dict(leitura) if leitura else None,
        "rejeitada": dict(rejeitada) if rejeitada else None,
        "score": dict(score) if score else None,
        "alerta": dict(alerta) if alerta else None,
    }
