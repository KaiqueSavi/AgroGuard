# 🏗️ Arquitetura Técnica — AgroGuard IA

> Documento de arquitetura aprofundada da solução. Complementa a visão geral apresentada no README.

---

## 1. Visão de alto nível

O AgroGuard IA segue uma arquitetura em camadas bem definidas, com separação clara entre **coleta**, **processamento**, **inteligência** e **interface**. Essa separação permite:

- Substituir componentes individualmente (ex.: trocar broker MQTT por Kafka) sem afetar o restante.
- Escalar verticalmente cada camada conforme a demanda.
- Auditar o fluxo de dados ponta a ponta — requisito da Sompo.

```mermaid
flowchart TB
    subgraph EDGE["🌾 Edge (campo)"]
        S1[Sensor IoT no equipamento]
        S2[GPS]
        S3[Acelerômetro / Giroscópio]
    end

    subgraph CLOUD["☁️ Cloud (AWS)"]
        direction TB

        subgraph INGEST["Ingestão"]
            MQTT[Broker MQTT<br/>Mosquitto]
            APIGW[API Gateway<br/>Webhooks externos]
        end

        subgraph PROC["Processamento"]
            ETL[Pipeline ETL<br/>Airflow + Python]
            ENRICH[Enriquecimento<br/>Clima · Solo · Histórico]
        end

        subgraph STORE["Armazenamento"]
            PG[(PostgreSQL +<br/>PostGIS)]
            S3[(S3<br/>Raw + Modelos)]
            REDIS[(Redis<br/>Cache de score)]
        end

        subgraph ML["Inteligência"]
            SCORE[Score Model<br/>XGBoost]
            CLASS[Classifier<br/>Random Forest]
            REC[Rec Engine<br/>Rules + ML]
        end

        subgraph SERVE["Servir"]
            API[FastAPI]
            FCM[Firebase Cloud<br/>Messaging]
        end
    end

    subgraph CLIENT["👥 Clientes"]
        APP[App Mobile<br/>Operador]
        WEB[Dashboard Web<br/>Gestor]
        SOMPO_API[Integração Sompo]
    end

    S1 & S2 & S3 --> MQTT
    MQTT --> ETL
    APIGW --> ETL
    ETL --> ENRICH
    ENRICH --> PG
    ENRICH --> S3
    PG --> SCORE & CLASS
    SCORE & CLASS --> REC
    REC --> REDIS
    REC --> API
    API --> FCM
    FCM --> APP
    API --> WEB
    API --> SOMPO_API
```

---

## 2. Decisões de arquitetura (ADRs resumidos)

### ADR-001: Por que MQTT em vez de HTTP para coleta IoT?
- **Decisão:** MQTT (Mosquitto)
- **Motivos:** baixo overhead, suporta conexões instáveis (comum em zona rural), QoS configurável, padrão de mercado IoT.
- **Trade-off:** exige broker; mais complexo de operar que REST.

