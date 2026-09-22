"""
Fixtures compartilhadas da suíte AgroGuard IA.

- modelos_tmp : treina um regressor pequeno (rápido) em pasta temporária e aponta
                AGROGUARD_MODELS_DIR para ela — os testes não dependem dos
                joblib gitignorados de ml/models.
- db_engine   : banco de TESTE `agroguard_test` no PostgreSQL local (porta do .env,
                padrão 5433). Cria o banco se não existir e aplica sql/schema.sql.
                Nunca toca no banco de desenvolvimento `agroguard`.
                Sem AGROGUARD_REQUIRE_DB=1, testes que dependem dele são PULADOS
                com motivo; com a variável, a ausência do banco é FALHA.
- api_client  : TestClient da API com chaves de teste injetadas por env.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Carrega .env (porta do banco etc.) sem sobrescrever variáveis já definidas.
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
except ImportError:  # pragma: no cover
    pass

CSV = ROOT / "data" / "synthetic_dataset.csv"

# Chaves de teste (kid:papel:segredo). Só valem dentro da suíte.
CHAVES_TESTE = {
    "dispositivo": "sim-test-0001",
    "operador": "ope-test-0001",
    "gestor": "ges-test-0001",
    "seguradora": "seg-test-0001",
    "admin": "adm-test-0001",
}
os.environ.setdefault(
    "AGROGUARD_API_KEYS",
    ",".join(f"{p[:3]}01:{p}:{s}" for p, s in CHAVES_TESTE.items()),
)


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def modelos_tmp(tmp_path_factory) -> Path:
    """Treina um regressor pequeno (~2 s) e devolve a pasta com os artefatos."""
    import json

    import joblib
    import pandas as pd
    from sklearn.compose import ColumnTransformer
    from sklearn.ensemble import GradientBoostingRegressor
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder

    from ml.features import CATEGORICAL_FEATURES, FEATURE_COLUMNS, NUMERIC_FEATURES, TARGET_SCORE

    pasta = tmp_path_factory.mktemp("modelos")
    df = pd.read_csv(CSV).sample(n=1000, random_state=42)
    prep = ColumnTransformer(
        [("num", "passthrough", NUMERIC_FEATURES),
         ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES)]
    )
    pipe = Pipeline([("prep", prep), ("model", GradientBoostingRegressor(n_estimators=50, random_state=42))])
    pipe.fit(df[FEATURE_COLUMNS], df[TARGET_SCORE].astype(float))
    joblib.dump(pipe, pasta / "reg_score.joblib")

    baseline = {c: float(df[c].median()) for c in NUMERIC_FEATURES}
    baseline.update({c: str(df[c].mode().iloc[0]) for c in CATEGORICAL_FEATURES})
    (pasta / "baseline_features.json").write_text(json.dumps(baseline), encoding="utf-8")
    (pasta / "model_meta.json").write_text(json.dumps({"modelo_versao": "vtest"}), encoding="utf-8")

    os.environ["AGROGUARD_MODELS_DIR"] = str(pasta)
    return pasta


# ---------------------------------------------------------------------------
# Banco de teste
# ---------------------------------------------------------------------------
def _url_base(db: str) -> str:
    user = os.getenv("POSTGRES_USER", "agroguard")
    pwd = os.getenv("POSTGRES_PASSWORD", "agroguard")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5433")
    return f"postgresql+psycopg2://{user}:{pwd}@{host}:{port}/{db}"


TEST_DB = "agroguard_test"


@pytest.fixture(scope="session")
def db_engine():
    """Engine apontada para `agroguard_test`, com o schema aplicado."""
    from sqlalchemy import create_engine, text

    exigir = os.getenv("AGROGUARD_REQUIRE_DB") == "1"
    try:
        admin = create_engine(_url_base("postgres"), isolation_level="AUTOCOMMIT", pool_pre_ping=True)
        with admin.connect() as conn:
            existe = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": TEST_DB}
            ).scalar()
            if not existe:
                conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    except Exception as exc:  # banco fora do ar
        if exigir:
            raise
        pytest.skip(f"PostgreSQL local indisponível ({exc.__class__.__name__}); defina AGROGUARD_REQUIRE_DB=1 para exigir.")

    url = _url_base(TEST_DB)
    os.environ["DATABASE_URL"] = url
    engine = create_engine(url, pool_pre_ping=True)
    schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    with engine.begin() as conn:
        conn.exec_driver_sql(schema)
    yield engine
    engine.dispose()


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def api_client(db_engine, modelos_tmp):
    """TestClient da API (importado tardiamente: o pacote agroguard é criado pela U1)."""
    from fastapi.testclient import TestClient

    from agroguard.api.main import create_app

    with TestClient(create_app()) as client:
        yield client


@pytest.fixture
def chaves() -> dict[str, str]:
    """Segredos por papel para montar o header X-API-Key nos testes."""
    return dict(CHAVES_TESTE)
