"""
AgroGuard IA — Rotas de auditoria (Sprint 3/4)
================================================

Trilha de uso e de rejeições — acesso restrito a `admin`. HTTP puro: toda a
consulta vive em `auditoria.servico`.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from agroguard.api.auth import Identidade, Papel, exigir_papel
from agroguard.api.schemas import LogUsoOut, RejeicaoOut
from agroguard.auditoria import servico as auditoria_servico

router = APIRouter(prefix="/auditoria", tags=["auditoria"])


@router.get("/logs", response_model=list[LogUsoOut])
def logs(
    request: Request,
    limite: int = Query(default=100, ge=1, le=1000),
    identidade: Identidade = Depends(exigir_papel(Papel.ADMIN)),
) -> list[LogUsoOut]:
    linhas = auditoria_servico.listar_logs(request.app.state.engine, limite)
    return [LogUsoOut(**linha) for linha in linhas]


@router.get("/rejeitadas", response_model=list[RejeicaoOut])
def rejeitadas(
    request: Request,
    limite: int = Query(default=100, ge=1, le=1000),
    identidade: Identidade = Depends(exigir_papel(Papel.ADMIN)),
) -> list[RejeicaoOut]:
    linhas = auditoria_servico.listar_rejeitadas(request.app.state.engine, limite)
    return [RejeicaoOut(**linha) for linha in linhas]


@router.get("/{request_id}")
def rastrear(
    request_id: str,
    request: Request,
    identidade: Identidade = Depends(exigir_papel(Papel.ADMIN)),
) -> dict[str, Any]:
    return auditoria_servico.rastrear(request.app.state.engine, request_id)
