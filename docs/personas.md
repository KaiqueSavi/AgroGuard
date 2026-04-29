# 👥 Personas — AgroGuard IA

> Detalhamento das três personas-chave do AgroGuard IA, com contexto, dores, ganhos e jobs-to-be-done.

---

## Persona 1 — Carlos, Operador de Colheitadeira

### Identificação

| Campo | Valor |
|---|---|
| **Nome (fictício)** | Carlos Henrique Souza |
| **Idade** | 38 anos |
| **Localização** | Sorriso – MT |
| **Cargo** | Operador de máquinas agrícolas |
| **Experiência** | 12 anos no campo |
| **Equipamentos que opera** | Colheitadeira John Deere S780, trator Case Magnum |
| **Escolaridade** | Ensino médio completo + cursos técnicos da SENAR |
| **Tecnologia** | Smartphone Android, usa WhatsApp diariamente, pouca familiaridade com dashboards |

### Um dia na vida

5h30 — Acorda, café com a esposa.
6h00 — Desloca-se para a fazenda em moto.
6h30 — Inspeção visual da máquina, abastecimento.
7h00 — Início da colheita.
12h00 — Almoço no campo (marmita).
13h00 — Retomada.
18h30 — Encerramento; relatório no caderno.
19h30 — Retorno pra casa.

> *"Na safra a gente trabalha de sol a sol. Tem dia que rodo 14 horas em cima da máquina. Quando dá problema, é prejuízo pra todo mundo."*

### Dores

- 🔴 **Atolamentos surpresa** — entrou em área molhada sem saber e perdeu um dia inteiro de trabalho.
- 🔴 **Falta de alerta antecipado** — só descobre que vai chover olhando o céu.
- 🔴 **Pressão por produtividade** — janela curta, qualquer parada custa caro.
- 🔴 **Comunicação manual com gestor** — usa rádio ou WhatsApp; nem sempre tem sinal.
- 🔴 **Histórico esquecido** — o problema que ele teve mês passado não fica documentado em lugar nenhum.

### Ganhos esperados

- ✅ Saber **antes** se a área onde vai operar está em risco.
- ✅ Receber **recomendação simples** (ex.: "espera 4h", "vai pela rota B").
- ✅ Ter um canal **fácil pra registrar** o que aconteceu (foto, áudio).
- ✅ Sentir que a tecnologia o **ajuda**, não o **vigia**.

### Jobs-to-be-Done

> *Quando estou prestes a entrar numa área de operação, quero ter certeza de que ela é segura, para evitar incidentes que me responsabilizem ou parem minha jornada.*

> *Quando algo dá errado no campo, quero registrar rapidamente, para não perder o detalhe e ajudar a equipe.*

### Frases-chave (cliente real)

- *"Só queria ser avisado antes."*
- *"Eu não tenho tempo pra ficar olhando relatório."*
- *"Se for pra me ajudar, tem que ser no celular e em português claro."*

### User stories priorizadas

| ID | História | Prioridade Sprint 1 |
|---|---|---|
| US01 | Receber alerta no celular antes de entrar em área de risco | ⭐⭐⭐ Alta |
| US02 | Ver rota alternativa quando rota atual for crítica | ⭐⭐ Média |
| US03 | Registrar ocorrências com foto/áudio | ⭐ Baixa |

---

## Persona 2 — Marina, Gestora de Frota Agrícola

### Identificação

| Campo | Valor |
|---|---|
| **Nome (fictício)** | Marina Castilhos |
| **Idade** | 42 anos |
| **Localização** | Cuiabá – MT (escritório), supervisiona 6 fazendas |
| **Cargo** | Gerente de operações em cooperativa agrícola |
| **Formação** | Engenheira Agrônoma, MBA em Agronegócio |
| **Equipe** | 38 equipamentos, 45 operadores, 6 fazendas parceiras |
| **Tecnologia** | Notebook + 2 monitores, planilhas, ERP da cooperativa, BI Power |

### Um dia na vida

7h00 — Reuniões diárias com fazendas via Teams.
9h00 — Análise de produtividade no Power BI.
11h00 — Negociação com fornecedores e seguradora.
14h00 — Visita técnica a uma fazenda (2x por semana).
17h00 — Relatório semanal para diretoria.
19h00 — Encerra.

> *"Eu preciso de uma visão consolidada. Hoje eu só descubro problema quando alguém liga pedindo guincho."*

