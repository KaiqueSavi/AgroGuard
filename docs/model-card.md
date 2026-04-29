# 🧠 Model Card — AgroGuard IA

> Documento padronizado descrevendo os modelos preditivos do AgroGuard IA, suas características, limitações e considerações éticas.
> Baseado no template ["Model Cards for Model Reporting" (Mitchell et al., 2019)](https://arxiv.org/abs/1810.03993).

---

## 1. Detalhes do Modelo

| Campo | Valor |
|---|---|
| **Nome do sistema** | AgroGuard IA |
| **Versão** | 0.1 (Sprint 1 — proposta) |
| **Data** | 2026-04 |
| **Tipo** | Modelo combinado (regressão + classificação + regras) |
| **Algoritmos propostos** | XGBoost (regressão), Random Forest (classificação), regras de negócio (recomendação) |
| **Frameworks** | scikit-learn, XGBoost, Pandas |
| **Mantenedores** | Equipe AgroGuard — FIAP × Sompo Challenge |
| **Licença** | Acadêmico / a definir com Sompo |

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

### 4.1 Modelo de score (regressão)

| Métrica | Alvo | Justificativa |
|---|---|---|
| **RMSE** | < 8 pontos | Erro absoluto baixo no score 0–100 |
| **MAE** | < 6 pontos | Robustez a outliers |
| **R²** | > 0.75 | Ajuste razoável aos padrões |

### 4.2 Modelo de classificação

| Métrica | Alvo | Justificativa |
|---|---|---|
| **F1 macro** | > 0.75 | Penaliza desempenho ruim em classes raras (Crítico) |
| **Recall em "Crítico"** | > 0.85 | Falsos negativos são caros (sinistros não evitados) |
| **AUC-ROC** | > 0.88 | Separabilidade global |
| **Precision em "Crítico"** | > 0.50 | Equilibrar com recall (não exagerar nos alertas) |

### 4.3 Recomendação

- **Aceitação pelo operador** (acompanhada via feedback no app) — alvo: > 60%.
- **Sinistros evitados** (estimativa contrafactual) — KPI de negócio.

### 4.4 Metodologia de avaliação

- Split estratificado 70/15/15 (treino/val/teste)
- Validação cruzada em 5 folds estratificados
- Avaliação separada por tipo de equipamento
- Análise de fairness por região e operador (ver seção 8)

---

## 5. Dados de treinamento

### 5.1 Dataset Sprint 1–2 (sintético)

- **Origem:** `data/synthetic_dataset.csv` gerado por `data/generate_dataset.py`
- **Tamanho:** 10.000 registros
- **Janela temporal simulada:** jan–abr 2026
- **Variáveis:** 21 features + 5 targets (ver `data-dictionary.md`)
- **Distribuição de classes:** ~55% Baixo, ~39% Médio, ~5% Alto, ~0.4% Crítico
- **Taxa de sinistros:** ~10–11%

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

| Versão | Data | Mudanças |
|---|---|---|
| 0.1 | 2026-04 | Versão inicial, proposta da Sprint 1 (apenas especificação) |
| 0.2 | _Sprint 2_ | Primeira implementação treinada em dataset sintético |
| 0.3 | _Sprint 3_ | Integração com features de clima real |
| 1.0 | _Sprint 4_ | Modelo final do Challenge, deploy em staging |

---

## 10. Contato

- Equipe AgroGuard: ver `README.md` seção "Equipe"
- Repositório: GitHub privado (acesso restrito a tutores e equipe)
