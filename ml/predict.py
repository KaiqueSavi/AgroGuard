"""
AgroGuard IA — Inferência e persistência dos scores (Sprint 3-4 / v0.3)
==========================================================================

Score em lote, IDEMPOTENTE, via `ml/inferencia.py` — a mesma função `prever()`
usada pela API. Só processa leituras que AINDA NÃO têm score para a
`modelo_versao` corrente (LEFT JOIN ... WHERE s.id IS NULL): rodar de novo não
duplica nem sobrescreve nada, e rodar após um novo `python -m ml.train`
(nova `modelo_versao`) gera só os scores que faltam.

Regra de alerta: alerta = (risco_score >= ALERT_THRESHOLD)  [80].

Uso:
    python -m ml.predict
    (requer: leituras já carregadas via load_to_db.py e modelos em ml/models/)
"""
from __future__ import annotations

import json

import pandas as pd
from sqlalchemy import text

from ml.db import get_engine
from ml.features import ALERT_THRESHOLD, CLASSES_ORDER, FEATURE_COLUMNS
from ml.inferencia import carregar_modelos, prever

CHUNK_SIZE = 2000


def _tem_coluna_fatores(engine) -> bool:
    """Verifica em information_schema se `scores_risco.fatores_principais`
    existe. O schema v1 (ainda em uso em alguns ambientes de dev) não tem essa
    coluna; o schema v2 (JSONB), sendo adicionado em paralelo, tem."""
    with engine.connect() as conn:
        existe = conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'scores_risco' AND column_name = 'fatores_principais'"
            )
        ).scalar()
    return bool(existe)


def main() -> None:
    engine = get_engine()
    modelos = carregar_modelos()
    modelo_versao = modelos.versao
    tem_fatores = _tem_coluna_fatores(engine)

    # 1) Lê SOMENTE as leituras que ainda não têm score para esta modelo_versao
    #    (join com equipamentos p/ trazer tipo_equip/idade — features que vivem
    #    na tabela equipamentos). Idempotência: 2ª execução processa 0 linhas.
    leituras = pd.read_sql(
        text(
            """
            SELECT l.*, e.tipo_equip, e.idade_equipamento_anos
            FROM leituras_telemetria l
            JOIN equipamentos e ON e.equip_id = l.equip_id
            LEFT JOIN scores_risco s
                   ON s.leitura_id = l.id AND s.modelo_versao = :v
            WHERE s.id IS NULL
            ORDER BY l.id
            """
        ),
        engine,
        params={"v": modelo_versao},
    )

    if leituras.empty:
        print(f"✅ Nada a fazer — todas as leituras já têm score para modelo_versao={modelo_versao!r} (0 inseridos).")
        return

    print(f"📥 {len(leituras):,} leituras sem score para modelo_versao={modelo_versao!r}")

    total_inseridas = 0
    total_alertas = 0
    contagem_classe = {c: 0 for c in CLASSES_ORDER}

    for inicio in range(0, len(leituras), CHUNK_SIZE):
        pedaco = leituras.iloc[inicio: inicio + CHUNK_SIZE]
        faltantes = [c for c in FEATURE_COLUMNS if c not in pedaco.columns]
        if faltantes:
            raise ValueError(f"Colunas de features ausentes na leitura do banco: {faltantes}")

        resultado = prever(modelos, pedaco)

        scores_df = pd.DataFrame({
            "leitura_id": pedaco["id"].values,
            "risco_score": resultado["risco_score"].values,
            "classe_risco": pd.Categorical(resultado["classe_risco"].values, categories=CLASSES_ORDER),
            "alerta": resultado["alerta"].values,
            "modelo_versao": resultado["modelo_versao"].values,
        })
        if tem_fatores:
            scores_df["fatores_principais"] = [
                json.dumps(f, ensure_ascii=False) for f in resultado["fatores_principais"].values
            ]

        with engine.begin() as conn:
            scores_df.to_sql("scores_risco", conn, if_exists="append",
                             index=False, chunksize=CHUNK_SIZE, method="multi")

        total_inseridas += len(scores_df)
        total_alertas += int(scores_df["alerta"].sum())
        for classe, n in scores_df["classe_risco"].value_counts().items():
            contagem_classe[classe] = contagem_classe.get(classe, 0) + int(n)

    print(f"   ✅ {total_inseridas:,} scores gravados em scores_risco (modelo_versao={modelo_versao!r})")
    print(f"   🚨 {total_alertas:,} alertas (score >= {ALERT_THRESHOLD})")
    print("   Distribuição de classe prevista:")
    print(pd.Series(contagem_classe).reindex(CLASSES_ORDER).fillna(0).astype(int).to_string())
    print("✅ Inferência concluída.")


if __name__ == "__main__":
    main()
