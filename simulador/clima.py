"""
AgroGuard IA — Enriquecimento opcional com clima real (Sprint 3/4)
=====================================================================

Sobrescreve o bloco `ambiente` de um payload já montado por
`simulador.simulador_iot.gerar_eventos` com dados reais do Open-Meteo
(https://open-meteo.com/, API pública, sem chave) para a latitude/longitude
da `telemetria` do próprio payload.

NUNCA é usado pelos testes (`tests/test_integracao.py`) nem levanta exceção:
qualquer falha (rede, timeout, resposta inesperada) devolve o payload
inalterado e a fonte "dataset_sintetico", para que o simulador continue
funcionando totalmente offline por padrão.
"""
from __future__ import annotations

from typing import Any

import httpx

URL_OPEN_METEO = "https://api.open-meteo.com/v1/forecast"


def _clip(valor: float, minimo: float, maximo: float) -> float:
    return max(minimo, min(maximo, valor))


def enriquecer_com_clima(payload: dict[str, Any], timeout: float = 3.0) -> tuple[dict[str, Any], str]:
    """
    Tenta sobrescrever `ambiente.{precip_24h_mm, precip_prev_6h_mm, vento_max_kmh}`
    com a previsão real do Open-Meteo para a posição do equipamento. Em caso de
    qualquer exceção, devolve `(payload, "dataset_sintetico")` sem modificar nada.
    """
    try:
        latitude = payload["telemetria"]["latitude"]
        longitude = payload["telemetria"]["longitude"]

        resposta = httpx.get(
            URL_OPEN_METEO,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "hourly": "precipitation",
                "daily": "precipitation_sum,wind_speed_10m_max",
                "past_days": 1,
                "forecast_days": 1,
                "timezone": "America/Sao_Paulo",
            },
            timeout=timeout,
        )
        resposta.raise_for_status()
        dados = resposta.json()

        precip_diaria = (dados.get("daily") or {}).get("precipitation_sum") or []
        vento_diario = (dados.get("daily") or {}).get("wind_speed_10m_max") or []
        precip_horaria = (dados.get("hourly") or {}).get("precipitation") or []

        novo = dict(payload)
        novo["ambiente"] = dict(payload["ambiente"])

        if precip_diaria and precip_diaria[-1] is not None:
            novo["ambiente"]["precip_24h_mm"] = round(_clip(float(precip_diaria[-1]), 0.0, 300.0), 1)
        if precip_horaria:
            ultimas_6h = [v for v in precip_horaria[-6:] if v is not None]
            if ultimas_6h:
                novo["ambiente"]["precip_prev_6h_mm"] = round(_clip(float(sum(ultimas_6h)), 0.0, 100.0), 1)
        if vento_diario and vento_diario[-1] is not None:
            novo["ambiente"]["vento_max_kmh"] = round(_clip(float(vento_diario[-1]), 0.0, 150.0), 1)

        return novo, "open-meteo"
    except Exception:
        return payload, "dataset_sintetico"
