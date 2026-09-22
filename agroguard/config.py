"""
AgroGuard IA — Configuração da API (Sprint 3/4)
================================================

Fonte única das variáveis de ambiente usadas pelo backend integrador.
Reaproveita a mesma resolução de `DATABASE_URL` de `ml/db.py` para não
duplicar a string de conexão entre o pipeline de ML e a API.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from ml.features import ALERT_THRESHOLD

ROOT = Path(__file__).resolve().parents[1]

try:
    from dotenv import load_dotenv

    _ENV_PATH = ROOT / ".env"
    if _ENV_PATH.exists():
        load_dotenv(_ENV_PATH, override=False)
except ImportError:  # pragma: no cover
    pass


def _resolver_database_url() -> str:
    """Mesma ordem de resolução de `ml.db.get_database_url`."""
    url = os.getenv("DATABASE_URL")
    if url:
        return url

    user = os.getenv("POSTGRES_USER", "agroguard")
    password = os.getenv("POSTGRES_PASSWORD", "agroguard")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "agroguard")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"


_PAPEIS_VALIDOS = {"dispositivo", "operador", "gestor", "seguradora", "admin"}


def _parse_chaves(bruto: str) -> dict[str, tuple[str, str]]:
    """
    Converte "kid:papel:segredo,kid:papel:segredo,..." em um dicionário
    {sha256(segredo): (kid, papel)} — nunca guardamos o segredo em claro.

    Uma entrada malformada NUNCA é silenciosamente ignorada — uma chave que devia existir e
    não existe (porque o parsing a descartou) é um jeito difícil de descobrir de trancar uma
    integração inteira fora da API. `ValueError` interrompe a configuração cedo, com uma
    mensagem que diz exatamente qual entrada e por quê.

    Cada entrada precisa ter exatamente 3 partes (kid, papel, segredo), separadas por ':' —
    por isso o segredo NÃO PODE conter ':' (quebraria a contagem de partes) nem ',' (é o
    separador entre entradas: um segredo com vírgula seria interpretado como duas entradas
    distintas). `papel` precisa ser um dos papéis conhecidos, e nem `kid` nem o segredo (já
    hasheado) podem se repetir entre entradas.
    """
    chaves: dict[str, tuple[str, str]] = {}
    kids_vistos: set[str] = set()
    for item in bruto.split(","):
        item = item.strip()
        if not item:
            continue
        partes = item.split(":")
        if len(partes) != 3:
            raise ValueError(
                f"Entrada inválida em AGROGUARD_API_KEYS (esperado 'kid:papel:segredo', sem ':' "
                f"extra no segredo): '{item}'."
            )
        kid, papel, segredo = (p.strip() for p in partes)
        if not kid or not papel or not segredo:
            raise ValueError(
                f"Entrada inválida em AGROGUARD_API_KEYS: kid, papel e segredo não podem ser "
                f"vazios (entrada: '{item}')."
            )
        if papel not in _PAPEIS_VALIDOS:
            raise ValueError(
                f"Papel '{papel}' desconhecido em AGROGUARD_API_KEYS (esperado um de "
                f"{sorted(_PAPEIS_VALIDOS)}; entrada: '{item}')."
            )
        if kid in kids_vistos:
            raise ValueError(f"kid '{kid}' duplicado em AGROGUARD_API_KEYS.")
        hash_segredo = hashlib.sha256(segredo.encode("utf-8")).hexdigest()
        if hash_segredo in chaves:
            raise ValueError(f"Segredo duplicado em AGROGUARD_API_KEYS (kid '{kid}').")
        kids_vistos.add(kid)
        chaves[hash_segredo] = (kid, papel)
    return chaves


@dataclass
class Settings:
    """Configuração resolvida da API — carregada uma vez e cacheada."""

    database_url: str = field(default_factory=_resolver_database_url)
    api_port: int = field(default_factory=lambda: int(os.getenv("API_PORT", "8001")))
    limiar_alerta: int = ALERT_THRESHOLD
    rate_limit_por_min: int = field(
        default_factory=lambda: int(os.getenv("RATE_LIMIT_POR_MIN", "120"))
    )
    exigir_assinatura_dispositivo: bool = field(
        default_factory=lambda: os.getenv("AGROGUARD_EXIGIR_ASSINATURA") == "1"
    )
    chaves: dict[str, tuple[str, str]] = field(
        default_factory=lambda: _parse_chaves(os.getenv("AGROGUARD_API_KEYS", ""))
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Configuração cacheada por processo."""
    return Settings()


def recarregar() -> Settings:
    """Limpa o cache e recarrega a configuração — usado pelos testes."""
    get_settings.cache_clear()
    return get_settings()
