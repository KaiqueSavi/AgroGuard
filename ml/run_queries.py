"""
AgroGuard IA — Executor das consultas analíticas (Sprint 2)
===========================================================

Roda cada bloco de `sql/queries.sql` contra o PostgreSQL e imprime os
resultados formatados. Útil para gerar os prints de execução do relatório
e validar as métricas de risco persistidas.

Uso:
    python ml/run_queries.py
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from db import get_engine

ROOT = Path(__file__).resolve().parents[1]
QUERIES_FILE = ROOT / "sql" / "queries.sql"

TITULOS = {
    "Q1": "Ranking dos equipamentos mais arriscados (US04)",
    "Q2": "Histórico de risco do equipamento EQ-014 (US07)",
    "Q3": "VALIDAÇÃO — taxa de sinistro real por classe prevista",
    "Q4": "Risco por faixa de proximidade de corpo d'água",
    "Q5": "Painel de alertas ativos (score >= 80)",
    "Q6": "Distribuição da frota por classe de risco",
}


def split_queries(sql_text: str) -> list[tuple[str, str]]:
    """Divide o arquivo em (rótulo Qn, statement) usando os comentários '-- Qn'."""
    # Remove comentários de linha mas guarda o rótulo Qn quando aparece
    blocos = []
    atual_label, atual_linhas = None, []
    for linha in sql_text.splitlines():
        m = re.match(r"^--\s*(Q\d+)\b", linha.strip())
        if m:
            if atual_label and atual_linhas:
                blocos.append((atual_label, "\n".join(atual_linhas)))
            atual_label, atual_linhas = m.group(1), []
            continue
        if linha.strip().startswith("--") or not linha.strip():
            continue
        if atual_label:
            atual_linhas.append(linha)
    if atual_label and atual_linhas:
        blocos.append((atual_label, "\n".join(atual_linhas)))

    # Cada bloco pode ter 1 statement (termina em ;)
    out = []
    for label, corpo in blocos:
        for stmt in filter(str.strip, corpo.split(";")):
            out.append((label, stmt.strip() + ";"))
    return out


def main() -> None:
    engine = get_engine()
    sql_text = QUERIES_FILE.read_text(encoding="utf-8")
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 160)

    for label, stmt in split_queries(sql_text):
        titulo = TITULOS.get(label, label)
        print("\n" + "=" * 78)
        print(f"  {label} — {titulo}")
        print("=" * 78)
        try:
            df = pd.read_sql(stmt, engine)
            print(df.to_string(index=False))
        except Exception as exc:  # pragma: no cover
            print(f"  ⚠️ erro: {exc}")


if __name__ == "__main__":
    main()
