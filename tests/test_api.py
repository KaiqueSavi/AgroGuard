"""
Testes end-to-end do backend integrador: entrada → banco → modelo → saída.

Usa `api_client` (TestClient + banco `agroguard_test` com o schema v2
aplicado) e `db_engine` para verificar diretamente as tabelas.
"""
from __future__ import annotations

import copy
import json

import pytest
from sqlalchemy import text

from ml.inferencia import classe_por_score

EQUIP_IDS = ["EQ-901", "EQ-902", "EQ-903"]

BASE_PAYLOAD = {
    "equipamento": {"equip_id": "EQ-901"},
    "telemetria": {
        "data_hora": "2026-02-01T08:00:00",
        "latitude": -12.5,
        "longitude": -55.7,
        "velocidade_kmh": 20.0,
        "inclinacao_graus": 3.0,
        "vibracao_g": 0.5,
    },
    "ambiente": {
        "precip_24h_mm": 5.0,
        "precip_prev_6h_mm": 1.0,
        "umidade_solo": 0.4,
        "vento_max_kmh": 10.0,
        "dist_corpo_dagua_m": 500,
        "declividade_pct": 2.0,
    },
    "operacao": {
        "tipo_operacao": "campo",
        "turno": "manha",
        "jornada_acumulada_h": 3.0,
        "dias_desde_manutencao": 5,
        "experiencia_operador_anos": 10,
    },
}


def _payload(equip_id: str, data_hora: str) -> dict:
    p = copy.deepcopy(BASE_PAYLOAD)
    p["equipamento"]["equip_id"] = equip_id
    p["telemetria"]["data_hora"] = data_hora
    return p


@pytest.fixture(scope="module", autouse=True)
def _seed_equipamentos(db_engine):
    with db_engine.begin() as conn:
        for equip_id in EQUIP_IDS:
            conn.execute(
                text(
                    """
                    INSERT INTO equipamentos (equip_id, tipo_equip, idade_equipamento_anos, fazenda, regiao)
                    VALUES (:id, 'Trator', 5, 'FAZ-01', 'Sorriso-MT')
                    ON CONFLICT (equip_id) DO NOTHING
                    """
                ),
                {"id": equip_id},
            )
    yield


def test_post_telemetria_valida_retorna_201(api_client, chaves, db_engine):
    payload = _payload("EQ-901", "2026-02-01T08:00:00")
    r = api_client.post("/telemetria", json=payload, headers={"X-API-Key": chaves["dispositivo"]})
    assert r.status_code == 201
    corpo = r.json()

    assert 0 <= corpo["risco_score"] <= 100
    assert corpo["classe_risco"] == classe_por_score(corpo["risco_score"])
    assert corpo["alerta"] == (corpo["risco_score"] >= 80)
    rid = corpo["request_id"]
    assert rid

    with db_engine.connect() as conn:
        leitura = conn.execute(
            text("SELECT * FROM leituras_telemetria WHERE request_id = :rid"), {"rid": rid}
        ).mappings().first()
        score = conn.execute(
            text("SELECT * FROM scores_risco WHERE request_id = :rid"), {"rid": rid}
        ).mappings().first()
        log = conn.execute(
            text("SELECT * FROM logs_uso WHERE request_id = :rid"), {"rid": rid}
        ).mappings().first()

    assert leitura is not None
    assert score is not None
    assert log is not None
    assert log["status_http"] == 201


def test_umidade_fora_da_faixa_retorna_422_e_registra_rejeicao(api_client, chaves, db_engine):
    payload = _payload("EQ-901", "2026-02-01T09:00:00")
    payload["ambiente"]["umidade_solo"] = 1.5  # acima do limite (0..1)

    r = api_client.post("/telemetria", json=payload, headers={"X-API-Key": chaves["dispositivo"]})
    assert r.status_code == 422
    corpo = r.json()
    assert corpo["codigo"] == "validacao"

    with db_engine.connect() as conn:
        rejeitada = conn.execute(
            text("SELECT * FROM leituras_rejeitadas WHERE request_id = :rid"), {"rid": corpo["request_id"]}
        ).mappings().first()
    assert rejeitada is not None
    assert rejeitada["codigo"] == "validacao"


