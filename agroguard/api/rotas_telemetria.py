"""
AgroGuard IA — Rotas de telemetria (Sprint 3/4)
================================================

HTTP puro: recebe o payload, delega para `telemetria.servico.processar` e
devolve o resultado. Nenhuma regra de negócio mora aqui — só parsing e
formatação.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, status

from agroguard.api.auth import Identidade, Papel, exigir_papel
from agroguard.api.schemas import LoteIn, LoteResultado, RejeicaoLoteItem, ScoreOut, TelemetriaIn
from agroguard.erros import ErroAgroGuard
from agroguard.telemetria import servico as telemetria_servico

router = APIRouter(tags=["telemetria"])

_PAPEIS_TELEMETRIA = (Papel.DISPOSITIVO, Papel.OPERADOR, Papel.ADMIN)


@router.post("/telemetria", response_model=ScoreOut, status_code=status.HTTP_201_CREATED)
def enviar_telemetria(
    payload: TelemetriaIn,
    request: Request,
    identidade: Identidade = Depends(exigir_papel(*_PAPEIS_TELEMETRIA)),
) -> ScoreOut:
    request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    resultado = telemetria_servico.processar(
        request.app.state.engine, request.app.state.modelos, payload, identidade, request_id
    )
    return ScoreOut(**resultado)


@router.post("/telemetria/lote", response_model=LoteResultado)
def enviar_lote(
    lote: LoteIn,
    request: Request,
    identidade: Identidade = Depends(exigir_papel(*_PAPEIS_TELEMETRIA)),
) -> LoteResultado:
    aceitos: list[ScoreOut] = []
    rejeitados: list[RejeicaoLoteItem] = []

    for indice, payload in enumerate(lote.leituras):
        request_id_item = str(uuid.uuid4())
        try:
            resultado = telemetria_servico.processar(
                request.app.state.engine, request.app.state.modelos, payload, identidade, request_id_item
            )
            aceitos.append(ScoreOut(**resultado))
        except ErroAgroGuard as exc:
            rejeitados.append(RejeicaoLoteItem(indice=indice, codigo=exc.codigo, mensagem=exc.mensagem))

    return LoteResultado(aceitos=aceitos, rejeitados=rejeitados)
