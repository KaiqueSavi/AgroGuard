"""
AgroGuard IA — Serviço de relatórios/tendências (Sprint 3/4)
=============================================================

Agregações sobre `vw_risco_completo` para os paineis de gestão e seguradora
(US04/US07): tendência por equipamento, região ou tipo de operação, e o
ranking dos equipamentos mais arriscados.
"""
from __future__ import annotations

import json
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from agroguard.erros import ErroValidacao


def normalizar_jsonb(valor: Any) -> list[Any]:
    """Normaliza uma coluna JSONB (`fatores_principais`/`recomendacoes`).

    O driver psycopg2 já devolve `list`/`dict` nativos, mas esta função também
    aceita uma string JSON (defensivo contra outro driver/serialização) e
    trata `None`/`NaN` como lista vazia — nunca lança.

    Fonte única: `app.consultas` (dashboard) e `relatorios.gerar_relatorio` (relatório
    semanal) importam esta implementação em vez de duplicá-la.
    """
    if valor is None:
        return []
    if isinstance(valor, float) and pd.isna(valor):
        return []
    if isinstance(valor, list):
        return valor
    if isinstance(valor, dict):
        return [valor]
    if isinstance(valor, str):
        texto = valor.strip()
        if not texto:
            return []
        try:
            carregado = json.loads(texto)
        except (json.JSONDecodeError, TypeError):
            return []
        return carregado if isinstance(carregado, list) else [carregado]
    return []


COLUNA_POR_AGRUPAMENTO = {
    "equipamento": "equip_id",
    "regiao": "regiao",
    "operacao": "tipo_operacao",
}

TRUNC_POR_JANELA = {
    "dia": "day",
    "semana": "week",
}


def tendencias(engine: Engine, por: str, janela: str, limite: int) -> list[dict[str, Any]]:
    """Score médio/pico, nº de alertas e taxa de sinistro por `por` e `janela`.

    `limite` é o número MÁXIMO de chaves (grupos) devolvidas — nunca um limite de linhas.
    Um `LIMIT` direto sobre as linhas já agrupadas por (chave, período) corta o resultado no
    meio de um grupo (ex.: `por=equipamento, limite=100` devolvendo só 6 dos 50 equipamentos,
    porque cada equipamento ocupa várias linhas — uma por período). Em vez disso, escolhem-se
    primeiro as `limite` chaves de maior score médio no período inteiro, e devolvem-se TODOS
    os períodos dessas chaves."""
    coluna = COLUNA_POR_AGRUPAMENTO.get(por)
    if coluna is None:
        raise ErroValidacao(f"'por' deve ser um de {sorted(COLUNA_POR_AGRUPAMENTO)} (recebido '{por}').")

    trunc = TRUNC_POR_JANELA.get(janela)
    if trunc is None:
        raise ErroValidacao(f"'janela' deve ser um de {sorted(TRUNC_POR_JANELA)} (recebido '{janela}').")

    # `coluna`/`trunc` vêm de um dicionário fechado (whitelist) — nunca do texto bruto do
    # usuário — por isso é seguro interpolá-los no SQL.
    query = text(
        f"""
        WITH top_chaves AS (
            SELECT {coluna} AS chave
            FROM vw_risco_completo
            WHERE risco_score IS NOT NULL
            GROUP BY {coluna}
            ORDER BY AVG(risco_score) DESC
            LIMIT :limite
        )
        SELECT
            v.{coluna}                                                       AS chave,
            date_trunc('{trunc}', v.data_hora)                               AS periodo,
            COUNT(*)                                                         AS leituras,
            ROUND(AVG(v.risco_score), 1)                                     AS score_medio,
            MAX(v.risco_score)                                               AS score_pico,
            SUM(CASE WHEN v.alerta THEN 1 ELSE 0 END)                        AS alertas,
            ROUND(100.0 * AVG(CASE WHEN v.sinistro THEN 1 ELSE 0 END), 2)    AS taxa_sinistro_pct
        FROM vw_risco_completo v
        JOIN top_chaves t ON t.chave = v.{coluna}
        WHERE v.risco_score IS NOT NULL
        GROUP BY v.{coluna}, date_trunc('{trunc}', v.data_hora)
        ORDER BY v.{coluna}, periodo
        """
    )
    with engine.connect() as conn:
        linhas = conn.execute(query, {"limite": limite}).mappings().all()
    return [dict(linha) for linha in linhas]


def listar_equipamentos(engine: Engine) -> list[dict[str, Any]]:
    """Frota com o último score/classe conhecido — apoia o painel de gestão (US04)."""
    query = text(
        """
        SELECT
            e.equip_id,
            e.tipo_equip,
            e.fazenda,
            e.regiao,
            v.risco_score  AS ultimo_score,
            v.classe_risco AS ultima_classe,
            v.data_hora    AS ultima_leitura_em
        FROM equipamentos e
        LEFT JOIN LATERAL (
            SELECT risco_score, classe_risco, data_hora
            FROM vw_risco_completo
            WHERE equip_id = e.equip_id AND risco_score IS NOT NULL
            ORDER BY data_hora DESC
            LIMIT 1
        ) v ON TRUE
        ORDER BY e.equip_id
        """
    )
    with engine.connect() as conn:
        linhas = conn.execute(query).mappings().all()
    return [dict(linha) for linha in linhas]


def ranking(engine: Engine, limite: int = 10) -> list[dict[str, Any]]:
    """Ranking dos equipamentos mais arriscados (score médio desc) — apoia US04."""
    query = text(
        """
        SELECT
            equip_id,
            tipo_equip,
            COUNT(*)                                    AS leituras,
            ROUND(AVG(risco_score), 1)                  AS score_medio,
            MAX(risco_score)                            AS score_pico,
            SUM(CASE WHEN alerta THEN 1 ELSE 0 END)      AS alertas_criticos,
            SUM(CASE WHEN sinistro THEN 1 ELSE 0 END)    AS sinistros_reais
        FROM vw_risco_completo
        WHERE risco_score IS NOT NULL
        GROUP BY equip_id, tipo_equip
        ORDER BY score_medio DESC
        LIMIT :limite
        """
    )
    with engine.connect() as conn:
        linhas = conn.execute(query, {"limite": limite}).mappings().all()
    return [dict(linha) for linha in linhas]
