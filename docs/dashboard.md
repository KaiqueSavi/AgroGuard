# 📊 Dashboard — AgroGuard IA (Sprint 3/4 · v2)

> O que cada aba mostra, para qual persona/User Story ela serve, como rodar
> localmente e a legenda de critérios de alerta (texto gerado a partir do
> código — sempre confira `agroguard/alertas/servico.py` como fonte da verdade).

## Como rodar

```bash
# Suba o banco (docker-compose) e ative o venv, se ainda não fez:
docker compose up -d db
source .venv/bin/activate

streamlit run app/streamlit_app.py
# abre em http://localhost:8501
```

Sem o PostgreSQL acessível, o dashboard cai automaticamente para
`data/synthetic_dataset.csv` — os KPIs, o mapa e a distribuição por classe
continuam funcionando, mas as abas **Alertas & recomendações** e
**Auditoria** avisam que precisam do banco (fazenda/região reais, alertas da
tabela `alertas`, `logs_uso`, `leituras_rejeitadas` só existem no Postgres).

Toda leitura de dados (SQL ou CSV) vive em `app/consultas.py` — é o único
módulo do pacote `app` que executa consulta. `app/streamlit_app.py` só monta
a interface e chama essas funções.

## Filtros (barra lateral)

Período (intervalo de `data_hora`), região, fazenda, tipo de equipamento,
classe de risco e equipamento. Todos combinam por `E` lógico; filtros vazios
mostram `st.info` em vez de travar a tela.

## Abas

### Visão geral
KPIs da frota (leituras, score médio, alertas ativos ≥ 80, taxa de sinistro,
equipamentos em Crítico *agora* — última leitura conhecida de cada
equipamento), mapa colorido por classe de risco, distribuição por classe e o
ranking top-10 de equipamentos por score médio (US04 — reaproveita
`agroguard.relatorios.servico.ranking` quando o banco está disponível). O
expander **"Leitura por perfil"** resume o que cada persona deve olhar:

- **Operador**: aba *Alertas & recomendações* — ação + critério explícito.
- **Gestor**: ranking acima + aba *Tendências* para priorizar contato.
- **Seguradora**: aba *Equipamento* — histórico completo para precificação (US07).

### Alertas & recomendações (US01 — Operador)
Lista os alertas da tabela `alertas` (populada pelo caminho da API — Sprint
3), ordenados do mais recente para o mais antigo, com equipamento,
fazenda/região, data/hora, nível, score, critério e recomendações formatadas
como `AÇÃO — critério`. **Quando a tabela `alertas` está vazia** (nenhuma
leitura chegou pela API ainda), a tela deriva os alertas ativos diretamente
de `vw_risco_completo` (`alerta = TRUE`) e deixa isso explícito na legenda:
*"derivado dos scores — nenhuma leitura chegou pela API ainda"*.

Também mostra contagem de alertas por nível e por região, e um expander
**"Critérios explícitos"** com o critério de alerta (`risco_score >= 80`) e a
tabela de regras importada de `agroguard.alertas.servico.REGRAS` — nunca
reimplementada aqui:

| ação | critério | prioridade |
|---|---|---|
| ADIAR_OPERACAO | umidade_solo > 0.7 e dist_corpo_dagua_m < 100 | alta |
| REDUZIR_VELOCIDADE | declividade_pct > 5 ou inclinacao_graus > 6 | alta |
| ATENCAO_CHUVA | precip_24h_mm > 30 ou precip_prev_6h_mm > 10 | media |
| INSPECAO_MECANICA | dias_desde_manutencao > 40 ou vibracao_g > 1.5 | media |
| PAUSA_JORNADA | jornada_acumulada_h > 10 | media |
| ROTA_ALTERNATIVA | tipo_operacao == 'transporte' e precip_24h_mm > 10 | media |
| MONITORAR (fallback) | risco_score >= 60 sem nenhum outro critério específico | baixa |

### Tendências (US04/US05 — Gestor e Seguradora)
Seletor **"Agrupar por"** (equipamento · região · tipo de operação) e
**"Janela"** (dia · semana), que chamam
`agroguard.relatorios.servico.tendencias` (as mesmas queries Q7–Q9 de
`sql/queries.sql`) quando o banco está disponível, ou agrupam o CSV em
pandas com a mesma lógica quando não está. Mostra:

- `st.line_chart` do score médio ao longo do tempo, uma linha por grupo
  (limitado aos 8 grupos com maior score médio, para manter legível).
- `st.bar_chart` do total de alertas por grupo no período.
- Tabela completa dos grupos exibidos.
- Um "insight" de uma linha: o grupo com maior score no período mais recente
  e o delta em relação ao período anterior.

### Equipamento (US07 — Seguradora/Sompo)
Seleciona um `equip_id` e mostra: cartão com score/classe/alerta/fazenda-
região da última leitura, gráfico (matplotlib) do score ao longo do tempo com
marcadores `X` vermelhos nas leituras com sinistro registrado e uma linha
tracejada no limiar de alerta, e uma tabela das últimas 20 leituras com
`fatores_principais` formatados como `fator (+x pts)` e as recomendações do
score (`AÇÃO — critério`).

### Auditoria (Sprint 3 — segurança/registros de uso)
Exige o banco de dados (não tem equivalente em CSV). Mostra os totais de
`logs_uso` e `leituras_rejeitadas`, as últimas 100 requisições registradas
(`ocorrido_em`, `kid`, `papel`, `método`, `rota`, `status_http`,
`duração_ms`) com a distribuição por status HTTP, e as últimas 50 leituras
rejeitadas pela validação (`código`, `motivo`, `recebido_em`).

## Relatório semanal (US05 — `relatorios/gerar_relatorio.py`)

Gera `reports/relatorio_risco.md` + figuras em `reports/figures/` a partir da
mesma base de dados/consultas do dashboard:

```bash
python -m relatorios.gerar_relatorio --semanas 8 --saida reports/relatorio_risco.md
```

Seções do relatório: período coberto, KPIs, top-5 equipamentos por score
médio (US05), tendência semanal por região (tabela + `tendencia_regiao.png`),
tendência semanal por tipo de operação (tabela + `tendencia_operacao.png`),
tendência dos top-5 equipamentos (`tendencia_top5_equipamentos.png`), alertas
abertos com recomendações e "Recomendações da semana" (as ações mais
frequentes nos alertas/scores do período, com o critério de `REGRAS`).

## Cores por classe de risco

| Classe | Cor |
|---|---|
| Baixo | `#2e7d32` |
| Médio | `#f9a825` |
| Alto | `#ef6c00` |
| Crítico | `#c62828` |
