"""
AgroGuard IA — Helper de conexão com o banco (Sprint 2)
=======================================================

Centraliza a criação da engine SQLAlchemy a partir das variáveis de ambiente
(.env). Todos os scripts (load_to_db, predict, run_queries, dashboard) importam
daqui para não duplicar a string de conexão.

Ordem de resolução:
    1. DATABASE_URL  (se definido explicitamente)
    2. POSTGRES_*    (monta postgresql+psycopg2://user:pass@host:port/db)
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

# Carrega .env se python-dotenv estiver disponível (opcional).
try:
    from dotenv import load_dotenv

    _ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
    if _ENV_PATH.exists():
        load_dotenv(_ENV_PATH)
except ImportError:  # pragma: no cover
    pass


def get_database_url() -> str:
    """Resolve a URL de conexão a partir do ambiente, com defaults de dev."""
    url = os.getenv("DATABASE_URL")
    if url:
        return url

    user = os.getenv("POSTGRES_USER", "agroguard")
    password = os.getenv("POSTGRES_PASSWORD", "agroguard")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "agroguard")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"


def get_engine(echo: bool = False) -> Engine:
    """Cria a engine SQLAlchemy (pool_pre_ping evita conexões mortas)."""
    return create_engine(get_database_url(), echo=echo, pool_pre_ping=True)


def ping() -> bool:
    """Retorna True se o banco responde. Útil para fallback no dashboard."""
    from sqlalchemy import text

    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


if __name__ == "__main__":
    print(f"DATABASE_URL = {get_database_url()}")
    print(f"Banco acessível: {ping()}")
