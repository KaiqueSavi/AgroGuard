# Validação da integração — Sprint 3/4

Este documento reúne as evidências de validação do simulador de fontes de dados
(`simulador/`) e dos testes de integração (`tests/test_integracao.py`) que provam,
ponta a ponta, que a coleta simulada de telemetria/ambiente/operação chega ao
backend AgroGuard **sem perda**, com o **score persistido consistente com o
modelo** carregado em memória, com **rastreabilidade completa por `request_id`**
e com **integridade/assinatura** verificáveis na borda da API.

## O que foi validado

1. **Coleta sem perda (confiabilidade).** `simulador.simulador_iot.gerar_eventos`
   gera um lote determinístico com uma fração deliberada de leituras inválidas
   (fora de faixa do schema, inconsistentes com a regra de negócio, equipamento
   desconhecido) e duplicadas (mesma `equip_id` + `data_hora` de um evento válido
   anterior do lote). `enviar` envia tudo para `POST /telemetria` e reconcilia:
   `enviados == aceitos + rejeitados + duplicados`, sem nenhum "erro silencioso".
   `tests/test_integracao.py::test_reconciliacao_sem_perda` prova isso contando as
   linhas realmente gravadas em `leituras_telemetria`, `scores_risco`, `alertas`,
   `leituras_rejeitadas` e `logs_uso` — filtrando pelos `request_id` do próprio
   lote — e comparando com o que a API respondeu.
2. **Consistência modelo ↔ banco.** `test_consistencia_score_modelo` reconstrói,
   para cada leitura aceita, a linha de features exatamente como
   `agroguard.risco.servico._linha_features` monta (join com `equipamentos` para
   `tipo_equip`/`idade_equipamento_anos`) e chama `ml.inferencia.prever` com o
   MESMO modelo carregado pela API (`modelos_tmp`) — o `risco_score`/`classe_risco`
   recalculados batem, bit a bit, com o que está gravado em `scores_risco`, e
   `alerta == (risco_score >= ALERT_THRESHOLD)` em 100% dos casos.
3. **Rastreabilidade.** `test_rastreabilidade` pega um `request_id` aceito e
   confirma que `GET /auditoria/{request_id}` (papel `admin`) encadeia log de uso,
   leitura, score (com `fatores_principais` como lista) e alerta (nulo ou coerente
   com a resposta do POST original).
4. **Integridade / assinatura.** `test_lote_e_assinatura` cobre `POST
   /telemetria/lote` (9 aceitos / 1 recusado por regra de negócio, no mesmo
   padrão de `tests/test_api.py::test_lote_com_um_item_invalido`), um `POST`
   assinado (`X-Signature` = HMAC-SHA256 do corpo canônico) aceito com `201`, e um
   `X-Signature` adulterado recusado com `401 assinatura`.
5. **Determinismo do simulador.** `test_simulador_determinista` prova que o mesmo
   `seed` produz exatamente os mesmos payloads (mesmo `agora` fixo) — pré-requisito
   para reproduzir qualquer achado da suíte.

## Como reproduzir

```bash
cd /Users/kaiquesavi/Documents/Github/agroguard-sprint2

# 1) Suíte de testes de integração (banco de teste `agroguard_test`, schema aplicado
#    automaticamente por tests/conftest.py — precisa do Postgres local em :5433).
AGROGUARD_REQUIRE_DB=1 .venv/bin/python -m pytest -q -m integracao

# 2) Suíte inteira (garante que a suíte nova não quebrou nada existente).
AGROGUARD_REQUIRE_DB=1 .venv/bin/python -m pytest -q -rA | tee docs/prints/pytest_output.txt

# 3) Execução manual contra a API viva (banco de DESENVOLVIMENTO `agroguard`,
#    50 equipamentos reais do dataset), com leituras inválidas, duplicadas e
#    assinatura HMAC:
.venv/bin/uvicorn agroguard.api.main:app --port 8001 &
.venv/bin/python -m simulador.simulador_iot \
    --n 100 --seed 42 --taxa-invalidos 0.05 --taxa-duplicados 0.05 --assinar \
    | tee docs/prints/simulador_execucao.txt

# 4) Evidência das linhas realmente gravadas no banco de desenvolvimento pela
#    execução acima (via docker exec no container do Postgres):
docker exec agroguard_db psql -U agroguard -d agroguard -c \
  "SELECT count(*) FROM logs_uso WHERE ocorrido_em >= now() - interval '10 minutes';"
docker exec agroguard_db psql -U agroguard -d agroguard -c \
  "SELECT codigo, count(*) FROM leituras_rejeitadas WHERE recebido_em >= now() - interval '10 minutes' GROUP BY codigo;"
docker exec agroguard_db psql -U agroguard -d agroguard -c \
  "SELECT count(*) FROM alertas WHERE criado_em >= now() - interval '10 minutes';"
```

## Resultados (execução real, 22/09/2026)

### Suíte de testes

| Comando | Resultado |
|---|---|
| `pytest -q -m integracao` | **5 passed** (0 skipped, 0 failed) — ver `docs/prints/pytest_output.txt` |
| `pytest -q -rA` (suíte inteira) | **57 passed**, 1 warning (deprecação do `httpx` no `TestClient`, pré-existente) |
| `python -m simulador.simulador_iot --help` | exit code `0` |