def test_leitura_duplicada_retorna_409_e_mantem_uma_linha(api_client, chaves, db_engine):
    payload = _payload("EQ-902", "2026-02-01T10:00:00")

    r1 = api_client.post("/telemetria", json=payload, headers={"X-API-Key": chaves["dispositivo"]})
    assert r1.status_code == 201

    r2 = api_client.post("/telemetria", json=payload, headers={"X-API-Key": chaves["dispositivo"]})
    assert r2.status_code == 409
    assert r2.json()["codigo"] == "duplicado"

    with db_engine.connect() as conn:
        n = conn.execute(
            text(
                "SELECT count(*) FROM leituras_telemetria WHERE equip_id = :eq AND data_hora = :dh"
            ),
            {"eq": "EQ-902", "dh": "2026-02-01T10:00:00"},
        ).scalar()
    assert n == 1


def test_parado_com_velocidade_alta_retorna_422_inconsistencia(api_client, chaves):
    payload = _payload("EQ-901", "2026-02-01T11:00:00")
    payload["operacao"]["tipo_operacao"] = "parado"
    payload["telemetria"]["velocidade_kmh"] = 40.0

    r = api_client.post("/telemetria", json=payload, headers={"X-API-Key": chaves["dispositivo"]})
    assert r.status_code == 422
    assert r.json()["codigo"] == "inconsistencia"


def test_equipamento_desconhecido_retorna_422(api_client, chaves):
    payload = _payload("EQ-999", "2026-02-01T12:00:00")
    r = api_client.post("/telemetria", json=payload, headers={"X-API-Key": chaves["dispositivo"]})
    assert r.status_code == 422
    assert r.json()["codigo"] == "equip_desconhecido"


def test_lote_com_um_item_invalido(api_client, chaves):
    lote = {
        "leituras": [
            _payload("EQ-901", "2026-02-01T13:00:00"),
            _payload("EQ-902", "2026-02-01T13:00:00"),
            _payload("EQ-999", "2026-02-01T13:00:00"),  # equipamento desconhecido
        ]
    }
    r = api_client.post("/telemetria/lote", json=lote, headers={"X-API-Key": chaves["dispositivo"]})
    assert r.status_code == 200
    corpo = r.json()
    assert len(corpo["aceitos"]) == 2
    assert len(corpo["rejeitados"]) == 1
    assert corpo["rejeitados"][0]["codigo"] == "equip_desconhecido"


def test_alerta_critico_gera_recomendacoes_e_fica_rastreavel(api_client, chaves, db_engine):
    # Combinação extrema (mas dentro das faixas válidas do schema) para garantir
    # score >= 80 mesmo com o modelo pequeno de teste (`modelos_tmp`, 50 estimators
    # treinados numa amostra de 1000 linhas) — o payload "só um pouco alto" do
    # cenário mínimo do enunciado (score ~76 nesse modelo) não é suficiente aqui.
    payload = _payload("EQ-903", "2026-02-01T14:00:00")
    payload["telemetria"].update({"velocidade_kmh": 15.0, "inclinacao_graus": 20.0, "vibracao_g": 4.5})
    payload["ambiente"].update(
        {
            "precip_24h_mm": 250.0,
            "precip_prev_6h_mm": 90.0,
            "umidade_solo": 0.98,
            "vento_max_kmh": 140.0,
            "dist_corpo_dagua_m": 5,
            "declividade_pct": 40.0,
        }
    )
    payload["operacao"].update(
        {
            "jornada_acumulada_h": 23.0,
            "dias_desde_manutencao": 360,
            "experiencia_operador_anos": 0,
            "turno": "noite",
        }
    )

    r = api_client.post("/telemetria", json=payload, headers={"X-API-Key": chaves["dispositivo"]})
    assert r.status_code == 201
    corpo = r.json()
    assert corpo["risco_score"] >= 80
    assert corpo["alerta"] is True

    acoes = {rec["acao"] for rec in corpo["recomendacoes"]}
    assert "ADIAR_OPERACAO" in acoes

    with db_engine.connect() as conn:
        alerta = conn.execute(
            text("SELECT * FROM alertas WHERE request_id = :rid"), {"rid": corpo["request_id"]}
        ).mappings().first()
    assert alerta is not None
    assert alerta["criterio"] == "risco_score >= 80"
    assert alerta["recomendacoes"]

    r_hist = api_client.get("/equipamentos/EQ-903/scores", headers={"X-API-Key": chaves["gestor"]})
    assert r_hist.status_code == 200
    assert any(item["leitura_id"] == corpo["leitura_id"] for item in r_hist.json())

    r_alertas = api_client.get("/alertas?status=aberto", headers={"X-API-Key": chaves["gestor"]})
    assert r_alertas.status_code == 200
    assert alerta["id"] in [a["id"] for a in r_alertas.json()]

    r_ack = api_client.post(f"/alertas/{alerta['id']}/reconhecer", headers={"X-API-Key": chaves["gestor"]})
    assert r_ack.status_code == 200
    assert r_ack.json()["status"] == "reconhecido"


