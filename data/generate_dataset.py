"""
AgroGuard IA — Gerador de Dataset Simulado
==========================================

Gera dataset sintético de telemetria + condições ambientais + sinistros
para treino e validação dos modelos preditivos do AgroGuard IA.

Saída: synthetic_dataset.csv  (~10.000 registros)

Uso:
    python generate_dataset.py [--n 10000] [--seed 42] [--out synthetic_dataset.csv]

Os dados são FICTÍCIOS, gerados com correlações realistas para representar
cenários de risco operacional em equipamentos agrícolas no Centro-Oeste do Brasil.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Configurações
# ---------------------------------------------------------------------------

TIPOS_EQUIPAMENTO = ["Colheitadeira", "Trator", "Pulverizador", "Caminhão"]
TIPOS_OPERACAO = ["campo", "transporte", "parado"]
TURNOS = ["manha", "tarde", "noite"]
TIPOS_SINISTRO = ["atolamento", "colisao", "tombamento", "mecanico"]
CLASSES_RISCO = ["Baixo", "Medio", "Alto", "Critico"]

# Centro aproximado: região agrícola de Sorriso/MT
LAT_BASE, LON_BASE = -12.45, -55.20


# ---------------------------------------------------------------------------
# Geração de features
# ---------------------------------------------------------------------------

def gerar_timestamps(n: int, rng: np.random.Generator) -> list[datetime]:
    """Gera timestamps espalhados em uma janela de safra (jan-abr 2026)."""
    inicio = datetime(2026, 1, 1, 5, 0, 0)
    fim = datetime(2026, 4, 30, 22, 0, 0)
    delta_seg = int((fim - inicio).total_seconds())
    offsets = rng.integers(0, delta_seg, size=n)
    return [inicio + timedelta(seconds=int(s)) for s in sorted(offsets)]


def gerar_equipamentos(n: int, rng: np.random.Generator) -> pd.DataFrame:
    """Cria pool de 50 equipamentos com características fixas."""
    n_equip = 50
    equip_ids = [f"EQ-{i:03d}" for i in range(1, n_equip + 1)]
    tipos = rng.choice(TIPOS_EQUIPAMENTO, size=n_equip, p=[0.30, 0.35, 0.20, 0.15])
    idades = rng.integers(1, 16, size=n_equip)
    pool = pd.DataFrame({
        "equip_id": equip_ids,
        "tipo_equip": tipos,
        "idade_equipamento_anos": idades,
    })
    # Sorteia n eventos do pool
    sorteios = rng.integers(0, n_equip, size=n)
    return pool.iloc[sorteios].reset_index(drop=True)


def gerar_clima(n: int, rng: np.random.Generator) -> pd.DataFrame:
    """Gera variáveis climáticas correlacionadas (chuva 24h ↔ previsão 6h ↔ umidade solo)."""
    # Distribuição bimodal: a maior parte do tempo seca, com episódios de chuva intensa
    seco = rng.uniform(0, 5, size=n)
    chuvoso = rng.gamma(shape=2.0, scale=15.0, size=n)
    mascara_chuva = rng.random(n) < 0.30
    precip_24h = np.where(mascara_chuva, chuvoso, seco)

    # Previsão para próximas 6h: parcialmente correlacionada
    precip_prev_6h = np.clip(
        precip_24h * rng.uniform(0.0, 0.4, size=n) + rng.normal(0, 2, size=n),
        0, None,
    )

    # Umidade do solo (0 a 1) — função de chuva acumulada
    umidade_solo = np.clip(0.20 + precip_24h * 0.012 + rng.normal(0, 0.05, size=n), 0.05, 0.98)

    # Vento máximo
    vento_max_kmh = np.clip(rng.gamma(shape=2.0, scale=6.0, size=n), 0, 80)

    return pd.DataFrame({
        "precip_24h_mm": precip_24h.round(1),
        "precip_prev_6h_mm": precip_prev_6h.round(1),
        "umidade_solo": umidade_solo.round(2),
        "vento_max_kmh": vento_max_kmh.round(1),
    })


def gerar_geografia(n: int, rng: np.random.Generator) -> pd.DataFrame:
    """Gera coordenadas, distância a corpos d'água e declividade."""
    lat = LAT_BASE + rng.normal(0, 0.05, size=n)
    lon = LON_BASE + rng.normal(0, 0.05, size=n)
    # Distância a água: log-normal (a maioria longe, alguns próximos)
    dist_agua = np.clip(rng.lognormal(mean=5.5, sigma=1.0, size=n), 5, 5000)
    # Declividade %: maioria plana, minoria acidentada
    declividade = np.clip(rng.gamma(shape=1.5, scale=1.5, size=n), 0, 15)
    return pd.DataFrame({
        "latitude": lat.round(5),
        "longitude": lon.round(5),
        "dist_corpo_dagua_m": dist_agua.round(0).astype(int),
        "declividade_pct": declividade.round(2),
    })


