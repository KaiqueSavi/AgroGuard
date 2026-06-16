# 📊 Relatório de Validação Estatística — AgroGuard IA

> **Projeto:** AgroGuard IA — Inteligência preditiva de riscos em equipamentos agrícolas
> **Contexto:** Challenge Sompo Seguros × FIAP — entrega da **Sprint 2** (de 4)
> **Versão dos modelos:** `v0.2` · **Seed:** `42` (reprodutível) · **Fonte das métricas:** `reports/metrics.json`

Este relatório documenta a validação estatística dos modelos de Machine Learning do AgroGuard IA. Todos os números reportados aqui foram extraídos diretamente do pipeline de treino/avaliação (`ml/train.py`) e das consultas de validação de negócio no PostgreSQL (`ml/run_queries.py`, `sql/queries.sql`).

---

## 1. Resumo dos resultados

O AgroGuard IA combina **três modelos** complementares, todos baseados em `scikit-learn` (sem `xgboost`):

| Modelo | Tipo | Algoritmo escolhido | Métrica principal (teste) |
|---|---|---|---|
| **Classificador de classe** (principal) | Classificação multiclasse | GradientBoosting | F1-macro = **0,6632** · accuracy = **0,8547** |
| **Regressor de score** (0–100) | Regressão | GradientBoostingRegressor | R² = **0,9361** · RMSE = **3,39** · MAE = **2,66** |
| **Classificador de sinistro** (complementar) | Classificação binária 0/1 | RandomForest *balanced* | AUC = **0,7489** · F1 = **0,3099** · recall = **0,2308** |

**Leitura executiva:**

- O **regressor de score** é o motor de alertas do produto: com **R² = 0,9361** e **RMSE de apenas 3,4 pontos** (em escala 0–100), ele estima o risco com precisão e sustenta o limiar de alerta (`score >= 80`) usado na **US01** (operador recebe alertas).
- O **classificador de classe** organiza os equipamentos em faixas (Baixo / Medio / Alto / Critico) para o mapa e o ranking de risco do gestor (**US04**), com **accuracy de 85,47%**.
- A **validação de negócio** confirma que a taxa de sinistro **real** cresce monotonicamente conforme a classe prevista (de **4,82%** em Baixo para **61,54%** em Critico), evidência de que o modelo de fato separa risco — fundamento para a consulta de score histórico da Sompo (**US07**).

---

## 2. Dataset e split

- **Arquivo:** `data/synthetic_dataset.csv`, gerado por `data/generate_dataset.py --seed 42`.
- **Dimensão:** **10.000 linhas × 26 colunas**.
- **Taxa de sinistro global:** **10,57%**.

### Split estratificado (70/15/15 por `classe_risco`)

| Partição | Linhas |
|---|---:|
| Treino | 7.000 |
| Validação | 1.500 |
| Teste | 1.500 |
| **Total** | **10.000** |

### Distribuição de `classe_risco` (dataset completo)

| Classe | Contagem | Proporção |
|---|---:|---:|
| Baixo | 5.517 | 55,17% |
| Medio | 3.907 | 39,07% |
| Alto | 533 | 5,33% |
| Critico | 43 | 0,43% |
| **Total** | **10.000** | **100%** |

> ⚠️ A classe **Critico** é extremamente rara (**43 em 10.000**), o que impõe um limite estatístico ao recall dessa classe específica (ver §3 e §9).

### Engenharia de features e anti-vazamento (data leakage)

- **Features `X`:** **13 numéricas + 3 categóricas** (`tipo_equip`, `tipo_operacao`, `turno`).
- **Pré-processamento:** `ColumnTransformer` — *OneHot* nas categóricas, numéricas em *passthrough*.
- **Alvos e derivados excluídos de `X`:** `risco_score`, `classe_risco`, `sinistro`, `tipo_sinistro`, `severidade_sinistro`.
- **`latitude`/`longitude` ficam FORA do modelo** (mantidas apenas para o mapa da **US04**), evitando que o modelo "memorize" coordenadas.

---

## 3. Classificador de classe (principal)

Modelo de produção: **GradientBoosting**. A seguir, a avaliação no conjunto de **teste** (1.500 leituras).

### 3.1 Matriz de confusão (teste)

Linhas = classe **REAL**, colunas = classe **PREVISTA** (ordem: Baixo, Medio, Alto, Critico).

| REAL \ PREVISTO | Baixo | Medio | Alto | Critico |
|---|---:|---:|---:|---:|
| **Baixo** | 753 | 75 | 0 | 0 |
| **Medio** | 100 | 468 | 18 | 0 |
| **Alto** | 0 | 17 | 60 | 3 |
| **Critico** | 0 | 1 | 4 | 1 |

![Matriz de confusão](./figures/confusion_matrix.png)

**Leitura:** os erros se concentram em classes **adjacentes** (Baixo↔Medio, Medio↔Alto), o que é desejável num problema ordinal de risco — não há nenhuma confusão entre os extremos (Baixo↔Critico = 0 em ambos os sentidos). A classe Critico, com apenas 6 amostras reais no teste, acerta 1 e dispersa as demais para Medio/Alto.

### 3.2 Métricas por classe (teste)

| Classe | Precision | Recall | F1 | Suporte |
|---|---:|---:|---:|---:|
| Baixo | 0,88 | 0,91 | 0,90 | 828 |
| Medio | 0,83 | 0,80 | 0,82 | 586 |
| Alto | 0,73 | 0,75 | 0,74 | 80 |
| Critico | 0,25 | 0,17 | 0,20 | 6 |

### 3.3 Métricas agregadas (teste)

| Métrica | Valor |
|---|---:|
| Accuracy | 0,8547 |
| F1-macro | 0,6632 |
| CV (5-fold) F1-macro | 0,5813 ± 0,0081 |

> A validação cruzada (5-fold) com F1-macro = **0,5813 ± 0,0081** apresenta desvio-padrão baixo, indicando **estabilidade** do modelo entre folds. O F1-macro é "puxado para baixo" pela classe Critico (F1 = 0,20), por construção (média não ponderada entre classes).

### 3.4 Comparação RandomForest vs GradientBoosting (validação) e justificativa

| Modelo | F1-macro (val.) | Accuracy (val.) |
|---|---:|---:|
| RandomForest | 0,6258 | 0,8687 |
| **GradientBoosting (escolhido)** | **0,6765** | **0,8707** |

**Justificativa da escolha:** o **GradientBoosting** vence em **ambas** as métricas de validação — F1-macro **+0,0507** (0,6765 vs 0,6258) e accuracy ligeiramente superior (0,8707 vs 0,8687). Como o F1-macro é a métrica mais sensível ao desempenho nas classes minoritárias (Alto/Critico), que são justamente as de maior interesse de negócio para a Sompo, optou-se pelo GradientBoosting como classificador de classe de produção.

---

## 4. Regressor de score (0–100)

Modelo: **GradientBoostingRegressor**. Avaliação no conjunto de **teste**.

| Métrica | Valor |
|---|---:|
| RMSE | 3,39 |
| MAE | 2,66 |
| R² | 0,9361 |

![Predito vs Real — Regressor de score](./figures/regression_pred_vs_real.png)

**Leitura:** o R² de **0,9361** indica que o modelo explica ~93,6% da variância do `risco_score`. Com **RMSE de 3,39** e **MAE de 2,66** numa escala de 0 a 100, o erro típico de predição é da ordem de **~3 pontos** — margem confortável para sustentar o **limiar de alerta = 80**. É por isso que, na arquitetura do produto, **o alerta da US01 é disparado pelo SCORE (regressor)** e não pela classe rara: o regressor é o componente mais robusto e preciso do conjunto.

---

## 5. Classificador de sinistro (complementar)

Modelo: **RandomForest** com `class_weight='balanced'`. Prediz a **ocorrência de sinistro (0/1)**. Avaliação no conjunto de **teste**.