def test_tendencias_por_regiao(api_client, chaves):
    r = api_client.get("/relatorios/tendencias?por=regiao&janela=semana", headers={"X-API-Key": chaves["gestor"]})
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert len(r.json()) >= 1


def test_auditoria_encadeia_por_request_id(api_client, chaves):
    payload = _payload("EQ-901", "2026-02-01T15:00:00")
    r = api_client.post("/telemetria", json=payload, headers={"X-API-Key": chaves["dispositivo"]})
    assert r.status_code == 201
    rid = r.json()["request_id"]

    r_aud = api_client.get(f"/auditoria/{rid}", headers={"X-API-Key": chaves["admin"]})
    assert r_aud.status_code == 200
    corpo = r_aud.json()
    assert corpo["log"] is not None
    assert corpo["leitura"] is not None
    assert corpo["score"] is not None


def test_auditoria_request_id_desconhecido_retorna_404(api_client, chaves):
    r = api_client.get("/auditoria/00000000-0000-0000-0000-000000000000", headers={"X-API-Key": chaves["admin"]})
    assert r.status_code == 404


def test_health_retorna_modelo_versao(api_client):
    r = api_client.get("/health")
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["modelo_versao"] is not None


# ---------------------------------------------------------------------------
# F1 — exceção não tratada: 500 com X-Request-Id + logs_uso (não só o handler genérico)
# ---------------------------------------------------------------------------
def test_excecao_nao_tratada_retorna_500_com_header_e_log(monkeypatch, db_engine, modelos_tmp, chaves):
    from fastapi.testclient import TestClient

    from agroguard.api.main import create_app
    from agroguard.telemetria import servico as telemetria_servico

    def _explode(*args, **kwargs):
        raise RuntimeError("falha proposital de teste")

    monkeypatch.setattr(telemetria_servico, "processar", _explode)

    payload = _payload("EQ-901", "2026-02-01T17:00:00")
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        r = client.post("/telemetria", json=payload, headers={"X-API-Key": chaves["dispositivo"]})

    assert r.status_code == 500
    assert "X-Request-Id" in r.headers
    corpo = r.json()
    assert corpo["codigo"] == "erro_interno"
    rid = r.headers["X-Request-Id"]
    assert corpo["request_id"] == rid

    with db_engine.connect() as conn:
        log = conn.execute(text("SELECT * FROM logs_uso WHERE request_id = :rid"), {"rid": rid}).mappings().first()
    assert log is not None
    assert log["status_http"] == 500