### Dores

- 🔴 **Reatividade** — só age depois que o sinistro acontece.
- 🔴 **Visibilidade fragmentada** — cada fazenda tem um sistema, dados não conversam.
- 🔴 **Custo de seguro alto** — falta argumento técnico pra negociar prêmios.
- 🔴 **Dificuldade de comparar** desempenho entre operadores e regiões.
- 🔴 **Relatório manual** — passa horas montando slide para diretoria.

### Ganhos esperados

- ✅ Mapa em tempo real com **todos os equipamentos coloridos por risco**.
- ✅ Ranking de **top 5 riscos da semana** com 1 clique.
- ✅ Métricas de **sinistros evitados** (prova de valor).
- ✅ Relatórios **exportáveis em PDF** para diretoria.
- ✅ Comparativo histórico para **negociar prêmios** com a seguradora.

### Jobs-to-be-Done

> *Quando inicio meu turno, quero saber rapidamente quais equipamentos estão em situação de risco, para priorizar ações preventivas.*

> *Quando preparo a renovação do seguro, quero apresentar dados de boas práticas da minha frota, para conseguir desconto na apólice.*

### User stories priorizadas

| ID | História | Prioridade Sprint 1 |
|---|---|---|
| US04 | Visualizar em mapa equipamentos com nível de risco | ⭐⭐⭐ Alta |
| US05 | Receber relatório semanal com top 5 riscos | ⭐⭐ Média |
| US06 | Comparar histórico de sinistros por região | ⭐⭐ Média |

---

## Persona 3 — Sompo Seguros (Underwriter / Analista de Sinistros)

### Identificação

| Campo | Valor |
|---|---|
| **Persona representada** | Equipe de subscrição e análise de sinistros agrícolas da Sompo |
| **Cargo típico** | Analista de subscrição sênior + analista de sinistros |
| **Localização** | São Paulo – SP |
| **Formação** | Atuária / Estatística / Engenharia |
| **Sistemas que usa** | Core de seguros, BI corporativo, plataformas de telemetria parceiras |

### Contexto

A Sompo precifica apólices, decide aceitar ou recusar riscos e investiga sinistros. Hoje, depende de:
- Histórico declarado pelo segurado (sujeito a inconsistências).
- Visitas técnicas pontuais.
- Dados de mercado agregados (sem granularidade por equipamento).

### Dores

- 🔴 **Falta de granularidade** — precificação ainda baseada em médias regionais.
- 🔴 **Tempo alto para análise de sinistros** — precisa coletar provas manualmente.
- 🔴 **Dificuldade em diferenciar bons e maus segurados** dentro de uma mesma carteira.
- 🔴 **Riscos emergentes** (mudanças climáticas, novas práticas) não capturados em modelos atuariais antigos.
- 🔴 **Concorrência** com seguradoras data-driven crescendo no agro.

### Ganhos esperados

- ✅ **API de risco em tempo real** integrável com o core.
- ✅ Histórico **auditável** de score por equipamento.
- ✅ **Contexto ambiental** disponível na análise de sinistro (chovia? distância de água? declive?).
- ✅ Capacidade de oferecer **descontos baseados em comportamento** (similar a telemática automotiva).
- ✅ **Redução de fraude** com evidências objetivas.

### Jobs-to-be-Done

> *Quando precifico uma apólice, quero acessar dados granulares de risco do segurado, para ajustar o prêmio a uma realidade individual.*

> *Quando analiso um sinistro, quero ver as condições ambientais e operacionais do momento exato, para validar a sinistralidade e identificar fraudes.*

### User stories priorizadas

| ID | História | Prioridade Sprint 1 |
|---|---|---|
| US07 | Acessar score histórico de cada equipamento | ⭐⭐⭐ Alta |
| US08 | Consultar contexto ambiental no momento do sinistro | ⭐⭐ Média |
| US09 | Oferecer descontos a clientes com score baixo | ⭐ Baixa |

---

## Mapa de prioridades — Sprint 1

| Persona | User story de maior prioridade | Entrega esperada |
|---|---|---|
| Carlos (operador) | US01 — alerta mobile | Mockup + fluxo de notificação |
| Marina (gestora) | US04 — mapa com risco | Mockup do dashboard |
| Sompo (seguradora) | US07 — score histórico | Especificação do endpoint da API |

> Cada uma dessas histórias tem um responsável técnico no grupo (ver `README.md`, seção 12).
