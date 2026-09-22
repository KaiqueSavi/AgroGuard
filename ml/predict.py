"""
AgroGuard IA — Inferência e persistência dos scores (Sprint 2)
==============================================================

Carrega o classificador de classe e o regressor de score treinados, gera as
predições para TODAS as leituras de telemetria do banco e grava em `scores_risco`.
É a etapa "modelo → banco" do pipeline (coleta → modelo → saída).

Regra de alerta: alerta = (risco_score >= ALERT_THRESHOLD)  [80].

Uso:
    python ml/predict.py
    (requer: leituras já carregadas via load_to_db.py e modelos em ml/models/)
"""
from __future__ import annotations

from pathlib import Path

import joblib
import pandas as pd
from sqlalchemy import text

from ml.db import get_engine
from ml.features import FEATURE_COLUMNS, ALERT_THRESHOLD, MODEL_VERSION, CLASSES_ORDER

ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT / "ml" / "models"


def main() -> None:
    engine = get_engine()

    # 1) Lê as leituras do banco (join com a dimensão equipamentos p/ trazer
    #    tipo_equip e idade — features que vivem na tabela equipamentos).
    leituras = pd.read_sql(
        """
        SELECT l.*, e.tipo_equip, e.idade_equipamento_anos
        FROM leituras_telemetria l
        JOIN equipamentos e ON e.equip_id = l.equip_id
        ORDER BY l.id
        """,
        engine,
    )
    if leituras.empty:
        raise SystemExit("❌ Nenhuma leitura no banco. Rode `python ml/load_to_db.py` antes.")
    print(f"📥 {len(leituras):,} leituras lidas do banco")

    # 2) Carrega modelos
    clf = joblib.load(MODELS_DIR / "clf_classe.joblib")
    reg = joblib.load(MODELS_DIR / "reg_score.joblib")

    X = leituras[FEATURE_COLUMNS].copy()

    # 3) Prediz score (regressão) e classe (classificação)
    score = reg.predict(X).clip(0, 100).round().astype(int)
    classe = clf.predict(X)

    scores_df = pd.DataFrame({
        "leitura_id": leituras["id"].values,
        "risco_score": score,
        "classe_risco": pd.Categorical(classe, categories=CLASSES_ORDER),
        "alerta": score >= ALERT_THRESHOLD,
        "modelo_versao": MODEL_VERSION,
    })

    # 4) Persiste em scores_risco (substitui scores anteriores desta versão)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM scores_risco WHERE modelo_versao = :v"),
                     {"v": MODEL_VERSION})
        scores_df.to_sql("scores_risco", conn, if_exists="append",
                         index=False, chunksize=2000, method="multi")

    n_alertas = int(scores_df["alerta"].sum())
    print(f"   ✅ {len(scores_df):,} scores gravados em scores_risco")
    print(f"   🚨 {n_alertas:,} alertas (score >= {ALERT_THRESHOLD})")
    print("   Distribuição de classe prevista:")
    print(scores_df["classe_risco"].value_counts().reindex(CLASSES_ORDER).fillna(0).astype(int).to_string())
    print("✅ Inferência concluída.")


if __name__ == "__main__":
    main()