def gerar_telemetria(n: int, tipos: pd.Series, rng: np.random.Generator) -> pd.DataFrame:
    """Gera telemetria coerente com o tipo de equipamento."""
    velocidade = np.zeros(n)
    inclinacao = np.zeros(n)
    vibracao = np.zeros(n)

    for i, tipo in enumerate(tipos):
        if tipo == "Caminhão":
            velocidade[i] = rng.uniform(20, 90)
            inclinacao[i] = rng.uniform(0, 4)
            vibracao[i] = rng.uniform(0.3, 1.2)
        elif tipo == "Colheitadeira":
            velocidade[i] = rng.uniform(3, 9)
            inclinacao[i] = rng.uniform(0, 8)
            vibracao[i] = rng.uniform(0.4, 1.8)
        elif tipo == "Trator":
            velocidade[i] = rng.uniform(5, 18)
            inclinacao[i] = rng.uniform(0, 7)
            vibracao[i] = rng.uniform(0.3, 1.5)
        else:  # Pulverizador
            velocidade[i] = rng.uniform(6, 14)
            inclinacao[i] = rng.uniform(0, 5)
            vibracao[i] = rng.uniform(0.2, 1.1)

    return pd.DataFrame({
        "velocidade_kmh": velocidade.round(1),
        "inclinacao_graus": inclinacao.round(1),
        "vibracao_g": vibracao.round(2),
    })


def gerar_operacao(n: int, ts: list[datetime], rng: np.random.Generator) -> pd.DataFrame:
    """Gera contexto operacional: turno, tipo de operação, jornada, manutenção, experiência."""
    turnos = []
    for t in ts:
        h = t.hour
        if 5 <= h < 12:
            turnos.append("manha")
        elif 12 <= h < 18:
            turnos.append("tarde")
        else:
            turnos.append("noite")

    tipo_op = rng.choice(TIPOS_OPERACAO, size=n, p=[0.65, 0.25, 0.10])
    jornada_h = np.clip(rng.gamma(shape=2.0, scale=2.5, size=n), 0.1, 14)
    dias_manut = np.clip(rng.gamma(shape=2.0, scale=8.0, size=n), 0, 90).astype(int)
    exp_op = np.clip(rng.gamma(shape=2.5, scale=3.0, size=n), 0, 30).astype(int)

    return pd.DataFrame({
        "turno": turnos,
        "tipo_operacao": tipo_op,
        "jornada_acumulada_h": jornada_h.round(1),
        "dias_desde_manutencao": dias_manut,
        "experiencia_operador_anos": exp_op,
    })


# ---------------------------------------------------------------------------
# Cálculo do score de risco e rótulos
# ---------------------------------------------------------------------------

def calcular_score(df: pd.DataFrame, rng: np.random.Generator) -> np.ndarray:
    """
    Score de risco 0–100 baseado em combinação ponderada de fatores.
    Esta lógica é o "ground truth" sintético — em produção, o modelo de ML aprenderia padrões similares.
    """
    score = np.zeros(len(df))

    # Risco ambiental
    score += np.clip(df["precip_24h_mm"] / 60 * 25, 0, 25)            # até 25 pts
    score += np.clip(df["precip_prev_6h_mm"] / 20 * 10, 0, 10)        # até 10 pts
    score += np.clip(df["umidade_solo"] * 15, 0, 15)                  # até 15 pts
    score += np.clip((1 - df["dist_corpo_dagua_m"] / 1000) * 10, 0, 10)  # até 10 pts
    score += np.clip(df["declividade_pct"] / 10 * 10, 0, 10)          # até 10 pts
    score += np.clip(df["vento_max_kmh"] / 50 * 5, 0, 5)              # até 5 pts

    # Risco operacional
    score += np.clip((df["jornada_acumulada_h"] - 6) * 2, 0, 10)      # até 10 pts (após 6h)
    score += np.clip(df["dias_desde_manutencao"] / 30 * 8, 0, 8)      # até 8 pts
    score += np.clip(df["vibracao_g"] / 2 * 5, 0, 5)                  # até 5 pts
    score += np.where(df["turno"] == "noite", 5, 0)                   # +5 pts noite
    score += np.clip((10 - df["experiencia_operador_anos"]) * 0.4, 0, 4)  # até 4 pts

    # Risco específico de transporte (alta velocidade + chuva)
    cond_transp = (df["tipo_operacao"] == "transporte") & (df["precip_24h_mm"] > 10)
    score += np.where(cond_transp, 8, 0)

    # Combo crítico: solo encharcado + perto de água + declive
    combo = (df["umidade_solo"] > 0.7) & (df["dist_corpo_dagua_m"] < 100) & (df["declividade_pct"] > 4)
    score += np.where(combo, 12, 0)

    # Ruído realista
    score += rng.normal(0, 3, size=len(df))

    return np.clip(score, 0, 100).round(0).astype(int)


