"""
AgroGuard IA — API (Sprint 3/4)
================================

Monta o FastAPI: middleware de rastreabilidade (request_id + logs_uso),
handlers de erro (mapeando `ErroAgroGuard` e `RequestValidationError` para
`ErroOut`), carga do modelo no startup e o registro das rotas de
telemetria, consulta e auditoria.

Rodar:
    uvicorn agroguard.api.main:app --port 8001
"""
from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from agroguard.api.auth import Identidade, Papel, exigir_papel
from agroguard.api.rotas_auditoria import router as router_auditoria
from agroguard.api.rotas_consulta import router as router_consulta
from agroguard.api.rotas_telemetria import router as router_telemetria
from agroguard.api.schemas import ErroOut
from agroguard.auditoria import servico as auditoria_servico
from agroguard.db import get_engine, ping
from agroguard.erros import ErroAgroGuard
from agroguard.logs import logar
from agroguard.risco import servico as risco_servico
from agroguard.telemetria import servico as telemetria_servico
from ml.inferencia import ModeloIndisponivel as ModeloAusente
from ml.inferencia import carregar_modelos

ROTAS_TELEMETRIA_POST = {"/telemetria", "/telemetria/lote"}


@asynccontextmanager
async def _lifespan(app: FastAPI):
    try:
        app.state.modelos = carregar_modelos()
        app.state.erro_modelos = None
        logar("modelos_carregados", modelo_versao=app.state.modelos.versao)
    except ModeloAusente as exc:
        app.state.modelos = None
        app.state.erro_modelos = str(exc)
        logar("modelo_indisponivel_no_startup", nivel="warning", erro=str(exc))
    yield


def _registrar_uso_seguro(app: FastAPI, request: Request, request_id: str, status_http: int, duracao_ms: int) -> None:
    """Grava `logs_uso`. Uma falha aqui nunca pode derrubar a resposta da requisição."""
    identidade: Identidade | None = getattr(request.state, "identidade", None)
    try:
        auditoria_servico.registrar_uso(
            app.state.engine,
            request_id=request_id,
            kid=identidade.kid if identidade else None,
            papel=identidade.papel.value if identidade else None,
            metodo=request.method,
            rota=request.url.path,
            status_http=status_http,
            duracao_ms=duracao_ms,
            ip=request.client.host if request.client else None,
        )
    except Exception as exc:  # nunca deixar o log de uso derrubar a resposta
        logar("falha_ao_registrar_uso", nivel="warning", erro=str(exc), request_id=request_id)


async def _registrar_rejeicao_validacao(app: FastAPI, request: Request, request_id: str, exc: RequestValidationError) -> None:
    import hashlib
    import json

    identidade: Identidade | None = getattr(request.state, "identidade", None)
    origem = "simulador" if identidade and identidade.kid.startswith("sim") else "api"

    corpo = await request.body()
    payload: dict[str, Any] | None = None
    payload_hash: str | None = None
    if corpo:
        payload_hash = hashlib.sha256(corpo).hexdigest()
        try:
            payload = json.loads(corpo)
        except ValueError:
            payload = None

    try:
        telemetria_servico.registrar_rejeicao(
            app.state.engine,
            codigo="validacao",
            motivo="; ".join(str(e.get("msg", e)) for e in exc.errors()) or "Payload inválido.",
            payload=payload,
            payload_hash=payload_hash,
            request_id=request_id,
            origem=origem,
        )
    except Exception as exc_interno:  # rastreabilidade não pode derrubar a resposta de erro
        logar("falha_ao_registrar_rejeicao", nivel="warning", erro=str(exc_interno), request_id=request_id)


def create_app() -> FastAPI:
    app = FastAPI(title="AgroGuard IA API", version="0.3", lifespan=_lifespan)
    app.state.engine = get_engine()
    app.state.modelos = None
    app.state.erro_modelos = None

    @app.middleware("http")
    async def rastreabilidade(request: Request, call_next):
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        request.state.request_id = request_id
        inicio = time.perf_counter()

        response = await call_next(request)

        duracao_ms = int(round((time.perf_counter() - inicio) * 1000))
        response.headers["X-Request-Id"] = request_id
        _registrar_uso_seguro(app, request, request_id, response.status_code, duracao_ms)
        return response

    @app.exception_handler(ErroAgroGuard)
    async def _erro_negocio(request: Request, exc: ErroAgroGuard) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        return JSONResponse(
            status_code=exc.http_status,
            content=ErroOut(
                codigo=exc.codigo, mensagem=exc.mensagem, request_id=request_id, detalhe=exc.detalhe
            ).model_dump(mode="json"),
        )

    @app.exception_handler(RequestValidationError)
    async def _erro_validacao(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        if request.url.path in ROTAS_TELEMETRIA_POST and request.method == "POST":
            await _registrar_rejeicao_validacao(app, request, request_id, exc)
        return JSONResponse(
            status_code=422,
            content=ErroOut(
                codigo="validacao",
                mensagem="Dados inválidos.",
                request_id=request_id,
                detalhe=exc.errors(),
            ).model_dump(mode="json"),
        )

    @app.exception_handler(Exception)
    async def _erro_generico(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logar("erro_nao_tratado", nivel="error", erro=str(exc), tipo=type(exc).__name__, request_id=request_id)
        return JSONResponse(
            status_code=500,
            content=ErroOut(
                codigo="erro_interno",
                mensagem="Erro interno inesperado.",
                request_id=request_id,
            ).model_dump(mode="json"),
        )

    @app.get("/health", tags=["saude"])
    def health() -> dict[str, Any]:
        banco_ok = ping(app.state.engine)
        modelos_carregados = app.state.modelos is not None
        return {
            "status": "ok" if (banco_ok and modelos_carregados) else "degradado",
            "banco": banco_ok,
            "modelo_versao": app.state.modelos.versao if app.state.modelos else None,
            "modelos_carregados": modelos_carregados,
        }

    @app.get("/modelo/info", tags=["saude"])
    def modelo_info(
        identidade: Identidade = Depends(exigir_papel(Papel.ADMIN, Papel.GESTOR, Papel.SEGURADORA)),
    ) -> dict[str, Any]:
        return risco_servico.info_modelo(app.state.modelos, app.state.erro_modelos)

    app.include_router(router_telemetria)
    app.include_router(router_consulta)
    app.include_router(router_auditoria)

    return app


app = create_app()