| Métrica | Valor |
|---|---:|
| AUC | 0,7489 |
| F1 | 0,3099 |
| Recall | 0,2308 |

![Curva ROC — sinistro](./figures/roc_sinistro.png)

**Leitura:** diferentemente do `risco_score`/`classe_risco` (que são funções determinísticas no gerador sintético), o alvo **sinistro é ESTOCÁSTICO** — representa um problema de ML mais próximo do "mundo real". Por isso, a **AUC de 0,7489** é o número mais "honesto" do conjunto: indica capacidade discriminativa moderada (bem acima do acaso = 0,50), porém com recall baixo (0,2308) por se tratar de evento raro e ruidoso. Este modelo é **complementar** ao motor principal de score e será o foco de melhoria com dados reais na Sprint 4.

---

## 6. Correlação das variáveis (Pearson)

### 6.1 Correlação das features com `risco_score` (ordenado)

| Feature | Pearson vs `risco_score` |
|---|---:|
| umidade_solo | +0,837 |
| precip_24h_mm | +0,828 |
| precip_prev_6h_mm | +0,703 |
| jornada_acumulada_h | +0,200 |
| dias_desde_manutencao | +0,169 |
| declividade_pct | +0,121 |
| vento_max_kmh | +0,070 |
| vibracao_g | +0,059 |
| idade_equipamento_anos | +0,013 |
| inclinacao_graus | −0,003 |
| velocidade_kmh | −0,015 |
| experiencia_operador_anos | −0,064 |
| dist_corpo_dagua_m | −0,178 |

### 6.2 Correlação das features com ocorrência de sinistro (0/1)

| Feature | Pearson vs sinistro |
|---|---:|
| umidade_solo | 0,291 |
| precip_24h_mm | 0,289 |
| precip_prev_6h_mm | 0,242 |

![Mapa de calor de correlações](./figures/correlation_heatmap.png)

**Interpretação:** as variáveis **hidrometeorológicas dominam** o risco. `umidade_solo` (+0,837) e `precip_24h_mm` (+0,828) têm correlação fortíssima com o `risco_score`, seguidas de `precip_prev_6h_mm` (+0,703). O mesmo trio lidera a correlação com a ocorrência de sinistro (0,291, 0,289 e 0,242). Já a `dist_corpo_dagua_m` apresenta correlação **negativa** com o score (−0,178): quanto mais longe da água, **menor** o risco — coerente com a intuição operacional e confirmado na §8 (Q4).

---

## 7. Importância de features (classificador GradientBoosting)

| Feature | Importância |
|---|---:|
| precip_24h_mm | 0,449 |
| jornada_acumulada_h | 0,158 |
| dist_corpo_dagua_m | 0,076 |
| turno_noite | 0,068 |
| dias_desde_manutencao | 0,066 |
| umidade_solo | 0,050 |
| declividade_pct | 0,041 |
| precip_prev_6h_mm | 0,035 |

![Importância de features](./figures/feature_importance.png)

**Leitura:** a **precipitação nas últimas 24h** (`precip_24h_mm`, importância **0,449**) é, isoladamente, o fator mais determinante para a classificação de risco — quase metade do "poder de decisão" do modelo. Em seguida vêm fatores **operacionais e de manutenção**: `jornada_acumulada_h` (0,158), `dist_corpo_dagua_m` (0,076), `turno_noite` (0,068) e `dias_desde_manutencao` (0,066). Note que a importância do modelo árvore não coincide perfeitamente com a correlação linear de Pearson (§6): a `umidade_solo`, embora tenha a maior correlação linear, divide seu sinal preditivo com `precip_24h_mm` (variáveis colineares), aparecendo com importância menor (0,050) no modelo.

---

## 8. Validação de negócio

Estas consultas rodam **diretamente no PostgreSQL 16** (serviço `db` do `docker-compose`), sobre a `vw_risco_completo`, validando se as predições persistidas têm aderência ao comportamento real de sinistros.