def classificar(score: np.ndarray) -> np.ndarray:
    """Mapeia score numérico em classe categórica."""
    bins = [-1, 30, 60, 80, 101]
    labels = CLASSES_RISCO
    return pd.cut(score, bins=bins, labels=labels).astype(str)


def gerar_sinistros(df: pd.DataFrame, score: np.ndarray, rng: np.random.Generator) -> pd.DataFrame:
    """Gera ocorrência de sinistro com probabilidade proporcional ao score."""
    prob_sinistro = np.clip((score / 100) ** 2.2, 0, 0.85)
    sinistro = (rng.random(len(df)) < prob_sinistro).astype(int)

    tipos = np.full(len(df), "", dtype=object)
    severidade = np.full(len(df), "", dtype=object)

    for i in range(len(df)):
        if sinistro[i] == 1:
            # Tipo do sinistro depende do contexto
            if df.iloc[i]["umidade_solo"] > 0.65 and df.iloc[i]["dist_corpo_dagua_m"] < 200:
                tipos[i] = "atolamento"
            elif df.iloc[i]["tipo_operacao"] == "transporte":
                tipos[i] = "colisao"
            elif df.iloc[i]["declividade_pct"] > 5:
                tipos[i] = "tombamento"
            elif df.iloc[i]["dias_desde_manutencao"] > 40 or df.iloc[i]["vibracao_g"] > 1.5:
                tipos[i] = "mecanico"
            else:
                tipos[i] = rng.choice(TIPOS_SINISTRO)

            # Severidade
            if score[i] >= 85:
                severidade[i] = rng.choice(["grave", "perda_total"], p=[0.7, 0.3])
            elif score[i] >= 60:
                severidade[i] = rng.choice(["moderado", "grave"], p=[0.6, 0.4])
            else:
                severidade[i] = rng.choice(["leve", "moderado"], p=[0.7, 0.3])

    return pd.DataFrame({
        "sinistro": sinistro,
        "tipo_sinistro": tipos,
        "severidade_sinistro": severidade,
    })


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def gerar_dataset(n: int = 10_000, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    timestamps = gerar_timestamps(n, rng)
    equip = gerar_equipamentos(n, rng)
    clima = gerar_clima(n, rng)
    geo = gerar_geografia(n, rng)
    telem = gerar_telemetria(n, equip["tipo_equip"], rng)
    op = gerar_operacao(n, timestamps, rng)

    df = pd.concat([equip, telem, clima, geo, op], axis=1)
    df.insert(0, "data_hora", timestamps)
    df.insert(0, "id", range(1, n + 1))

    score = calcular_score(df, rng)
    classe = classificar(score)
    sinistros = gerar_sinistros(df, score, rng)

    df["risco_score"] = score
    df["classe_risco"] = classe
    df = pd.concat([df, sinistros], axis=1)

    # Reordena colunas
    ordem = [
        "id", "data_hora", "equip_id", "tipo_equip", "idade_equipamento_anos",
        "latitude", "longitude",
        "velocidade_kmh", "inclinacao_graus", "vibracao_g",
        "precip_24h_mm", "precip_prev_6h_mm", "umidade_solo", "vento_max_kmh",
        "dist_corpo_dagua_m", "declividade_pct",
        "tipo_operacao", "turno", "jornada_acumulada_h",
        "dias_desde_manutencao", "experiencia_operador_anos",
        "risco_score", "classe_risco",
        "sinistro", "tipo_sinistro", "severidade_sinistro",
    ]
    return df[ordem]


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera dataset simulado AgroGuard IA")
    parser.add_argument("--n", type=int, default=10_000, help="Número de registros")
    parser.add_argument("--seed", type=int, default=42, help="Seed para reprodutibilidade")
    parser.add_argument("--out", type=str, default="synthetic_dataset.csv", help="Arquivo de saída")
    args = parser.parse_args()

    print(f"🔄 Gerando {args.n:,} registros (seed={args.seed})...")
    df = gerar_dataset(args.n, args.seed)

    out_path = Path(args.out)
    df.to_csv(out_path, index=False, encoding="utf-8")

    print(f"✅ Dataset salvo em: {out_path.resolve()}")
    print(f"   Linhas: {len(df):,} | Colunas: {len(df.columns)}")
    print(f"\n📊 Distribuição por classe de risco:")
    print(df["classe_risco"].value_counts().to_string())
    print(f"\n📊 Taxa de sinistros: {df['sinistro'].mean() * 100:.2f}%")
    print(f"\n📊 Tipos de sinistro (apenas sinistros):")
    print(df.loc[df["sinistro"] == 1, "tipo_sinistro"].value_counts().to_string())


if __name__ == "__main__":
    main()
