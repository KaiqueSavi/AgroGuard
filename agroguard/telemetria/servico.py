"""
AgroGuard IA — Serviço de telemetria (Sprint 3/4)
==================================================

Orquestra a entrada de uma leitura: valida consistência de negócio, verifica
duplicidade, grava a leitura e dispara o pipeline de risco/alerta. É o único
lugar que decide o que é uma leitura válida — as rotas apenas chamam
`processar`/`receber` e devolvem o resultado.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from agroguard.alertas import servico as alertas_servico
from agroguard.api.auth import Identidade
from agroguard.api.schemas import TelemetriaIn
from agroguard.erros import EquipamentoDesconhecido, Inconsistencia, LeituraDuplicada
from agroguard.erros import ModeloIndisponivel as ModeloIndisponivelHTTP
from agroguard.risco import servico as risco_servico
from ml.inferencia import Modelos


def _normalizar_data_hora(data_hora: datetime) -> datetime:
    """Converte para UTC naive — mesma convenção da coluna TIMESTAMP do banco."""
    if data_hora.tzinfo is not None:
        return data_hora.astimezone(timezone.utc).replace(tzinfo=None)
    return data_hora


def _validar_consistencia(payload: TelemetriaIn, data_hora: datetime) -> None:
    """Regras de consistência ENTRE campos — não expressáveis num único Field."""
    velocidade = payload.telemetria.velocidade_kmh
    tipo_operacao = payload.operacao.tipo_operacao

    if tipo_operacao == "parado" and velocidade >= 1.0:
        raise Inconsistencia(
            f"tipo_operacao='parado' exige velocidade_kmh < 1.0 (recebido {velocidade})."
        )
    if tipo_operacao == "transporte" and velocidade < 5.0:
        raise Inconsistencia(
            f"tipo_operacao='transporte' exige velocidade_kmh >= 5 (recebido {velocidade})."
        )
    if payload.ambiente.umidade_solo > 0.9 and payload.ambiente.precip_24h_mm == 0:
        raise Inconsistencia(
            "umidade_solo > 0.9 sem nenhuma precipitação nas últimas 24h é inconsistente."
        )

    limite_futuro = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=5)
    if data_hora > limite_futuro:
        raise Inconsistencia("data_hora não pode estar mais de 5 minutos no futuro.")


def _payload_canonico(payload: TelemetriaIn) -> tuple[dict[str, Any], str, str]:
    bruto = payload.model_dump(mode="json")
    canonico = json.dumps(bruto, sort_keys=True, separators=(",", ":"))
    hash_sha256 = hashlib.sha256(canonico.encode("utf-8")).hexdigest()
    return bruto, canonico, hash_sha256


def _origem_leitura(identidade: Identidade) -> str:
    """Dispositivos simulados (kid iniciado em 'sim') marcam a leitura como 'simulador'."""
    return "simulador" if identidade.kid.startswith("sim") else "api"


def _rejeitar(
    conn_ou_engine: Connection | Engine,
    codigo: str,
    motivo: str,
    payload_bruto: dict[str, Any] | None,
    payload_hash: str | None,
    request_id: str,
    origem: str,
) -> None:
    """
    Grava a rejeição numa transação INDEPENDENTE da leitura que a originou,
    para que ela sobreviva mesmo quando a transação principal é desfeita.
    """
    engine = conn_ou_engine.engine if isinstance(conn_ou_engine, Connection) else conn_ou_engine
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO leituras_rejeitadas
                    (origem, codigo, motivo, payload, payload_hash, request_id)
                VALUES
                    (:origem, :codigo, :motivo, :payload, :payload_hash, :request_id)
                """
            ),
            {
                "origem": origem,
                "codigo": codigo,
                "motivo": motivo,
                "payload": json.dumps(payload_bruto) if payload_bruto is not None else None,
                "payload_hash": payload_hash,
                "request_id": request_id,
            },
        )


def registrar_rejeicao(
    engine: Engine,
    codigo: str,
    motivo: str,
    payload: dict[str, Any] | None,
    payload_hash: str | None,
    request_id: str,
    origem: str,
) -> None:
    """
    Grava uma rejeição a partir de fora do fluxo de `receber` — usada pelo
    handler de `RequestValidationError` (payload que nem chegou a virar um
    `TelemetriaIn` válido).
    """
    _rejeitar(engine, codigo, motivo, payload, payload_hash, request_id, origem)


