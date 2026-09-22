"""
AgroGuard IA — Relatório semanal de risco (Sprint 4, US05)
=============================================================

Gera `reports/relatorio_risco.md` (+ figuras em `reports/figures/`) com os
KPIs da semana, o top-5 de equipamentos por score médio, as tendências
semanais por região/tipo de operação/top-5 equipamentos, os alertas abertos
com recomendações e as recomendações mais frequentes da semana.

Reaproveita a mesma base de dados/consultas do dashboard:
    - `agroguard.relatorios.servico` (tendências Q7–Q9, ranking, frota).
    - `agroguard.alertas.servico.REGRAS` (nomes/critérios das recomendações —
      nunca reimplementados aqui).

CLI:
    python -m relatorios.gerar_relatorio [--saida reports/relatorio_risco.md] [--semanas 8]
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agroguard.alertas.servico import REGRAS  # noqa: E402
from agroguard.relatorios import servico as relatorios_servico  # noqa: E402
from agroguard.relatorios.servico import normalizar_jsonb as _normalizar  # noqa: E402

CSV_PADRAO = ROOT / "data" / "synthetic_dataset.csv"
SAIDA_PADRAO = ROOT / "reports" / "relatorio_risco.md"
DPI = 130

COLUNA_POR_AGRUPAMENTO = {"equipamento": "equip_id", "regiao": "regiao", "operacao": "tipo_operacao"}
REGRA_POR_ACAO = {acao: criterio for acao, criterio, _, _ in REGRAS}


# ---------------------------------------------------------------------------
# Helpers de markdown
# ---------------------------------------------------------------------------
def _tabela_markdown(df: pd.DataFrame, colunas: list[str] | None = None) -> str:
    """Converte um DataFrame em tabela Markdown pipe, sem depender de `tabulate`."""
    if df is None or df.empty:
        return "_Sem dados no período._\n"
    cols = colunas or list(df.columns)
    cols = [c for c in cols if c in df.columns]
    linhas = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join(["---"] * len(cols)) + " |",
    ]
    for _, linha in df.iterrows():
        valores = []
        for c in cols:
            v = linha[c]
            if isinstance(v, float):
                valores.append(f"{v:.1f}")
            else:
                valores.append(str(v))
        linhas.append("| " + " | ".join(valores) + " |")
    return "\n".join(linhas) + "\n"


# ---------------------------------------------------------------------------
# Carregamento de dados (banco → CSV)
# ---------------------------------------------------------------------------
def _resolver_engine_padrao() -> Engine | None:
    try:
        from ml.db import get_engine, ping

        if ping():
            return get_engine()
    except Exception:
        pass
    return None


def _carregar_base(engine: Engine | None, csv_fallback: Path) -> tuple[pd.DataFrame, Engine | None]:
    """Devolve `(df, engine_efetiva)`. `engine_efetiva` é `None` quando caiu para o CSV."""
    eng = engine if engine is not None else _resolver_engine_padrao()
    if eng is not None:
        try:
            df = pd.read_sql("SELECT * FROM vw_risco_completo ORDER BY data_hora", eng)
            if not df.empty and df["risco_score"].notna().any():
                df["data_hora"] = pd.to_datetime(df["data_hora"])
                df["fatores_principais"] = df["fatores_principais"].apply(_normalizar)
                df["recomendacoes"] = df["recomendacoes"].apply(_normalizar)
                return df, eng
        except Exception:
            pass

    df = pd.read_csv(csv_fallback)
    df["data_hora"] = pd.to_datetime(df["data_hora"])
    for coluna, default in (("fazenda", "—"), ("regiao", "—")):
        if coluna not in df.columns:
            df[coluna] = default
    if "alerta" not in df.columns:
        from ml.features import ALERT_THRESHOLD

        df["alerta"] = df["risco_score"] >= ALERT_THRESHOLD
    df["fatores_principais"] = [[] for _ in range(len(df))]
    df["recomendacoes"] = [[] for _ in range(len(df))]
    return df, None


def _tendencia_df(engine: Engine | None, janela_df: pd.DataFrame, por: str, limite: int) -> pd.DataFrame:
    """Tendência semanal por `por`, via `relatorios.servico.tendencias` (Q7–Q9)
    quando há banco, senão agrupando o `janela_df` (CSV) em pandas."""
    if engine is not None:
        try:
            linhas = relatorios_servico.tendencias(engine, por, "semana", limite)
            df = pd.DataFrame(linhas)
            if not df.empty:
                df["periodo"] = pd.to_datetime(df["periodo"])
                cutoff = janela_df["data_hora"].min()
                if pd.notna(cutoff):
                    df = df[df["periodo"] >= (cutoff - pd.Timedelta(days=7))]
            return df
        except Exception:
            pass

    if janela_df.empty:
        return pd.DataFrame()
    coluna = COLUNA_POR_AGRUPAMENTO[por]
    tmp = janela_df.copy()
    tmp["periodo"] = tmp["data_hora"].dt.to_period("W").dt.start_time
    grouped = (
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
    grouped["score_medio"] = grouped["score_medio"].round(1)
    grouped["taxa_sinistro_pct"] = grouped["taxa_sinistro_pct"].round(2)
    return grouped.sort_values(["chave", "periodo"]).head(limite)


def _alertas_abertos(engine: Engine | None, janela_df: pd.DataFrame) -> pd.DataFrame:
    """Alertas com status='aberto' (tabela `alertas`); se vazio/sem banco,
    deriva das leituras com `alerta = True` na janela (mesmo critério do dashboard)."""
    if engine is not None:
        try:
            query = text(
                """
                SELECT a.equip_id, v.fazenda, v.regiao, v.data_hora, a.nivel,
                       v.risco_score, a.criterio, a.recomendacoes, a.status, a.criado_em
                FROM alertas a
                JOIN vw_risco_completo v ON v.id = a.leitura_id
                WHERE a.status = 'aberto'
                ORDER BY a.criado_em DESC
                """
            )
            with engine.connect() as conn:
                df = pd.read_sql(query, conn)
            if not df.empty:
                df["recomendacoes"] = df["recomendacoes"].apply(_normalizar)
                return df
        except Exception:
            pass

    if janela_df.empty or "alerta" not in janela_df.columns:
        return pd.DataFrame()
    cols = [c for c in ["equip_id", "fazenda", "regiao", "data_hora", "risco_score", "recomendacoes"] if c in janela_df.columns]
    return janela_df[janela_df["alerta"]][cols].sort_values("risco_score", ascending=False).copy()


def _recomendacoes_frequentes(alertas_df: pd.DataFrame, janela_df: pd.DataFrame, top_n: int = 5) -> list[dict[str, Any]]:
    """Conta a frequência de cada ação de recomendação (alertas abertos + scores
    da janela) e devolve o top-N com o critério explícito (tabela `REGRAS`)."""
    contagem: Counter[str] = Counter()
    for serie in (alertas_df.get("recomendacoes"), janela_df.get("recomendacoes")):
        if serie is None:
            continue
        for valor in serie:
            for item in _normalizar(valor):
                if isinstance(item, dict) and item.get("acao"):
                    contagem[item["acao"]] += 1
    return [
        {"acao": acao, "criterio": REGRA_POR_ACAO.get(acao, "—"), "ocorrencias": qtd}
        for acao, qtd in contagem.most_common(top_n)
    ]


# ---------------------------------------------------------------------------
# Figuras
# ---------------------------------------------------------------------------
def _plotar_tendencia(df: pd.DataFrame, titulo: str, caminho: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 4.5))
    if df is None or df.empty:
        ax.text(0.5, 0.5, "Sem dados no período", ha="center", va="center", transform=ax.transAxes)
        ax.axis("off")
    else:
        pivot = df.pivot_table(index="periodo", columns="chave", values="score_medio", aggfunc="mean").sort_index()
        pivot.plot(ax=ax, marker="o")
        ax.set_title(titulo)
        ax.set_xlabel("Semana")
        ax.set_ylabel("Score médio")
        ax.legend(fontsize=8, loc="upper left", bbox_to_anchor=(1.02, 1))
        fig.tight_layout()
    fig.savefig(caminho, dpi=DPI)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Montagem do Markdown
# ---------------------------------------------------------------------------
def _montar_markdown(
    *,
    inicio: pd.Timestamp,
    fim: pd.Timestamp,
    total_leituras: int,
    score_medio: float,
    total_alertas: int,
    taxa_sinistro: float,
    equipamentos_ativos: int,
    top5: pd.DataFrame,
    tendencia_regiao: pd.DataFrame,
    tendencia_operacao: pd.DataFrame,
    alertas_abertos: pd.DataFrame,
    recomendacoes_semana: list[dict[str, Any]],
    fig_regiao: Path,
    fig_operacao: Path,
    fig_top5: Path,
    pasta_saida: Path,
) -> str:
    def rel(p: Path) -> str:
        try:
            return str(p.relative_to(pasta_saida))
        except ValueError:
            return str(p)

    partes = ["# Relatório semanal de risco — AgroGuard IA", ""]

    partes += ["## Período coberto", ""]
    partes.append(f"De **{inicio:%d/%m/%Y}** a **{fim:%d/%m/%Y}**.")
    partes.append("")

    partes += ["## Indicadores da semana (KPIs)", ""]
    partes.append(f"- Leituras no período: **{total_leituras:,}**")
    partes.append(f"- Score médio: **{score_medio:.1f}**")
    partes.append(f"- Alertas ativos: **{total_alertas:,}**")
    partes.append(f"- Taxa de sinistro: **{taxa_sinistro:.2f}%**")
    partes.append(f"- Equipamentos com leitura no período: **{equipamentos_ativos}**")
    partes.append("")

    partes += ["## Top 5 equipamentos por score médio (US05)", ""]
    colunas_top5 = [c for c in ["equip_id", "tipo_equip", "leituras", "score_medio", "score_pico", "alertas_criticos", "sinistros_reais"] if c in top5.columns]
    partes.append(_tabela_markdown(top5, colunas_top5))
    partes.append("")

    partes += ["## Tendência semanal por região", ""]
    colunas_tend = ["chave", "periodo", "leituras", "score_medio", "score_pico", "alertas", "taxa_sinistro_pct"]
    partes.append(_tabela_markdown(tendencia_regiao, [c for c in colunas_tend if c in tendencia_regiao.columns]))
    partes.append(f"![Tendência por região]({rel(fig_regiao)})")
    partes.append("")

    partes += ["## Tendência semanal por tipo de operação", ""]
    partes.append(_tabela_markdown(tendencia_operacao, [c for c in colunas_tend if c in tendencia_operacao.columns]))
    partes.append(f"![Tendência por tipo de operação]({rel(fig_operacao)})")
    partes.append("")

    partes += ["## Tendência dos top 5 equipamentos", ""]
    partes.append(f"![Tendência dos top 5 equipamentos]({rel(fig_top5)})")
    partes.append("")

    partes += ["## Alertas abertos e recomendações", ""]
    if alertas_abertos.empty:
        partes.append("_Nenhum alerta aberto no período._")
    else:
        exibir = alertas_abertos.copy()
        exibir["recomendacoes"] = exibir["recomendacoes"].apply(
            lambda lst: " · ".join(f"{i.get('acao', '?')} — {i.get('criterio', '?')}" for i in _normalizar(lst)) or "—"
        )
        colunas_alertas = [c for c in ["equip_id", "fazenda", "regiao", "data_hora", "nivel", "risco_score", "criterio", "recomendacoes", "status"] if c in exibir.columns]
        partes.append(_tabela_markdown(exibir, colunas_alertas))
    partes.append("")

    partes += ["## Recomendações da semana", ""]
    if not recomendacoes_semana:
        partes.append("_Sem recomendações registradas nos scores/alertas do período._")
    else:
        for item in recomendacoes_semana:
            partes.append(f"- **{item['acao']}** ({item['ocorrencias']}x) — {item['criterio']}")
    partes.append("")

    return "\n".join(partes) + "\n"


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------
def gerar(
    engine: Engine | None = None,
    saida: Path = SAIDA_PADRAO,
    semanas: int = 8,
    csv_fallback: Path = CSV_PADRAO,
) -> Path:
    """Gera o relatório semanal de risco (Markdown + figuras). Devolve o Path do .md."""
    saida = Path(saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    figures_dir = saida.parent / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    df, eng_efetiva = _carregar_base(engine, Path(csv_fallback))

    if df.empty:
        saida.write_text("# Relatório semanal de risco — AgroGuard IA\n\n_Sem dados disponíveis._\n", encoding="utf-8")
        return saida

    fim = df["data_hora"].max()
    inicio_janela = fim - pd.Timedelta(weeks=semanas)
    janela_df = df[df["data_hora"] >= inicio_janela].copy()
    if janela_df.empty:
        janela_df = df.copy()
        inicio_janela = df["data_hora"].min()

    total_leituras = len(janela_df)
    score_medio = float(janela_df["risco_score"].mean())
    total_alertas = int(janela_df["alerta"].sum())
    taxa_sinistro = 100 * float(janela_df["sinistro"].mean()) if "sinistro" in janela_df.columns else 0.0
    equipamentos_ativos = int(janela_df["equip_id"].nunique())

    top5 = pd.DataFrame()
    if eng_efetiva is not None:
        try:
            top5 = pd.DataFrame(relatorios_servico.ranking(eng_efetiva, limite=5))
        except Exception:
            top5 = pd.DataFrame()
    if top5.empty:
        top5 = (
            janela_df.groupby(["equip_id", "tipo_equip"])
            .agg(
                leituras=("id", "count"),
                score_medio=("risco_score", "mean"),
                score_pico=("risco_score", "max"),
                alertas_criticos=("alerta", "sum"),
                sinistros_reais=("sinistro", "sum"),
            )
            .reset_index()
            .sort_values("score_medio", ascending=False)
            .head(5)
        )
        top5["score_medio"] = top5["score_medio"].round(1)

    tendencia_regiao = _tendencia_df(eng_efetiva, janela_df, "regiao", limite=2000)
    tendencia_operacao = _tendencia_df(eng_efetiva, janela_df, "operacao", limite=2000)
    tendencia_equip = _tendencia_df(eng_efetiva, janela_df, "equipamento", limite=5000)

    top5_ids = top5["equip_id"].tolist() if "equip_id" in top5.columns else []
    tendencia_top5 = (
        tendencia_equip[tendencia_equip["chave"].isin(top5_ids)] if not tendencia_equip.empty else tendencia_equip
    )

    fig_regiao = figures_dir / "tendencia_regiao.png"
    fig_operacao = figures_dir / "tendencia_operacao.png"
    fig_top5 = figures_dir / "tendencia_top5_equipamentos.png"
    _plotar_tendencia(tendencia_regiao, "Score médio por região", fig_regiao)
    _plotar_tendencia(tendencia_operacao, "Score médio por tipo de operação", fig_operacao)
    _plotar_tendencia(tendencia_top5, "Score médio — top 5 equipamentos", fig_top5)

    alertas_abertos = _alertas_abertos(eng_efetiva, janela_df)
    recomendacoes_semana = _recomendacoes_frequentes(alertas_abertos, janela_df)

    conteudo = _montar_markdown(
        inicio=inicio_janela,
        fim=fim,
        total_leituras=total_leituras,
        score_medio=score_medio,
        total_alertas=total_alertas,
        taxa_sinistro=taxa_sinistro,
        equipamentos_ativos=equipamentos_ativos,
        top5=top5,
        tendencia_regiao=tendencia_regiao,
        tendencia_operacao=tendencia_operacao,
        alertas_abertos=alertas_abertos,
        recomendacoes_semana=recomendacoes_semana,
        fig_regiao=fig_regiao,
        fig_operacao=fig_operacao,
        fig_top5=fig_top5,
        pasta_saida=saida.parent,
    )
    saida.write_text(conteudo, encoding="utf-8")
    return saida


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera o relatório semanal de risco AgroGuard IA")
    parser.add_argument("--saida", type=Path, default=SAIDA_PADRAO, help="Caminho do .md de saída")
    parser.add_argument("--semanas", type=int, default=8, help="Janela de semanas cobertas pelo relatório")
    args = parser.parse_args()

    caminho = gerar(saida=args.saida, semanas=args.semanas)
    print(f"✅ Relatório gerado em {caminho}")


if __name__ == "__main__":
    main()
