"""
AgroGuard IA — Dashboard de Monitoramento de Risco (Sprint 2)
=============================================================

Front-end básico (Streamlit) que consome os scores de risco persistidos no
PostgreSQL e materializa as User Stories US01 (alertas), US04 (mapa/ranking
do gestor) e US07 (histórico por equipamento).

Executar:
    streamlit run app/streamlit_app.py

Fallback: se o banco não estiver acessível, lê de data/synthetic_dataset.csv
(sem a coluna de score do modelo — usa o score do dataset apenas para demo).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Permite importar ml/db.py e ml/features.py
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ml"))

from features import CLASSES_ORDER, ALERT_THRESHOLD  # noqa: E402

CLASSE_CORES = {
    "Baixo": "#2e7d32",
    "Medio": "#f9a825",
    "Alto": "#ef6c00",
    "Critico": "#c62828",
}
# RGB para o mapa (pydeck via st.map usa cores por coluna)
CLASSE_RGB = {
    "Baixo": [46, 125, 50],
    "Medio": [249, 168, 37],
    "Alto": [239, 108, 0],
    "Critico": [198, 40, 40],
}

st.set_page_config(page_title="AgroGuard IA — Monitor de Risco", page_icon="🌾", layout="wide")


# ---------------------------------------------------------------------------
# Carregamento de dados (banco → fallback CSV)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=60)
def carregar_dados() -> tuple[pd.DataFrame, str]:
    """Tenta o PostgreSQL; cai para o CSV se indisponível."""
    try:
        from db import get_engine, ping

        if ping():
            engine = get_engine()
            df = pd.read_sql("SELECT * FROM vw_risco_completo ORDER BY data_hora", engine)
            if not df.empty and df["risco_score"].notna().any():
                df["data_hora"] = pd.to_datetime(df["data_hora"])
                return df, "PostgreSQL (vw_risco_completo)"
    except Exception:
        pass

    # Fallback CSV
    df = pd.read_csv(ROOT / "data" / "synthetic_dataset.csv")
    df["data_hora"] = pd.to_datetime(df["data_hora"])
    df["alerta"] = df["risco_score"] >= ALERT_THRESHOLD
    return df, "CSV (fallback — scores do dataset, banco indisponível)"


df, fonte = carregar_dados()

# ---------------------------------------------------------------------------
# Cabeçalho
# ---------------------------------------------------------------------------
st.title("🌾 AgroGuard IA — Monitor de Risco Operacional")
st.caption(
    "Inteligência preditiva de riscos em equipamentos agrícolas · Challenge Sompo × FIAP · Sprint 2"
)
st.caption(f"Fonte de dados: **{fonte}** · {len(df):,} leituras")

# ---------------------------------------------------------------------------
# Filtros (sidebar)
# ---------------------------------------------------------------------------
st.sidebar.header("Filtros")
equips = ["(todos)"] + sorted(df["equip_id"].unique().tolist())
sel_equip = st.sidebar.selectbox("Equipamento", equips)
sel_classes = st.sidebar.multiselect(
    "Classe de risco", CLASSES_ORDER, default=CLASSES_ORDER
)
tipos = sorted(df["tipo_equip"].unique().tolist())
sel_tipos = st.sidebar.multiselect("Tipo de equipamento", tipos, default=tipos)

fdf = df[df["classe_risco"].isin(sel_classes) & df["tipo_equip"].isin(sel_tipos)].copy()
if sel_equip != "(todos)":
    fdf = fdf[fdf["equip_id"] == sel_equip]

# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------
c1, c2, c3, c4 = st.columns(4)
c1.metric("Leituras (filtro)", f"{len(fdf):,}")
c2.metric("Score médio da frota", f"{fdf['risco_score'].mean():.1f}" if len(fdf) else "—")
c3.metric("Alertas ativos (≥80)", f"{int(fdf['alerta'].sum()):,}")
taxa_sin = 100 * fdf["sinistro"].mean() if len(fdf) else 0
c4.metric("Taxa de sinistro", f"{taxa_sin:.2f}%")

st.divider()

# ---------------------------------------------------------------------------
# Mapa + distribuição
# ---------------------------------------------------------------------------
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
    dist = (
        fdf["classe_risco"].value_counts().reindex(CLASSES_ORDER).fillna(0).astype(int)
    )
    st.bar_chart(dist, color="#ef6c00")

st.divider()

# ---------------------------------------------------------------------------
# Ranking de risco (US04)
# ---------------------------------------------------------------------------
st.subheader("📊 Ranking de equipamentos por risco (US04 — Gestor)")
ranking = (
    fdf.groupby(["equip_id", "tipo_equip"])
    .agg(
        leituras=("id", "count"),
        score_medio=("risco_score", "mean"),
        score_pico=("risco_score", "max"),
        alertas=("alerta", "sum"),
        sinistros=("sinistro", "sum"),
    )
    .reset_index()
    .sort_values("score_medio", ascending=False)
    .head(10)
)
ranking["score_medio"] = ranking["score_medio"].round(1)
st.dataframe(ranking, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# Painel de alertas (US01 — Operador)
# ---------------------------------------------------------------------------
st.subheader(f"🚨 Alertas preventivos ativos (score ≥ {ALERT_THRESHOLD}) — US01 Operador")


def recomendar(row) -> str:
    recs = []
    if row["umidade_solo"] > 0.7 and row["dist_corpo_dagua_m"] < 100:
        recs.append("ADIAR operação — solo encharcado perto de água")
    if row["declividade_pct"] > 5:
        recs.append("Reduzir velocidade — terreno inclinado (risco tombamento)")
    if row["precip_24h_mm"] > 30:
        recs.append("Atenção: chuva acumulada alta nas últimas 24h")
    if row["dias_desde_manutencao"] > 40:
        recs.append("Solicitar inspeção mecânica")
    return " · ".join(recs) if recs else "Monitorar — risco elevado"


alertas = fdf[fdf["alerta"]].sort_values("risco_score", ascending=False).head(20).copy()
if len(alertas):
    alertas["recomendacao"] = alertas.apply(recomendar, axis=1)
    cols_show = [
        "equip_id", "tipo_equip", "data_hora", "risco_score", "classe_risco",
        "precip_24h_mm", "umidade_solo", "dist_corpo_dagua_m", "recomendacao",
    ]
    st.dataframe(alertas[cols_show], use_container_width=True, hide_index=True)
else:
    st.success("Nenhum alerta ativo no filtro atual. ✅")

# ---------------------------------------------------------------------------
# Evolução do score (US07 — histórico auditável)
# ---------------------------------------------------------------------------
if sel_equip != "(todos)":
    st.subheader(f"📈 Evolução do score — {sel_equip} (US07 — Sompo)")
    serie = fdf.sort_values("data_hora").set_index("data_hora")["risco_score"]
    st.line_chart(serie, color="#1565c0")
else:
    st.caption("💡 Selecione um equipamento na barra lateral para ver a evolução temporal do score (US07).")
