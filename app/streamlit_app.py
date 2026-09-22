"""
AgroGuard IA — Dashboard de Monitoramento de Risco (Sprint 3/4 · v2)
======================================================================

Interface Streamlit que consome `vw_risco_completo` (PostgreSQL) e materializa
as User Stories:
    - US01 (Operador)   → aba "Alertas & recomendações"
    - US04 (Gestora)     → abas "Visão geral" e "Tendências"
    - US05 (Sompo)       → ranking/tendências (mesma base do relatório semanal)
    - US07 (Sompo)       → aba "Equipamento" (histórico auditável)
    - Auditoria (Sprint 3: segurança) → aba "Auditoria"

Toda leitura de dados (SQL ou CSV) vive em `app/consultas.py` — este arquivo
só monta a interface e delega.

Executar:
    streamlit run app/streamlit_app.py

Fallback: se o banco não estiver acessível, os KPIs/mapa/tendências usam
`data/synthetic_dataset.csv` (sem fazenda/região/alertas reais) — as abas
"Alertas & recomendações" e "Auditoria" avisam que exigem o banco.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

# Permite importar agroguard/, ml/ e app/ quando executado via `streamlit run`.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agroguard.alertas.servico import CRITERIO_ALERTA, REGRAS  # noqa: E402
from app import consultas  # noqa: E402
from ml.features import ALERT_THRESHOLD, CLASSES_ORDER  # noqa: E402

CLASSE_CORES = {
    "Baixo": "#2e7d32",
    "Medio": "#f9a825",
    "Alto": "#ef6c00",
    "Critico": "#c62828",
}
CLASSE_RGB = {
    "Baixo": [46, 125, 50],
    "Medio": [249, 168, 37],
    "Alto": [239, 108, 0],
    "Critico": [198, 40, 40],
}
AGRUPAMENTO_LABELS = {"equipamento": "Equipamento", "regiao": "Região", "operacao": "Tipo de operação"}
JANELA_LABELS = {"dia": "Dia", "semana": "Semana"}

st.set_page_config(page_title="AgroGuard IA — Monitor de Risco", page_icon="🌾", layout="wide")


# ---------------------------------------------------------------------------
# Carregamento de dados
# ---------------------------------------------------------------------------
try:
    from ml.db import get_engine, ping

    _banco_ok = ping()
except Exception:
    _banco_ok = False

engine = get_engine() if _banco_ok else None
df, fonte = consultas.carregar_visao(engine)
banco_disponivel = fonte.startswith("PostgreSQL")

# ---------------------------------------------------------------------------
# Cabeçalho
# ---------------------------------------------------------------------------
st.title("🌾 AgroGuard IA — Monitor de Risco Operacional")
if banco_disponivel:
    st.caption("Sprint 4 · fonte: PostgreSQL (vw_risco_completo)")
else:
    st.caption(f"Sprint 4 · fonte: {fonte}")
    st.warning(
        "Banco de dados indisponível — exibindo dados do CSV sintético. "
        "As abas **Alertas & recomendações** e **Auditoria** precisam do PostgreSQL "
        "para mostrar o conteúdo completo (fazenda, região, alertas reais, logs)."
    )
st.caption(f"{len(df):,} leituras carregadas.")

if df.empty:
    st.error("Nenhum dado disponível (nem banco, nem CSV). Verifique a configuração.")
    st.stop()

# ---------------------------------------------------------------------------
# Filtros (sidebar)
# ---------------------------------------------------------------------------
st.sidebar.header("Filtros")

data_min = df["data_hora"].min()
data_max = df["data_hora"].max()
periodo = st.sidebar.date_input(
    "Período",
    value=(data_min.date(), data_max.date()),
    min_value=data_min.date(),
    max_value=data_max.date(),
)

regioes = sorted(df["regiao"].dropna().unique().tolist()) if "regiao" in df.columns else []
sel_regioes = st.sidebar.multiselect("Região", regioes, default=regioes) if regioes else []

fazendas = sorted(df["fazenda"].dropna().unique().tolist()) if "fazenda" in df.columns else []
sel_fazendas = st.sidebar.multiselect("Fazenda", fazendas, default=fazendas) if fazendas else []

tipos = sorted(df["tipo_equip"].dropna().unique().tolist())
sel_tipos = st.sidebar.multiselect("Tipo de equipamento", tipos, default=tipos)

sel_classes = st.sidebar.multiselect("Classe de risco", CLASSES_ORDER, default=CLASSES_ORDER)

equip_opcoes = ["(todos)"] + sorted(df["equip_id"].dropna().unique().tolist())
sel_equip = st.sidebar.selectbox("Equipamento", equip_opcoes)

# Aplica período (sempre) + demais filtros
if isinstance(periodo, tuple) and len(periodo) == 2:
    ini, fim = periodo
else:
    ini, fim = data_min.date(), data_max.date()
periodo_df = df[(df["data_hora"].dt.date >= ini) & (df["data_hora"].dt.date <= fim)].copy()

fdf = periodo_df[
    periodo_df["classe_risco"].isin(sel_classes) & periodo_df["tipo_equip"].isin(sel_tipos)
].copy()
if sel_regioes:
    fdf = fdf[fdf["regiao"].isin(sel_regioes)]
if sel_fazendas:
    fdf = fdf[fdf["fazenda"].isin(sel_fazendas)]
if sel_equip != "(todos)":
    fdf = fdf[fdf["equip_id"] == sel_equip]

tab_visao, tab_alertas, tab_tendencias, tab_equip, tab_auditoria = st.tabs(
    ["Visão geral", "Alertas & recomendações", "Tendências", "Equipamento", "Auditoria"]
)


# ---------------------------------------------------------------------------
# Aba: Visão geral
# ---------------------------------------------------------------------------
with tab_visao:
    if fdf.empty:
        st.info("Nenhuma leitura no filtro atual. Ajuste os filtros na barra lateral.")
    else:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Leituras (filtro)", f"{len(fdf):,}")
        c2.metric("Score médio", f"{fdf['risco_score'].mean():.1f}")
        c3.metric(f"Alertas ativos (≥{ALERT_THRESHOLD})", f"{int(fdf['alerta'].sum()):,}")
        taxa_sin = 100 * fdf["sinistro"].mean() if "sinistro" in fdf.columns else 0.0
        c4.metric("Taxa de sinistro", f"{taxa_sin:.2f}%")
        ultimas = consultas.ultima_leitura_por_equipamento(fdf)
        criticos_agora = int((ultimas["classe_risco"] == "Critico").sum()) if not ultimas.empty else 0
        c5.metric("Equip. em Crítico agora", f"{criticos_agora}")

        st.divider()
        col_map, col_dist = st.columns([2, 1])
        with col_map:
            st.subheader("🗺️ Mapa da frota por nível de risco")
            mapa = fdf.dropna(subset=["latitude", "longitude"]).copy()
            if len(mapa):
                mapa["color"] = mapa["classe_risco"].map(CLASSE_RGB)
                st.map(mapa, latitude="latitude", longitude="longitude", color="color", size=20)
                st.caption("🟢 Baixo · 🟡 Médio · 🟠 Alto · 🔴 Crítico")
            else:
                st.info("Sem coordenadas no filtro atual.")
        with col_dist:
            st.subheader("Distribuição por classe")
            dist = fdf["classe_risco"].value_counts().reindex(CLASSES_ORDER).fillna(0).astype(int)
            st.bar_chart(dist, color="#ef6c00")

        st.divider()
        st.subheader("📊 Ranking de equipamentos por risco (US04 — Gestor)")
        rank_df = pd.DataFrame()
        if banco_disponivel:
            rank_df = consultas.ranking(engine, limite=10)
        if rank_df.empty:
            rank_df = (
                fdf.groupby(["equip_id", "tipo_equip"])
                .agg(
                    leituras=("id", "count"),
                    score_medio=("risco_score", "mean"),
                    score_pico=("risco_score", "max"),
                    alertas_criticos=("alerta", "sum"),
                    sinistros_reais=("sinistro", "sum"),
                )
                .reset_index()
                .sort_values("score_medio", ascending=False)
                .head(10)
            )
            rank_df["score_medio"] = rank_df["score_medio"].round(1)
        st.dataframe(rank_df, width="stretch", hide_index=True)

        with st.expander("💡 Leitura por perfil"):
            st.markdown(
                "- **Operador**: acompanhe a aba *Alertas & recomendações* — cada linha traz "
                "a ação recomendada e o critério explícito que a disparou.\n"
                "- **Gestor**: use o ranking acima e a aba *Tendências* para priorizar contato "
                "com os equipamentos/regiões com score médio subindo.\n"
                "- **Seguradora**: a aba *Equipamento* mostra o histórico completo de score e "
                "sinistro por equipamento — base para precificação e auditoria (US07)."
            )


# ---------------------------------------------------------------------------
# Aba: Alertas & recomendações
# ---------------------------------------------------------------------------
with tab_alertas:
    st.subheader(f"🚨 Alertas & recomendações — critério: `{CRITERIO_ALERTA}`")

    alertas_reais = pd.DataFrame()
    if banco_disponivel:
        alertas_reais = consultas.carregar_alertas(engine)

    if not alertas_reais.empty:
        origem_label = "tabela `alertas` (Sprint 3: API)"
        alertas_show = alertas_reais.copy()
    else:
        origem_label = "derivado dos scores — nenhuma leitura chegou pela API ainda"
        alertas_show = consultas.alertas_derivados(fdf, limite=200)

    if alertas_show.empty:
        st.success("Nenhum alerta ativo no filtro atual. ✅")
    else:
        st.caption(f"Origem: {origem_label} · {len(alertas_show):,} alerta(s)")

        def _fmt_recomendacoes(lst) -> str:
            if not lst:
                return "—"
            return " · ".join(f"{item.get('acao', '?')} — {item.get('criterio', '?')}" for item in lst)

        alertas_show = alertas_show.copy()
        alertas_show["recomendacoes_fmt"] = alertas_show["recomendacoes"].apply(_fmt_recomendacoes)
        colunas_pref = [
            c
            for c in ["equip_id", "fazenda", "regiao", "data_hora", "nivel", "risco_score",
                      "criterio", "recomendacoes_fmt", "status", "criado_em"]
            if c in alertas_show.columns
        ]
        st.dataframe(
            alertas_show[colunas_pref].rename(columns={"recomendacoes_fmt": "recomendações"}),
            width="stretch",
            hide_index=True,
        )

        col_nivel, col_regiao = st.columns(2)
        with col_nivel:
            st.caption("Alertas por nível")
            if "nivel" in alertas_show.columns:
                st.bar_chart(alertas_show["nivel"].value_counts())
        with col_regiao:
            st.caption("Alertas por região")
            if "regiao" in alertas_show.columns:
                st.bar_chart(alertas_show["regiao"].value_counts())

    with st.expander("📋 Critérios explícitos"):
        st.markdown(f"**Critério de alerta:** `{CRITERIO_ALERTA}`")
        regras_df = pd.DataFrame(
            [{"ação": acao, "critério": criterio, "prioridade": prioridade} for acao, criterio, _, prioridade in REGRAS]
        )
        st.dataframe(regras_df, width="stretch", hide_index=True)


# ---------------------------------------------------------------------------
# Aba: Tendências
# ---------------------------------------------------------------------------
with tab_tendencias:
    st.subheader("📈 Tendências de risco por equipamento, região ou operação")

    col_por, col_janela = st.columns(2)
    with col_por:
        por = st.selectbox(
            "Agrupar por", list(AGRUPAMENTO_LABELS), format_func=lambda k: AGRUPAMENTO_LABELS[k]
        )
    with col_janela:
        janela = st.selectbox(
            "Janela", list(JANELA_LABELS), format_func=lambda k: JANELA_LABELS[k]
        )

    if banco_disponivel:
        tend_df = consultas.tendencias(engine, por, janela, limite=2000)
    else:
        coluna = {"equipamento": "equip_id", "regiao": "regiao", "operacao": "tipo_operacao"}[por]
        freq = {"dia": "D", "semana": "W"}[janela]
        tmp = df.copy()
        tmp["periodo"] = tmp["data_hora"].dt.to_period(freq).dt.start_time
        tend_df = (
            tmp.groupby([coluna, "periodo"])
            .agg(
                leituras=("id", "count"),
                score_medio=("risco_score", "mean"),
                score_pico=("risco_score", "max"),
                alertas=("alerta", "sum"),
                taxa_sinistro_pct=("sinistro", lambda s: 100 * s.mean()),
            )
            .reset_index()
            .rename(columns={coluna: "chave"})
        )
        tend_df["score_medio"] = tend_df["score_medio"].round(1)
        tend_df["taxa_sinistro_pct"] = tend_df["taxa_sinistro_pct"].round(2)
        tend_df = tend_df.sort_values(["chave", "periodo"])

    if tend_df.empty:
        st.info("Sem dados suficientes para calcular tendências no filtro atual.")
    else:
        media_por_chave = tend_df.groupby("chave")["score_medio"].mean().sort_values(ascending=False)
        top_chaves = media_por_chave.head(8).index.tolist()
        tend_top = tend_df[tend_df["chave"].isin(top_chaves)]

        pivot_score = tend_top.pivot_table(index="periodo", columns="chave", values="score_medio", aggfunc="mean").sort_index()
        st.caption("Score médio ao longo do tempo (top 8 por score médio)")
        st.line_chart(pivot_score)

        pivot_alertas = tend_top.groupby("chave")["alertas"].sum().sort_values(ascending=False)
        st.caption("Total de alertas no período (top 8)")
        st.bar_chart(pivot_alertas)

        st.dataframe(tend_top.sort_values(["chave", "periodo"]), width="stretch", hide_index=True)

        # Insight: chave com maior score no período mais recente + delta vs período anterior.
        periodos_ordenados = sorted(tend_df["periodo"].unique())
        if len(periodos_ordenados) >= 1:
            ultimo_periodo = periodos_ordenados[-1]
            atual = tend_df[tend_df["periodo"] == ultimo_periodo].sort_values("score_medio", ascending=False)
            if not atual.empty:
                linha_top = atual.iloc[0]
                chave_top = linha_top["chave"]
                score_top = linha_top["score_medio"]
                delta_txt = ""
                if len(periodos_ordenados) >= 2:
                    periodo_anterior = periodos_ordenados[-2]
                    anterior = tend_df[(tend_df["periodo"] == periodo_anterior) & (tend_df["chave"] == chave_top)]
                    if not anterior.empty:
                        delta = score_top - anterior.iloc[0]["score_medio"]
                        delta_txt = f" ({delta:+.1f} pts vs. período anterior)"
                st.info(
                    f"💡 Maior risco recente: **{chave_top}** com score médio "
                    f"**{score_top:.1f}**{delta_txt}."
                )


# ---------------------------------------------------------------------------
# Aba: Equipamento
# ---------------------------------------------------------------------------
with tab_equip:
    st.subheader("🚜 Histórico por equipamento (US07)")

    equip_disponiveis = sorted(periodo_df["equip_id"].dropna().unique().tolist())
    if not equip_disponiveis:
        st.info("Nenhum equipamento no período selecionado.")
    else:
        indice_default = equip_disponiveis.index(sel_equip) if sel_equip in equip_disponiveis else 0
        equip_escolhido = st.selectbox("Equipamento", equip_disponiveis, index=indice_default, key="equip_tab")

        serie = periodo_df[periodo_df["equip_id"] == equip_escolhido].sort_values("data_hora")
        if serie.empty:
            st.info("Sem leituras para este equipamento no período.")
        else:
            ultima = serie.iloc[-1]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Score atual", f"{ultima['risco_score']:.0f}")
            c2.metric("Classe atual", str(ultima["classe_risco"]))
            c3.metric("Alerta ativo", "Sim" if bool(ultima["alerta"]) else "Não")
            fazenda_regiao = f"{ultima.get('fazenda', '—')} / {ultima.get('regiao', '—')}"
            c4.metric("Fazenda / Região", fazenda_regiao)

            fig, ax = plt.subplots(figsize=(10, 4))
            ax.plot(serie["data_hora"], serie["risco_score"], color="#1565c0", linewidth=1.5, label="Score de risco")
            if "sinistro" in serie.columns:
                sinistros = serie[serie["sinistro"] == True]  # noqa: E712
                if not sinistros.empty:
                    ax.scatter(
                        sinistros["data_hora"], sinistros["risco_score"],
                        color="#c62828", marker="X", s=90, zorder=5, label="Sinistro registrado",
                    )
            ax.axhline(ALERT_THRESHOLD, color="#ef6c00", linestyle="--", linewidth=1, label=f"Limiar de alerta ({ALERT_THRESHOLD})")
            ax.set_xlabel("Data/hora")
            ax.set_ylabel("Score de risco")
            ax.set_title(f"Evolução do score — {equip_escolhido}")
            ax.legend(loc="upper left", fontsize=8)
            fig.autofmt_xdate()
            fig.tight_layout()
            st.pyplot(fig)
            plt.close(fig)

            st.caption("Últimas 20 leituras — fatores que mais contribuíram para o score e recomendações")

            def _fmt_fatores(lst) -> str:
                if not lst:
                    return "—"
                partes = []
                for item in lst:
                    fator = item.get("fator", "?")
                    pts = item.get("contribuicao_pts")
                    partes.append(f"{fator} (+{pts:.1f} pts)" if isinstance(pts, (int, float)) else str(fator))
                return " · ".join(partes)

            def _fmt_recs(lst) -> str:
                if not lst:
                    return "—"
                return " · ".join(f"{item.get('acao', '?')} — {item.get('criterio', '?')}" for item in lst)

            ultimas20 = serie.sort_values("data_hora", ascending=False).head(20).copy()
            ultimas20["fatores"] = ultimas20["fatores_principais"].apply(_fmt_fatores)
            ultimas20["recomendacoes_fmt"] = ultimas20["recomendacoes"].apply(_fmt_recs)
            colunas = [
                c
                for c in ["data_hora", "risco_score", "classe_risco", "alerta", "sinistro", "fatores", "recomendacoes_fmt"]
                if c in ultimas20.columns
            ]
            st.dataframe(
                ultimas20[colunas].rename(columns={"recomendacoes_fmt": "recomendações"}),
                width="stretch",
                hide_index=True,
            )


# ---------------------------------------------------------------------------
# Aba: Auditoria
# ---------------------------------------------------------------------------
with tab_auditoria:
    st.subheader("🔒 Auditoria de uso e rejeições (Sprint 3: segurança/registros de uso)")

    if not banco_disponivel:
        st.info("A aba de auditoria exige o banco de dados — conecte o PostgreSQL para ver logs e rejeições.")
    else:
        totais = consultas.contar_auditoria(engine)
        c1, c2 = st.columns(2)
        c1.metric("Total de requisições registradas", f"{totais['logs_uso']:,}")
        c2.metric("Total de leituras rejeitadas", f"{totais['leituras_rejeitadas']:,}")

        st.divider()
        st.markdown("**Últimas 100 requisições (`logs_uso`)**")
        logs_df = consultas.carregar_logs(engine, limite=100)
        if logs_df.empty:
            st.info("Nenhum log de uso registrado ainda.")
        else:
            st.dataframe(logs_df, width="stretch", hide_index=True)
            st.caption("Distribuição por status HTTP")
            st.bar_chart(logs_df["status_http"].value_counts())

        st.divider()
        st.markdown("**Últimas 50 leituras rejeitadas (`leituras_rejeitadas`)**")
        rejeitadas_df = consultas.carregar_rejeitadas(engine, limite=50)
        if rejeitadas_df.empty:
            st.info("Nenhuma leitura rejeitada registrada ainda.")
        else:
            st.dataframe(rejeitadas_df, width="stretch", hide_index=True)
