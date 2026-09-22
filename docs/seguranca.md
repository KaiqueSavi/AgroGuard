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
- **Rate limit por chave E por IP** (`RATE_LIMIT_POR_MIN`): token bucket em memória, em duas
  camadas. Por `kid`, depois da autenticação — protege a API de uma chave comprometida ou de um
  cliente com bug em loop. Por IP (`ip:<host>`), ANTES de validar a chave — sem essa segunda
  camada, uma chave ausente ou inválida nunca seria limitada, e um flood de requisições não
  autenticadas (adivinhando chaves, por exemplo) passaria livre. Ambas devolvem
  `429 limite_excedido`. Uma resposta `429` NUNCA vira uma linha em `logs_uso` — sob flood, gravar
  uma linha por requisição recusada seria o próprio ataque de negação de serviço contra o banco;
  em vez disso, ela é registrada como uma linha de log estruturado (`evento=limite_excedido`,
  `agroguard/logs.py`) em arquivo/stdout.
- **Assinatura de integridade opcional** (`X-Signature`): quando presente, deve ser o HMAC-SHA256
  hexadecimal do corpo cru da requisição, usando o próprio segredo da chave. Para o papel
  `dispositivo`, a assinatura passa a ser **obrigatória** quando `AGROGUARD_EXIGIR_ASSINATURA=1`
  (desligado por padrão em desenvolvimento). `X-Signature` não carrega nonce nem timestamp — ver
  "Anti-replay" abaixo para o que isso significa na prática.
- **Guarda de tamanho de corpo**: o middleware recusa (`413 payload_grande`) qualquer requisição
  com `Content-Length` acima de 1 MB, antes de qualquer parsing — protege contra um corpo enorme
  consumindo memória/CPU só para ser rejeitado depois pela validação de schema.
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

## Anti-replay: o que `X-Signature` cobre (e o que não cobre)

`X-Signature` prova INTEGRIDADE (o corpo não foi alterado em trânsito) e AUTENTICIDADE (quem
assinou tinha o segredo) — não prova FRESCOR. A assinatura não carrega nonce nem timestamp: um
atacante que capture uma requisição assinada válida pode reenviá-la bit a bit e ela ainda teria
uma assinatura válida (é o mesmo corpo, com o mesmo segredo).

O que efetivamente neutraliza o replay hoje, rota a rota:

- **`POST /telemetria` e `/telemetria/lote`**: a restrição `UNIQUE (equip_id, data_hora)` em
  `leituras_telemetria` rejeita qualquer reenvio do mesmo evento com `409 duplicado` — o replay é
  inofensivo, não uma segunda leitura fantasma.
- **`POST /alertas/{id}/reconhecer`**: é idempotente por construção (`UPDATE ... SET status =
  'reconhecido' WHERE id = :id`) — reenviar a mesma requisição não tem efeito colateral além do
  primeiro `UPDATE` (o alerta já está `reconhecido`; os reenvios seguintes só confirmam o mesmo
  estado).

Isso cobre o MVP porque as únicas rotas mutáveis assináveis têm essa proteção "de graça" pela
própria modelagem dos dados — mas não é uma defesa GERAL contra replay, e uma rota mutável futura
sem uma chave natural de deduplicação ficaria exposta. Ver "nonce + janela de tempo" abaixo.

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
- **Nonce + janela de tempo em `X-Signature`**: proteção geral contra replay (rejeitar uma
  assinatura reenviada fora de uma janela curta, ou já vista antes) — hoje o MVP se apoia na
  deduplicação natural de cada rota mutável (ver "Anti-replay" acima), que cobre as rotas
  existentes mas não generaliza para uma rota mutável futura sem chave natural de dedup.