### ADR-002: Por que PostgreSQL com PostGIS?
- **Decisão:** PostgreSQL + extensão PostGIS
- **Motivos:** consultas geoespaciais nativas (distância a corpos d'água, polígonos de fazendas), open source, maduro.
- **Trade-off:** menos performático que data warehouses para analytics massiva — para Sprint 4+ podemos adicionar BigQuery/Athena.

### ADR-003: Por que XGBoost + Random Forest e não Deep Learning?
- **Decisão:** modelos baseados em árvores
- **Motivos:** dados tabulares, alta interpretabilidade (importante para a seguradora), bom desempenho mesmo com dataset pequeno, treinamento rápido.
- **Trade-off:** pode perder ganho marginal vs. modelos mais complexos. Aceitável no estágio atual.

### ADR-004: Por que FastAPI?
- **Decisão:** FastAPI
- **Motivos:** validação automática via Pydantic, docs OpenAPI gerados, async nativo, performance comparável a Node.js.
- **Trade-off:** ecossistema Python — ok pois mantém stack unificada com modelos.

### ADR-005: Mobile nativo ou React Native?
- **Decisão:** React Native (com possibilidade de evoluir pra Flutter na Sprint 3+)
- **Motivos:** time enxuto, code sharing com web, push via Firebase OOB.
- **Trade-off:** menor performance em apps que exigem hardware intensivo — não é nosso caso.

---

## 3. Fluxo detalhado: do sensor ao alerta

```mermaid
sequenceDiagram
    participant IoT as Sensor IoT
    participant Broker as Broker MQTT
    participant ETL as Pipeline ETL
    participant Clima as API Clima
    participant DB as PostgreSQL
    participant Model as Modelo XGBoost
    participant API as FastAPI
    participant FCM as Firebase
    participant App as App Operador

    IoT->>Broker: MQTT publish (lat, lon, vel, vibr) [10s]
    Broker->>ETL: Consume mensagem
    ETL->>Clima: GET /weather?lat=...&lon=...
    Clima-->>ETL: precip_24h, vento, prev_6h
    ETL->>DB: Enrich + INSERT em telemetria
    ETL->>Model: Predict(features)
    Model-->>ETL: score=94, classe=Critico
    ETL->>DB: UPDATE com score
    alt score >= 80
        ETL->>API: POST /alerta
        API->>FCM: Send push
        FCM->>App: Notificação push
        App-->>App: Exibe alerta + recomendação
    end
```

---

## 4. Componentes — detalhamento técnico

### 4.1 Camada de coleta (Edge)

**Hardware previsto (cenário ideal):**
- Microcontrolador ESP32 ou similar
- Módulo GPS (NEO-6M)
- Acelerômetro/giroscópio (MPU-6050)
- Conectividade: 4G/LoRaWAN

**Frequência de envio:**
- Posição GPS: a cada 10 s
- Vibração/inclinação: a cada 5 s (média móvel)
- Heartbeat: a cada 60 s

**Para protótipo (Sprint 3):** simulador em Python que replica o comportamento usando o `synthetic_dataset.csv`.

### 4.2 Camada de ingestão

- **Broker:** Mosquitto rodando em container Docker
- **Tópicos MQTT:**
  - `agroguard/{equip_id}/telemetry`
  - `agroguard/{equip_id}/heartbeat`
  - `agroguard/{equip_id}/event`
- **Autenticação:** mTLS por equipamento + tokens HMAC nas mensagens
- **API Gateway:** AWS API Gateway para webhooks externos (Sompo, parceiros)

### 4.3 Pipeline ETL

- **Orquestração:** Apache Airflow (DAGs por hora)
- **Transformações principais:**
  1. Validação de schema (Pydantic)
  2. Enriquecimento com clima (cache de 30 min)
  3. Enriquecimento com solo/topografia (cache permanente por região)
  4. Cálculo de features derivadas (jornada acumulada, dias desde manutenção)
  5. Inferência de modelo (latência alvo < 200 ms)
  6. Persistência

### 4.4 Armazenamento

| Dado | Tecnologia | Retenção |
|---|---|---|
| Telemetria bruta | S3 (Parquet) | 5 anos |
| Telemetria enriquecida | PostgreSQL | 12 meses |
| Score histórico | PostgreSQL | 5 anos |
| Modelos versionados | S3 + MLflow | indefinido |
| Cache de predições | Redis | 5 min |
| Logs de auditoria | CloudWatch | 12 meses |

### 4.5 Camada de IA

**Pipeline de treino:**
1. Dataset (synthetic na Sprint 2, real na Sprint 4+)
2. Split estratificado (70/15/15)
3. Treinamento XGBoost + Random Forest
4. Avaliação (AUC, F1 macro, confusion matrix)
5. Versionamento via MLflow
6. Deploy via API com health-check

**Pipeline de inferência:**
- Latência alvo: P99 < 250 ms
- Throughput esperado: 100 req/s na Sprint 4 (pico em horário de operação)
- Estratégia de retreino: semanal, com gate manual para promover ao prod

### 4.6 Servir e notificar

- **API:** FastAPI com OpenAPI docs públicas
- **Auth:** JWT (operador/gestor) + API Key (Sompo)
- **Rate limit:** 1.000 req/min por cliente
- **Push:** Firebase Cloud Messaging (Android primeiro, iOS na Sprint 4)

### 4.7 Frontend

**App mobile (operador):**
- React Native + Expo
- Telas: Home (status), Mapa, Histórico, Registro de ocorrência
- Funciona offline (fila local de eventos sincronizada quando volta sinal)

**Dashboard web (gestor):**
- React + Vite + TypeScript
- Mapbox para visualização geoespacial
- Recharts para KPIs
- Export PDF de relatórios via API server-side

---

## 5. Infraestrutura

### 5.1 Ambiente alvo

```mermaid
flowchart LR
    subgraph PROD[AWS - Produção]
        EC2[EC2 Auto Scaling<br/>API + ETL]
        RDS[(RDS PostgreSQL<br/>Multi-AZ)]
        ELC[(ElastiCache<br/>Redis)]
        S3B[(S3 Buckets)]
        CW[CloudWatch]
    end
    subgraph DEV[Local - Dev]
        DC[Docker Compose<br/>Postgres + Redis<br/>+ FastAPI]
    end
```

### 5.2 CI/CD

- **Repo:** GitHub privado
- **Pipeline:** GitHub Actions
- **Etapas:** lint → testes → build container → deploy em staging → smoke tests → promote para prod (manual)
- **Versionamento de modelos:** MLflow + tags semânticas

### 5.3 Observabilidade

- **Logs:** CloudWatch (estruturados em JSON)
- **Métricas:** Prometheus + Grafana
- **Trace distribuído:** OpenTelemetry
- **Alertas operacionais:** PagerDuty/Slack para SREs

---

## 6. Segurança em profundidade

| Camada | Controle |
|---|---|
| Edge | mTLS, HMAC, certificado por dispositivo |
| Rede | VPC privada, security groups restritivos, WAF na API |
| App | OWASP Top 10 mitigado, dependências escaneadas (Snyk) |
| Dados | Criptografia AES-256 em repouso, TLS 1.3 em trânsito |
| Identidade | JWT curto + refresh, MFA para gestores e Sompo |
| Auditoria | Trilha imutável (CloudTrail + S3 Object Lock) |
| LGPD | DPIA realizado, consentimento granular, anonimização em datasets de treino |

---

## 7. Limitações conhecidas e mitigações

| Limitação | Mitigação planejada |
|---|---|
| Conectividade rural intermitente | Buffer local no edge + sync diferido |
| Dados climáticos com baixa granularidade | Combinar múltiplas fontes (INMET + estação local quando disponível) |
| Cold start para equipamentos novos | Score baseado em "perfil semelhante" enquanto não há histórico |
| Drift do modelo | Monitoramento contínuo + retreino agendado |
| Resistência cultural ao app | Onboarding com cooperativa + treinamento prático |

---

## 8. Roadmap de evolução da arquitetura

| Sprint | Evolução |
|---|---|
| 1 | Arquitetura proposta (este doc) |
| 2 | PoC local com Docker Compose, modelo treinado em dataset simulado |
| 3 | API real + simulador IoT + integração com clima real |
| 4 | Deploy em staging na AWS, dashboard funcional, demo end-to-end |
| Pós-Challenge | Edge real, retreino automático, integração com core Sompo |
