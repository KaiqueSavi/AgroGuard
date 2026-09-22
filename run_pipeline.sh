#!/usr/bin/env bash
# ============================================================================
# AgroGuard IA — Pipeline completo de dados + IA (Sprint 2)
# ----------------------------------------------------------------------------
# Executa, em ordem, todo o fluxo: gera dataset → sobe banco → ingere →
# EDA → treina/valida modelos → gera scores → roda queries de risco.
#
# Pré-requisitos:
#   - Docker em execução
#   - venv ativo com requirements.txt instalado  (source .venv/bin/activate)
#
# Uso:
#   ./run_pipeline.sh
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

echo "════════════════════════════════════════════════════════════════"
echo "  AgroGuard IA — Pipeline Sprint 2"
echo "════════════════════════════════════════════════════════════════"

echo -e "\n▶ [1/7] Subindo PostgreSQL (Docker)…"
docker compose up -d db
until docker exec agroguard_db pg_isready -U "${POSTGRES_USER:-agroguard}" >/dev/null 2>&1; do
  sleep 1
done
echo "  ✔ banco pronto"

echo -e "\n▶ [2/7] Gerando dataset simulado (seed=42)…"
python data/generate_dataset.py --seed 42 --out data/synthetic_dataset.csv

echo -e "\n▶ [3/7] Ingestão do CSV no PostgreSQL…"
python -m ml.load_to_db

echo -e "\n▶ [4/7] Análise exploratória (EDA)…"
python -m ml.eda

echo -e "\n▶ [5/7] Treino + validação dos modelos…"
python -m ml.train --seed 42

echo -e "\n▶ [6/7] Inferência → grava scores no banco…"
python -m ml.predict

echo -e "\n▶ [7/7] Consultas analíticas de risco…"
python -m ml.run_queries

echo -e "\n✅ Pipeline concluído."
echo "   Dashboard:  streamlit run app/streamlit_app.py"
