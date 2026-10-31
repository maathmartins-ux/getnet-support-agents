# Spec — Getnet Multi-Agent Support System

Commitada antes de qualquer código de domínio. Congelada (OWNERSHIP.json): mudança aqui é decisão da sessão principal.

## Problema

Lojistas da Getnet (Brasil) mandam mensagens livres (pt ou en) para um único endpoint HTTP. Um sistema de pelo
menos três agentes cooperantes — Router, Knowledge (RAG sobre o site da Getnet + busca web) e Customer Support
(dados do próprio lojista via ferramentas) — precisa decidir quem atende, buscar a informação certa e devolver uma
resposta útil em JSON, com escalonamento humano quando não houver confiança.

## Agentes (nome no código → papel do enunciado)

| Código (`AgentName`) | Papel no enunciado | O que faz |
|---|---|---|
| `router` (módulo `router.py`) | Agent 1 — Router | intent, plano inicial, idioma, confiança; entrada de toda mensagem |
| supervisor (`supervisor.py`) | parte do Router ("manages workflow and data flow") | executa o plano, lê `ok/insufficient/error`, replaneja dentro de `ALLOWED`, `MAX_STEPS` |
| `faq` | Agent 2 — **Knowledge Agent** | RAG (BM25 + glossário pt↔en + rerank Haiku ao vivo) sobre corpus Getnet Brasil; busca web para `general` |
| `records` | Agent 3 — **Customer Support Agent** | ferramentas de CRM do lojista (≥ 2 leitura + escrita com confirmação) |
| `escalation` | Agent 4 (bônus) — **Human Escalation Agent** | ticket persistido, fila `/operator`, resposta do humano volta à conversa |

Os nomes `faq`/`records` são os do contrato do kit (`schemas.AgentName`); a documentação e as respostas usam
"knowledge" e "support". Trocar o literal agora quebraria 8 forks em paralelo (ADR 0003).

## Taxonomia de intents (o router devolve exatamente uma)

| Intent | Quando | Plano inicial | Escala se falhar? |
|---|---|---|---|
| `knowledge` | pergunta sobre produto, serviço, tarifa, regra ou funcionamento da Getnet, **sem** depender dos dados do lojista | `["faq"]` | sim (sem fonte → humano) |
| `support` | pergunta sobre os **dados do próprio lojista**: vendas, recebimentos/depósitos, saldo, antecipação dele, contestação dele | `["records"]` | sim (erro de tool → tenta knowledge → humano) |
| `troubleshoot` | **problema operacional** na maquininha ou numa transação (não conecta, erro, recusa, bobina, tela) | `["records", "faq"]` (status do terminal / transação recusada **e** manual) | sim |
| `general` | pergunta geral fora da Getnet que a web responde: clima, câmbio, notícia, data | `["faq"]` com busca web | **não** (`NO_ESCALATION`): sem web, responde com honestidade |
| `multi` | duas ou mais perguntas de intents diferentes na mesma mensagem | união ordenada dos planos | conforme cada parte |
| `human_request` | pedido explícito de atendente/humano | `["escalation"]` | — |
| `blocked` | barrado pelo guardrail (injeção, jailbreak, dado de terceiro, abuso) | `[]` | não |

**Regra support × troubleshoot:** se a mensagem descreve um **sintoma** ("não conecta", "erro", "recusada",
"travou") é `troubleshoot`, mesmo que cite "minha maquininha". Se pede um **dado** ("quando cai", "quanto vendi",
"meu saldo", "antecipar meu valor") é `support`. Se pede **como funciona** algo, sem dado nem sintoma, é `knowledge`.

**Regra general × knowledge:** clima, câmbio e qualquer assunto sem relação com Getnet → `general` (web). Pergunta
sobre outro banco, adquirente ou produto que a Getnet não tem → `knowledge` (o RAG não acha → `insufficient` →
humano), não `general`.

## Ferramentas do Customer Support Agent (fork B; nomes congelados)

| Tool | Tipo | Risco | Retorno |
|---|---|---|---|
| `get_settlements` | leitura | — | agenda de recebimentos (data da venda, valor, modalidade, data prevista em dias úteis, status) |
| `get_transactions` | leitura | — | transações recentes (aprovadas e recusadas, com código e motivo da recusa) |
| `get_terminal_status` | leitura | — | maquininha: modelo, conectividade (chip/Wi-Fi), último sinal, versão, bloqueio |
| `restart_terminal` | escrita | normal | pede confirmação (`pending_action`) |
| `request_anticipation` | escrita | high | pede confirmação; sem valor → propõe o total disponível |
| `open_chargeback` | escrita | high | pede confirmação; **só sobre transação aprovada** |

A identidade das tools vem sempre do servidor (`user_id` do token ou do corpo em modo demo); o modelo nunca escolhe
o lojista. Lojistas do CRM: `cliente1988` (cenários do enunciado) e `cliente2024`.

