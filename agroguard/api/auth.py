"""
AgroGuard IA — Autenticação, autorização e rate limit (Sprint 3/4)
===================================================================

Cada chamada autenticada carrega um `X-API-Key` (o segredo em claro) que é
hasheado e comparado em tempo constante contra os segredos configurados em
`AGROGUARD_API_KEYS`. A partir da chave válida resolve-se a identidade
(`kid` + `papel`), aplica-se o rate limit por chave e, quando presente,
valida-se a assinatura de integridade `X-Signature` (HMAC-SHA256 do corpo
cru, com o próprio segredo recebido).
"""
from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from enum import Enum
from threading import Lock

from fastapi import Request

from agroguard.config import get_settings
from agroguard.erros import AssinaturaInvalida, LimiteExcedido, NaoAutenticado, NaoAutorizado


class Papel(str, Enum):
    DISPOSITIVO = "dispositivo"
    OPERADOR = "operador"
    GESTOR = "gestor"
    SEGURADORA = "seguradora"
    ADMIN = "admin"


@dataclass
class Identidade:
    kid: str
    papel: Papel


class _BaldeDeTokens:
    """Rate limit em memória (token bucket) por `kid` — um processo, sem estado externo."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._estado: dict[str, tuple[float, float]] = {}

    def permitir(self, kid: str, limite_por_min: int) -> bool:
        if limite_por_min <= 0:
            return True
        agora = time.monotonic()
        taxa_por_seg = limite_por_min / 60.0
        with self._lock:
            tokens, ultimo = self._estado.get(kid, (float(limite_por_min), agora))
            tokens = min(float(limite_por_min), tokens + (agora - ultimo) * taxa_por_seg)
            if tokens < 1.0:
                self._estado[kid] = (tokens, agora)
                return False
            self._estado[kid] = (tokens - 1.0, agora)
            return True

    def resetar(self) -> None:
        with self._lock:
            self._estado.clear()


_balde = _BaldeDeTokens()


def resetar_limitador() -> None:
    """Zera o estado do rate limiter — usado pelos testes."""
    _balde.resetar()


def _resolver_identidade(chave_recebida: str) -> tuple[str, Papel] | None:
    """Compara `chave_recebida` (hasheada) contra os segredos configurados, em tempo constante."""
    hash_recebido = hashlib.sha256(chave_recebida.encode("utf-8")).hexdigest()
    for hash_armazenado, (kid, papel_str) in get_settings().chaves.items():
        if hmac.compare_digest(hash_recebido, hash_armazenado):
            try:
                return kid, Papel(papel_str)
            except ValueError:
                return None
    return None


def exigir_papel(*papeis: Papel):
    """
    Dependência FastAPI: autentica via `X-API-Key`, exige um dos `papeis`
    informados (nenhum = qualquer papel autenticado), aplica o rate limit
    por chave e valida a assinatura de integridade opcional/obrigatória.
    """

    async def dependencia(request: Request) -> Identidade:
        settings = get_settings()

        chave_recebida = request.headers.get("X-API-Key")
        if not chave_recebida:
            raise NaoAutenticado("Cabeçalho X-API-Key ausente.")

        resolvido = _resolver_identidade(chave_recebida)
        if resolvido is None:
            raise NaoAutenticado("Chave de API inválida.")
        kid, papel = resolvido

        if papeis and papel not in papeis:
            raise NaoAutorizado(f"Papel '{papel.value}' não tem acesso a esta rota.")

        if not _balde.permitir(kid, settings.rate_limit_por_min):
            raise LimiteExcedido()

        assinatura = request.headers.get("X-Signature")
        if assinatura is not None:
            corpo = await request.body()
            esperado = hmac.new(chave_recebida.encode("utf-8"), corpo, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(assinatura.strip().lower(), esperado):
                raise AssinaturaInvalida("Assinatura X-Signature não confere com o corpo da requisição.")
        elif papel is Papel.DISPOSITIVO and settings.exigir_assinatura_dispositivo:
            raise AssinaturaInvalida("Assinatura X-Signature é obrigatória para dispositivos.")

        identidade = Identidade(kid=kid, papel=papel)
        request.state.identidade = identidade
        return identidade

    return dependencia
