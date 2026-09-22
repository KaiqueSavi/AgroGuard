"""
AgroGuard IA — Acesso a dados do dashboard (Sprint 4)
=======================================================

Único módulo do dashboard (`app/streamlit_app.py`) que executa SQL ou lê o
CSV de fallback. As telas do Streamlit só chamam funções daqui — nenhum
outro arquivo do pacote `app` monta consulta própria.

Fontes de verdade reaproveitadas (nunca duplicadas aqui):
    - `agroguard.relatorios.servico` — tendências, ranking e frota (Q7–Q9).
    - `ml.db` — engine/ping do PostgreSQL.
    - `ml.features` — limiar de alerta.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy import text
from sqlalchemy.engine import Engine

from agroguard.logs import logar
from agroguard.relatorios import servico as relatorios_servico
from ml.features import ALERT_THRESHOLD

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "synthetic_dataset.csv"

# Reexportado: `agroguard.relatorios.servico.normalizar_jsonb` é a implementação única —
# o relatório semanal (`relatorios.gerar_relatorio`) importa a mesma função, nunca uma cópia.
normalizar_jsonb = relatorios_servico.normalizar_jsonb


def _resolver_engine(engine: Engine | None) -> Engine:
    """Usa a engine recebida ou cria uma nova a partir de `ml.db` (env)."""
    if engine is not None:
        return engine
    from ml.db import get_engine

    return get_engine()


@st.cache_data(ttl=60, show_spinner=False, hash_funcs={Engine: id})
def carregar_visao(engine: Engine | None = None) -> tuple[pd.DataFrame, str]:
    """Tenta o PostgreSQL (`vw_risco_completo`); cai para o CSV sintético.

    Devolve `(df, fonte)`, onde `fonte` descreve de onde os dados vieram —
    usado no cabeçalho do dashboard e para decidir se abas que exigem banco
    (Alertas/Auditoria) podem operar em modo completo.
    """
    banco_acessivel = False
    try:
        from ml.db import ping

        if ping():
            banco_acessivel = True
            eng = _resolver_engine(engine)
            df = pd.read_sql("SELECT * FROM vw_risco_completo ORDER BY data_hora", eng)
            if not df.empty and df["risco_score"].notna().any():
                df["data_hora"] = pd.to_datetime(df["data_hora"])
                df["fatores_principais"] = df["fatores_principais"].apply(normalizar_jsonb)
                df["recomendacoes"] = df["recomendacoes"].apply(normalizar_jsonb)
                return df, "PostgreSQL (vw_risco_completo)"
    except Exception as exc:
        banco_acessivel = False
        logar("consulta_dashboard_falhou", nivel="warning", funcao="carregar_visao", erro=str(exc))

    df = pd.read_csv(CSV_PATH)
    df["data_hora"] = pd.to_datetime(df["data_hora"])
    df["alerta"] = df["risco_score"] >= ALERT_THRESHOLD
    for coluna, default in (("fazenda", "—"), ("regiao", "—")):
        if coluna not in df.columns:
            df[coluna] = default
    df["fatores_principais"] = [[] for _ in range(len(df))]
    df["recomendacoes"] = [[] for _ in range(len(df))]
    if banco_acessivel:
        # Banco respondeu, mas a view não tem nenhum score ainda (ex.: leituras existem,
        # mas `python -m ml.predict` nunca rodou) — não é a mesma situação de "banco fora
        # do ar", e o rótulo não deveria dizer isso.
        fonte = "CSV (fallback — banco acessível, mas sem scores; rode python -m ml.predict)"
    else:
        fonte = "CSV (fallback — banco indisponível)"
    return df, fonte


def alertas_derivados(df: pd.DataFrame, limite: int = 50) -> pd.DataFrame:
    """Deriva os alertas ativos a partir de `vw_risco_completo` (`alerta = TRUE`).

    Usado quando a tabela `alertas` está vazia porque nenhuma leitura chegou
    ainda pelo caminho da API — não executa SQL, apenas filtra o `df` já
    carregado por `carregar_visao`.
    """
    if df.empty or "alerta" not in df.columns:
        return pd.DataFrame()
    return df[df["alerta"]].sort_values("data_hora", ascending=False).head(limite).copy()


@st.cache_data(ttl=60, show_spinner=False, hash_funcs={Engine: id})
def carregar_alertas(engine: Engine | None = None, limite: int = 200) -> pd.DataFrame:
    """Alertas emitidos pela API (tabela `alertas`), do mais recente ao mais antigo."""
    try:
        eng = _resolver_engine(engine)
        query = text(
            """
            SELECT a.id, a.equip_id, v.fazenda, v.regiao, v.data_hora, a.nivel,
                   v.risco_score, a.criterio, a.recomendacoes, a.status, a.criado_em
            FROM alertas a
            JOIN vw_risco_completo v ON v.id = a.leitura_id
            ORDER BY a.criado_em DESC
            LIMIT :limite
            """
        )
        with eng.connect() as conn:
            df = pd.read_sql(query, conn, params={"limite": limite})
    except Exception as exc:
        logar("consulta_dashboard_falhou", nivel="warning", funcao="carregar_alertas", erro=str(exc))
        return pd.DataFrame()
    if not df.empty:
        df["recomendacoes"] = df["recomendacoes"].apply(normalizar_jsonb)
    return df


@st.cache_data(ttl=30, show_spinner=False, hash_funcs={Engine: id})
def carregar_logs(engine: Engine | None = None, limite: int = 100) -> pd.DataFrame:
    """Últimas linhas de `logs_uso` — trilha de auditoria de uso da API."""
    try:
        eng = _resolver_engine(engine)
        query = text(
            """
            SELECT ocorrido_em, kid, papel, metodo, rota, status_http, duracao_ms
            FROM logs_uso
            ORDER BY ocorrido_em DESC
            LIMIT :limite
            """
        )
        with eng.connect() as conn:
            return pd.read_sql(query, conn, params={"limite": limite})
    except Exception as exc:
        logar("consulta_dashboard_falhou", nivel="warning", funcao="carregar_logs", erro=str(exc))
        return pd.DataFrame()


@st.cache_data(ttl=30, show_spinner=False, hash_funcs={Engine: id})
def carregar_rejeitadas(engine: Engine | None = None, limite: int = 50) -> pd.DataFrame:
    """Últimas linhas de `leituras_rejeitadas` — o que a validação recusou."""
    try:
        eng = _resolver_engine(engine)
        query = text(
            """
            SELECT recebido_em, origem, codigo, motivo
            FROM leituras_rejeitadas
            ORDER BY recebido_em DESC
            LIMIT :limite
            """
        )
        with eng.connect() as conn:
            return pd.read_sql(query, conn, params={"limite": limite})
    except Exception as exc:
        logar("consulta_dashboard_falhou", nivel="warning", funcao="carregar_rejeitadas", erro=str(exc))
        return pd.DataFrame()


@st.cache_data(ttl=30, show_spinner=False, hash_funcs={Engine: id})
def contar_auditoria(engine: Engine | None = None) -> dict[str, int]:
    """Totais de `logs_uso` e `leituras_rejeitadas` (independente do LIMIT das telas)."""
    try:
        eng = _resolver_engine(engine)
        with eng.connect() as conn:
            logs = conn.execute(text("SELECT COUNT(*) FROM logs_uso")).scalar() or 0
            rejeitadas = conn.execute(text("SELECT COUNT(*) FROM leituras_rejeitadas")).scalar() or 0
        return {"logs_uso": int(logs), "leituras_rejeitadas": int(rejeitadas)}
    except Exception as exc:
        logar("consulta_dashboard_falhou", nivel="warning", funcao="contar_auditoria", erro=str(exc))
        return {"logs_uso": 0, "leituras_rejeitadas": 0}


@st.cache_data(ttl=60, show_spinner=False, hash_funcs={Engine: id})
def tendencias(engine: Engine | None, por: str, janela: str, limite: int = 500) -> pd.DataFrame:
    """Delegação fina para `agroguard.relatorios.servico.tendencias` (Q7–Q9)."""
    try:
        eng = _resolver_engine(engine)
        linhas = relatorios_servico.tendencias(eng, por, janela, limite)
    except Exception as exc:
        logar("consulta_dashboard_falhou", nivel="warning", funcao="tendencias", erro=str(exc))
        return pd.DataFrame()
    df = pd.DataFrame(linhas)
    if not df.empty:
        df["periodo"] = pd.to_datetime(df["periodo"])
    return df


@st.cache_data(ttl=60, show_spinner=False, hash_funcs={Engine: id})
def ranking(engine: Engine | None = None, limite: int = 10) -> pd.DataFrame:
    """Delegação fina para `agroguard.relatorios.servico.ranking` (US04)."""
    try:
        eng = _resolver_engine(engine)
        linhas = relatorios_servico.ranking(eng, limite)
    except Exception as exc:
        logar("consulta_dashboard_falhou", nivel="warning", funcao="ranking", erro=str(exc))
        return pd.DataFrame()
    return pd.DataFrame(linhas)


@st.cache_data(ttl=60, show_spinner=False, hash_funcs={Engine: id})
def listar_equipamentos(engine: Engine | None = None) -> pd.DataFrame:
    """Delegação fina para `agroguard.relatorios.servico.listar_equipamentos`."""
    try:
        eng = _resolver_engine(engine)
        linhas = relatorios_servico.listar_equipamentos(eng)
    except Exception as exc:
        logar("consulta_dashboard_falhou", nivel="warning", funcao="listar_equipamentos", erro=str(exc))
        return pd.DataFrame()
    return pd.DataFrame(linhas)


def ultima_leitura_por_equipamento(df: pd.DataFrame) -> pd.DataFrame:
    """Última leitura conhecida de cada equipamento (por `data_hora`) — sem SQL."""
    if df.empty or "equip_id" not in df.columns:
        return df
    return (
        df.sort_values("data_hora")
        .groupby("equip_id", as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )
