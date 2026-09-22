# Relatório semanal de risco — AgroGuard IA

## Período coberto

De **27/07/2026** a **21/09/2026**.

## Indicadores da semana (KPIs)

- Leituras no período: **1**
- Score médio: **99.0**
- Alertas ativos: **1**
- Taxa de sinistro: **0.00%**
- Equipamentos com leitura no período: **1**

## Top 5 equipamentos por score médio (US05)

| equip_id | tipo_equip | leituras | score_medio | score_pico | alertas_criticos | sinistros_reais |
| --- | --- | --- | --- | --- | --- | --- |
| EQ-043 | Pulverizador | 182 | 34.3 | 79 | 0 | 24 |
| EQ-006 | Colheitadeira | 211 | 34.1 | 89 | 1 | 22 |
| EQ-019 | Trator | 207 | 34.0 | 78 | 0 | 27 |
| EQ-034 | Caminhão | 190 | 33.8 | 74 | 0 | 18 |
| EQ-040 | Colheitadeira | 210 | 33.6 | 82 | 1 | 20 |


## Tendência semanal por região

| chave | periodo | leituras | score_medio | score_pico | alertas | taxa_sinistro_pct |
| --- | --- | --- | --- | --- | --- | --- |
| Sinop-MT | 2026-09-21 00:00:00 | 1 | 99.0 | 99 | 1 | 0.00 |

![Tendência por região](figures/tendencia_regiao.png)

## Tendência semanal por tipo de operação

| chave | periodo | leituras | score_medio | score_pico | alertas | taxa_sinistro_pct |
| --- | --- | --- | --- | --- | --- | --- |
| campo | 2026-09-21 00:00:00 | 1 | 99.0 | 99 | 1 | 0.00 |

![Tendência por tipo de operação](figures/tendencia_operacao.png)

## Tendência dos top 5 equipamentos

![Tendência dos top 5 equipamentos](figures/tendencia_top5_equipamentos.png)

## Alertas abertos e recomendações

| equip_id | fazenda | regiao | data_hora | nivel | risco_score | criterio | recomendacoes | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EQ-014 | FAZ-03 | Sinop-MT | 2026-09-21 23:30:00 | Critico | 99 | risco_score >= 80 | ADIAR_OPERACAO — umidade_solo > 0.7 e dist_corpo_dagua_m < 100 · REDUZIR_VELOCIDADE — declividade_pct > 5 ou inclinacao_graus > 6 · ATENCAO_CHUVA — precip_24h_mm > 30 ou precip_prev_6h_mm > 10 · INSPECAO_MECANICA — dias_desde_manutencao > 40 ou vibracao_g > 1.5 · PAUSA_JORNADA — jornada_acumulada_h > 10 | aberto |


## Recomendações da semana

- **ADIAR_OPERACAO** (2x) — umidade_solo > 0.7 e dist_corpo_dagua_m < 100
- **REDUZIR_VELOCIDADE** (2x) — declividade_pct > 5 ou inclinacao_graus > 6
- **ATENCAO_CHUVA** (2x) — precip_24h_mm > 30 ou precip_prev_6h_mm > 10
- **INSPECAO_MECANICA** (2x) — dias_desde_manutencao > 40 ou vibracao_g > 1.5
- **PAUSA_JORNADA** (2x) — jornada_acumulada_h > 10

