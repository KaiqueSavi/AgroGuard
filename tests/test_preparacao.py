"""
Testes de `ml/preparacao.py` — pipeline de preparação de dados (v0.3).

Puramente pandas: não depende de banco nem de modelos treinados.
"""
from __future__ import annotations

import pandas as pd
import pytest

from ml.preparacao import DadosInvalidos, preparar


def _linha(**overrides) -> dict:
    base = {
        "equip_id": "EQ-001",
        "data_hora": "2026-01-01 08:00:00",
        "tipo_equip": "Trator",
        "tipo_operacao": "campo",
        "turno": "manha",
        "velocidade_kmh": 10.0,
        "inclinacao_graus": 2.0,
        "vibracao_g": 0.5,
        "precip_24h_mm": 5.0,
        "precip_prev_6h_mm": 1.0,
        "umidade_solo": 0.3,
        "vento_max_kmh": 10.0,
        "dist_corpo_dagua_m": 500.0,
        "declividade_pct": 2.0,
        "jornada_acumulada_h": 4.0,
        "dias_desde_manutencao": 10,
        "experiencia_operador_anos": 5,
        "idade_equipamento_anos": 3,
    }
    base.update(overrides)
    return base


def test_remove_duplicatas_exatas():
    df = pd.DataFrame([_linha(), _linha()])  # linhas idênticas
    limpo, relatorio = preparar(df)
    assert len(limpo) == 1
    assert relatorio["duplicatas_exatas"] == 1
    assert relatorio["duplicatas_chave"] == 0
    assert relatorio["linhas_entrada"] == 2
    assert relatorio["linhas_saida"] == 1


def test_remove_duplicatas_por_chave_mesmo_com_outros_valores_diferentes():
    df = pd.DataFrame([
        _linha(velocidade_kmh=10.0),
        _linha(velocidade_kmh=99.0),  # mesma chave (equip_id, data_hora), resto diferente
    ])
    limpo, relatorio = preparar(df)
    assert len(limpo) == 1
    assert relatorio["duplicatas_exatas"] == 0
    assert relatorio["duplicatas_chave"] == 1
    # mantém a primeira ocorrência
    assert limpo.iloc[0]["velocidade_kmh"] == 10.0


def test_faltantes_numericos_preenchidos_com_mediana_por_tipo_equip():
    df = pd.DataFrame([
        _linha(equip_id="EQ-001", data_hora="2026-01-01 08:00", tipo_equip="Trator", velocidade_kmh=10.0),
        _linha(equip_id="EQ-002", data_hora="2026-01-01 09:00", tipo_equip="Trator", velocidade_kmh=20.0),
        _linha(equip_id="EQ-003", data_hora="2026-01-01 10:00", tipo_equip="Trator", velocidade_kmh=None),
        _linha(equip_id="EQ-004", data_hora="2026-01-01 11:00", tipo_equip="Caminhão", velocidade_kmh=60.0),
        _linha(equip_id="EQ-005", data_hora="2026-01-01 12:00", tipo_equip="Caminhão", velocidade_kmh=80.0),
        _linha(equip_id="EQ-006", data_hora="2026-01-01 13:00", tipo_equip="Caminhão", velocidade_kmh=None),
    ])
    limpo, relatorio = preparar(df)
    assert relatorio["faltantes_preenchidos"]["velocidade_kmh"] == 2

    trator_preenchido = limpo.loc[limpo["equip_id"] == "EQ-003", "velocidade_kmh"].iloc[0]
    caminhao_preenchido = limpo.loc[limpo["equip_id"] == "EQ-006", "velocidade_kmh"].iloc[0]
    # mediana do grupo Trator (10, 20) = 15; mediana do grupo Caminhão (60, 80) = 70
    assert trator_preenchido == pytest.approx(15.0)
    assert caminhao_preenchido == pytest.approx(70.0)


def test_fora_de_faixa_e_clipado_e_contado():
    df = pd.DataFrame([
        _linha(velocidade_kmh=500.0),   # acima do máximo (120)
        _linha(equip_id="EQ-002", umidade_solo=-1.0),  # abaixo do mínimo (0)
    ])
    limpo, relatorio = preparar(df)
    assert relatorio["valores_clipados"]["velocidade_kmh"] == 1
    assert relatorio["valores_clipados"]["umidade_solo"] == 1
    assert limpo.loc[limpo["equip_id"] == "EQ-001", "velocidade_kmh"].iloc[0] == 120
    assert limpo.loc[limpo["equip_id"] == "EQ-002", "umidade_solo"].iloc[0] == 0


def test_estrito_levanta_em_vez_de_clipar():
    df = pd.DataFrame([_linha(velocidade_kmh=500.0)])
    with pytest.raises(DadosInvalidos):
        preparar(df, estrito=True)


def test_categoria_invalida_e_rejeitada():
    df = pd.DataFrame([
        _linha(equip_id="EQ-001"),
        _linha(equip_id="EQ-002", tipo_equip="Moto"),  # fora do domínio conhecido
    ])
    limpo, relatorio = preparar(df)
    assert len(limpo) == 1
    assert relatorio["rejeitadas"] == 1
    assert relatorio["motivos"]["tipo_equip_invalido"] == 1
    assert "EQ-002" not in limpo["equip_id"].values


def test_linhas_sem_chave_sao_rejeitadas():
    df = pd.DataFrame([
        _linha(equip_id="EQ-001"),
        _linha(equip_id=None),
        _linha(data_hora=None, equip_id="EQ-003"),
    ])
    limpo, relatorio = preparar(df)
    assert len(limpo) == 1
    assert relatorio["motivos"]["equip_id_ou_data_hora_ausente"] == 2


def test_dataframe_vazio_levanta_dados_invalidos():
    with pytest.raises(DadosInvalidos):
        preparar(pd.DataFrame())


def test_todas_as_linhas_rejeitadas_levanta_dados_invalidos():
    df = pd.DataFrame([_linha(tipo_equip="Moto"), _linha(equip_id="EQ-002", tipo_equip="Moto2")])
    with pytest.raises(DadosInvalidos):
        preparar(df)
