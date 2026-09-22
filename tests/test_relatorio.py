"""
Testes de `relatorios/gerar_relatorio.py` (Sprint 4, US05) + do normalizador
JSONB de `app/consultas.py` + smoke test de compilação do dashboard.

Usa a fixture `db_engine` (tests/conftest.py): banco de teste `agroguard_test`
com o schema v2 aplicado, vazio. Sem AGROGUARD_REQUIRE_DB=1 os testes que
dependem dele são pulados; com a variável, a ausência do banco é falha.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from app.consultas import normalizar_jsonb
from ml.inferencia import classe_por_score
from relatorios.gerar_relatorio import gerar

EQUIP_IDS = ["EQ-T01", "EQ-T02"]

LEITURA_BASE = {
    "latitude": -12.5,
    "longitude": -55.5,
    "velocidade_kmh": 20.0,
    "inclinacao_graus": 3.0,
    "vibracao_g": 0.5,
    "precip_24h_mm": 10.0,
    "precip_prev_6h_mm": 2.0,
    "umidade_solo": 0.4,
    "vento_max_kmh": 15.0,
    "dist_corpo_dagua_m": 300,
    "declividade_pct": 2.0,
    "tipo_operacao": "campo",
    "turno": "manha",
    "jornada_acumulada_h": 4.0,
    "dias_desde_manutencao": 10,
    "experiencia_operador_anos": 8,
}


@pytest.fixture
def _seed_relatorio(db_engine):
    """2 equipamentos + ~40 leituras/scores ao longo de 3 semanas.

    `db_engine` é session-scoped (tests/conftest.py) e compartilhado com os
    demais módulos de teste, que não limpam o que inserem — por isso os dois
    equipamentos aqui recebem scores propositalmente muito altos (90+, perto
    do teto de 100). O `ranking()` do relatório é GLOBAL (todo `vw_risco_completo`),
    então isso garante que os equipamentos semeados apareçam no top-5 mesmo
    quando outros módulos já povoaram o banco de teste com leituras/score médio
    bem mais baixos (o próprio dashboard mostra médias reais na casa de 30–40).
    """
    agora = datetime(2026, 6, 22, 12, 0, 0)
    total_inseridas = 0
    with db_engine.begin() as conn:
        for equip_id in EQUIP_IDS:
            conn.execute(
                text(
                    """
                    INSERT INTO equipamentos (equip_id, tipo_equip, idade_equipamento_anos, fazenda, regiao)
                    VALUES (:id, 'Trator', 5, 'FAZ-TESTE', 'Regiao-Teste')
                    ON CONFLICT (equip_id) DO NOTHING
                    """
                ),
                {"id": equip_id},
            )

        for semana in range(3):
            base = agora - timedelta(weeks=(2 - semana))
            for equip_id in EQUIP_IDS:
                for i in range(7):
                    data_hora = base + timedelta(hours=i * 5)
                    # Ambos ficam sistematicamente altos (90+) para dominar o ranking
                    # GLOBAL mesmo com outros módulos de teste já tendo semeado dados;
                    # EQ-T01 sobe mais ao longo das semanas do que EQ-T02 (dá para
                    # distinguir os dois na tabela e no "insight" de tendência).
                    if equip_id == "EQ-T01":
                        score = min(90 + semana * 3 + (i % 3), 100)
                    else:
                        score = min(90 + (i % 4), 99)
                    alerta = score >= 80
                    classe = classe_por_score(score)

                    leitura_id = conn.execute(
                        text(
                            """
                            INSERT INTO leituras_telemetria (
                                equip_id, data_hora, latitude, longitude, velocidade_kmh,
                                inclinacao_graus, vibracao_g, precip_24h_mm, precip_prev_6h_mm,
                                umidade_solo, vento_max_kmh, dist_corpo_dagua_m, declividade_pct,
                                tipo_operacao, turno, jornada_acumulada_h, dias_desde_manutencao,
                                experiencia_operador_anos
                            ) VALUES (
                                :equip_id, :data_hora, :latitude, :longitude, :velocidade_kmh,
                                :inclinacao_graus, :vibracao_g, :precip_24h_mm, :precip_prev_6h_mm,
                                :umidade_solo, :vento_max_kmh, :dist_corpo_dagua_m, :declividade_pct,
                                :tipo_operacao, :turno, :jornada_acumulada_h, :dias_desde_manutencao,
                                :experiencia_operador_anos
                            )
                            RETURNING id
                            """
                        ),
                        {"equip_id": equip_id, "data_hora": data_hora, **LEITURA_BASE},
                    ).scalar_one()

                    conn.execute(
                        text(
                            """
                            INSERT INTO scores_risco (
                                leitura_id, risco_score, classe_risco, alerta,
                                fatores_principais, recomendacoes
                            ) VALUES (
                                :leitura_id, :risco_score, :classe_risco, :alerta,
                                '[{"fator": "precip_24h_mm", "valor": 10.0, "contribuicao_pts": 5.0}]',
                                '[]'
                            )
                            """
                        ),
                        {
                            "leitura_id": leitura_id,
                            "risco_score": score,
                            "classe_risco": classe,
                            "alerta": alerta,
                        },
                    )
                    total_inseridas += 1
    return total_inseridas


def test_gerar_relatorio_cria_md_e_figuras_com_secoes_e_top5(db_engine, _seed_relatorio, tmp_path):
    assert _seed_relatorio >= 40

    saida = tmp_path / "r.md"
    caminho = gerar(engine=db_engine, saida=saida, semanas=8)

    assert caminho == saida
    assert saida.exists()
    conteudo = saida.read_text(encoding="utf-8")

    for titulo in [
        "# Relatório semanal de risco — AgroGuard IA",
        "## Período coberto",
        "## Indicadores da semana (KPIs)",
        "## Top 5 equipamentos por score médio (US05)",
        "## Tendência semanal por região",
        "## Tendência semanal por tipo de operação",
        "## Tendência dos top 5 equipamentos",
        "## Alertas abertos e recomendações",
        "## Recomendações da semana",
    ]:
        assert titulo in conteudo, f"seção ausente no relatório: {titulo}"

    # Top-5 deve conter os equipamentos semeados (só existem 2 no banco de teste).
    for equip_id in EQUIP_IDS:
        assert equip_id in conteudo

    figures_dir = tmp_path / "figures"
    for nome in ["tendencia_regiao.png", "tendencia_operacao.png", "tendencia_top5_equipamentos.png"]:
        arquivo = figures_dir / nome
        assert arquivo.exists(), f"figura ausente: {nome}"
        assert arquivo.stat().st_size > 1024, f"figura suspeita de vazia: {nome}"


def test_gerar_relatorio_sem_dados_nao_lanca(tmp_path):
    """Engine inalcançável força o fallback pro CSV; CSV vazio → relatório mínimo, sem lançar."""
    csv_vazio = tmp_path / "vazio.csv"
    colunas = ["id", "data_hora", "equip_id", "tipo_equip", "risco_score", "classe_risco", "sinistro"]
    pd.DataFrame(columns=colunas).to_csv(csv_vazio, index=False)

    # Porta sem listener: pd.read_sql falha rápido e o código cai para o CSV.
    engine_inalcancavel = create_engine("postgresql+psycopg2://invalido:invalido@localhost:1/invalido")

    saida = tmp_path / "r.md"
    caminho = gerar(engine=engine_inalcancavel, saida=saida, semanas=8, csv_fallback=csv_vazio)

    assert caminho.exists()
    assert "Sem dados disponíveis" in caminho.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# normalizar_jsonb — puro pandas, sem banco
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "valor, esperado",
    [
        (None, []),
        ([], []),
        ([{"acao": "MONITORAR"}], [{"acao": "MONITORAR"}]),
        ({"acao": "MONITORAR"}, [{"acao": "MONITORAR"}]),
        ("[]", []),
        ('[{"acao": "MONITORAR"}]', [{"acao": "MONITORAR"}]),
        ('{"acao": "MONITORAR"}', [{"acao": "MONITORAR"}]),
        ("", []),
        ("não é json", []),
    ],
)
def test_normalizar_jsonb(valor, esperado):
    assert normalizar_jsonb(valor) == esperado


def test_normalizar_jsonb_trata_nan_como_lista_vazia():
    assert normalizar_jsonb(float("nan")) == []
    assert normalizar_jsonb(math.nan) == []


# ---------------------------------------------------------------------------
# Smoke test: o dashboard compila
# ---------------------------------------------------------------------------
def test_streamlit_app_compila():
    import py_compile

    caminho = Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py"
    py_compile.compile(str(caminho), doraise=True)