### 8.1 Q3 — Taxa de sinistro REAL por classe PREVISTA

> 🎯 **Teste-chave de validade do modelo:** se as predições têm valor, a taxa de sinistro **real** deve **crescer monotonicamente** conforme a classe prevista sobe de Baixo para Critico.

| Classe prevista | Leituras | Score médio | Taxa de sinistro real |
|---|---:|---:|---:|
| Baixo | 5.729 | 24,4 | 4,82% |
| Medio | 3.722 | 39,8 | 14,59% |
| Alto | 510 | 67,2 | 41,96% |
| Critico | 39 | 80,0 | 61,54% |

✅ **Monotonicidade confirmada:** a taxa de sinistro real cresce **estritamente** a cada faixa — **4,82% → 14,59% → 41,96% → 61,54%**. Um equipamento classificado como **Critico** tem ~**12,8×** mais chance de sinistro do que um classificado como **Baixo**. Isso demonstra, em linguagem de negócio, que o ranking de risco da **US04** e o score histórico da **US07** são acionáveis e bem calibrados.

### 8.2 Q4 — Risco por faixa de distância a corpo d'água

| Faixa de distância | Score médio | Taxa de sinistro |
|---|---:|---:|
| 0–50 m | 35,5 | 12,20% |
| 50–200 m | 34,7 | 11,61% |
| 200–500 m | 32,6 | 10,78% |
| > 500 m | 28,3 | 8,27% |

![Risco por distância a corpo d'água](./figures/eda_score_by_distagua.png)

**Leitura:** confirma o sinal negativo da correlação da §6 — quanto **mais próximo** de corpos d'água, **maior** o score médio e a taxa de sinistro (12,20% a 0–50 m vs 8,27% acima de 500 m). A `dist_corpo_dagua_m` é, portanto, uma variável crítica acionável para recomendações operacionais (ex.: cautela redobrada em talhões ribeirinhos).

### 8.3 Distribuição dos scores persistidos e alertas

| Classe prevista | Leituras |
|---|---:|
| Baixo | 5.729 |
| Medio | 3.722 |
| Alto | 510 |
| Critico | 39 |

- **Limiar de alerta:** `score >= 80`.
- **Alertas gerados:** **26** leituras.

![Distribuição dos scores](./figures/score_distribution.png)

![Taxa de sinistro](./figures/eda_sinistro_rate.png)

---

## 9. Limitações honestas

Em coerência com o rigor acadêmico do Challenge, registramos as limitações sem inflar resultados:

1. **Classe "Critico" é rara** — apenas **43 em 10.000** no dataset (6 no teste), resultando em **recall baixo (0,17)** para essa classe.
   - **Mitigação:** o **ALERTA da US01 é disparado pelo SCORE** (regressor com **R² = 0,94** e **RMSE = 3,4**), e não pela classe rara, contornando a fragilidade do recall de Critico. Estão previstos ainda *threshold tuning* e a incorporação de **mais dados reais na Sprint 4**.

2. **`risco_score` e `classe_risco` são funções determinísticas** do gerador sintético — os modelos aprendem essa **função latente** a partir das features brutas. É **válido academicamente**, mas deve ser documentado como limitação: parte do alto R²/accuracy reflete a recuperação de uma regra conhecida. Em contraste, o alvo **`sinistro` é ESTOCÁSTICO** (AUC = 0,75) e representa um problema de ML mais **realista**.

3. **Dados 100% sintéticos.** A **validação cruzada com dados reais** está prevista para a **Sprint 4**, quando o pipeline será confrontado com telemetria de campo.

---

### 📎 Referências do repositório

- Métricas brutas: `reports/metrics.json` (`modelo_versao = v0.2`, `seed = 42`)
- Pipeline de treino/avaliação: `ml/train.py`
- Consultas de validação (Q1..Q6): `sql/queries.sql` · execução: `ml/run_queries.py`
- Esquema do banco (DDL): `sql/schema.sql`
- Figuras: `reports/figures/`
