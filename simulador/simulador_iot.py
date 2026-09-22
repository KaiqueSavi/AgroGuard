"""
AgroGuard IA — Simulador de fontes de dados (Sprint 3/4)
==========================================================

"Dispositivo IoT" simulado de ponta a ponta: gera eventos determinísticos
(`gerar_eventos`) a partir do dataset sintético (`data/synthetic_dataset.csv`)
— combinando os blocos `telemetria`/`ambiente`/`operacao` de
`simulador.fontes` — e os envia para a API (`enviar`), reconciliando o que
foi enviado com o que a API aceitou, rejeitou ou detectou como duplicado.

Usado por:
  - `tests/test_integracao.py` (confiabilidade da coleta e consistência)
  - a CLI abaixo, para gerar a evidência manual de `docs/validacao.md`

Rodar:
    python -m simulador.simulador_iot --n 100 --seed 42 \
        --taxa-invalidos 0.05 --taxa-duplicados 0.05 --assinar
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import hmac
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from random import Random
from typing import Any, Callable

import pandas as pd

from simulador.fontes import ambiente as fonte_ambiente
from simulador.fontes import operacao as fonte_operacao
from simulador.fontes import telemetria as fonte_telemetria

ROOT = Path(__file__).resolve().parents[1]
CSV_PADRAO = ROOT / "data" / "synthetic_dataset.csv"

# Rotação determinística dos três motivos de leitura inválida.
_KINDS_INVALIDAS = ("fora_de_faixa", "inconsistente", "equip_desconhecido")
_CODIGO_POR_KIND = {
    "fora_de_faixa": "validacao",
    "inconsistente": "inconsistencia",
    "equip_desconhecido": "equip_desconhecido",
}


@dataclass
class Evento:
    """Um evento gerado por `gerar_eventos`: o payload pronto para POST + o veredito esperado."""

    indice: int
    payload: dict[str, Any]
    tipo: str  # 'valido' | 'invalido' | 'duplicado'
    motivo_esperado: str | None = None


@dataclass
class Reconciliacao:
    """Resultado agregado de `enviar`: quanto foi enviado x aceito x recusado x duplicado."""

    enviados: int = 0
    aceitos: int = 0
    rejeitados_validacao: int = 0
    rejeitados_inconsistencia: int = 0
    rejeitados_equip: int = 0
    duplicados_409: int = 0
    outros_erros: int = 0
    alertas: int = 0
    request_ids: list[str] = field(default_factory=list)
    respostas: list[tuple[Evento | None, int, Any]] = field(default_factory=list)

    def linha(self) -> str:
        rejeitados = (
            self.rejeitados_validacao
            + self.rejeitados_inconsistencia
            + self.rejeitados_equip
            + self.outros_erros
        )
        soma = self.aceitos + rejeitados + self.duplicados_409
        ok = "✔" if soma == self.enviados else "✘"
        return (
            f"enviados={self.enviados} aceitos={self.aceitos} rejeitados={rejeitados} "
            f"duplicados={self.duplicados_409} alertas={self.alertas} "
            f"(A+R+D={soma} {ok})"
        )


def _clip(valor: float, minimo: float, maximo: float) -> float:
    return max(minimo, min(maximo, valor))


# ---------------------------------------------------------------------------
# Geração de eventos
# ---------------------------------------------------------------------------
def _carregar_dataset(csv: Path) -> pd.DataFrame:
    return pd.read_csv(csv)


def _equipamentos_padrao(df: pd.DataFrame) -> list[str]:
    """Os equip_id do CSV, em ordem estável — mesma lista para todo `seed`."""
    return sorted(df["equip_id"].unique().tolist())


def gerar_eventos(
    n: int,
    seed: int,
    taxa_invalidos: float = 0.0,
    taxa_duplicados: float = 0.0,
    csv: Path | str = CSV_PADRAO,
    agora: datetime | None = None,
    equipamentos: list[str] | None = None,
) -> list[Evento]:
    """
    Gera `n` eventos determinísticos (mesmo `seed` -> mesmos payloads):

      - `round(n * taxa_invalidos)` eventos inválidos, rotacionados
        deterministicamente entre três motivos: fora de faixa (schema),
        inconsistente (regra de negócio) e equipamento desconhecido;
      - `round(n * taxa_duplicados)` eventos duplicados: cópia EXATA de um
        evento VÁLIDO anterior do mesmo lote (mesma `equip_id` + `data_hora`),
        posicionada depois do original — para disparar 409 na API;
      - o restante, eventos válidos, com jitter gaussiano pequeno sobre uma
        linha real do dataset sintético.

    `equipamentos` restringe os `equip_id` sorteados (por exemplo, aos que
    foram cadastrados no banco de teste); por padrão, os 50 do CSV.
    """
    df_completo = _carregar_dataset(Path(csv))
    equip_ids = equipamentos if equipamentos is not None else _equipamentos_padrao(df_completo)
    df = df_completo[df_completo["equip_id"].isin(equip_ids)].reset_index(drop=True)
    if df.empty:
        raise ValueError("Nenhuma linha do dataset corresponde aos `equipamentos` informados.")

    agora_base = agora if agora is not None else datetime.utcnow()
    rng = Random(seed)

    n_invalidos = round(n * taxa_invalidos)
    n_duplicados = round(n * taxa_duplicados)
    n_validos = n - n_invalidos - n_duplicados
    if n_validos < 0:
        raise ValueError("taxa_invalidos + taxa_duplicados não pode superar 1.0.")
    if n_duplicados and n_validos == 0:
        raise ValueError("taxa_duplicados > 0 exige ao menos um evento válido no lote para duplicar.")

    def _linha_para(equip_id: str) -> pd.Series:
        subset = df[df["equip_id"] == equip_id]
        if subset.empty:
            subset = df
        posicao = rng.randrange(len(subset))
        return subset.iloc[posicao]

    def _montar_payload(equip_id: str, linha: pd.Series, indice: int) -> dict[str, Any]:
        # Offset em milissegundos: garante `data_hora` único por evento sem
        # nunca ultrapassar o limite de "5 minutos no futuro" da API, mesmo
        # para lotes grandes (até 500 leituras/lote).
        agora_evento = agora_base + timedelta(milliseconds=indice)
        return {
            "equipamento": {"equip_id": equip_id},
            "telemetria": fonte_telemetria.amostrar(linha, agora_evento, rng),
            "ambiente": fonte_ambiente.amostrar(linha, agora_evento, rng),
            "operacao": fonte_operacao.amostrar(linha, agora_evento, rng),
        }

    eventos: list[Evento] = []
    validos: list[Evento] = []
    indice = 0

    for _ in range(n_validos):
        equip_id = equip_ids[indice % len(equip_ids)]
        linha = _linha_para(equip_id)
        payload = _montar_payload(equip_id, linha, indice)
        evento = Evento(indice=indice, payload=payload, tipo="valido", motivo_esperado=None)
        eventos.append(evento)
        validos.append(evento)
        indice += 1

    for j in range(n_invalidos):
        kind = _KINDS_INVALIDAS[j % len(_KINDS_INVALIDAS)]
        equip_id = equip_ids[indice % len(equip_ids)]
        linha = _linha_para(equip_id)
        payload = _montar_payload(equip_id, linha, indice)

        if kind == "fora_de_faixa":
            payload["ambiente"]["umidade_solo"] = 1.5  # fora de 0..1 (validação de schema)
        elif kind == "inconsistente":
            payload["operacao"]["tipo_operacao"] = "parado"
            payload["telemetria"]["velocidade_kmh"] = 40.0  # parado exige < 1.0
        else:  # equip_desconhecido
            payload["equipamento"]["equip_id"] = "EQ-999"

        eventos.append(
            Evento(indice=indice, payload=payload, tipo="invalido", motivo_esperado=_CODIGO_POR_KIND[kind])
        )
        indice += 1

    for k in range(n_duplicados):
        original = validos[k % len(validos)]
        payload = copy.deepcopy(original.payload)
        eventos.append(Evento(indice=indice, payload=payload, tipo="duplicado", motivo_esperado="duplicado"))
        indice += 1

    return eventos


# ---------------------------------------------------------------------------
# Envio + reconciliação
# ---------------------------------------------------------------------------
def _assinar(segredo: str, corpo: bytes) -> str:
    return hmac.new(segredo.encode("utf-8"), corpo, hashlib.sha256).hexdigest()


def _classificar_resposta(evento: Evento, status: int, corpo: Any, reconciliacao: Reconciliacao) -> None:
    reconciliacao.respostas.append((evento, status, corpo))

    rid = corpo.get("request_id") if isinstance(corpo, dict) else None
    if rid:
        reconciliacao.request_ids.append(rid)

    if status in (200, 201):
        reconciliacao.aceitos += 1
        if isinstance(corpo, dict) and corpo.get("alerta"):
            reconciliacao.alertas += 1
        return

    codigo = corpo.get("codigo") if isinstance(corpo, dict) else None
    if status == 409 or codigo == "duplicado":
        reconciliacao.duplicados_409 += 1
    elif codigo == "validacao":
        reconciliacao.rejeitados_validacao += 1
    elif codigo == "inconsistencia":
        reconciliacao.rejeitados_inconsistencia += 1
    elif codigo == "equip_desconhecido":
        reconciliacao.rejeitados_equip += 1
    else:
        reconciliacao.outros_erros += 1


def enviar(
    cliente: Any,
    eventos: list[Evento],
    api_key: str,
    intervalo: float = 0.0,
    assinar: bool = False,
    base_url: str = "",
    on_evento: Callable[[Evento, int, Any], None] | None = None,
) -> Reconciliacao:
    """
    Envia um `POST {base_url}/telemetria` por evento, reconciliando
    aceitos/rejeitados/duplicados. `cliente` é qualquer objeto com `.post`
    compatível com `httpx.Client`/`fastapi.testclient.TestClient` (ambos
    aceitam `content=` + `headers=`).

    Quando `assinar=True`, adiciona `X-Signature` = HMAC-SHA256(api_key,
    corpo canônico) em hexadecimal — o corpo é serializado com
    `json.dumps(..., separators=(',', ':'))` e enviado via `content=` (em vez
    de `json=`) para que os bytes assinados sejam EXATAMENTE os bytes que o
    servidor recebe.
    """
    reconciliacao = Reconciliacao(enviados=len(eventos))
    url = f"{base_url}/telemetria" if base_url else "/telemetria"

    for evento in eventos:
        corpo_bruto = json.dumps(evento.payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
        if assinar:
            headers["X-Signature"] = _assinar(api_key, corpo_bruto)

        resposta = cliente.post(url, content=corpo_bruto, headers=headers)
        try:
            corpo_resposta = resposta.json()
        except Exception:
            corpo_resposta = None

        _classificar_resposta(evento, resposta.status_code, corpo_resposta, reconciliacao)
        if on_evento is not None:
            on_evento(evento, resposta.status_code, corpo_resposta)

        if intervalo:
            time.sleep(intervalo)

    return reconciliacao


def enviar_lote(
    cliente: Any,
    eventos: list[Evento],
    api_key: str,
    assinar: bool = False,
    base_url: str = "",
) -> Reconciliacao:
    """Envia todos os `eventos` numa ÚNICA chamada a `POST /telemetria/lote` (até 500)."""
    reconciliacao = Reconciliacao(enviados=len(eventos))
    url = f"{base_url}/telemetria/lote" if base_url else "/telemetria/lote"
    corpo = {"leituras": [evento.payload for evento in eventos]}
    corpo_bruto = json.dumps(corpo, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    if assinar:
        headers["X-Signature"] = _assinar(api_key, corpo_bruto)

    resposta = cliente.post(url, content=corpo_bruto, headers=headers)
    try:
        corpo_resposta = resposta.json()
    except Exception:
        corpo_resposta = None
    reconciliacao.respostas.append((None, resposta.status_code, corpo_resposta))

    if resposta.status_code == 200 and isinstance(corpo_resposta, dict):
        for item in corpo_resposta.get("aceitos", []):
            reconciliacao.aceitos += 1
            if item.get("request_id"):
                reconciliacao.request_ids.append(item["request_id"])
            if item.get("alerta"):
                reconciliacao.alertas += 1
        for item in corpo_resposta.get("rejeitados", []):
            codigo = item.get("codigo")
            if codigo == "duplicado":
                reconciliacao.duplicados_409 += 1
            elif codigo == "validacao":
                reconciliacao.rejeitados_validacao += 1
            elif codigo == "inconsistencia":
                reconciliacao.rejeitados_inconsistencia += 1
            elif codigo == "equip_desconhecido":
                reconciliacao.rejeitados_equip += 1
            else:
                reconciliacao.outros_erros += 1
    else:
        reconciliacao.outros_erros += len(eventos)

    return reconciliacao


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _resolver_api_key(argumento: str | None) -> str:
    if argumento:
        return argumento

    do_env = os.getenv("AGROGUARD_SIM_KEY")
    if do_env:
        return do_env

    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env", override=False)
    except ImportError:  # pragma: no cover
        pass

    bruto = os.getenv("AGROGUARD_API_KEYS", "")
    for item in bruto.split(","):
        partes = item.strip().split(":", 2)
        if len(partes) == 3 and partes[1] == "dispositivo":
            return partes[2]

    raise SystemExit(
        "Nenhuma chave de API encontrada: informe --api-key, defina AGROGUARD_SIM_KEY "
        "ou AGROGUARD_API_KEYS no .env (kid:papel:segredo)."
    )


def _linha_evento(evento: Evento, status: int, corpo: Any) -> str:
    equip_id = evento.payload["equipamento"]["equip_id"]
    if status in (200, 201) and isinstance(corpo, dict):
        detalhe = f"score={corpo.get('risco_score')} classe={corpo.get('classe_risco')}"
    else:
        codigo = corpo.get("codigo") if isinstance(corpo, dict) else status
        detalhe = f"erro={codigo}"
    return f"[{evento.indice:04d}] tipo={evento.tipo:<9} equip={equip_id} status={status} {detalhe}"


def _construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m simulador.simulador_iot",
        description=(
            "Simulador de fontes de dados AgroGuard — gera telemetria/ambiente/operação "
            "sintéticas (com uma fração deliberada de leituras inválidas e duplicadas) e "
            "envia para a API AgroGuard."
        ),
    )
    parser.add_argument("--n", type=int, default=100, help="Quantidade de eventos a gerar.")
    parser.add_argument("--seed", type=int, default=42, help="Semente determinística do gerador.")
    parser.add_argument("--taxa-invalidos", type=float, default=0.0, help="Fração de eventos inválidos (0..1).")
    parser.add_argument("--taxa-duplicados", type=float, default=0.0, help="Fração de eventos duplicados (0..1).")
    parser.add_argument("--base-url", default="http://localhost:8001", help="URL base da API (somente localhost).")
    parser.add_argument("--api-key", default=None, help="Segredo do papel dispositivo (padrão: env/​.env).")
    parser.add_argument("--intervalo", type=float, default=0.0, help="Pausa (s) entre requisições.")
    parser.add_argument("--assinar", action="store_true", help="Assina cada requisição com X-Signature (HMAC-SHA256).")
    parser.add_argument("--clima-real", action="store_true", help="Enriquece o bloco `ambiente` via Open-Meteo.")
    parser.add_argument("--lote", action="store_true", help="Envia tudo de uma vez via POST /telemetria/lote.")
    return parser


def _main(argv: list[str] | None = None) -> int:
    args = _construir_parser().parse_args(argv)
    api_key = _resolver_api_key(args.api_key)

    eventos = gerar_eventos(
        n=args.n, seed=args.seed, taxa_invalidos=args.taxa_invalidos, taxa_duplicados=args.taxa_duplicados
    )

    if args.clima_real:
        from simulador.clima import enriquecer_com_clima

        for evento in eventos:
            evento.payload, _fonte = enriquecer_com_clima(evento.payload)

    import httpx

    with httpx.Client(base_url=args.base_url, timeout=10.0) as cliente:
        if args.lote:
            reconciliacao = enviar_lote(cliente, eventos, api_key, assinar=args.assinar)
            _, status_lote, corpo_lote = reconciliacao.respostas[0]
            print(f"lote enviado: {len(eventos)} leituras em 1 requisição (status={status_lote})")
        else:
            reconciliacao = enviar(
                cliente,
                eventos,
                api_key,
                intervalo=args.intervalo,
                assinar=args.assinar,
                on_evento=lambda ev, status, corpo: print(_linha_evento(ev, status, corpo)),
            )

    print(reconciliacao.linha())

    rejeitados = (
        reconciliacao.rejeitados_validacao
        + reconciliacao.rejeitados_inconsistencia
        + reconciliacao.rejeitados_equip
        + reconciliacao.outros_erros
    )
    soma = reconciliacao.aceitos + rejeitados + reconciliacao.duplicados_409
    return 0 if soma == reconciliacao.enviados else 1


def main() -> None:
    raise SystemExit(_main())


if __name__ == "__main__":
    main()
