"""
AgroGuard IA — Fonte simulada: telemetria (Sprint 3/4)
=========================================================

Gera o bloco `telemetria` do payload de `POST /telemetria` a partir de uma
linha do dataset sintético, com jitter gaussiano pequeno (clipado às faixas
de `agroguard.api.schemas.TelemetriaCampos`).

A velocidade é jitterada de forma condicionada a `linha["tipo_operacao"]`
para respeitar as regras de consistência de
`agroguard.telemetria.servico._validar_consistencia`:
  - parado     -> velocidade_kmh < 1.0
  - transporte -> velocidade_kmh >= 5.0
"""
from __future__ import annotations

from datetime import datetime
from random import Random

import pandas as pd


def _clip(valor: float, minimo: float, maximo: float) -> float:
    return max(minimo, min(maximo, valor))


def amostrar(linha: pd.Series, agora: datetime, rng: Random) -> dict:
    """Bloco `telemetria`: geolocalização + estado instantâneo do equipamento."""
    tipo_operacao = str(linha["tipo_operacao"])

    velocidade = float(linha["velocidade_kmh"]) + rng.gauss(0.0, 1.5)
    if tipo_operacao == "parado":
        velocidade = _clip(velocidade, 0.0, 0.9)
    elif tipo_operacao == "transporte":
        velocidade = _clip(velocidade, 5.0, 120.0)
    else:
        velocidade = _clip(velocidade, 0.0, 120.0)

    latitude = _clip(float(linha["latitude"]) + rng.gauss(0.0, 0.01), -90.0, 90.0)
    longitude = _clip(float(linha["longitude"]) + rng.gauss(0.0, 0.01), -180.0, 180.0)
    inclinacao = _clip(float(linha["inclinacao_graus"]) + rng.gauss(0.0, 0.5), 0.0, 45.0)
    vibracao = _clip(float(linha["vibracao_g"]) + rng.gauss(0.0, 0.05), 0.0, 5.0)

    return {
        "data_hora": agora.isoformat(),
        "latitude": round(latitude, 5),
        "longitude": round(longitude, 5),
        "velocidade_kmh": round(velocidade, 1),
        "inclinacao_graus": round(inclinacao, 1),
        "vibracao_g": round(vibracao, 2),
    }
