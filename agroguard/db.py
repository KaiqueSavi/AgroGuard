"""
AgroGuard IA — Engine e schema do banco para a API (Sprint 3/4)
================================================================

CLI:
    python -m agroguard.db --ping             # testa a conexão
    python -m agroguard.db --aplicar-schema    # aplica sql/schema.sql
"""
from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine, create_engine

from agroguard.config import get_settings

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "sql" / "schema.sql"


def get_engine(echo: bool = False) -> Engine:
    """Cria a engine SQLAlchemy da API (pool_pre_ping evita conexões mortas)."""
    return create_engine(get_settings().database_url, echo=echo, pool_pre_ping=True)


def aplicar_schema(engine: Engine, path: Path = SCHEMA_PATH) -> None:
    """Aplica (idempotentemente) o schema SQL na engine informada."""
    sql = path.read_text(encoding="utf-8")
    with engine.begin() as conn:
        conn.exec_driver_sql(sql)


def ping(engine: Engine | None = None) -> bool:
    """Retorna True se o banco responde."""
    eng = engine or get_engine()
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Utilitários de banco da API AgroGuard")
    parser.add_argument("--ping", action="store_true", help="Testa a conexão com o banco")
    parser.add_argument("--aplicar-schema", action="store_true", help="Aplica sql/schema.sql")
    args = parser.parse_args()

    engine = get_engine()
    settings = get_settings()

    if args.aplicar_schema:
        aplicar_schema(engine)
        print("✅ Schema aplicado.")

    if args.ping or not (args.aplicar_schema):
        ok = ping(engine)
        host = settings.database_url.split("@")[-1]
        print(f"Banco: {host} — acessível: {ok}")
        if not ok:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
