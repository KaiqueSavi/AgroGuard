-- ============================================================================
-- AgroGuard IA — Consultas Analíticas de Risco (Sprint 2)
-- ----------------------------------------------------------------------------
-- Queries que materializam as métricas de risco demandadas pelas User Stories.
-- Rodar:  psql "$DATABASE_URL" -f sql/queries.sql
--    ou:  python ml/run_queries.py   (executa todas e imprime os resultados)
--
-- Mapa User Story → query:
--   US04 (Gestora Marina) → Q1 ranking, Q4 mapa por região, Q5 alertas
--   US07 (Sompo)          → Q2 histórico por equipamento
--   Validação do modelo   → Q3 (taxa de sinistro observada por classe prevista)
-- ============================================================================


-- ----------------------------------------------------------------------------
-- Q1 — Ranking dos equipamentos mais arriscados (US04: priorizar contato)
--      Score médio, pico de risco e nº de alertas críticos por equipamento.
-- ----------------------------------------------------------------------------
SELECT
    v.equip_id,
    v.tipo_equip,
    COUNT(*)                                   AS leituras,
    ROUND(AVG(v.risco_score), 1)               AS score_medio,
    MAX(v.risco_score)                         AS score_pico,
    SUM(CASE WHEN v.alerta THEN 1 ELSE 0 END)  AS alertas_criticos,
    SUM(CASE WHEN v.sinistro THEN 1 ELSE 0 END) AS sinistros_reais
FROM vw_risco_completo v
GROUP BY v.equip_id, v.tipo_equip
ORDER BY score_medio DESC
LIMIT 10;


-- ----------------------------------------------------------------------------
-- Q2 — Histórico de risco de UM equipamento (US07: Sompo precificação)
--      Evolução temporal do score — auditável por leitura.
-- ----------------------------------------------------------------------------
SELECT
    v.data_hora,
    v.risco_score,
    v.classe_risco,
    v.alerta,
    v.precip_24h_mm,
    v.umidade_solo,
    v.dist_corpo_dagua_m,
    v.sinistro,
    v.tipo_sinistro
FROM vw_risco_completo v
WHERE v.equip_id = 'EQ-014'          -- parametrizável
ORDER BY v.data_hora
LIMIT 25;


-- ----------------------------------------------------------------------------
-- Q3 — VALIDAÇÃO: taxa de sinistro REAL observada por classe de risco PREVISTA.
--      Se o modelo é bom, a taxa deve crescer monotonicamente
--      Baixo < Medio < Alto < Critico. Evidência de poder preditivo.
-- ----------------------------------------------------------------------------
SELECT
    v.classe_risco,
    COUNT(*)                                              AS leituras,
    ROUND(AVG(v.risco_score), 1)                          AS score_medio,
    SUM(CASE WHEN v.sinistro THEN 1 ELSE 0 END)           AS sinistros,
    ROUND(100.0 * AVG(CASE WHEN v.sinistro THEN 1 ELSE 0 END), 2) AS taxa_sinistro_pct
FROM vw_risco_completo v
GROUP BY v.classe_risco
ORDER BY CASE v.classe_risco
            WHEN 'Baixo' THEN 1 WHEN 'Medio' THEN 2
            WHEN 'Alto'  THEN 3 WHEN 'Critico' THEN 4 END;


-- ----------------------------------------------------------------------------
-- Q4 — Risco por faixa de proximidade de corpo d'água (US04 + análise crítica).
--      Materializa as faixas da proposta: <50m crítico … >500m baixo.
-- ----------------------------------------------------------------------------
SELECT
    CASE
        WHEN v.dist_corpo_dagua_m < 50  THEN '0-50 m (crítico)'
        WHEN v.dist_corpo_dagua_m < 200 THEN '50-200 m (alto)'
        WHEN v.dist_corpo_dagua_m < 500 THEN '200-500 m (médio)'
        ELSE                                 '> 500 m (baixo)'
    END                                                   AS faixa_dist_agua,
    COUNT(*)                                              AS leituras,
    ROUND(AVG(v.risco_score), 1)                          AS score_medio,
    ROUND(100.0 * AVG(CASE WHEN v.sinistro THEN 1 ELSE 0 END), 2) AS taxa_sinistro_pct
FROM vw_risco_completo v
GROUP BY 1
ORDER BY MIN(v.dist_corpo_dagua_m);


-- ----------------------------------------------------------------------------
-- Q5 — Painel de ALERTAS ativos (US01/US04): leituras com score >= 80.
--      Lista o que o operador/gestor veria como notificação preventiva.
-- ----------------------------------------------------------------------------
SELECT
    v.equip_id,
    v.tipo_equip,
    v.data_hora,
    v.risco_score,
    v.classe_risco,
    v.precip_24h_mm,
    v.umidade_solo,
    v.dist_corpo_dagua_m,
    v.declividade_pct,
    v.tipo_operacao
FROM vw_risco_completo v
WHERE v.alerta IS TRUE
ORDER BY v.risco_score DESC
LIMIT 20;


-- ----------------------------------------------------------------------------
-- Q6 — Distribuição da frota por classe de risco (KPI de cabeçalho do dashboard).
-- ----------------------------------------------------------------------------
SELECT
    v.classe_risco,
    COUNT(*)                                          AS leituras,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct
FROM vw_risco_completo v
GROUP BY v.classe_risco
ORDER BY CASE v.classe_risco
            WHEN 'Baixo' THEN 1 WHEN 'Medio' THEN 2
            WHEN 'Alto'  THEN 3 WHEN 'Critico' THEN 4 END;
