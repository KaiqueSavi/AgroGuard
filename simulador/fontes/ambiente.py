"""
AgroGuard IA — Fonte simulada: ambiente (Sprint 3/4)
=======================================================

Gera o bloco `ambiente` do payload de `POST /telemetria` a partir de uma
linha do dataset sintético, com jitter gaussiano pequeno (clipado às faixas
de `agroguard.api.schemas.AmbienteIn`).

Evita deliberadamente a inconsistência de negócio "umidade_solo > 0.9 sem
nenhuma precipitação nas últimas 24h" (`agroguard.telemetria.servico`) para
que um evento VÁLIDO nunca seja recusado por acidente do jitter — leituras
inválidas propositais são injetadas por `simulador.simulador_iot`.
"""
from __future__ import annotations

from datetime import datetime
from random import Random

import pandas as pd


def _clip(valor: float, minimo: float, maximo: float) -> float:
    return max(minimo, min(maximo, valor))


def amostrar(linha: pd.Series, agora: datetime, rng: Random) -> dict:
    """Bloco `ambiente`: clima e geografia em torno do equipamento."""
    precip_24h = _clip(float(linha["precip_24h_mm"]) + rng.gauss(0.0, 2.0), 0.0, 300.0)
    precip_6h = _clip(float(linha["precip_prev_6h_mm"]) + rng.gauss(0.0, 1.0), 0.0, 100.0)
    umidade = _clip(float(linha["umidade_solo"]) + rng.gauss(0.0, 0.02), 0.0, 1.0)
    if umidade > 0.9 and precip_24h <= 0.0:
        precip_24h = 0.1  # evita "umidade alta sem nenhuma chuva" (inconsistência de negócio)
    vento = _clip(float(linha["vento_max_kmh"]) + rng.gauss(0.0, 3.0), 0.0, 150.0)
    dist_agua = int(round(_clip(float(linha["dist_corpo_dagua_m"]) + rng.gauss(0.0, 20.0), 0.0, 10000.0)))
    declividade = _clip(float(linha["declividade_pct"]) + rng.gauss(0.0, 0.3), 0.0, 45.0)

    return {
        "precip_24h_mm": round(precip_24h, 1),
        "precip_prev_6h_mm": round(precip_6h, 1),
        "umidade_solo": round(umidade, 2),
        "vento_max_kmh": round(vento, 1),
        "dist_corpo_dagua_m": dist_agua,
        "declividade_pct": round(declividade, 2),
    }
