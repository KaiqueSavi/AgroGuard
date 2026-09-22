"""
AgroGuard IA — Testes de integração do simulador de fontes de dados
======================================================================

Prova, ponta a ponta, que a simulação de telemetria/ambiente/operação
(`simulador.simulador_iot`) chega íntegra ao backend: reconciliação sem
perda (enviados == aceitos + rejeitados + duplicados), consistência entre
o score persistido e o modelo (`ml.inferencia`), rastreabilidade completa
por `request_id` e integridade/assinatura da requisição.

Todos os testes exigem o PostgreSQL local (`AGROGUARD_REQUIRE_DB=1`) — ver
`tests/conftest.py`.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime

import pandas as pd
import pytest
from sqlalchemy import bindparam, text

from ml.features import ALERT_THRESHOLD, FEATURE_COLUMNS
from ml.inferencia import carregar_modelos, classe_por_score, prever
from simulador.simulador_iot import CSV_PADRAO, enviar, gerar_eventos

pytestmark = pytest.mark.integracao

# ---------------------------------------------------------------------------
# Frota: os mesmos 50 `equip_id` do dataset sintético, cadastrados no banco
# de teste — assim `gerar_eventos(..., equipamentos=EQUIP_IDS_CSV)` sorteia
# apenas equipamentos que existem em `agroguard_test.equipamentos`.
# ---------------------------------------------------------------------------
_DF_EQUIPAMENTOS = (
    pd.read_csv(CSV_PADRAO).groupby("equip_id").first()[["tipo_equip", "idade_equipamento_anos"]]
)
EQUIP_IDS_CSV = sorted(_DF_EQUIPAMENTOS.index.tolist())


@pytest.fixture(scope="module", autouse=True)
def _seed_equipamentos_csv(db_engine):
    with db_engine.begin() as conn:
        for equip_id in EQUIP_IDS_CSV:
            linha = _DF_EQUIPAMENTOS.loc[equip_id]
            conn.execute(
                text(
                    """
                    INSERT INTO equipamentos (equip_id, tipo_equip, idade_equipamento_anos, fazenda, regiao)
                    VALUES (:id, :tipo, :idade, 'FAZ-01', 'Sorriso-MT')
                    ON CONFLICT (equip_id) DO NOTHING
                    """
                ),
                {"id": equip_id, "tipo": str(linha["tipo_equip"]), "idade": int(linha["idade_equipamento_anos"])},
            )
    yield
    # `db_engine` é uma fixture de SESSÃO (compartilhada com todo o resto da
    # suíte, ver tests/conftest.py): as ~200 leituras "ao vivo" (data_hora ==
    # agora real) que este módulo insere nos 50 equip_id do dataset ficariam
    # no banco de teste depois que o módulo termina e, por serem recentes,
    # distorceriam o ranking "top 5 por score médio" de
    # tests/test_relatorio.py (que roda depois, em ordem alfabética, e conta
    # com apenas 2 equipamentos próprios no banco). `equip_id` do CSV é um
    # namespace que NENHUM outro arquivo de teste usa — apagar as leituras
    # (cascata para scores_risco/alertas) devolve o banco compartilhado ao
    # estado que os outros arquivos esperam, sem tocar em nada que eles
    # tenham inserido.
    with db_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM leituras_telemetria WHERE equip_id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": EQUIP_IDS_CSV},
        )


def _in_ids(sql: str):
    """`text(sql)` com `:ids` expansível para `WHERE ... IN :ids`."""
    return text(sql).bindparams(bindparam("ids", expanding=True))


def _chave_papel(papel: str) -> str:
    """
    Lê o segredo de teste de `AGROGUARD_API_KEYS` (já injetado em
    `os.environ` pelo módulo `tests/conftest.py`) — igual à fixture `chaves`,
    mas sem a dependência de escopo função, para poder ser usada por uma
    fixture de escopo módulo.
    """
    bruto = os.environ.get("AGROGUARD_API_KEYS", "")
    for item in bruto.split(","):
        partes = item.strip().split(":", 2)
        if len(partes) == 3 and partes[1] == papel:
            return partes[2]
    raise RuntimeError(f"Nenhuma chave de teste para o papel '{papel}' em AGROGUARD_API_KEYS.")


# ---------------------------------------------------------------------------
# Lote principal: gerado e enviado UMA vez (fixture de módulo) e reaproveitado
# pelos testes de reconciliação, consistência de modelo e rastreabilidade —
# assim os três testes enxergam exatamente o mesmo conjunto de leituras.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def resultado_lote_principal(api_client):
    # 200 requisições sem pausa excederiam o rate limit padrão (120/min, ver
    # `agroguard.config.Settings.rate_limit_por_min`) e derrubariam parte do
    # lote em 429 — o que não tem relação com a reconciliação que este teste
    # quer provar. Afrouxamos o limite só durante este envio (mesmo padrão de
    # `tests/test_auth.py::test_rate_limit_excedido`: env + `recarregar()` +
    # `resetar_limitador()`) e devolvemos tudo ao normal antes de retornar.
    from agroguard.api.auth import resetar_limitador
    from agroguard.config import recarregar

    anterior = os.environ.get("RATE_LIMIT_POR_MIN")
    os.environ["RATE_LIMIT_POR_MIN"] = "1000000"
    recarregar()
    resetar_limitador()
    try:
        eventos = gerar_eventos(
            n=200, seed=7, taxa_invalidos=0.05, taxa_duplicados=0.05, equipamentos=EQUIP_IDS_CSV
        )
        reconciliacao = enviar(api_client, eventos, _chave_papel("dispositivo"))
    finally:
        if anterior is None:
            os.environ.pop("RATE_LIMIT_POR_MIN", None)
        else:
            os.environ["RATE_LIMIT_POR_MIN"] = anterior
        recarregar()
        resetar_limitador()

    return eventos, reconciliacao


def test_reconciliacao_sem_perda(resultado_lote_principal, db_engine):
    eventos, reconciliacao = resultado_lote_principal

    assert reconciliacao.enviados == 200
    assert reconciliacao.aceitos == 180
    assert reconciliacao.duplicados_409 == 10
    rejeitados_total = (
        reconciliacao.rejeitados_validacao
        + reconciliacao.rejeitados_inconsistencia
        + reconciliacao.rejeitados_equip
    )
    assert rejeitados_total == 10
    assert reconciliacao.outros_erros == 0
    assert len(reconciliacao.request_ids) == 200  # toda resposta (2xx/4xx) carrega request_id

    with db_engine.connect() as conn:
        n_leituras = conn.execute(
            _in_ids(
                "SELECT count(*) FROM leituras_telemetria "
                "WHERE request_id IN :ids AND origem IN ('api', 'simulador')"
            ),
            {"ids": reconciliacao.request_ids},
        ).scalar()
        n_scores = conn.execute(
            _in_ids("SELECT count(*) FROM scores_risco WHERE request_id IN :ids"),
            {"ids": reconciliacao.request_ids},
        ).scalar()
        n_scores_duplicados = conn.execute(
            _in_ids(
                """
                SELECT count(*) FROM (
                    SELECT leitura_id, modelo_versao FROM scores_risco
                    WHERE request_id IN :ids
                    GROUP BY leitura_id, modelo_versao
                    HAVING count(*) > 1
                ) t
                """
            ),
            {"ids": reconciliacao.request_ids},
        ).scalar()
        n_alertas_db = conn.execute(
            _in_ids("SELECT count(*) FROM alertas WHERE request_id IN :ids"),
            {"ids": reconciliacao.request_ids},
        ).scalar()
        n_alertas_score = conn.execute(
            _in_ids(
                f"SELECT count(*) FROM scores_risco WHERE request_id IN :ids AND risco_score >= {ALERT_THRESHOLD}"
            ),
            {"ids": reconciliacao.request_ids},
        ).scalar()
        rejeitadas = conn.execute(
            _in_ids("SELECT codigo, count(*) AS n FROM leituras_rejeitadas WHERE request_id IN :ids GROUP BY codigo"),
            {"ids": reconciliacao.request_ids},
        ).mappings().all()
        n_logs = conn.execute(
            _in_ids("SELECT count(*) FROM logs_uso WHERE request_id IN :ids"),
            {"ids": reconciliacao.request_ids},
        ).scalar()

    assert n_leituras == 180
    assert n_scores == 180
    assert n_scores_duplicados == 0  # nenhuma leitura com 2 scores para a mesma modelo_versao
    assert n_alertas_db == reconciliacao.alertas
    assert n_alertas_db == n_alertas_score

    # `leituras_rejeitadas` grava toda leitura recusada — inclusive as
    # duplicadas (`codigo='duplicado'`, ver docs/api.md e
    # `agroguard.telemetria.servico.receber`) — então o total aqui é
    # rejeitados_de_negocio (10) + duplicados (10) = 20, não só os 10 inválidos.
    n_rejeitadas_total = sum(linha["n"] for linha in rejeitadas)
    assert n_rejeitadas_total == 20

    esperado_por_codigo: dict[str, int] = {}
    for e in eventos:
        if e.tipo in ("invalido", "duplicado"):
            esperado_por_codigo[e.motivo_esperado] = esperado_por_codigo.get(e.motivo_esperado, 0) + 1
    assert esperado_por_codigo == {"validacao": 4, "inconsistencia": 3, "equip_desconhecido": 3, "duplicado": 10}
    assert {linha["codigo"]: linha["n"] for linha in rejeitadas} == esperado_por_codigo

    assert n_logs == 200


def test_consistencia_score_modelo(resultado_lote_principal, db_engine, modelos_tmp):
    _eventos, reconciliacao = resultado_lote_principal
    modelos = carregar_modelos()

    with db_engine.connect() as conn:
        linhas = conn.execute(
            _in_ids(
                """
                SELECT l.velocidade_kmh, l.inclinacao_graus, l.vibracao_g,
                       l.precip_24h_mm, l.precip_prev_6h_mm, l.umidade_solo, l.vento_max_kmh,
                       l.dist_corpo_dagua_m, l.declividade_pct, l.tipo_operacao, l.turno,
                       l.jornada_acumulada_h, l.dias_desde_manutencao, l.experiencia_operador_anos,
                       e.tipo_equip, e.idade_equipamento_anos,
                       s.risco_score, s.classe_risco, s.alerta
                FROM leituras_telemetria l
                JOIN equipamentos e ON e.equip_id = l.equip_id
                JOIN scores_risco s ON s.leitura_id = l.id
                WHERE l.request_id IN :ids
                """
            ),
            {"ids": reconciliacao.request_ids},
        ).mappings().all()

    assert len(linhas) == 180

    for linha in linhas:
        registro = {
            "idade_equipamento_anos": float(linha["idade_equipamento_anos"]),
            "velocidade_kmh": float(linha["velocidade_kmh"]),
            "inclinacao_graus": float(linha["inclinacao_graus"]),
            "vibracao_g": float(linha["vibracao_g"]),
            "precip_24h_mm": float(linha["precip_24h_mm"]),
            "precip_prev_6h_mm": float(linha["precip_prev_6h_mm"]),
            "umidade_solo": float(linha["umidade_solo"]),
            "vento_max_kmh": float(linha["vento_max_kmh"]),
            "dist_corpo_dagua_m": float(linha["dist_corpo_dagua_m"]),
            "declividade_pct": float(linha["declividade_pct"]),
            "jornada_acumulada_h": float(linha["jornada_acumulada_h"]),
            "dias_desde_manutencao": float(linha["dias_desde_manutencao"]),
            "experiencia_operador_anos": float(linha["experiencia_operador_anos"]),
            "tipo_equip": linha["tipo_equip"],
            "tipo_operacao": linha["tipo_operacao"],
            "turno": linha["turno"],
        }
        assert set(registro) >= set(FEATURE_COLUMNS)

        resultado = prever(modelos, pd.DataFrame([registro])).iloc[0]

        assert int(resultado["risco_score"]) == int(linha["risco_score"])
        assert str(resultado["classe_risco"]) == linha["classe_risco"]
        assert linha["classe_risco"] == classe_por_score(int(linha["risco_score"]))
        assert bool(linha["alerta"]) == (int(linha["risco_score"]) >= ALERT_THRESHOLD)


def test_lote_e_assinatura(api_client, chaves):
    # `/telemetria/lote` valida a lista INTEIRA como um único corpo Pydantic:
    # um item fora de faixa (kind "fora_de_faixa") derrubaria o lote inteiro
    # em 422 antes de qualquer processamento por item. Por isso montamos o
    # lote com um item de negócio inválido (schema válido, mas recusado por
    # `agroguard.telemetria.servico`) — o mesmo padrão de
    # `tests/test_api.py::test_lote_com_um_item_invalido`.
    eventos = gerar_eventos(
        n=60, seed=123, taxa_invalidos=0.2, taxa_duplicados=0.0, equipamentos=EQUIP_IDS_CSV
    )
    validos = [e for e in eventos if e.tipo == "valido"][:9]
    invalido_negocio = next(e for e in eventos if e.motivo_esperado in ("inconsistencia", "equip_desconhecido"))
    lote = validos + [invalido_negocio]
    assert len(lote) == 10

    r_lote = api_client.post(
        "/telemetria/lote",
        json={"leituras": [e.payload for e in lote]},
        headers={"X-API-Key": chaves["dispositivo"]},
    )
    assert r_lote.status_code == 200
    corpo_lote = r_lote.json()
    assert len(corpo_lote["aceitos"]) == 9
    assert len(corpo_lote["rejeitados"]) == 1
    assert corpo_lote["rejeitados"][0]["codigo"] == invalido_negocio.motivo_esperado

    # POST único assinado (X-Signature = HMAC-SHA256 do corpo canônico).
    evento_assinado = gerar_eventos(n=1, seed=321, equipamentos=EQUIP_IDS_CSV)[0]
    reconciliacao_assinada = enviar(api_client, [evento_assinado], chaves["dispositivo"], assinar=True)
    assert reconciliacao_assinada.aceitos == 1
    _, status_assinado, _corpo_assinado = reconciliacao_assinada.respostas[0]
    assert status_assinado == 201

    # Assinatura adulterada, sobre um evento NOVO (data_hora distinta): 401.
    evento_adulterado = gerar_eventos(n=1, seed=654, equipamentos=EQUIP_IDS_CSV)[0]
    corpo_bruto = json.dumps(evento_adulterado.payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    assinatura_valida = hmac.new(chaves["dispositivo"].encode("utf-8"), corpo_bruto, hashlib.sha256).hexdigest()
    assinatura_adulterada = ("0" if assinatura_valida[0] != "0" else "1") + assinatura_valida[1:]

    r_adulterado = api_client.post(
        "/telemetria",
        content=corpo_bruto,
        headers={
            "X-API-Key": chaves["dispositivo"],
            "Content-Type": "application/json",
            "X-Signature": assinatura_adulterada,
        },
    )
    assert r_adulterado.status_code == 401
    assert r_adulterado.json()["codigo"] == "assinatura"


def test_rastreabilidade(resultado_lote_principal, api_client, chaves):
    _eventos, reconciliacao = resultado_lote_principal

    evento_aceito, status_aceito, corpo_aceito = next(
        (ev, status, corpo) for ev, status, corpo in reconciliacao.respostas if status == 201
    )
    assert status_aceito == 201
    rid = corpo_aceito["request_id"]

    r_aud = api_client.get(f"/auditoria/{rid}", headers={"X-API-Key": chaves["admin"]})
    assert r_aud.status_code == 200
    corpo_aud = r_aud.json()

    assert corpo_aud["log"] is not None
    assert corpo_aud["log"]["status_http"] == 201
    assert corpo_aud["leitura"] is not None
    assert corpo_aud["leitura"]["equip_id"] == evento_aceito.payload["equipamento"]["equip_id"]
    assert corpo_aud["score"] is not None
    assert isinstance(corpo_aud["score"]["fatores_principais"], list)
    assert corpo_aud["score"]["risco_score"] == corpo_aceito["risco_score"]

    if corpo_aceito.get("alerta"):
        assert corpo_aud["alerta"] is not None
        assert corpo_aud["alerta"]["nivel"] == corpo_aceito["nivel_alerta"]
    else:
        assert corpo_aud["alerta"] is None


def test_simulador_determinista():
    agora_fixo = datetime(2026, 3, 1, 8, 0, 0)
    eventos_1 = gerar_eventos(
        n=30, seed=2024, taxa_invalidos=0.1, taxa_duplicados=0.1, equipamentos=EQUIP_IDS_CSV, agora=agora_fixo
    )
    eventos_2 = gerar_eventos(
        n=30, seed=2024, taxa_invalidos=0.1, taxa_duplicados=0.1, equipamentos=EQUIP_IDS_CSV, agora=agora_fixo
    )

    assert len(eventos_1) == len(eventos_2) == 30
    for e1, e2 in zip(eventos_1, eventos_2):
        assert e1.indice == e2.indice
        assert e1.tipo == e2.tipo
        assert e1.motivo_esperado == e2.motivo_esperado
        assert e1.payload == e2.payload