# ---------------------------------------------------------------------------
# F2 — /telemetria/lote valida item a item (um item ruim não derruba o lote)
# ---------------------------------------------------------------------------
def test_lote_com_item_invalido_de_schema_nao_derruba_lote_inteiro(api_client, chaves, db_engine):
    payload_valido = _payload("EQ-902", "2026-02-01T18:00:00")
    payload_invalido = _payload("EQ-901", "2026-02-01T18:00:00")
    payload_invalido["ambiente"]["umidade_solo"] = 1.5  # fora de 0..1: inválido de schema

    lote = {"leituras": [payload_valido, payload_invalido]}
    r = api_client.post("/telemetria/lote", json=lote, headers={"X-API-Key": chaves["dispositivo"]})
    assert r.status_code == 200
    corpo = r.json()
    assert len(corpo["aceitos"]) == 1
    assert len(corpo["rejeitados"]) == 1
    assert corpo["rejeitados"][0]["codigo"] == "validacao"

    with db_engine.connect() as conn:
        n = conn.execute(
            text("SELECT count(*) FROM leituras_telemetria WHERE equip_id = :eq AND data_hora = :dh"),
            {"eq": "EQ-902", "dh": "2026-02-01T18:00:00"},
        ).scalar()
    assert n == 1


# ---------------------------------------------------------------------------
# F3 — histórico de scores devolve as leituras MAIS RECENTES (não as mais antigas)
# ---------------------------------------------------------------------------
def test_historico_scores_retorna_as_leituras_mais_recentes(api_client, chaves):
    equip_id = "EQ-901"
    for hora in ("19", "20", "21"):
        payload = _payload(equip_id, f"2026-02-01T{hora}:00:00")
        r = api_client.post("/telemetria", json=payload, headers={"X-API-Key": chaves["dispositivo"]})
        assert r.status_code == 201

    r_hist = api_client.get(f"/equipamentos/{equip_id}/scores?limite=2", headers={"X-API-Key": chaves["gestor"]})
    assert r_hist.status_code == 200
    corpo = r_hist.json()
    assert len(corpo) == 2

    horas = [item["data_hora"] for item in corpo]
    assert horas == sorted(horas)  # ordem crescente (do mais antigo pro mais recente, dentro do recorte)
    assert horas[-1].startswith("2026-02-01T21:00:00")  # a leitura MAIS RECENTE está presente
    assert horas[0].startswith("2026-02-01T20:00:00")  # a segunda mais recente, não a mais antiga


# ---------------------------------------------------------------------------
# F7 — /auditoria/{request_id} com um valor que não é UUID retorna 422, não 500
# ---------------------------------------------------------------------------
def test_auditoria_request_id_invalido_retorna_422(api_client, chaves):
    r = api_client.get("/auditoria/abc", headers={"X-API-Key": chaves["admin"]})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# F9 — 422 não ecoa `input`/`url` do payload; corpo grande demais vira 413
# ---------------------------------------------------------------------------
def test_erro_validacao_nao_ecoa_input_do_payload(api_client, chaves):
    payload = _payload("EQ-901", "2026-02-01T22:00:00")
    payload["ambiente"]["umidade_solo"] = 1.5

    r = api_client.post("/telemetria", json=payload, headers={"X-API-Key": chaves["dispositivo"]})
    assert r.status_code == 422
    detalhe = r.json()["detalhe"]
    assert detalhe
    for erro in detalhe:
        assert "input" not in erro
        assert "url" not in erro


def test_payload_grande_retorna_413(api_client):
    corpo_grande = json.dumps({"x": "a" * 1_200_000}).encode("utf-8")
    r = api_client.post(
        "/telemetria",
        content=corpo_grande,
        headers={"X-API-Key": "irrelevante-para-este-teste", "Content-Type": "application/json"},
    )
    assert r.status_code == 413
    assert r.json()["codigo"] == "payload_grande"


# ---------------------------------------------------------------------------
# F18 — /openapi.json expõe X-API-Key como security scheme (Authorize no Swagger)
# ---------------------------------------------------------------------------
def test_openapi_expoe_security_scheme_x_api_key(api_client):
    r = api_client.get("/openapi.json")
    assert r.status_code == 200
    schemas = r.json().get("components", {}).get("securitySchemes", {})
    assert schemas
    assert any(s.get("type") == "apiKey" and s.get("name") == "X-API-Key" for s in schemas.values())
