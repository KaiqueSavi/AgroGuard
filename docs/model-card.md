# 🧠 Model Card — AgroGuard IA

> Documento padronizado descrevendo os modelos preditivos do AgroGuard IA, suas características, limitações e considerações éticas.
> Baseado no template ["Model Cards for Model Reporting" (Mitchell et al., 2019)](https://arxiv.org/abs/1810.03993).

---

## 1. Detalhes do Modelo

| Campo | Valor |
|---|---|
| **Nome do sistema** | AgroGuard IA |
| **Versão** | 0.2 (Sprint 2 — primeira implementação treinada) |
| **Data** | 2026-06 |
| **Tipo** | Modelo combinado (regressão + classificação + classificação complementar) |
| **Algoritmos implementados** | GradientBoosting (classificação de classe — principal), GradientBoostingRegressor (score 0–100), RandomForest balanced (classificação de sinistro — complementar) |
| **Framework** | scikit-learn |
| **Reprodutibilidade** | `seed=42`, split estratificado 70/15/15 por `classe_risco`, `ColumnTransformer` (OneHot nas categóricas, numéricas passthrough) |
| **Mantenedores** | Equipe AgroGuard — FIAP × Sompo Challenge |
| **Licença** | Acadêmico / a definir com Sompo |

> ℹ️ Nota de evolução: na Sprint 1 (v0.1) os algoritmos propostos incluíam **XGBoost**. Na implementação da Sprint 2 optou-se por **GradientBoosting do scikit-learn** (sem dependência de XGBoost), simplificando o stack e mantendo desempenho competitivo na validação.

---

## 2. Uso pretendido

### 2.1 Casos de uso primários

- Estimar **score de risco operacional** (0–100) de um equipamento agrícola em tempo quase real.
- Classificar a operação corrente em **Baixo / Médio / Alto / Crítico**.
- Gerar **recomendações de ação preventiva** (adiar, mudar rota, reduzir velocidade, inspecionar).

### 2.2 Usuários previstos

- **Operadores agrícolas** — recebem alertas e recomendações no app mobile.
- **Gestores de frota** — monitoram a frota via dashboard.
- **Analistas da Sompo** — usam histórico de risco para precificação e análise de sinistros.

### 2.3 Casos de uso fora de escopo

- ❌ Substituir o operador em decisões críticas de campo.
- ❌ Aprovar ou negar sinistros automaticamente.
- ❌ Substituir inspeções mecânicas regulares.
- ❌ Diagnosticar falhas mecânicas específicas (apenas indica risco aumentado).

---

## 3. Fatores

### 3.1 Grupos relevantes

- **Por tipo de equipamento:** colheitadeira, trator, pulverizador, caminhão.
- **Por região:** Centro-Oeste (Sprint 1–4); expansão para outras regiões em fase posterior.
- **Por porte de operação:** pequeno produtor, cooperativa média, grande fazenda.

### 3.2 Condições de instrumentação

- Dependência de telemetria IoT funcional. Em equipamentos sem sensor, fallback para perfil-base + clima.

---

## 4. Métricas

> 📊 **Resultados v0.2 (Sprint 2)** — fonte: `reports/metrics.json` (`modelo_versao=v0.2`, `seed=42`). Avaliação no **conjunto de teste** (1.500 registros). As colunas **Alvo (v0.1)** preservam as metas hipotéticas originais para fins de comparação.

### 4.1 Modelo de score (regressão) — `GradientBoostingRegressor`

| Métrica | Alvo (v0.1) | **Resultado v0.2 (teste)** | Status |
|---|---|---|---|
| **RMSE** | < 8 pontos | **3,39** | ✅ |
| **MAE** | < 6 pontos | **2,66** | ✅ |
| **R²** | > 0.75 | **0,9361** | ✅ |

### 4.2 Modelo de classificação de classe (principal) — `GradientBoosting`

**Comparação na validação (escolha do modelo):** RandomForest F1-macro=0,6258 / acc=0,8687 vs. **GradientBoosting F1-macro=0,6765 / acc=0,8707** → GradientBoosting escolhido.

| Métrica | Alvo (v0.1) | **Resultado v0.2 (teste)** | Status |
|---|---|---|---|
| **Accuracy** | — | **0,8547** | — |
| **F1 macro** | > 0.75 | **0,6632** | ⚠️ abaixo do alvo (puxado pela classe rara "Crítico") |
| **AUC-ROC (sep. global)** | > 0.88 | ver §4.3 (sinistro) | — |
| **CV 5-fold (F1-macro)** | — | **0,5813 ± 0,0081** | — |

**Recall (e demais métricas) por classe — teste:**

| Classe | Precision | Recall | F1 | Suporte |
|---|---|---|---|---|
| Baixo | 0,88 | **0,91** | 0,90 | 828 |
| Médio | 0,83 | **0,80** | 0,82 | 586 |
| Alto | 0,73 | **0,75** | 0,74 | 80 |
| Crítico | 0,25 | **0,17** | 0,20 | 6 |

> ⚠️ O alvo original "Recall em Crítico > 0,85" **não foi atingido** (recall=0,17) — ver limitação detalhada e mitigação na §8.1.

**Matriz de confusão (linhas = real, colunas = previsto):**

| Real ↓ / Previsto → | Baixo | Médio | Alto | Crítico |
|---|---|---|---|---|
| **Baixo** | 753 | 75 | 0 | 0 |
| **Médio** | 100 | 468 | 18 | 0 |
| **Alto** | 0 | 17 | 60 | 3 |
| **Crítico** | 0 | 1 | 4 | 1 |

### 4.3 Modelo de classificação de sinistro (complementar) — `RandomForest balanced`

Alvo binário **estocástico** (ocorrência de sinistro 0/1), representando um problema de ML mais realista que a classe determinística.

| Métrica | **Resultado v0.2 (teste)** |
|---|---|
| **AUC-ROC** | **0,7489** |
| **F1** | **0,3099** |
| **Recall** | **0,2308** |

### 4.4 Recomendação

- **Aceitação pelo operador** (acompanhada via feedback no app) — alvo: > 60%.
- **Sinistros evitados** (estimativa contrafactual) — KPI de negócio.

### 4.5 Metodologia de avaliação

- Split estratificado 70/15/15 por `classe_risco` (treino=7000 / validação=1500 / teste=1500), `seed=42`
- Validação cruzada em 5 folds estratificados (classificador de classe: F1-macro=0,5813 ± 0,0081)
- Pré-processamento via `ColumnTransformer` (OneHot nas 3 categóricas, 13 numéricas passthrough)
- **Anti-vazamento (data leakage):** alvos e derivados (`risco_score`, `classe_risco`, `sinistro`, `tipo_sinistro`, `severidade_sinistro`) **não** entram em X; `latitude`/`longitude` ficam **fora** do modelo (mantidos só para o mapa)
- Validação de negócio via consultas SQL no banco (taxa de sinistro real por classe prevista — ver §4.6)
- Análise de fairness por região e operador (ver seção 8)

### 4.6 Validação de negócio (taxa de sinistro real por classe prevista)

A taxa de sinistro real **cresce monotonicamente** conforme a classe prevista, evidência de que o modelo separa risco de forma útil:

| Classe prevista | Leituras | Score médio | Taxa de sinistro real |
|---|---|---|---|
| Baixo | 5.729 | 24,4 | 4,82% |
| Médio | 3.722 | 39,8 | 14,59% |
| Alto | 510 | 67,2 | 41,96% |
| Crítico | 39 | 80,0 | 61,54% |

**Distância a corpo d'água (variável crítica):** risco decresce com a distância — 0–50 m: score 35,5 / 12,20%; 50–200 m: 34,7 / 11,61%; 200–500 m: 32,6 / 10,78%; >500 m: 28,3 / 8,27%.

**Alertas:** limiar = score ≥ 80 → **26 alertas** persistidos.

---

## 5. Dados de treinamento

### 5.1 Dataset Sprint 1–2 (sintético)

- **Origem:** `data/synthetic_dataset.csv` gerado por `data/generate_dataset.py --seed 42`
- **Tamanho:** 10.000 registros × 26 colunas
- **Split:** treino=7.000, validação=1.500, teste=1.500
- **Janela temporal simulada:** jan–abr 2026
- **Features do modelo (X):** 13 numéricas + 3 categóricas (`tipo_equip`, `tipo_operacao`, `turno`) — alvos e geolocalização ficam fora (ver §4.5 anti-vazamento e `data-dictionary.md`)
- **Distribuição de `classe_risco`:** Baixo=5.517, Medio=3.907, Alto=533, Critico=43
- **Taxa de sinistro global:** 10,57%

### 5.2 Limitações dos dados sintéticos

- Não capturam totalmente sazonalidade plurianual.
- Padrões regionais específicos podem ser sub-representados.
- Vieses de operador (estilo individual) não são simulados em profundidade.
- **Mitigação:** validação cruzada com dados reais (Sompo + parceiros) prevista para Sprint 4.

### 5.3 Dataset futuro (Sprint 4+)

- Dados reais fornecidos pela Sompo (anonimizados) — sob acordo de confidencialidade.
- Telemetria de equipamentos parceiros (sob consentimento).
- Bases públicas adicionais: INMET, MapBiomas, EMBRAPA Solos.

---

## 6. Dados de avaliação

- Mesma origem do treinamento (split estratificado).
- **Holdout temporal:** validação extra usando últimos 30 dias do dataset, simulando produção.
- Avaliação adicional por **slice**: tipo de equipamento, turno, condição climática.

---

## 7. Análises éticas

### 7.1 Riscos identificados

1. **Falsos negativos críticos** — não detectar um cenário de risco real pode causar acidente, lesão ou morte.
2. **Falsos positivos excessivos** — operadores deixam de confiar nos alertas (alarm fatigue).
3. **Discriminação de operadores** — uso indevido do score para penalizar pessoas específicas.
4. **Privacidade** — geolocalização e jornada de trabalho são dados sensíveis.
5. **Dependência tecnológica** — operadores deixarem de usar julgamento próprio.

### 7.2 Mitigações

- 🛡️ **Recall alto em Crítico** como métrica não negociável.
- 🛡️ **Threshold tuning** para equilibrar alertas (revisado a cada release).
- 🛡️ **Score nunca usado isoladamente para decisões trabalhistas** — política contratual com cooperativas.
- 🛡️ **LGPD compliance** — dados anonimizados em treino, consentimento explícito, finalidade declarada.
- 🛡️ **Mensagens reforçando autonomia do operador** no app ("essa é uma sugestão, decisão final é sua").

### 7.3 Considerações de fairness

- Avaliação por região e operador para identificar disparidades.
- Documentação clara dos limites do modelo na comunicação com clientes.
- Direito de contestação: usuários podem questionar predições e receber explicação (XAI via SHAP).

---

## 8. Limitações e recomendações

### 8.1 Limitações técnicas

- **Recall baixo na classe "Crítico" (0,17).** A classe é rara no dataset (43/10.000 → apenas **6 exemplos no teste**), o que torna o recall instável e abaixo do alvo original de 0,85.
  - 🛡️ **Mitigação principal:** o **ALERTA operacional é baseado no SCORE** (regressor com **R²=0,9361 / RMSE=3,39**), e não na classe rara — assim o sistema não depende de acertar a etiqueta "Crítico" para disparar o aviso (limiar score ≥ 80).
  - 🛡️ **Threshold tuning** revisado a cada release.
  - 🛡️ **Mais dados reais na Sprint 4** para reforçar a representação da classe Crítico.
- **Alvo determinístico no gerador sintético.** `risco_score` e `classe_risco` são função determinística das features no gerador; os modelos aprendem essa função latente a partir das features brutas (válido academicamente, mas explica o R² alto). Já o alvo **`sinistro` é estocástico** (AUC=0,7489) e representa um problema de ML mais "real".
- **Dados 100% sintéticos** — validação cruzada com dados reais prevista para Sprint 4.
- Dependência de qualidade de sinal IoT no campo.
- Latência de até 6 minutos em casos de cold-start de cache.
- Score perde acurácia quando faltam variáveis-chave (ex.: sem dado de chuva → score conservador).
- Cobertura inicial restrita à região Centro-Oeste — generalização exige novo treino.

### 8.2 Limitações operacionais

- Modelo precisa ser **retreinado periodicamente** (mínimo trimestral) para acompanhar drift.
- Mudanças no portfólio de equipamentos podem invalidar o modelo (modelos novos = perfis novos).
- Recomendações dependem de cadastro atualizado de rotas e fazendas.

### 8.3 Recomendações de uso responsável

- ✅ Combinar score com **bom senso humano**.
- ✅ Tratar score como **uma das entradas** de decisão, não a única.
- ✅ Comunicar **incertezas** ao usuário (intervalo de confiança quando aplicável).
- ✅ Auditar regularmente predições em casos extremos.

---

## 9. Histórico de versões

| Versão | Data | Status | Mudanças |
|---|---|---|---|
| 0.1 | 2026-04 | Concluída | Versão inicial, proposta da Sprint 1 (apenas especificação) |
| 0.2 | 2026-06 | Concluída (Sprint 2) | Primeira implementação treinada em dataset sintético. Classe: GradientBoosting (acc=0,8547 / F1-macro=0,6632). Score: GradientBoostingRegressor (RMSE=3,39 / MAE=2,66 / R²=0,9361). Sinistro: RandomForest balanced (AUC=0,7489). Troca de XGBoost → GradientBoosting (scikit-learn); pipeline anti-vazamento; validação de negócio via SQL. |
| **0.3** | **2026-09** | **✅ Concluída (Sprint 3-4)** | **Pipeline de preparação de dados** (duplicatas/faltantes/fora-de-faixa) + **ajuste final do regressor por grid em validação** (RMSE=3,20 / MAE=2,50 / R²=0,9430) + **classe derivada do score** (F1-macro=0,8171 vs. 0,6632 do classificador direto) + **explicabilidade por contrafactual** (`fatores_principais`, sem SHAP) + **CV corrigida** (5 folds em treino+val) + **análise do limiar de alerta**. Ver §11. |
| 1.0 | _futura_ | Planejada | Deploy em staging; validação com dados reais Sompo |

---

## 11. v0.3 (Sprint 3-4) — refinamento de dados, ajuste final do modelo e explicabilidade

> 📊 Todos os números desta seção vêm de `reports/metrics.json` (`modelo_versao=v0.3`, `seed=42`, split 70/15/15 idêntico ao da v0.2). Sem SHAP — explicabilidade por contrafactual (§11.5).

### 11.1 O que mudou e por quê

- **Preparação de dados** (`ml/preparacao.py`) passou a rodar ANTES do split: remove duplicatas exatas e por chave (`equip_id`,`data_hora`), imputa faltantes (mediana por `tipo_equip`, moda para categóricas), clipa fora-de-faixa e rejeita chave ausente/categoria inválida. Relatório em `reports/data_quality.json` (no dataset sintético atual, já limpo: 0 duplicatas/faltantes/clipagens/rejeições — o pipeline foi validado com casos sujos sintéticos em `tests/test_preparacao.py`).
- **Regressor de score**: busca em grade avaliada na **validação** (nunca no teste), refit em treino+val, avaliação **única** no teste — ver §11.2.
- **Classe de risco derivada do score** em vez de classificador direto: a classe "Critico" tem só 43/10.000 exemplos (6 no teste) — pouco para um classificador aprender diretamente. A v0.3 reaproveita o score (que tem 8.500 exemplos de treino contínuos) e aplica as mesmas faixas de negócio já congeladas em `ml.inferencia.classe_por_score`. O ganho é grande e honesto: F1-macro sobe de 0,6632 para 0,8171 — ver §11.3.
- **CV corrigida**: a v0.2 rodava a validação cruzada de 5 folds, por engano, **só no split de teste** (1.500 linhas — `ml/train.py:164-166` na v0.2). A v0.3 roda em treino+validação (8.500 linhas).
- **Explicabilidade** (§11.5) via contrafactual, sem dependência de SHAP.

### 11.2 Regressor de score — grid e métricas

Grade: `n_estimators∈{200,400}` × `learning_rate∈{0.05,0.1}` × `max_depth∈{2,3,4}` × `subsample∈{0.8,1.0}` (24 combinações, tabela completa em `metrics.json → regressor_score.grid_busca`). Seleção por **MAE(val)**.

**Melhor config:** `n_estimators=400, learning_rate=0.1, max_depth=2, subsample=0.8` (MAE-val=2,5669).

| Métrica (teste) | v0.2 | **v0.3** |
|---|---:|---:|
| R² | 0,9361 | **0,9430** |
| RMSE | 3,39 | **3,204** |
| MAE | 2,66 | **2,495** |
| MAE (faixa crítica, score real 70–90) | — | **3,172** |
| CV(5, treino+val) RMSE | — (CV inválida na v0.2) | **3,243 ± 0,037** |

### 11.3 Classe de risco — comparação honesta

| Métrica (teste) | classificador_direto_v02 | **regressao_faixas_v03** |
|---|---:|---:|
| Accuracy | 0,8547 | **0,8773** |
| F1-macro | 0,6632 | **0,8171** |
| Recall Critico | 0,1667 | **0,6667** |
| Precision Critico | 0,25 | **0,6667** |
| Recall Alto∪Critico (score real>60) | 0,7907 | **0,8721** |
| CV(5) F1-macro | — | **0,8222 ± 0,0407** |

Ambos os modelos são salvos (`reg_score.joblib` é o motor de produção; `clf_classe.joblib` — classificador direto — é mantido só por compatibilidade com consumidores existentes).

### 11.4 Limiar de alerta (score ≥ 80)

| | precision | recall | F1 |
|---|---:|---:|---:|
| vs. score real ≥ 80 | 0,6667 | 0,5714 | 0,6154 |
| vs. classe Crítico real | 0,6667 | 0,6667 | 0,6667 |

Sinistro real: **66,67%** acima do limiar vs. **9,30%** abaixo.

| Limiar alternativo | Precision | Recall | F1 |
|---:|---:|---:|---:|
| 70 | 0,8621 | 0,8065 | 0,8333 |
| 75 | 0,9286 | 0,8125 | 0,8667 |
| **80 (escolhido)** | 0,6667 | 0,5714 | 0,6154 |
| 85 | 0,5000 | 0,3333 | 0,4000 |

80 continua o limiar de negócio (`ALERT_THRESHOLD`) por coincidir com a borda Alto/Critico e ser conservador quanto a falso alerta — mesmo não sendo o de F1 máximo nesta amostra de teste pequena.

### 11.5 Explicabilidade (`fatores_principais`, sem SHAP)

`ml/explicabilidade.py::fatores_principais` explica cada previsão por **contrafactual**: para cada uma das 16 features, substitui o valor da leitura pela mediana (numéricas) ou moda (categóricas) do treino+val (`baseline_features.json`) e reprediz o score com o mesmo regressor — tudo em UMA chamada `predict` (17 linhas: original + 16 contrafactuais), garantindo determinismo e velocidade. `contribuicao_pts = score_original − score_com_feature_neutra`: positivo = a feature elevou o score acima do "típico"; negativo = reduziu. Os 3 fatores de maior `|contribuicao_pts|` (empate desempatado a favor do positivo) ficam em `fatores_principais`, devolvidos por `ml.inferencia.prever()`/`prever_uma()` e persistidos por `ml.predict.py` quando a coluna existir no schema do banco (checado via `information_schema.columns` em tempo de execução — o schema v1, ainda em uso em alguns ambientes, não tem essa coluna).

### 11.6 Limitações (v0.3)

- **Classe "Critico" continua rara no teste (6 linhas).** O salto de recall (0,1667→0,6667) representa só 2 acertos a mais em 6 linhas — estatisticamente instável (uma leitura a mais/menos muda o número em ~17 p.p.). O alerta de produção continua ancorado no score contínuo (R²=0,943), não na classe rara.
- **Dados 100% sintéticos** — `risco_score`/`classe_risco` continuam função determinística do gerador (`data/generate_dataset.py`); validação com dados reais da Sompo segue como trabalho futuro.
- A explicabilidade por contrafactual assume features aproximadamente independentes (não modela interações); é uma aproximação local, não uma decomposição aditiva exata como SHAP.

---

## 10. Contato

- Equipe AgroGuard: ver `README.md` seção "Equipe"
- Repositório: GitHub privado (acesso restrito a tutores e equipe)
