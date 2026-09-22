"""
AgroGuard IA — Contratos de entrada/saída da API (Sprint 3/4)
==============================================================

Schemas Pydantic v2. Validam apenas forma e faixa de cada campo — as regras
de CONSISTÊNCIA entre campos (ex.: `parado` implica velocidade baixa) vivem
em `agroguard.telemetria.servico`, não aqui: um schema não decide negócio.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class EquipamentoRef(BaseModel):
    equip_id: str = Field(..., pattern=r"^EQ-\d{3}$")


class TelemetriaCampos(BaseModel):
    data_hora: datetime
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    velocidade_kmh: float = Field(..., ge=0, le=120)
    inclinacao_graus: float = Field(..., ge=0, le=45)
    vibracao_g: float = Field(..., ge=0, le=5)


class AmbienteIn(BaseModel):
    precip_24h_mm: float = Field(..., ge=0, le=300)
    precip_prev_6h_mm: float = Field(..., ge=0, le=100)
    umidade_solo: float = Field(..., ge=0, le=1)
    vento_max_kmh: float = Field(..., ge=0, le=150)
    dist_corpo_dagua_m: int = Field(..., ge=0, le=10000)
    declividade_pct: float = Field(..., ge=0, le=45)


class OperacaoIn(BaseModel):
    tipo_operacao: Literal["campo", "transporte", "parado"]
    turno: Literal["manha", "tarde", "noite"]
    jornada_acumulada_h: float = Field(..., ge=0, le=24)
    dias_desde_manutencao: int = Field(..., ge=0, le=365)
    experiencia_operador_anos: int = Field(..., ge=0, le=50)


class TelemetriaIn(BaseModel):
    equipamento: EquipamentoRef
    telemetria: TelemetriaCampos
    ambiente: AmbienteIn
    operacao: OperacaoIn


class LoteIn(BaseModel):
    leituras: list[TelemetriaIn] = Field(..., min_length=1, max_length=500)


class ScoreOut(BaseModel):
    leitura_id: int
    equip_id: str
    data_hora: datetime
    risco_score: int
    classe_risco: str
    alerta: bool
    nivel_alerta: str | None = None
    fatores_principais: list[dict[str, Any]] = Field(default_factory=list)
    recomendacoes: list[dict[str, Any]] = Field(default_factory=list)
    regras_aplicadas: list[str] = Field(default_factory=list)
    modelo_versao: str
    request_id: UUID
    latencia_ms: int


class RejeicaoLoteItem(BaseModel):
    """Uma linha de `POST /telemetria/lote` que não foi aceita."""

    indice: int
    codigo: str
    mensagem: str


class LoteResultado(BaseModel):
    aceitos: list[ScoreOut] = Field(default_factory=list)
    rejeitados: list[RejeicaoLoteItem] = Field(default_factory=list)


class AlertaOut(BaseModel):
    id: int
    score_id: int | None = None
    leitura_id: int | None = None
    equip_id: str
    nivel: str
    criterio: str
    mensagem: str
    recomendacoes: list[dict[str, Any]] = Field(default_factory=list)
    status: str
    request_id: UUID | None = None
    criado_em: datetime


class TendenciaOut(BaseModel):
    chave: str
    periodo: datetime
    leituras: int
    score_medio: float
    score_pico: int
    alertas: int
    taxa_sinistro_pct: float


class LogUsoOut(BaseModel):
    id: int
    request_id: UUID
    ocorrido_em: datetime
    kid: str | None = None
    papel: str | None = None
    metodo: str | None = None
    rota: str | None = None
    status_http: int | None = None
    duracao_ms: int | None = None
    ip: str | None = None
    detalhe: dict[str, Any] | None = None


class RejeicaoOut(BaseModel):
    id: int
    recebido_em: datetime
    origem: str | None = None
    codigo: str
    motivo: str
    payload: dict[str, Any] | None = None
    payload_hash: str | None = None
    request_id: UUID | None = None


class ErroOut(BaseModel):
    codigo: str
    mensagem: str
    request_id: str | None = None
    detalhe: Any = None
