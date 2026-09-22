# AgroGuard IA — API (Sprint 3/4)

Backend integrador do pipeline **entrada → banco → modelo → saída**: recebe telemetria via HTTP,
valida, persiste em PostgreSQL, pontua o risco através de `ml.inferencia`, gera alertas com
critério e recomendações explícitos, e audita cada requisição.

- Base local: `http://localhost:8001` (porta configurável em `API_PORT`)
- Rodar: `uvicorn agroguard.api.main:app --port 8001`
- Toda rota autenticada exige o header `X-API-Key` — ver [`docs/seguranca.md`](./seguranca.md).
- Toda resposta carrega o header `X-Request-Id` (ecoado do request ou gerado pela API), que
  correlaciona a requisição com `logs_uso`, `leituras_telemetria`, `scores_risco` e `alertas`.

## Rotas × papéis

| Rota | Método | Papéis permitidos | Descrição |
|---|---|---|---|
| `/health` | GET | público | Status da API: banco acessível, versão e carregamento do modelo |
| `/modelo/info` | GET | admin, gestor, seguradora | Versão do modelo, pasta dos artefatos e métricas de `reports/metrics.json` |
| `/telemetria` | POST | dispositivo, operador, admin | Envia UMA leitura; retorna o score de risco |
| `/telemetria/lote` | POST | dispositivo, operador, admin | Envia até 500 leituras; retorna aceitos/rejeitados |
| `/equipamentos` | GET | gestor, seguradora, admin | Frota com o último score/classe conhecido |
| `/equipamentos/{equip_id}/scores` | GET | gestor, seguradora, admin | Histórico de score de UM equipamento (US07) |
| `/alertas` | GET | gestor, seguradora, admin | Lista alertas (filtro opcional `status=aberto\|reconhecido`) |
| `/alertas/{id}/reconhecer` | POST | gestor, admin | Marca um alerta como reconhecido |
| `/relatorios/tendencias` | GET | gestor, seguradora, admin | Tendência semanal/diária por equipamento, região ou operação |
| `/auditoria/logs` | GET | admin | Log de uso da API (uma linha por requisição) |
| `/auditoria/rejeitadas` | GET | admin | Leituras recusadas pela validação |
| `/auditoria/{request_id}` | GET | admin | Encadeia log + leitura + score + alerta de um `request_id` |

## Exemplo — enviar uma leitura

```bash
curl -s -X POST http://localhost:8001/telemetria \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-dispositivo-troque-me" \
  -d '{
    "equipamento": {"equip_id": "EQ-014"},
    "telemetria": {
      "data_hora": "2026-02-01T08:00:00",
      "latitude": -12.5, "longitude": -55.7,
      "velocidade_kmh": 20.0, "inclinacao_graus": 3.0, "vibracao_g": 0.5
    },
    "ambiente": {
      "precip_24h_mm": 5.0, "precip_prev_6h_mm": 1.0, "umidade_solo": 0.4,
      "vento_max_kmh": 10.0, "dist_corpo_dagua_m": 500, "declividade_pct": 2.0
    },
    "operacao": {
      "tipo_operacao": "campo", "turno": "manha", "jornada_acumulada_h": 3.0,
      "dias_desde_manutencao": 5, "experiencia_operador_anos": 10
    }
  }'
```

Resposta (`201 Created`):

```json
{
  "leitura_id": 10001,
  "equip_id": "EQ-014",
  "data_hora": "2026-02-01T08:00:00",
  "risco_score": 17,
  "classe_risco": "Baixo",
  "alerta": false,
  "nivel_alerta": null,
  "fatores_principais": [{"fator": "turno", "valor": "manha", "contribuicao_pts": -5.3}],
  "recomendacoes": [],
  "regras_aplicadas": [],
  "modelo_versao": "v0.3",
  "request_id": "b5bc84e3-2901-48cd-8a6a-23aa46be5caf",
  "latencia_ms": 105
}
```

Quando `risco_score >= 80` (critério de alerta, `ml.features.ALERT_THRESHOLD`), a resposta também
traz `alerta: true`, `nivel_alerta` (`Alto` ou `Critico`) e `recomendacoes` não vazias (ex.:
`ADIAR_OPERACAO`, `REDUZIR_VELOCIDADE`) — a mesma leitura já aparece em `GET /alertas`.

## Erros

Toda falha de negócio devolve o mesmo formato (`ErroOut`) e o header `X-Request-Id`:

```json
{"codigo": "inconsistencia", "mensagem": "...", "request_id": "...", "detalhe": null}
```

| Código | HTTP | Quando acontece |
|---|---|---|
| `validacao` | 422 | Payload não passa nas faixas do schema (ex.: `umidade_solo` fora de 0–1) |
| `inconsistencia` | 422 | Payload válido, mas inconsistente entre campos (ex.: `parado` com velocidade alta) |
| `equip_desconhecido` | 422 | `equip_id` não está cadastrado na frota |
| `duplicado` | 409 | Já existe leitura para o mesmo `equip_id` + `data_hora` |
| `nao_autenticado` | 401 | `X-API-Key` ausente ou inválida |
| `assinatura` | 401 | `X-Signature` ausente (quando exigida) ou não confere com o corpo |
| `nao_autorizado` | 403 | Chave válida, mas papel sem acesso à rota |
| `limite_excedido` | 429 | Rate limit por chave excedido |
| `nao_encontrado` | 404 | Recurso inexistente (alerta, `request_id` de auditoria) |
| `modelo_indisponivel` | 503 | Modelo de ML não carregado (`python -m ml.train` não rodou) |
| `erro_interno` | 500 | Erro inesperado — nunca expõe stack trace na resposta |

Toda leitura recusada (`validacao`, `inconsistencia`, `equip_desconhecido`, `duplicado`) também
gera uma linha em `leituras_rejeitadas`, e toda requisição gera uma linha em `logs_uso` — ver
[`docs/seguranca.md`](./seguranca.md).
