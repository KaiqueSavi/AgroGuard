"""
AgroGuard IA — Ingestão do dataset no PostgreSQL (Sprint 2)
==========================================================

Lê o `synthetic_dataset.csv` e popula as tabelas relacionais:
    equipamentos · leituras_telemetria · sinistros

Os SCORES não são carregados aqui — são gerados pelo modelo em `predict.py`
e gravados na tabela `scores_risco` (separação coleta → inferência).

Uso:
    python ml/load_to_db.py [--csv data/synthetic_dataset.csv]

Pré-requisito: `docker compose up -d db` (schema aplicado automaticamente).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from ml.db import get_engine

ROOT = Path(__file__).resolve().parents[1]


REGIOES = ["Sorriso-MT", "Lucas do Rio Verde-MT", "Sinop-MT"]


def _fazenda_regiao(equip_id: str) -> tuple[str, str]:
    """Deriva fazenda/região deterministicamente a partir do número do equip_id."""
    n = int(equip_id[-3:])
    regiao = REGIOES[n % 3]
    fazenda = f"FAZ-{(n % 6) + 1:02d}"
    return fazenda, regiao


def carregar(csv_path: str) -> None:
    df = pd.read_csv(csv_path)
    print(f"📂 {len(df):,} linhas lidas de {csv_path}")

    engine = get_engine()

    # --- 1) equipamentos (dimensão deduplicada) ---
    equipamentos = (
        df[["equip_id", "tipo_equip", "idade_equipamento_anos"]]
        .drop_duplicates(subset="equip_id")
        .sort_values("equip_id")
        .copy()
    )
    derivado = equipamentos["equip_id"].apply(_fazenda_regiao)
    equipamentos["fazenda"] = derivado.apply(lambda t: t[0])
    equipamentos["regiao"] = derivado.apply(lambda t: t[1])

    # --- 2) leituras_telemetria (fato) ---
    leituras_cols = [
        "id", "equip_id", "data_hora", "latitude", "longitude",
        "velocidade_kmh", "inclinacao_graus", "vibracao_g",
        "precip_24h_mm", "precip_prev_6h_mm", "umidade_solo", "vento_max_kmh",
        "dist_corpo_dagua_m", "declividade_pct",
        "tipo_operacao", "turno", "jornada_acumulada_h",
        "dias_desde_manutencao", "experiencia_operador_anos",
    ]
    leituras = df[leituras_cols].copy()
    leituras["origem"] = "dataset"

    # --- 3) sinistros (rótulo) ---
    sinistros = pd.DataFrame({
        "leitura_id": df["id"],
        "ocorreu": df["sinistro"].astype(bool),
        "tipo_sinistro": df["tipo_sinistro"].replace("", pd.NA),
        "severidade_sinistro": df["severidade_sinistro"].replace("", pd.NA),
    })

    with engine.begin() as conn:
        # Limpa tabelas (re-ingestão idempotente) respeitando FKs
        conn.execute(text(
            "TRUNCATE logs_uso, leituras_rejeitadas, alertas, scores_risco, "
            "sinistros, leituras_telemetria, equipamentos RESTART IDENTITY CASCADE"
        ))

        equipamentos.to_sql("equipamentos", conn, if_exists="append", index=False)
        print(f"   ✅ equipamentos:        {len(equipamentos):>6,}")

        leituras.to_sql("leituras_telemetria", conn, if_exists="append",
                        index=False, chunksize=2000, method="multi")
        print(f"   ✅ leituras_telemetria: {len(leituras):>6,}")

        sinistros.to_sql("sinistros", conn, if_exists="append",
                         index=False, chunksize=2000, method="multi")
        print(f"   ✅ sinistros:           {len(sinistros):>6,}")

        # A carga usa ids explícitos (1..N) — reposiciona a sequência da
        # coluna IDENTITY para que as próximas leituras via API/simulador
        # continuem a numeração sem colidir com o dataset.
        conn.execute(text(
            "SELECT setval(pg_get_serial_sequence('leituras_telemetria', 'id'), "
            "(SELECT max(id) FROM leituras_telemetria))"
        ))

    # Confirma contagens
    with engine.connect() as conn:
        for tab in ("equipamentos", "leituras_telemetria", "sinistros"):
            n = conn.execute(text(f"SELECT COUNT(*) FROM {tab}")).scalar()
            print(f"   • {tab:22s} = {n:,} linhas")

    print("✅ Ingestão concluída.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingestão CSV → PostgreSQL")
    parser.add_argument("--csv", default=str(ROOT / "data" / "synthetic_dataset.csv"))
    args = parser.parse_args()
    carregar(args.csv)


if __name__ == "__main__":
    main()
