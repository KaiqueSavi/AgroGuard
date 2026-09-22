# AgroGuard IA — Segurança da API (Sprint 3/4)

Registro do que a API implementa em matéria de autenticação, autorização e rastreabilidade, e do
que fica deliberadamente fora do MVP.

## O que está implementado

- **Chaves por papel** (`X-API-Key`): cada chave é um segredo opaco associado a um `kid` e a um
  papel (`dispositivo | operador | gestor | seguradora | admin`), configurados em
  `AGROGUARD_API_KEYS="kid:papel:segredo,..."`. Nenhum segredo em claro é guardado em memória além
  do necessário para validar a requisição — o que fica em `Settings.chaves` é `sha256(segredo)`.
- **Comparação em tempo constante**: a chave recebida é hasheada e comparada contra os segredos
  configurados com `hmac.compare_digest`, para não vazar informação por tempo de resposta.
- **Autorização por papel**: cada rota declara os papéis aceitos via `exigir_papel(*papeis)`; um
  papel autenticado mas fora da lista recebe `403 nao_autorizado`, nunca um "quase acesso".
- **Rate limit por chave** (`RATE_LIMIT_POR_MIN`): token bucket em memória por `kid` — protege a
  API de uma chave comprometida ou de um cliente com bug em loop. Devolve `429 limite_excedido`.
- **Assinatura de integridade opcional** (`X-Signature`): quando presente, deve ser o HMAC-SHA256
  hexadecimal do corpo cru da requisição, usando o próprio segredo da chave. Para o papel
  `dispositivo`, a assinatura passa a ser **obrigatória** quando `AGROGUARD_EXIGIR_ASSINATURA=1`
  (desligado por padrão em desenvolvimento).
- **Hash do payload** (`payload_hash`, sha256 do JSON canônico): grava-se em toda leitura aceita e
  em toda rejeição — permite provar depois que dois envios eram (ou não) o mesmo payload.
- **Deduplicação**: `UNIQUE (equip_id, data_hora)` em `leituras_telemetria` — reenvio do mesmo
  instante para o mesmo equipamento é recusado (`409 duplicado`), não sobrescrito silenciosamente.
- **`logs_uso`**: uma linha por requisição (autenticada ou não, sucesso ou erro), com `kid`, papel,
  método, rota, status HTTP, duração e IP — nunca o segredo. Uma falha ao gravar o log nunca
  derruba a resposta (é logada como aviso e a requisição segue normalmente).
- **`leituras_rejeitadas`**: toda leitura recusada (validação de schema, inconsistência,
  equipamento desconhecido ou duplicidade) fica registrada com o motivo e o payload recebido —
  nada desaparece silenciosamente.
- **`request_id`**: gerado (ou ecoado, se o cliente enviar `X-Request-Id`) em todo request,
  devolvido no header de toda resposta e gravado em `logs_uso`, `leituras_telemetria`,
  `scores_risco`, `alertas` e `leituras_rejeitadas` — permite reconstruir, para qualquer
  requisição, exatamente o que entrou, o que foi decidido e por quê (`GET /auditoria/{request_id}`).
- **Sem stack trace em erro**: o handler genérico (`500`) loga o traceback internamente
  (`agroguard.logs`) mas nunca o inclui na resposta HTTP.
- **Segredos fora do controle de versão**: `.env` está no `.gitignore`; só `.env.example` (com
  placeholders "troque-me") é versionado.

## O que NÃO está implementado (e por que é aceitável no MVP)

- **JWT/OAuth2**: as chaves de API estáticas por papel cobrem o cenário real do desafio (um
  número pequeno e conhecido de integrações — dispositivos de campo, o dashboard interno, a
  seguradora) sem a complexidade operacional de um IdP. Trocar por OAuth2/JWT é um upgrade natural
  se a API precisar autenticar usuários finais diretamente, não integrações servidor-a-servidor.
- **TLS/HTTPS na própria API**: a API roda atrás de terminação TLS da infraestrutura (proxy/load
  balancer) em produção; localmente, em `http://localhost:8001`, TLS não se aplica. Não é
  responsabilidade do código da aplicação.
- **Rotação automática de chaves**: as chaves são trocadas manualmente (variável de ambiente); não
  há um endpoint de rotação. Aceitável para o número de integrações do MVP — vira um item de
  hardening se o número de chaves crescer.
- **Rate limit distribuído**: o token bucket é por processo (memória), não compartilhado entre
  réplicas. Suficiente para a instância única do MVP; um deployment com múltiplas réplicas exigiria
  um backend compartilhado (Redis, por exemplo).
