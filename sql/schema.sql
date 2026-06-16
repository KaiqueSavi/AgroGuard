-- ============================================================================
-- AgroGuard IA — Schema do Banco de Dados (Sprint 2)
-- ----------------------------------------------------------------------------
-- PostgreSQL 16. Modela a persistência da telemetria coletada no campo, os
-- sinistros históricos e os scores de risco gerados pelo motor de ML.
--
-- Aplicado AUTOMATICAMENTE pelo docker-compose na 1ª subida do container
-- (montado em /docker-entrypoint-initdb.d/). Para aplicar manualmente:
--   psql "$DATABASE_URL" -f sql/schema.sql
--
-- Modelo relacional (3FN):
--   equipamentos    1 ─── N  leituras_telemetria
--   leituras_telemetria 1 ─ 1  scores_risco   (score gerado pelo modelo)
--   leituras_telemetria 1 ─ 0/1 sinistros      (rótulo histórico do evento)
-- ============================================================================

-- Idempotência: permite re-rodar o script em dev sem erro.
DROP TABLE IF EXISTS scores_risco       CASCADE;
DROP TABLE IF EXISTS sinistros          CASCADE;
DROP TABLE IF EXISTS leituras_telemetria CASCADE;
DROP TABLE IF EXISTS equipamentos       CASCADE;

-- ----------------------------------------------------------------------------
-- 1) Frota de equipamentos (dimensão)
-- ----------------------------------------------------------------------------
CREATE TABLE equipamentos (
    equip_id                VARCHAR(10) PRIMARY KEY,             -- ex.: 'EQ-014'
    tipo_equip              VARCHAR(20) NOT NULL,                -- Colheitadeira | Trator | Pulverizador | Caminhão
    idade_equipamento_anos  SMALLINT NOT NULL CHECK (idade_equipamento_anos BETWEEN 0 AND 60),
    CONSTRAINT chk_tipo_equip CHECK (
        tipo_equip IN ('Colheitadeira', 'Trator', 'Pulverizador', 'Caminhão')
    )
);

COMMENT ON TABLE  equipamentos IS 'Cadastro da frota — uma linha por equipamento.';
COMMENT ON COLUMN equipamentos.equip_id IS 'Identificador único do equipamento (EQ-XXX).';

-- ----------------------------------------------------------------------------
-- 2) Leituras de telemetria + contexto ambiental/operacional (fato)
-- ----------------------------------------------------------------------------
CREATE TABLE leituras_telemetria (
    id                          BIGINT PRIMARY KEY,              -- id do dataset (1..N)
    equip_id                    VARCHAR(10) NOT NULL REFERENCES equipamentos(equip_id),
    data_hora                   TIMESTAMP   NOT NULL,

    -- Geolocalização (GPS embarcado)
    latitude                    DOUBLE PRECISION NOT NULL,
    longitude                   DOUBLE PRECISION NOT NULL,

    -- Telemetria do equipamento (IoT)
    velocidade_kmh              NUMERIC(6,1)  NOT NULL,
    inclinacao_graus            NUMERIC(5,1)  NOT NULL,
    vibracao_g                  NUMERIC(5,2)  NOT NULL,

    -- Variáveis climáticas / ambientais (API de clima + bases públicas)
    precip_24h_mm               NUMERIC(6,1)  NOT NULL,
    precip_prev_6h_mm           NUMERIC(6,1)  NOT NULL,
    umidade_solo                NUMERIC(4,2)  NOT NULL CHECK (umidade_solo BETWEEN 0 AND 1),
    vento_max_kmh               NUMERIC(6,1)  NOT NULL,

    -- Geografia / topografia (MapBiomas/ANA + SRTM/EMBRAPA)
    dist_corpo_dagua_m          INTEGER       NOT NULL CHECK (dist_corpo_dagua_m >= 0),
    declividade_pct             NUMERIC(5,2)  NOT NULL,

    -- Contexto operacional
    tipo_operacao               VARCHAR(15)   NOT NULL,          -- campo | transporte | parado
    turno                       VARCHAR(10)   NOT NULL,          -- manha | tarde | noite
    jornada_acumulada_h         NUMERIC(5,1)  NOT NULL,
    dias_desde_manutencao       SMALLINT      NOT NULL,
    experiencia_operador_anos   SMALLINT      NOT NULL,

    CONSTRAINT chk_tipo_operacao CHECK (tipo_operacao IN ('campo', 'transporte', 'parado')),
    CONSTRAINT chk_turno         CHECK (turno IN ('manha', 'tarde', 'noite'))
);