## Requisitos

| ID | Requisito (do enunciado) | Módulo | Teste / eval |
|---|---|---|---|
| FR-01 | ≥ 3 agentes distintos + mecanismo claro de comunicação (chamada direta + supervisor com agentes como tools) | `router.py`, `supervisor.py`, `agents.py` | `tests/test_domain_supervisor.py`, split `replan` |
| FR-02 | Router é a entrada e decide agente ou sequência | `router.py` | `tests/test_domain_router.py`, `intent_acc` |
| FR-03 | Knowledge: RAG sobre o site da Getnet (ingestão → armazenamento → busca → geração) | `ingest.py`, `rag.py`, `agents.faq_agent` | `evals/retrieval*.jsonl` (Recall@3, MRR) |
| FR-04 | Knowledge: busca web para perguntas gerais | `agents.faq_agent` + `prompts/general.md` | AC-02, AC-07 |
| FR-05 | Support: dados do lojista com ≥ 2 tools | `tools.py`, `agents.records_agent` | `tests/test_tools.py`, AC-03, AC-05, AC-08 |
| FR-06 | `POST /chat` com `{"message","user_id"}` → JSON útil | `api.py` | `tests/test_domain_http.py` |
| FR-07 | Bônus: 4º agente de escalonamento humano + handoff quando não há confiança | `agents.escalation_agent`, `/operator` | `tests/test_hitl.py`, split `replan` |
| FR-08 | Bônus: guardrails (inseguro, irrelevante, sensível, não suportado) | `guardrails.py` | `evals/cases.d/e.jsonl`, `tests/test_domain_guardrails.py` |
| FR-09 | Bônus: avaliação e observabilidade | `evals/`, `observability.py` | `scripts/check.py`, `/metrics` |
| NFR-01 | Sobe com um comando (Docker) | `Dockerfile`, `docker-compose.yml` | `scripts/check.py --docker` |
| NFR-02 | Funciona sem chave de LLM (modo offline determinístico) | `config.py` | CI |
| NFR-03 | Identidade: `AUTH_MODE=demo` no compose (aceita o payload do enunciado, `identity_verified=false`); `required` testado (ADR 0001) | `api.py`, `auth.py` | `tests/test_auth_modes.py`, `tests/test_domain_http.py` |
| NFR-04 | Réplicas: estado em SQLite de um nó, declarado (ADR 0002) | `store.py` | ADR 0002 |

## Cenários de aceite (literais do enunciado; `user_id` = `cliente1988`)

| ID | Mensagem | Intent | Rota / ferramenta | Handoff |
|---|---|---|---|---|
| AC-01 | What's the difference between the Get Clássica and the Get Smart? | `knowledge` | faq com fontes | não |
| AC-02 | What's the weather forecast in Porto Alegre tomorrow? | `general` | faq + web | não |
| AC-03 | When will the money from yesterday's sales be deposited? | `support` | `get_settlements` | não |
| AC-04 | Do I need a bank account to receive my sales via Pix? | `knowledge` | faq com fontes | não |
| AC-05 | My card machine won't connect to the internet, what should I do? | `troubleshoot` | `get_terminal_status` + faq | não |
| AC-06 | How does receivables advance (antecipação) work with Getnet? | `knowledge` | faq com fontes | não |
| AC-07 | What's the euro exchange rate today? | `general` | faq + web | não |
| AC-08 | My card machine is showing a transaction decline error. | `troubleshoot` | `get_transactions` + faq | não |
| AC-09 | How many installments can I split a sale into with the crediário? | `knowledge` | faq com fontes | não |
| AC-10 | Can I sell through WhatsApp using the Payment Link? | `knowledge` | faq com fontes | não |

Cada AC é o caso `official-NN` em `evals/cases.jsonl`. Resposta no idioma da pergunta.

## Splits do eval

`official` (10, gate) · `replan` (≥ 20, gate: o plano inicial falha e o supervisor desvia) · `parallel` · `approval`
(escrita só com confirmação) · casos dos forks em `evals/cases.d/` (C1: variação, memória, hard; E: guardrail) ·
`heldout` (`evals/heldout_blind.jsonl`, 24 casos escritos por autor cego só com enunciado + esta SPEC, **fora do gate,
nunca editado**, nenhuma frase dele pode aparecer em regra ou exemplo).

## Fora de escopo
- Integração real com sistemas da Getnet (CRM é fictício, em `data/crm/`).
- Pagamento real; ações de escrita executam só no CRM fictício, após confirmação do dono.
- Multi-réplica com estado compartilhado (ADR 0002).

## Divisão em forks

Ver OWNERSHIP.json. Contrato: `src/app/schemas.py` (`RouterDecision`, `AgentName`), assinatura de
`pipeline.handle(req, user_id, identity_verified)`, status `ok|insufficient|error` dos agentes, nomes de intents e
de tools desta SPEC.
