"""
AgroGuard IA — Serviço de relatórios/tendências (Sprint 3/4)
=============================================================

Agregações sobre `vw_risco_completo` para os paineis de gestão e seguradora
(US04/US07): tendência por equipamento, região ou tipo de operação, e o
ranking dos equipamentos mais arriscados.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from agroguard.erros import ErroValidacao

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
    """Score médio/pico, nº de alertas e taxa de sinistro por `por` e `janela`."""
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
        SELECT
            {coluna}                                                       AS chave,
            date_trunc('{trunc}', data_hora)                               AS periodo,
            COUNT(*)                                                       AS leituras,
            ROUND(AVG(risco_score), 1)                                     AS score_medio,
            MAX(risco_score)                                               AS score_pico,
            SUM(CASE WHEN alerta THEN 1 ELSE 0 END)                        AS alertas,
            ROUND(100.0 * AVG(CASE WHEN sinistro THEN 1 ELSE 0 END), 2)    AS taxa_sinistro_pct
        FROM vw_risco_completo
        WHERE risco_score IS NOT NULL
        GROUP BY {coluna}, date_trunc('{trunc}', data_hora)
        ORDER BY {coluna}, periodo
        LIMIT :limite
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