### Reconciliação do lote de `test_reconciliacao_sem_perda` (n=200, seed=7, 5% inválidos, 5% duplicados)

| Métrica | Esperado | Observado |
|---|---|---|
| enviados | 200 | 200 |
| aceitos | 180 | 180 |
| rejeitados (validação + inconsistência + equip. desconhecido) | 10 | 10 (4 + 3 + 3) |
| duplicados (409) | 10 | 10 |
| `leituras_telemetria` gravadas (`origem in ('api','simulador')`, por `request_id` do lote) | 180 | 180 |
| `scores_risco` gravados (1 por leitura, sem duplicidade por `modelo_versao`) | 180 | 180 |
| `leituras_rejeitadas` gravadas (10 inválidas + 10 duplicadas, ver nota) | 20 | 20 |
| `logs_uso` gravados (uma linha por requisição, inclusive as recusadas) | 200 | 200 |

> **Nota:** `leituras_rejeitadas` registra **toda** leitura recusada, inclusive as
> duplicadas (`codigo='duplicado'`) — documentado em `docs/api.md` ("Toda leitura
> recusada (validacao, inconsistencia, equip_desconhecido, duplicado) também gera
> uma linha em leituras_rejeitadas"). Por isso o total nessa tabela é
> 10 (inválidas) + 10 (duplicadas) = 20, e não 10.

### Execução manual contra a API viva (`--n 100 --seed 42 --taxa-invalidos 0.05 --taxa-duplicados 0.05 --assinar`, banco `agroguard` de desenvolvimento)

Linha de reconciliação impressa pelo simulador (verbatim, `docs/prints/simulador_execucao.txt`):

```
enviados=100 aceitos=90 rejeitados=5 duplicados=5 alertas=0 (A+R+D=100 ✔)
```

Contagem real no banco de desenvolvimento (`docker exec agroguard_db psql ...`),
filtrando pelos últimos 10 minutos após a execução:

| Tabela / filtro | Contagem |
|---|---|
| `leituras_telemetria` (origem = `simulador`) | 90 |
| `scores_risco` | 90 |
| `logs_uso` (uma por requisição, inclusive 4xx/409) | 100 |
| `leituras_rejeitadas` — total | 10 |
| `leituras_rejeitadas` — `validacao` | 2 |
| `leituras_rejeitadas` — `inconsistencia` | 2 |
| `leituras_rejeitadas` — `equip_desconhecido` | 1 |
| `leituras_rejeitadas` — `duplicado` | 5 |
| `alertas` | 0 (nenhum evento deste lote cruzou `risco_score >= 80`) |

`90 (aceitos) + 5 (rejeitados de negócio) + 5 (duplicados) = 100 = enviados` — sem
perda. `90 leituras_telemetria` + `90 scores_risco`: uma linha de score por
leitura, sem nenhuma leitura sem score. As `leituras_rejeitadas` somam as 5
rejeições de negócio (2 `validacao` + 2 `inconsistencia` + 1 `equip_desconhecido`)
com as 5 duplicadas (`codigo='duplicado'`) — 10 linhas no total, mesmo motivo
documentado na nota da seção anterior.

## Limitações conhecidas

- **Processo único, sem concorrência real.** O simulador roda em série (um `POST`
  por vez, ou um único lote via `--lote`); ele não reproduz múltiplos
  dispositivos IoT enviando simultaneamente. As regras de negócio (duplicidade,
  rate limit) foram desenhadas e testadas para esse caso serial.
- **Dados sintéticos.** As leituras partem de `data/synthetic_dataset.csv` com
  jitter gaussiano pequeno — plausíveis, mas não são leituras reais de campo.
- **Clima real é opcional e nunca teve seu resultado usado pela suíte.**
  `simulador.clima.enriquecer_com_clima` (Open-Meteo, `--clima-real`) depende de
  rede externa; falhas de rede são silenciosas por design (mantém o payload
  sintético) e nenhum teste automatizado depende de uma resposta real da
  Open-Meteo.
- **Rate limit ajustado durante o teste de reconciliação.** O lote de 200 eventos
  de `test_reconciliacao_sem_perda` é enviado sem pausa; para não confundir
  "recusado pelo rate limit" com "recusado pela validação de negócio" (o que
  este teste quer provar), a fixture eleva temporariamente
  `RATE_LIMIT_POR_MIN` só durante o envio (mesmo padrão de
  `tests/test_auth.py::test_rate_limit_excedido`) e devolve o valor original
  antes de retornar — o rate limit em si já tem teste dedicado em
  `tests/test_auth.py`.
- **Banco de teste compartilhado entre arquivos.** `tests/conftest.py` usa uma
  única engine `agroguard_test` de escopo de sessão para toda a suíte. Para não
  poluir o ranking "top 5" de `tests/test_relatorio.py` com as leituras "ao vivo"
  deste módulo, `tests/test_integracao.py` limpa (`DELETE`) as leituras que
  gravou nos 50 `equip_id` do dataset ao final do módulo — os demais efeitos
  (leituras rejeitadas, logs de uso) permanecem, pois não afetam nenhuma
  asserção de outro arquivo.
