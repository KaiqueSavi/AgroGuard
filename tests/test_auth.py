"""
Testes de autenticação, autorização, assinatura e rate limit da API.

Usa a fixture `api_client` (que depende de `db_engine`/`modelos_tmp`) — sem
`AGROGUARD_REQUIRE_DB=1` esses testes são pulados quando o PostgreSQL local
não está disponível.
"""
from __future__ import annotations


def _assert_formato_erro(resposta) -> dict:
    """Toda resposta de erro carrega X-Request-Id e o corpo no formato ErroOut."""
    assert "X-Request-Id" in resposta.headers
    corpo = resposta.json()
    assert set(corpo) >= {"codigo", "mensagem", "request_id"}
    assert corpo["request_id"] == resposta.headers["X-Request-Id"]
    return corpo


def test_sem_chave_retorna_401(api_client):
    r = api_client.post("/telemetria", json={})
    assert r.status_code == 401
    corpo = _assert_formato_erro(r)
    assert corpo["codigo"] == "nao_autenticado"


def test_chave_errada_retorna_401(api_client):
    r = api_client.post("/telemetria", json={}, headers={"X-API-Key": "chave-que-nao-existe"})
    assert r.status_code == 401
    corpo = _assert_formato_erro(r)
    assert corpo["codigo"] == "nao_autenticado"


def test_operador_nao_acessa_auditoria(api_client, chaves):
    r = api_client.get("/auditoria/logs", headers={"X-API-Key": chaves["operador"]})
    assert r.status_code == 403
    corpo = _assert_formato_erro(r)
    assert corpo["codigo"] == "nao_autorizado"


def test_seguradora_nao_envia_telemetria(api_client, chaves):
    r = api_client.post("/telemetria", json={}, headers={"X-API-Key": chaves["seguradora"]})
    assert r.status_code == 403
    corpo = _assert_formato_erro(r)
    assert corpo["codigo"] == "nao_autorizado"


def test_assinatura_invalida_retorna_401(api_client, chaves):
    r = api_client.post(
        "/telemetria",
        json={"qualquer": "coisa"},
        headers={"X-API-Key": chaves["dispositivo"], "X-Signature": "0" * 64},
    )
    assert r.status_code == 401
    corpo = _assert_formato_erro(r)
    assert corpo["codigo"] == "assinatura"


def test_rate_limit_excedido(api_client, chaves, monkeypatch):
    from agroguard.api.auth import resetar_limitador
    from agroguard.config import recarregar

    resetar_limitador()
    monkeypatch.setenv("RATE_LIMIT_POR_MIN", "2")
    recarregar()
    try:
        headers = {"X-API-Key": chaves["gestor"]}
        r1 = api_client.get("/alertas", headers=headers)
        r2 = api_client.get("/alertas", headers=headers)
        r3 = api_client.get("/alertas", headers=headers)

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r3.status_code == 429
        corpo = _assert_formato_erro(r3)
        assert corpo["codigo"] == "limite_excedido"
    finally:
        monkeypatch.undo()
        recarregar()
        resetar_limitador()