def receber(
    conn: Connection,
    payload: TelemetriaIn,
    identidade: Identidade,
    request_id: str,
    origem: str,
) -> dict[str, Any]:
    """
    Valida e grava UMA leitura em `leituras_telemetria`, usando `conn` (uma
    transação já aberta pelo chamador — normalmente `processar`). Em caso de
    recusa, grava a rejeição numa transação própria e relança o erro.
    """
    payload_bruto, _canonico, payload_hash = _payload_canonico(payload)
    equip_id = payload.equipamento.equip_id
    data_hora = _normalizar_data_hora(payload.telemetria.data_hora)

    existe_equip = conn.execute(
        text("SELECT 1 FROM equipamentos WHERE equip_id = :id"), {"id": equip_id}
    ).scalar()
    if not existe_equip:
        motivo = f"Equipamento {equip_id} não está cadastrado na frota."
        _rejeitar(conn, "equip_desconhecido", motivo, payload_bruto, payload_hash, request_id, origem)
        raise EquipamentoDesconhecido(motivo)

    try:
        _validar_consistencia(payload, data_hora)
    except Inconsistencia as exc:
        _rejeitar(conn, "inconsistencia", exc.mensagem, payload_bruto, payload_hash, request_id, origem)
        raise

    duplicada = conn.execute(
        text("SELECT 1 FROM leituras_telemetria WHERE equip_id = :eq AND data_hora = :dh"),
        {"eq": equip_id, "dh": data_hora},
    ).scalar()
    if duplicada:
        motivo = f"Já existe leitura de {equip_id} em {data_hora.isoformat()}."
        _rejeitar(conn, "duplicado", motivo, payload_bruto, payload_hash, request_id, origem)
        raise LeituraDuplicada(motivo)

    origem_leitura = _origem_leitura(identidade)
    leitura_id = conn.execute(
        text(
            """
            INSERT INTO leituras_telemetria (
                equip_id, data_hora, latitude, longitude,
                velocidade_kmh, inclinacao_graus, vibracao_g,
                precip_24h_mm, precip_prev_6h_mm, umidade_solo, vento_max_kmh,
                dist_corpo_dagua_m, declividade_pct,
                tipo_operacao, turno, jornada_acumulada_h,
                dias_desde_manutencao, experiencia_operador_anos,
                origem, payload_hash, payload_bruto, request_id
            ) VALUES (
                :equip_id, :data_hora, :latitude, :longitude,
                :velocidade_kmh, :inclinacao_graus, :vibracao_g,
                :precip_24h_mm, :precip_prev_6h_mm, :umidade_solo, :vento_max_kmh,
                :dist_corpo_dagua_m, :declividade_pct,
                :tipo_operacao, :turno, :jornada_acumulada_h,
                :dias_desde_manutencao, :experiencia_operador_anos,
                :origem, :payload_hash, :payload_bruto, :request_id
            )
            RETURNING id
            """
        ),
        {
            "equip_id": equip_id,
            "data_hora": data_hora,
            "latitude": payload.telemetria.latitude,
            "longitude": payload.telemetria.longitude,
            "velocidade_kmh": payload.telemetria.velocidade_kmh,
            "inclinacao_graus": payload.telemetria.inclinacao_graus,
            "vibracao_g": payload.telemetria.vibracao_g,
            "precip_24h_mm": payload.ambiente.precip_24h_mm,
            "precip_prev_6h_mm": payload.ambiente.precip_prev_6h_mm,
            "umidade_solo": payload.ambiente.umidade_solo,
            "vento_max_kmh": payload.ambiente.vento_max_kmh,
            "dist_corpo_dagua_m": payload.ambiente.dist_corpo_dagua_m,
            "declividade_pct": payload.ambiente.declividade_pct,
            "tipo_operacao": payload.operacao.tipo_operacao,
            "turno": payload.operacao.turno,
            "jornada_acumulada_h": payload.operacao.jornada_acumulada_h,
            "dias_desde_manutencao": payload.operacao.dias_desde_manutencao,
            "experiencia_operador_anos": payload.operacao.experiencia_operador_anos,
            "origem": origem_leitura,
            "payload_hash": payload_hash,
            "payload_bruto": json.dumps(payload_bruto),
            "request_id": request_id,
        },
    ).scalar_one()

    return {
        "id": leitura_id,
        "equip_id": equip_id,
        "data_hora": data_hora,
        "velocidade_kmh": float(payload.telemetria.velocidade_kmh),
        "inclinacao_graus": float(payload.telemetria.inclinacao_graus),
        "vibracao_g": float(payload.telemetria.vibracao_g),
        "precip_24h_mm": float(payload.ambiente.precip_24h_mm),
        "precip_prev_6h_mm": float(payload.ambiente.precip_prev_6h_mm),
        "umidade_solo": float(payload.ambiente.umidade_solo),
        "vento_max_kmh": float(payload.ambiente.vento_max_kmh),
        "dist_corpo_dagua_m": int(payload.ambiente.dist_corpo_dagua_m),
        "declividade_pct": float(payload.ambiente.declividade_pct),
        "tipo_operacao": payload.operacao.tipo_operacao,
        "turno": payload.operacao.turno,
        "jornada_acumulada_h": float(payload.operacao.jornada_acumulada_h),
        "dias_desde_manutencao": int(payload.operacao.dias_desde_manutencao),
        "experiencia_operador_anos": int(payload.operacao.experiencia_operador_anos),
    }


def processar(
    engine: Engine,
    modelos: Modelos | None,
    payload: TelemetriaIn,
    identidade: Identidade,
    request_id: str | UUID,
) -> dict[str, Any]:
    """
    Pipeline completo entrada → banco → modelo → saída, numa ÚNICA transação:
    recebe a leitura, pontua o risco e, se for o caso, cria o alerta. Se
    qualquer etapa após `receber` falhar, a leitura também não é gravada.
    """
    if modelos is None:
        raise ModeloIndisponivelHTTP("Modelo de risco não carregado — rode `python -m ml.train`.")

    request_id_str = str(request_id)
    origem = _origem_leitura(identidade)

    inicio = time.perf_counter()
    with engine.begin() as conn:
        leitura = receber(conn, payload, identidade, request_id_str, origem)
        score = risco_servico.avaliar(conn, modelos, leitura, request_id_str, inicio)
        alerta = alertas_servico.avaliar(conn, score, request_id_str)

    return {
        "leitura_id": leitura["id"],
        "equip_id": leitura["equip_id"],
        "data_hora": leitura["data_hora"],
        "risco_score": score["risco_score"],
        "classe_risco": score["classe_risco"],
        "alerta": score["alerta"],
        "nivel_alerta": alerta["nivel"] if alerta else None,
        "fatores_principais": score["fatores_principais"],
        "recomendacoes": score["recomendacoes"],
        "regras_aplicadas": score["regras_aplicadas"],
        "modelo_versao": score["modelo_versao"],
        "request_id": request_id_str,
        "latencia_ms": score["latencia_ms"],
    }