COMMENT ON TABLE leituras_telemetria IS
    'Leitura instantânea de um equipamento: telemetria IoT + enriquecimento ambiental/operacional.';

-- Índices para as consultas de risco mais frequentes (ranking, histórico, mapa)
CREATE INDEX idx_leituras_equip       ON leituras_telemetria (equip_id);
CREATE INDEX idx_leituras_data_hora   ON leituras_telemetria (data_hora);
CREATE INDEX idx_leituras_dist_agua   ON leituras_telemetria (dist_corpo_dagua_m);

-- ----------------------------------------------------------------------------
-- 3) Scores de risco gerados pelo modelo de ML (fato derivado)
-- ----------------------------------------------------------------------------
CREATE TABLE scores_risco (
    id              BIGSERIAL PRIMARY KEY,
    leitura_id      BIGINT NOT NULL REFERENCES leituras_telemetria(id) ON DELETE CASCADE,
    risco_score     SMALLINT NOT NULL CHECK (risco_score BETWEEN 0 AND 100),
    classe_risco    VARCHAR(10) NOT NULL,                        -- Baixo | Medio | Alto | Critico
    alerta          BOOLEAN NOT NULL DEFAULT FALSE,              -- TRUE quando score >= limiar (80)
    modelo_versao   VARCHAR(20) NOT NULL DEFAULT 'v0.2',
    gerado_em       TIMESTAMP   NOT NULL DEFAULT now(),
    CONSTRAINT chk_classe_risco CHECK (classe_risco IN ('Baixo', 'Medio', 'Alto', 'Critico')),
    CONSTRAINT uq_score_por_leitura UNIQUE (leitura_id, modelo_versao)
);

COMMENT ON TABLE scores_risco IS
    'Score de risco (0–100) e classe previstos pelo modelo para cada leitura. alerta=TRUE dispara notificação.';

CREATE INDEX idx_scores_leitura  ON scores_risco (leitura_id);
CREATE INDEX idx_scores_classe   ON scores_risco (classe_risco);
CREATE INDEX idx_scores_alerta   ON scores_risco (alerta) WHERE alerta IS TRUE;

-- ----------------------------------------------------------------------------
-- 4) Sinistros históricos (rótulo / ground-truth)
-- ----------------------------------------------------------------------------
CREATE TABLE sinistros (
    id                  BIGSERIAL PRIMARY KEY,
    leitura_id          BIGINT NOT NULL REFERENCES leituras_telemetria(id) ON DELETE CASCADE,
    ocorreu             BOOLEAN NOT NULL,                        -- houve sinistro nesta leitura?
    tipo_sinistro       VARCHAR(15),                            -- atolamento|colisao|tombamento|mecanico (NULL se não ocorreu)
    severidade_sinistro VARCHAR(15),                            -- leve|moderado|grave|perda_total
    CONSTRAINT uq_sinistro_por_leitura UNIQUE (leitura_id)
);

COMMENT ON TABLE sinistros IS
    'Registro histórico de sinistro associado a uma leitura (usado como rótulo de treino e validação).';

CREATE INDEX idx_sinistros_leitura ON sinistros (leitura_id);
CREATE INDEX idx_sinistros_ocorreu ON sinistros (ocorreu);

-- ----------------------------------------------------------------------------
-- 5) View de conveniência: leitura + score + sinistro (1 linha por leitura)
--    Simplifica o dashboard e as queries analíticas.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_risco_completo AS
SELECT
    l.id,
    l.equip_id,
    e.tipo_equip,
    e.idade_equipamento_anos,
    l.data_hora,
    l.latitude,
    l.longitude,
    l.velocidade_kmh,
    l.vibracao_g,
    l.precip_24h_mm,
    l.umidade_solo,
    l.dist_corpo_dagua_m,
    l.declividade_pct,
    l.tipo_operacao,
    l.turno,
    l.jornada_acumulada_h,
    l.dias_desde_manutencao,
    s.risco_score,
    s.classe_risco,
    s.alerta,
    COALESCE(si.ocorreu, FALSE) AS sinistro,
    si.tipo_sinistro,
    si.severidade_sinistro
FROM leituras_telemetria l
JOIN equipamentos e        ON e.equip_id = l.equip_id
LEFT JOIN scores_risco s   ON s.leitura_id = l.id
LEFT JOIN sinistros si     ON si.leitura_id = l.id;

COMMENT ON VIEW vw_risco_completo IS
    'Visão consolidada (leitura + score do modelo + sinistro) — base do dashboard e das análises.';
