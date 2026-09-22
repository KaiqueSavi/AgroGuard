"""
AgroGuard IA — Fonte simulada: operação (Sprint 3/4)
=======================================================

Gera o bloco `operacao` do payload de `POST /telemetria` a partir de uma
linha do dataset sintético, com jitter gaussiano pequeno (clipado às faixas
de `agroguard.api.schemas.OperacaoIn`).

`turno` é sempre derivado da HORA de `agora` (o instante em que o evento é
"emitido" pelo simulador) — não do `turno` histórico da linha do CSV, que
corresponde a outro horário: 5–12 manhã, 12–18 tarde, senão noite.
`tipo_operacao` vem direto de `linha["tipo_operacao"]`, a MESMA linha usada
por `simulador.fontes.telemetria.amostrar` — é assim que a velocidade
jitterada lá permanece consistente com o tipo de operação aqui.
"""
from __future__ import annotations

from datetime import datetime
from random import Random

import pandas as pd


def _clip(valor: float, minimo: float, maximo: float) -> float:
    return max(minimo, min(maximo, valor))


def _turno_por_hora(hora: int) -> str:
    if 5 <= hora < 12:
        return "manha"
    if 12 <= hora < 18:
        return "tarde"
    return "noite"


def amostrar(linha: pd.Series, agora: datetime, rng: Random) -> dict:
    """Bloco `operacao`: contexto do turno de trabalho no instante `agora`."""
    jornada = _clip(float(linha["jornada_acumulada_h"]) + rng.gauss(0.0, 0.5), 0.0, 24.0)
    dias_manutencao = int(round(_clip(float(linha["dias_desde_manutencao"]) + rng.gauss(0.0, 2.0), 0.0, 365.0)))
    experiencia = int(round(_clip(float(linha["experiencia_operador_anos"]) + rng.gauss(0.0, 1.0), 0.0, 50.0)))

    return {
        "tipo_operacao": str(linha["tipo_operacao"]),
        "turno": _turno_por_hora(agora.hour),
        "jornada_acumulada_h": round(jornada, 1),
        "dias_desde_manutencao": dias_manutencao,
        "experiencia_operador_anos": experiencia,
    }
