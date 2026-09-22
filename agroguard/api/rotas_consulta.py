"""
AgroGuard IA — Rotas de consulta (Sprint 3/4)
==============================================

Painéis de gestão, seguradora e administração: frota, histórico de score
por equipamento, alertas e tendências. HTTP puro — toda a agregação vive
em `relatorios.servico`, `risco.servico` e `alertas.servico`.
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request

from agroguard.alertas import servico as alertas_servico
from agroguard.api.auth import Identidade, Papel, exigir_papel
from agroguard.api.schemas import AlertaOut, TendenciaOut
from agroguard.relatorios import servico as relatorios_servico
from agroguard.risco import servico as risco_servico

router = APIRouter(tags=["consulta"])

_PAPEIS_CONSULTA = (Papel.GESTOR, Papel.SEGURADORA, Papel.ADMIN)


@router.get("/equipamentos")
def listar_equipamentos(
    request: Request,
    identidade: Identidade = Depends(exigir_papel(*_PAPEIS_CONSULTA)),
) -> list[dict[str, Any]]:
    return relatorios_servico.listar_equipamentos(request.app.state.engine)


@router.get("/equipamentos/{equip_id}/scores")
def historico_scores(
    equip_id: str,
    request: Request,
    limite: int = Query(default=100, ge=1, le=1000),
    identidade: Identidade = Depends(exigir_papel(*_PAPEIS_CONSULTA)),
) -> list[dict[str, Any]]:
    return risco_servico.historico_scores(request.app.state.engine, equip_id, limite)


@router.get("/alertas", response_model=list[AlertaOut])
def listar_alertas(
    request: Request,
    status: str | None = Query(default=None),
    limite: int = Query(default=50, ge=1, le=500),
    identidade: Identidade = Depends(exigir_papel(*_PAPEIS_CONSULTA)),
) -> list[AlertaOut]:
    with request.app.state.engine.connect() as conn:
        linhas = alertas_servico.listar(conn, status, limite)
    return [AlertaOut(**linha) for linha in linhas]


@router.post("/alertas/{id_alerta}/reconhecer", response_model=AlertaOut)
def reconhecer_alerta(
    id_alerta: int,
    request: Request,
    identidade: Identidade = Depends(exigir_papel(Papel.GESTOR, Papel.ADMIN)),
) -> AlertaOut:
    with request.app.state.engine.begin() as conn:
        linha = alertas_servico.reconhecer(conn, id_alerta)
    return AlertaOut(**linha)


@router.get("/relatorios/tendencias", response_model=list[TendenciaOut])
def tendencias(
    request: Request,
    por: Literal["equipamento", "regiao", "operacao"] = Query(...),
    janela: Literal["dia", "semana"] = Query(default="semana"),
    limite: int = Query(default=100, ge=1, le=1000),
    identidade: Identidade = Depends(exigir_papel(*_PAPEIS_CONSULTA)),
) -> list[TendenciaOut]:
    linhas = relatorios_servico.tendencias(request.app.state.engine, por, janela, limite)
    return [
        TendenciaOut(
            chave=str(linha["chave"]),
            periodo=linha["periodo"],
            leituras=linha["leituras"],
            score_medio=float(linha["score_medio"] or 0),
            score_pico=int(linha["score_pico"] or 0),
            alertas=int(linha["alertas"] or 0),
            taxa_sinistro_pct=float(linha["taxa_sinistro_pct"] or 0),
        )
        for linha in linhas
    ]
