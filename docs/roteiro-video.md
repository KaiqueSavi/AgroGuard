# 🎬 Roteiro do vídeo — Sprint 4 (≤ 5 minutos, YouTube "não listado")

> Narração humana obrigatória. Um integrante narra; a tela mostra o terminal, o Swagger e o dashboard.
> Antes de gravar: `docker compose up -d db`, `./run_pipeline.sh`, `uvicorn agroguard.api.main:app --port 8001` e `streamlit run app/streamlit_app.py` já rodando.

| Tempo | Tela | Fala (resumo) |
|---|---|---|
| 0:00–0:30 | Capa do README (integrantes) | "AgroGuard IA: prevenção de sinistros em equipamentos agrícolas para a Sompo. Nas Sprints 1 e 2 desenhamos a solução e treinamos o modelo. Nas Sprints 3 e 4 integramos tudo em um MVP funcional." |
| 0:30–1:15 | `docs/architecture.md` (diagrama entrada → API → banco → modelo → saída) | "Os dados de telemetria, ambiente e operação entram por uma API em Python (FastAPI). A API autentica por chave e papel, valida e rejeita entradas inconsistentes, grava no PostgreSQL, chama o modelo v0.3, gera score, classe, alerta e recomendações, e registra tudo para auditoria." |
| 1:15–2:15 | Terminal: `python -m simulador.simulador_iot --n 50 --taxa-invalidos 0.1 --taxa-duplicados 0.1` | "O simulador IoT envia leituras reais do dataset com timestamps atuais, incluindo eventos inválidos e duplicados de propósito. Veja a reconciliação: enviados = aceitos + rejeitados + duplicados. Nada se perde, nada entra duas vezes." |
| 2:15–3:00 | Swagger `http://localhost:8001/docs` → `POST /telemetria` com chave de operador; depois `GET /auditoria/{request_id}` com chave admin | "Uma leitura crítica: score 9x, classe Crítico, alerta com o critério explícito `risco_score >= 80`, os três fatores que mais pesaram e as recomendações. Com o request_id, o admin rastreia log → leitura → score → alerta." |
| 3:00–3:30 | Swagger sem chave / com chave de operador em `/auditoria/logs` | "Sem chave: 401. Operador tentando auditoria: 403. Limite de requisições: 429. As chaves ficam fora do git, comparadas em tempo constante." |
| 3:30–4:20 | Dashboard Streamlit: abas Visão geral → Alertas & recomendações → Tendências (por região) → Equipamento (EQ-014) → Auditoria | "O gestor vê mapa, ranking e alertas com recomendação; a Sompo consulta o histórico do equipamento com os fatores; as tendências por região e tipo de operação mostram onde o risco cresce semana a semana." |
| 4:20–4:50 | `reports/metrics.json` / model card v0.3 + `pytest` verde | "Modelo v0.3: score por regressão ajustada e classe por faixas — recall da classe Crítico subiu de 0,17 para [valor real]. A suíte de testes de integração prova o fluxo de ponta a ponta contra o banco local." |
| 4:50–5:00 | README (checklist) | "Repositório privado com o tutor convidado, README com a evolução das quatro sprints. Obrigado." |

**Dicas:** grave em 1080p; feche abas desnecessárias; use as chaves de `.env.example`; substitua "[valor real]" pelo número de `reports/metrics.json` (`comparacao_v02_v03`).
