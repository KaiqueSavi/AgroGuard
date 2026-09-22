"""
Testes de `ml/inferencia.py` — contrato de inferência (v0.3, com explicabilidade).

Usa a fixture `modelos_tmp` (tests/conftest.py): treina um regressor pequeno em
pasta temporária e aponta AGROGUARD_MODELS_DIR para ela.
"""
from __future__ import annotations

import pandas as pd
import pytest

from ml.features import FEATURE_COLUMNS
from ml.inferencia import ALERT_THRESHOLD, carregar_modelos, classe_por_score, prever, prever_uma


@pytest.mark.parametrize(
    "score, classe_esperada",
    [
        (0, "Baixo"),
        (30, "Baixo"),
        (31, "Medio"),
        (60, "Medio"),
        (61, "Alto"),
        (80, "Alto"),
        (81, "Critico"),
        (100, "Critico"),
    ],
)
def test_classe_por_score_bins(score, classe_esperada):
    assert classe_por_score(score) == classe_esperada


def _linha_base() -> dict:
    return {
        "idade_equipamento_anos": 5,
        "velocidade_kmh": 10.0,
        "inclinacao_graus": 2.0,
        "vibracao_g": 0.5,
        "precip_24h_mm": 2.0,
        "precip_prev_6h_mm": 0.5,
        "umidade_solo": 0.3,
        "vento_max_kmh": 10.0,
        "dist_corpo_dagua_m": 2000.0,
        "declividade_pct": 1.0,
        "jornada_acumulada_h": 3.0,
        "dias_desde_manutencao": 10,
        "experiencia_operador_anos": 8,
        "tipo_equip": "Trator",
        "tipo_operacao": "campo",
        "turno": "manha",
    }


def test_prever_retorna_colunas_do_contrato_e_indice_original(modelos_tmp):
    modelos = carregar_modelos()
    df = pd.DataFrame([_linha_base(), _linha_base()], index=[10, 20])

    resultado = prever(modelos, df)

    assert list(resultado.columns) == [
        "risco_score", "classe_risco", "alerta", "fatores_principais", "modelo_versao",
    ]
    assert list(resultado.index) == [10, 20]
    assert (resultado["alerta"] == (resultado["risco_score"] >= ALERT_THRESHOLD)).all()


def test_prever_e_deterministico(modelos_tmp):
    modelos = carregar_modelos()
    df = pd.DataFrame([_linha_base()])

    r1 = prever(modelos, df)
    r2 = prever(modelos, df)

    pd.testing.assert_frame_equal(
        r1.drop(columns=["fatores_principais"]),
        r2.drop(columns=["fatores_principais"]),
    )
    assert r1["fatores_principais"].iloc[0] == r2["fatores_principais"].iloc[0]


def test_fatores_principais_tem_ate_3_itens_ordenados_por_contribuicao_absoluta(modelos_tmp):
    modelos = carregar_modelos()
    df = pd.DataFrame([_linha_base()])

    resultado = prever(modelos, df)
    fatores = resultado["fatores_principais"].iloc[0]

    assert isinstance(fatores, list)
    assert len(fatores) <= 3
    for item in fatores:
        assert set(item.keys()) == {"fator", "valor", "contribuicao_pts"}
        assert item["fator"] in FEATURE_COLUMNS

    contribuicoes_abs = [abs(f["contribuicao_pts"]) for f in fatores]
    assert contribuicoes_abs == sorted(contribuicoes_abs, reverse=True)


def test_linha_molhada_perto_de_agua_declive_tem_score_maior_que_linha_seca_longe_plana(modelos_tmp):
    modelos = carregar_modelos()

    linha_alto_risco = _linha_base()
    linha_alto_risco.update({
        "umidade_solo": 0.95,
        "precip_24h_mm": 80.0,
        "precip_prev_6h_mm": 30.0,
        "dist_corpo_dagua_m": 20.0,
        "declividade_pct": 12.0,
    })

    linha_baixo_risco = _linha_base()
    linha_baixo_risco.update({
        "umidade_solo": 0.1,
        "precip_24h_mm": 0.0,
        "precip_prev_6h_mm": 0.0,
        "dist_corpo_dagua_m": 9000.0,
        "declividade_pct": 0.0,
    })

    df = pd.DataFrame([linha_alto_risco, linha_baixo_risco])
    resultado = prever(modelos, df)

    score_alto = resultado["risco_score"].iloc[0]
    score_baixo = resultado["risco_score"].iloc[1]
    assert score_alto > score_baixo


def test_prever_uma_devolve_um_dict_com_as_mesmas_chaves(modelos_tmp):
    modelos = carregar_modelos()
    resultado = prever_uma(modelos, _linha_base())

    assert isinstance(resultado, dict)
    assert set(resultado.keys()) == {
        "risco_score", "classe_risco", "alerta", "fatores_principais", "modelo_versao",
    }
