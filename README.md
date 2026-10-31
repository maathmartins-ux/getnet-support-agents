# Getnet Support Agents

Sistema multiagente de atendimento ao lojista Getnet: responde dúvidas de produto com RAG sobre o site
oficial, consulta os dados do próprio lojista com ferramentas, busca na web o que é geral (clima, câmbio) e
passa para um humano quando não tem base para responder.

| | |
|---|---|
| Rodar | `docker compose up -d --build` → `http://localhost:8000/docs` · console do operador em `/operator` |
| Testar | `python scripts/check.py --docker` (lint, testes, eval com gate, build, imagem sem extras, smoke do container) |
| CI | [GitHub Actions](../../actions/workflows/ci.yml) (o run do último commit está na aba Actions) |
| Vídeo | [walkthrough na página de Releases](../../releases/tag/video) (MP4 + legendas; narração por IA a partir do roteiro do autor, telas e números reais) |
| Docs | [Arquitetura](docs/ARCHITECTURE.md) · [Observabilidade](docs/OBSERVABILITY.md) · [Runbook](docs/RUNBOOK.md) · [SPEC](docs/SPEC.md) · [ADRs](docs/adr/) |

> **Para quem avalia lendo.** Toda afirmação deste README aponta um arquivo, um teste ou um resultado
> commitado em `evals/results/`. Os números da §5 são gerados por `scripts/fill_readme.py`, nunca digitados.

## 1. Como construir, configurar, rodar e testar

### 1.1 Docker (caminho do avaliador)

```bash
cp .env.example .env                      # opcional: sem chave roda no modo offline determinístico
docker compose up -d --build
curl -s localhost:8000/health
curl -s -X POST localhost:8000/chat -H "Content-Type: application/json" \
     -d '{"message":"What is the difference between the Get Clássica and the Get Smart?","user_id":"cliente1988"}'
```

O payload literal do enunciado (`{"message", "user_id"}`) funciona porque o compose do desafio liga
`AUTH_MODE=demo`; a resposta traz `identity_verified=false` para ninguém confundir demo com segurança
([ADR 0001](docs/adr/0001-auth-mode-demo.md)). Com identidade verificada:

```bash
TOKEN=$(docker compose exec -T api python -m app.auth cliente1988)   # JWT de desenvolvimento assinado
curl -s -X POST localhost:8000/chat -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" -d '{"message":"Quando cai o dinheiro das vendas de ontem?"}'
```

### 1.2 Local (sem Docker)

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.lock && .venv/bin/pip install -e .
.venv/bin/uvicorn app.api:app --app-dir src --reload          # Windows: .venv\Scripts\uvicorn.exe
```

### 1.3 Configuração (`.env`, todas opcionais)

| Variável | Padrão | Efeito |
|---|---|---|
| `LLM_PROVIDER` | `offline` | `anthropic` liga os modelos; `offline` usa só os caminhos determinísticos (CI) |
| `ANTHROPIC_API_KEY` | — | chave do provedor (nunca commitada; `.env` está no `.gitignore`) |
| `AUTH_MODE` | `required` no código, `demo` no compose | identidade só do Bearer × aceita `user_id` do corpo marcado como não verificado |
| `AUTH_SECRET`, `TOKEN_TTL_MIN`, `AUTH_ISSUER`, `AUTH_AUDIENCE` | segredo de dev, 60, `app`, `app-api` | JWT HS256 com `exp`/`iss`/`aud`/`jti` |
| `OPERATOR_KEYS` | — | `nome:chave,...`: chave pessoal por operador (a auditoria grava quem respondeu) |
| `RATE_LIMIT_PER_MIN` | 30 | por identidade (por IP no modo demo); falha fechado |
| `RETRIEVER` / `RERANK` | `bm25` / `auto` | `hybrid` = BM25 + embeddings (RRF); rerank do top-20 pelo Haiku quando há LLM |
| `COVERAGE_MIN_SCORE` | calibrado | limiar do portão "sem fonte, sem afirmação" (escolhido por `--calibrate-gate`) |
| `ROUTER_MODEL`, `SUPERVISOR_MODEL`, `AGENT_MODEL`, `*_EFFORT` | ver `src/app/config.py` | modelo e effort por papel |
| `ACTION_TTL_MIN`, `SLA_HIGH_MIN`, `SLA_NORMAL_MIN` | 15, 120, 480 | validade da ação pendente e SLA do caso humano |
| `TELEGRAM_*` | — | canal opcional do operador (aviso do caso + `/responder T-xxxx texto`) |
| `OTEL_EXPORTER` | — | `console` ou `otlp` liga OpenTelemetry (extra `.[otel]`) |

### 1.4 Testes

```bash
python scripts/check.py            # ruff + pytest + eval offline com gate
python scripts/check.py --docker   # + build, imagem sem extras de dev e smoke HTTP do container
python -m evals.run_evals --compare-retrievers --rerank       # Recall@3/MRR por retriever
powershell -File scripts/live_eval.ps1 -MaxUsd 3               # ao vivo por split, com teto de US$ (bash: scripts/live_eval.sh)
```

**Estratégia de testes** (detalhe em [docs/EVAL_STRATEGY.md](docs/EVAL_STRATEGY.md)), em quatro camadas:

| Camada | O que prova | Onde |
|---|---|---|
| Unidade | cada peça isolada: tokenização e BM25, regras do router, tabela do supervisor, tools, guardrails, JWT | `tests/test_*.py` |
| Integração da orquestração | o turno inteiro pelo `TestClient` com LLM falso que injeta falha: replanejamento, paralelismo, handoff, retomada | `tests/test_supervisor.py`, `tests/test_hitl.py`, `tests/test_parallel.py` |
| HTTP no container | os 10 cenários do enunciado × `AUTH_MODE` demo e required | `tests/test_domain_http.py`, smoke do `check.py --docker` |
| Qualidade de IA | golden set por split com gate no CI, held-out cego, ao vivo com pass^k, juiz LLM calibrado contra rótulos humanos | `evals/` |

## 2. Arquitetura

```mermaid
flowchart LR
  U[Lojista + token] --> API[/POST /chat/] --> RL[Auth demo/required + rate limit] --> G1[Guardrail regex + PII]
  G1 --> G2[Guardrail Haiku] & R[Router Haiku / regras + k-NN]
  G1 --> M[(SQLite: histórico, memória, tickets, ações)]
  R --> S{Supervisor Sonnet low / tabela}
  S -->|lote paralelo| A1[Knowledge faq: RAG + web] & A2[Support records: tools do CRM]
  A1 & A2 -->|status ok / insufficient / error| S
  S -->|replaneja| E[Escalation] --> Q[(Fila de handoff)] --> OP[/operator ou Telegram/] -->|resposta + retomada| M
```

| Agente do enunciado | Nome no código | Fonte de verdade | Saída |
|---|---|---|---|
| Agent 1 — Router | `src/app/router.py` + supervisor (`src/app/supervisor.py`) | taxonomia da [SPEC](docs/SPEC.md) | intent, plano, idioma, confiança; replanejamento |
| Agent 2 — Knowledge | `faq` (`agents.faq_agent`) | corpus do site Getnet Brasil; busca web só para `general` | resposta com `sources` citadas, ou `insufficient` |
| Agent 3 — Customer Support | `records` (`agents.records_agent`) | CRM do lojista autenticado, 6 tools | dados, `tool_calls`, `pending_action` para escrita |
| Agent 4 (bônus) — Human Escalation | `escalation` | fila persistida de tickets | protocolo; a resposta humana volta à conversa |

Os nomes `faq`/`records` são o contrato do kit; trocá-los com 8 forks em paralelo custaria a integração
([ADR 0003](docs/adr/0003-kit-declarado.md)). Os agentes se comunicam por **chamada direta de função** com um
contrato único (`AgentResult` com `status: ok | insufficient | error`, em `src/app/agents.py`); com LLM, o
supervisor os enxerga como **tools** (`faq_agent`, `records_agent`, `escalation_agent`, JSON Schema `strict`).
O supervisor decide pelo status, nunca pelo texto, e todo desvio do plano vai para `replans` na resposta.

**Taxonomia (SPEC) e plano inicial de cada intent:**

| Intent | Quando | Plano | Se falhar |
|---|---|---|---|
| `knowledge` | como funciona produto, tarifa ou regra da Getnet | `faq` | sem fonte → humano |
| `support` | **dado** do próprio lojista (quando cai, quanto vendi, antecipar meu valor) | `records` | erro de tool → knowledge → humano |
| `troubleshoot` | **sintoma** operacional (não conecta, erro, recusa) | `records` + `faq` | humano |
| `general` | clima, câmbio, assunto fora da Getnet | `faq` com busca web | **não escala**: sem web, diz que não sabe |
| `multi` | duas perguntas de intents diferentes | união ordenada, em paralelo | conforme cada parte |
| `human_request` | pede atendente | `escalation` | — |
| `blocked` | guardrail barrou | — | recusa padrão |

Os três diagramas detalhados (agentes, RAG, HITL) estão em [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

### 2.1 Fluxo de uma mensagem

| # | Etapa | Código | LLM? |
|---|---|---|---|
| 1 | Autenticação (JWT ou demo) e rate limit no SQLite | `src/app/auth.py` | não |
| 2 | Guardrail 1: regex de injeção (com desofuscação), PII mascarada antes de qualquer outra etapa | `src/app/guardrails.py` | não |
| 3 | Em paralelo: guardrail 2 (classificador Haiku) e router | `src/app/pipeline.py` | sim (Haiku) |
| 4 | Router: intenção, plano, idioma, confiança (JSON schema + few-shot dinâmico; regras + k-NN offline) | `src/app/router.py` | sim, com fallback |
| 5 | Supervisor: executa o plano, roda agentes independentes em paralelo, lê o status e replaneja dentro de `ALLOWED` e `MAX_STEPS` | `src/app/supervisor.py` | sim (Sonnet low), com fallback em tabela |
| 6 | Agentes: knowledge `faq` (RAG/web), support `records` (tools `get_settlements`, `get_transactions`, `get_terminal_status`; escrita `restart_terminal`, `request_anticipation`, `open_chargeback` só com confirmação), escalation (ticket) | `src/app/agents.py`, `src/app/tools.py` | sim (Sonnet medium), com caminho determinístico |
| 7 | Saída segura: máscara de PII e **checagem de todo número contra fonte, tool e pergunta** | `src/app/grounding.py` | não |
| 8 | Persistência: mensagens, resumo rolante, memória do lojista, analytics do request | `src/app/store.py` | não |
| 9 | Resposta JSON: `answer`, `intent`, `route`, `replans`, `sources`, `tool_calls`, `handoff`, `pending_action`, `unsupported_numbers`, `usage` (tokens e US$) | `src/app/schemas.py` | — |

### 2.2 RAG: ingestão → armazenamento → busca → geração

| Fase | O que acontece | Código / dado |
|---|---|---|
| Ingestão | `python -m app.ingest` baixa as páginas de produto e suporte do site Getnet **Brasil** (só `site.getnet.com.br`/`getnet.com.br`; `getnet.net/pt` é Portugal e fica fora), extrai só o texto visível, remove menu e rodapé (linha repetida em metade das páginas) e grava trechos **literais** de 300–800 caracteres com título, URL, data de coleta e SHA-256 | `src/app/ingest.py`, [docs/SOURCES.md](docs/SOURCES.md), [docs/SOURCES_SUPORTE.md](docs/SOURCES_SUPORTE.md) |
| Armazenamento | JSONL versionado no git em `data/knowledge/`; documento com injeção é descartado na carga (`poisoned_docs_dropped_total`); índice em memória recarregado quando o arquivo muda | `src/app/rag.py::load_docs` |
| Busca | consulta expandida pelo glossário pt↔en → BM25 (k1 1,5, b 0,75, título com peso 2) ou híbrido (BM25 + embeddings por RRF k=60) → rerank do top-20 pelo Haiku | `src/app/rag.py`, `data/glossary.json` |
| Portão | sem trecho acima de `COVERAGE_MIN_SCORE` → `insufficient` → o supervisor replaneja (pergunta da Getnet sem fonte → humano; `general` usa a web e nunca escala) | `src/app/agents.py::covered_hits` |
| Geração | Sonnet responde só dos trechos numerados, cita `[n]` ou devolve `NOT_IN_SOURCES`; número da resposta conferido contra os trechos | `src/app/prompts/faq.md`, `src/app/grounding.py` |
| Medida | Recall@3 e MRR por retriever, com e sem rerank | `evals/retrieval.jsonl`, `evals/results/` |

### 2.3 Como usei LLM, e onde NÃO usei

| Papel | Modelo / effort | Por quê |
|---|---|---|
| router, guardrail 2, reranker | Haiku 5.5, low | classificação curta com schema; barato e rápido |
| supervisor | Sonnet 5.5, low | só escolhe o próximo especialista |
| agentes (knowledge, support, resume) | Sonnet 5.5, medium | redige com fonte e usa tools |
| juiz do eval | Opus 5.5, medium | pelo menos tão capaz quanto o julgado |

Recursos do provedor usados: tool use com `strict` (especialistas como tools do supervisor; tools do CRM),
JSON schema na saída do router, web search nativo para perguntas gerais, effort por papel. Nos modelos 5.5 não
existe `temperature`: a estabilidade vem de schema, enum e código determinístico.

**Onde NÃO usei LLM, de propósito:**
- autenticação, rate limit e identidade das tools (o `user_id` vem do token, nunca do modelo);
- guardrail 1 e máscara de PII (regex auditável roda antes de qualquer modelo ver o texto);
- **checagem de números** da resposta (`src/app/grounding.py`): determinística, roda em todo turno;
- cálculo de liquidação em dias úteis e feriados, e execução das ações (`src/app/tools.py`);
- portão de cobertura, transições permitidas (`ALLOWED`) e teto de passos (`MAX_STEPS`);
- memória de longo prazo e resumo rolante (auditáveis, sem custo, sem PII);
- o caminho offline inteiro: o CI roda sem chave e qualquer erro do provedor cai nele.

### 2.4 Servidor MCP

O mesmo sistema é exposto como servidor MCP em `/mcp` (`src/app/mcp_server.py`), para ser usado por outro
agente (Claude Desktop, Claude Code): `ask` (o turno inteiro), `search_knowledge` (busca com fonte) e
`crm_tool` (tools do CRM). Exige Bearer JWT antes do protocolo (401 anônimo); a identidade vem do token e a
escrita continua exigindo confirmação do dono (`tests/test_mcp.py`).

## 3. Cobertura da régua de avaliação

Mapa para quem avalia **lendo**: código, teste que prova e onde está o número. Os números vêm dos
blocos da §5, gerados de `evals/results/` por `scripts/fill_readme.py`. Todo caminho em crase desta
seção existe: `tests/test_evidence.py` falha se um sumir. Reproduzir tudo: `python scripts/check.py --docker`.

| Critério | O que foi feito | Código | Prova | Número |
|---|---|---|---|---|
| Business & Challenge Fit | os 10 cenários literais do enunciado no split `official`, via HTTP nos dois modos de auth; multi-turno | `src/app/tools.py` | `evals/cases.jsonl` | §5 Offline e Ao vivo, `official` |
| Orchestration | Supervisor LLM com agentes como tools, lê `insufficient`/`error` e replaneja; tabela PLANS/FALLBACK/ALLOWED/MAX_STEPS; agentes independentes em paralelo | `src/app/supervisor.py` | `tests/test_supervisor.py::test_llm_reads_insufficient_and_replans_to_escalation`, `tests/test_supervisor.py::test_llm_disallowed_transition_is_refused`, `tests/test_parallel.py::test_independent_agents_run_in_parallel_in_plan_order` | §5 Replanejamento, splits `replan` e `parallel` |
| Router | Haiku com JSON schema e few-shot dinâmico (8 exemplos mais parecidos); regra por frase + k-NN de n-gramas no offline; seguimento pela última fala com assunto; teste que reprova frase do held-out copiada para regra | `src/app/router.py` | `tests/test_router.py::test_llm_failure_falls_back_to_rules`, `tests/test_router_knn.py::test_unseen_paraphrase_goes_to_right_intent`, `tests/test_router_followup.py::test_follow_up_skips_acknowledgement`, `tests/test_router_contamination.py::test_detector_catches_v3_leak` | §5 Offline, `intent_acc` |
| Context, Knowledge & RAG | BM25 e híbrido (RRF) atrás de `RETRIEVER`, com **rerank do top-20 pelo Haiku** quando há LLM; "sem fonte, sem afirmação"; **todo número da resposta conferido contra fonte, tool e pergunta** (sem LLM; `unsupported_numbers` na resposta) | `src/app/rag.py`, `src/app/grounding.py` | `tests/test_rag.py::test_compare_retrievers_reports_both`, `tests/test_rerank.py::test_rerank_follows_the_llm_order_and_keeps_bm25_scores`, `tests/test_rerank_eval.py::test_compare_adds_a_rerank_row_only_when_asked`, `tests/test_agents.py::test_faq_llm_not_in_sources_is_insufficient`, `tests/test_grounding.py::test_pipeline_flags_invented_number_and_counts_it`, `evals/retrieval.jsonl` | §5 Offline, Recall@3, MRR e `numbers_acc` |
| Tool & Action | JSON Schema, identidade do servidor, escrita com confirmação do dono; **risco alto com aprovação de operador (quatro olhos)**; ação pendente expira (TTL); execução única entre réplicas; **servidor MCP em `/mcp`** (ask, search_knowledge, crm_tool; JWT obrigatório) | `src/app/actions.py`, `src/app/tools.py`, `src/app/mcp_server.py` | `tests/test_mcp.py::test_crm_tool_identity_comes_from_token_and_write_needs_confirmation`, `tests/test_mcp.py::test_anonymous_gets_401_before_the_protocol`, `tests/test_agents.py::test_tool_identity_is_server_side`, `tests/test_hitl.py::test_high_risk_action_needs_owner_then_operator_and_runs_once`, `tests/test_hitl.py::test_pending_action_expires`, `tests/test_memory_and_handoff.py::test_claim_is_atomic` | §5 Offline, `tools_acc` |
| Security & Identity | JWT HS256 com `exp`/`iss`/`aud`/`jti` e revogação; operador com chave pessoal (auditoria); rate limit no SQLite que falha fechado; `AUTH_MODE` required/demo; guardrails regex + Haiku com desofuscação e injeção indireta; PII mascarada na entrada, no log e na saída | `src/app/auth.py`, `src/app/guardrails.py` | `tests/test_identity.py::test_expired_token_is_rejected`, `tests/test_identity.py::test_revoked_token_is_rejected_via_api`, `tests/test_identity.py::test_rate_limit_fails_closed`, `tests/test_guardrails.py::test_obfuscated_injection_is_caught`, `tests/test_guardrails.py::test_poisoned_document_is_dropped_at_load`, `docs/adr/0001-auth-mode-demo.md` | §5 Offline, split `guardrail` |
| Memory, State & Resilience | Histórico em SQLite (WAL, vários processos) com **resumo rolante** além da janela; memória de longo prazo por usuário; queda do LLM cai no determinístico | `src/app/store.py`, `src/app/pipeline.py` | `tests/test_memory_and_handoff.py::test_history_survives_restart`, `tests/test_analytics.py::test_rolling_digest_keeps_early_facts_beyond_the_window`, `tests/test_identity.py::test_sqlite_survives_concurrent_writers`, `tests/test_agents.py::test_records_llm_failure_uses_deterministic_path` | §5 Offline, split `memory` |
| Human Oversight | Fila persistida e console; **a resposta do operador retoma a conversa na hora**; aprovação de ação de risco; SLA com re-escalonamento único; Telegram ida e volta | `src/app/resume.py`, `src/app/api.py`, `src/app/notify.py` | `tests/test_hitl.py::test_operator_reply_resumes_the_conversation_immediately`, `tests/test_hitl.py::test_overdue_case_is_escalated_once`, `tests/test_hitl.py::test_two_simultaneous_replies_only_one_wins`, `tests/test_notify.py::test_reply_from_telegram_resumes_conversation` | §5 Offline, `handoff_acc` |
| Evaluation & Quality | Gate offline no CI; ao vivo por split com teto de US$; `--repeat N` (pass^k, instáveis); juiz calibrado (kappa, TPR/TNR); checagem numérica sem LLM; matriz de falhas; limiar do portão por medida | `evals/run_evals.py`, `evals/judge.py`, `src/app/grounding.py` | `tests/test_evals.py::test_gate_passes_in_process`, `tests/test_evals.py::test_calibration_reports_tpr_tnr`, `tests/test_evals.py::test_repeat_reports_pass_hat_k_and_unstable_cases`, `tests/test_rag.py::test_gate_threshold_is_chosen_by_measurement`, `tests/test_eval_isolation.py::test_each_case_starts_without_memory_of_other_cases`, `tests/test_eval_judge_evidence.py::test_live_rows_record_tool_calls_sources_and_evidence`, `tests/test_eval_language_ci.py::test_detects_language_of_the_text`, `evals/judge_calibration.jsonl` | §5 Offline, Ao vivo e Juiz |
| Observability, Reliability & Cost | Log JSON com `trace_id` e status de cada agente; US$ e tokens por request; `/metrics`; **alertas Prometheus provisionados**; `/analytics` (resolução, custo por resolvido, 👍/👎); OTel por env; SLOs e painéis em `docs/OBSERVABILITY.md` | `src/app/observability.py`, `src/app/analytics.py`, `ops/alerts.yml` | `tests/test_agents.py::test_cost_per_request_from_price_table`, `tests/test_alerts.py::test_alert_rules_are_valid_and_actionable`, `tests/test_analytics.py::test_every_request_is_logged_and_feedback_is_owned`, `tests/test_otel.py::test_console_exporter_emits_span_linked_to_trace_id` | §5 Ao vivo, `cost_usd` e p95 |
| Production Engineering | Dockerfile multi-stage não-root, base fixada por digest com Dependabot, extra opcional embutido (`EXTRAS=hybrid`), lockfiles, smoke do container no CI; scripts em bash e PowerShell; runbook | `Dockerfile` | `scripts/check.py`, `.github/workflows/ci.yml`, `.github/dependabot.yml`, `requirements.lock`, `requirements-hybrid.lock`, `scripts/live_eval.sh`, `docs/RUNBOOK.md` | link do CI no topo |
| Engineering Judgment | Decisões com a alternativa descartada e o número que a descartou; limitações com próximo passo; ADRs | `docs/adr/0001-auth-mode-demo.md` | §4 e §9 deste README | — |

## 4. Decisões e trade-offs

| Decisão | Alternativa descartada | O que descartou |
|---|---|---|
| Supervisor LLM com tabela determinística como fallback ([ADR 0004](docs/adr/0004-supervisor-llm-com-tabela.md)) | só LLM / só tabela | só LLM deixa o CI dependente de chave; só tabela não replaneja casos novos. Ver §5 Replanejamento, offline × ao vivo |
| Agentes independentes em threads | asyncio | os agentes fazem I/O síncrono (SQLite, SDK); threads cortam o p95 sem reescrever a pilha (`tests/test_parallel.py`) |
| Effort por papel (supervisor low, agentes medium) | um effort global | o p95 ao vivo da v2 vinha do supervisor em medium (comentário em `src/app/config.py`) |
| BM25 + rerank Haiku do top-20 ([ADR 0005](docs/adr/0005-rag-bm25-rerank.md)) | embeddings desde o início | medido antes do relógio: o BM25 já acha a fonte no top-20 em 90,4% e no top-3 em 70,8%; o gargalo é a ordem, não o recall (`src/app/config.py`). Números deste corpus: `--compare-retrievers --rerank` em `evals/results/` |
| Glossário pt↔en na consulta | traduzir a pergunta com LLM | custo e latência em todo turno para um mapeamento fixo de termos de produto |
| Portão de cobertura com limiar calibrado | limiar escolhido à mão | `--calibrate-gate` escolhe o limiar que maximiza respondidas com recusa ≥ 85% (`tests/test_rag.py::test_gate_threshold_is_chosen_by_measurement`) |
| Checagem de números sem LLM ([ADR 0006](docs/adr/0006-checagem-numerica-sem-llm.md)) | juiz LLM em todo turno | determinística, grátis, roda em 100% dos turnos; o juiz fica no eval |
| SQLite atrás de `Store` | Postgres/Redis | sobe com um comando; a troca para réplicas fica isolada num módulo ([ADR 0002](docs/adr/0002-replicas-sqlite.md)) |

## 5. Avaliação

Números gerados por `python scripts/fill_readme.py` a partir de `evals/results/`.

### Offline (gate do CI)

<!-- eval:begin -->
Modo: `in-process` · provedor `offline`

| Métrica | official | replan | parallel | approval | human | official-var | memory | hard | guardrail | heldout | ALL |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| cases | 10 | 20 | 12 | 10 | 1 | 54 | 13 | 42 | 34 | 24 | 220 |
| intent_acc | 90.0 [IC95 59.6–98.2; n=10] | 100.0 [IC95 83.9–100.0; n=20] | 50.0 [IC95 25.4–74.6; n=12] | 80.0 [IC95 49.0–94.3; n=10] | 100.0 [IC95 20.7–100.0; n=1] | 83.3 [IC95 71.3–91.0; n=54] | 61.5 [IC95 35.5–82.3; n=13] | 54.8 [IC95 39.9–68.8; n=42] | 88.2 [IC95 73.4–95.3; n=34] | 62.5 [IC95 42.7–78.8; n=24] | 75.0 [IC95 68.9–80.3; n=220] |
| handoff_acc | 100.0 [IC95 72.2–100.0; n=10] | 10.0 [IC95 2.8–30.1; n=20] | 91.7 [IC95 64.6–98.5; n=12] | 100.0 [IC95 72.2–100.0; n=10] | 100.0 [IC95 20.7–100.0; n=1] | 100.0 [IC95 89.3–100.0; n=32] | 100.0 [IC95 34.2–100.0; n=2] | 80.0 [IC95 37.6–96.4; n=5] | 100.0 [IC95 34.2–100.0; n=2] | 86.4 [IC95 66.7–95.3; n=22] | 80.2 [IC95 72.0–86.4; n=116] |
| handoff_outcome_acc | 100.0 [IC95 72.2–100.0; n=10] | 10.0 [IC95 2.8–30.1; n=20] | 91.7 [IC95 64.6–98.5; n=12] | 100.0 [IC95 72.2–100.0; n=10] | 100.0 [IC95 20.7–100.0; n=1] | 100.0 [IC95 89.3–100.0; n=32] | 100.0 [IC95 34.2–100.0; n=2] | 80.0 [IC95 37.6–96.4; n=5] | 100.0 [IC95 34.2–100.0; n=2] | 86.4 [IC95 66.7–95.3; n=22] | 80.2 [IC95 72.0–86.4; n=116] |
| blocked_acc | — | — | — | — | — | — | — | — | 100.0 [IC95 86.7–100.0; n=25] | 0.0 [IC95 0.0–65.8; n=2] | 92.6 [IC95 76.6–97.9; n=27] |
| language_acc | 40.0 [IC95 16.8–68.7; n=10] | 65.0 [IC95 43.3–81.9; n=20] | 66.7 [IC95 39.1–86.2; n=12] | 90.0 [IC95 59.6–98.2; n=10] | 100.0 [IC95 20.7–100.0; n=1] | 75.9 [IC95 63.1–85.4; n=54] | 84.6 [IC95 57.8–95.7; n=13] | — | — | 77.3 [IC95 56.6–89.9; n=22] | 73.2 [IC95 65.4–79.8; n=142] |
| tools_acc | 100.0 [IC95 43.9–100.0; n=3] | — | 50.0 [IC95 25.4–74.6; n=12] | 80.0 [IC95 49.0–94.3; n=10] | — | 66.7 [IC95 43.7–83.7; n=18] | 0.0 [IC95 0.0–49.0; n=4] | 60.0 [IC95 31.3–83.2; n=10] | 50.0 [IC95 15.0–85.0; n=4] | 25.0 [IC95 7.1–59.1; n=8] | 56.5 [IC95 44.8–67.6; n=69] |
| pending_action_acc | — | — | — | 80.0 [IC95 49.0–94.3; n=10] | — | — | — | 100.0 [IC95 34.2–100.0; n=2] | 50.0 [IC95 9.5–90.5; n=2] | — | 78.6 [IC95 52.4–92.4; n=14] |
| replanned_acc | — | 10.0 [IC95 2.8–30.1; n=20] | — | — | — | — | — | — | — | — | 10.0 [IC95 2.8–30.1; n=20] |
| no_leak_acc | — | — | — | — | — | — | — | — | 100.0 [IC95 51.0–100.0; n=4] | — | 100.0 [IC95 51.0–100.0; n=4] |
| numbers_acc | 100.0 [IC95 72.2–100.0; n=10] | 100.0 [IC95 83.9–100.0; n=20] | 100.0 [IC95 75.8–100.0; n=12] | 100.0 [IC95 72.2–100.0; n=10] | 100.0 [IC95 20.7–100.0; n=1] | 100.0 [IC95 93.4–100.0; n=54] | 84.6 [IC95 57.8–95.7; n=13] | 100.0 [IC95 91.6–100.0; n=42] | 100.0 [IC95 70.1–100.0; n=9] | 100.0 [IC95 86.2–100.0; n=24] | 99.0 [IC95 96.3–99.7; n=195] |
| language_undetected | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| recall@3 | — | — | — | — | — | — | — | — | — | — | — |
| mrr | — | — | — | — | — | — | — | — | — | — | — |
| p50_ms | 906.0 | 588.5 | 855.0 | 306.3 | 591.9 | 594.1 | 629.6 | 213.9 | 57.4 | 228.8 | 435.6 |
| p95_ms | 13355.9 | 1257.3 | 7329.2 | 817.2 | 591.9 | 2071.2 | 8628.4 | 515.4 | 423.9 | 639.7 | 1702.3 |
| cost_usd | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| crashes | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

Gate (splits approval, guardrail, human, memory, official, official-var, parallel, replan): intent 82.5% [IC95 75.7–87.7; n=154] (mínimo 90%) → **FAIL**. Medidos fora do gate: hard, heldout. Isolamento: `db_per_case`.

Falhas por checagem × split: blocked heldout 2 · handoff hard 1, heldout 3, parallel 1, replan 18 · handoff_outcome hard 1, heldout 3, parallel 1, replan 18 · intent approval 2, guardrail 4, hard 19, heldout 9, memory 5, official 1, official-var 9, parallel 6 · language approval 1, heldout 5, memory 2, official 6, official-var 13, parallel 4, replan 7 · numbers memory 2 · pending_action approval 2, guardrail 1 · replanned replan 18 · tools approval 2, guardrail 2, hard 4, heldout 6, memory 4, official-var 6, parallel 6
Confusão de intenção (esperada → obtida): blocked → knowledge 1, support 1 · general → knowledge 3, support 1 · human_request → knowledge 1 · knowledge → support 6, general 2, human_request 1, multi 2 · multi → general 3, knowledge 3, support 3, human_request 1 · support → knowledge 8, general 2, multi 2, troubleshoot 1 · troubleshoot → support 4, knowledge 10

Portão sem fonte: limiar efetivo 0.5 (MIN_SCORE) → responde 72.1% [IC95 60.4–81.3; n=68] dos com fonte, recusa 0.0% [IC95 0.0–17.6; n=18] dos sem fonte · recomendado 8.378 → responde 52.9% [IC95 41.2–64.3; n=68], recusa 88.9% [IC95 67.2–96.9; n=18] (68 com fonte, 18 sem; 0 sem fonte fora da conta por não chegarem ao agente de conhecimento; critério: max pos_answered com neg_refused >= 0.85; empate → menor limiar)

Retrieval ativo (bm25, `evals/retrieval.jsonl`): Recall@3 **0.57** · MRR **0.618** · hit@3 0.721 [IC95 60.4–81.3; n=68] (68 perguntas)
<!-- eval:end -->

### Ao vivo (LLM real, por split)

<!-- eval-live:begin -->
_Eval ao vivo não rodado (sem chave no relógio ou cortado). Ver Limitações._
<!-- eval-live:end -->

### Juiz LLM sobre as respostas ao vivo

<!-- judge:begin -->
_Juiz não rodado._
<!-- judge:end -->

### Replanejamento

<!-- replan:begin -->
| fonte | casos | replanned_acc | handoff_acc | handoff_outcome_acc | intent_acc |
|---|---:|---:|---:|---:|---:|
| offline | 20 | 10.0 [IC95 2.8–30.1; n=20] | 10.0 [IC95 2.8–30.1; n=20] | 10.0 [IC95 2.8–30.1; n=20] | 100.0 [IC95 83.9–100.0; n=20] |

- `replan-13` (offline): faq:no_source->escalation
- `replan-17` (offline): faq:no_source->escalation
<!-- replan:end -->

## 6. Spec e rastreabilidade

Spec em [docs/SPEC.md](docs/SPEC.md), commitada antes do código. ADRs em [docs/adr/](docs/adr/).

## 7. Linha do tempo (git log)

<!-- timeline:begin -->
| hora | min | commit |
|---|---:|---|
| 14:13:56 | 0 | chore: scaffold from entregar-desafio-cronometrado kit v3.6.0 |
| 14:23:03 | 9 | fork e: 25 casos de guardrail bloqueáveis (injeção direta/indireta, ofuscação, jailbreak, outro lojista, abuso) |
| 14:23:41 | 10 | fork b: CRM de 2 lojistas com datas relativas |
| 14:23:50 | 10 | fork c2: EVAL_STRATEGY (taxonomia, splits, gate, pass^k, Wilson, juiz TPR/TNR, produção) |
| 14:24:42 | 11 | fork d: esqueleto do README (rodar, arquitetura, fluxo, RAG, LLM, MCP, decisões, limitações) |
| 14:24:42 | 11 | fork c2: VIDEO_SCRIPT (14 cenas, números por chave, aviso de narração por IA) |
| 14:25:12 | 11 | fork o: router com general/troubleshoot e supervisor com NO_ESCALATION |
| 14:25:25 | 11 | fork b: 7 tools do lojista com dias úteis e risco |
| 14:25:34 | 12 | fork a2: corpus suporte (129 trechos literais site.getnet.com.br) |
| 14:25:56 | 12 | fork d: ARCHITECTURE com 3 diagramas mermaid (agentes, RAG, HITL) |
| 14:26:09 | 12 | fork a1: ingest BR + 69 trechos de produto |
| 14:26:57 | 13 | fork e: 10 cenários HTTP em demo/required e recusas de token (sem exp, expirado, alg none, iss/aud, revogado) |
| 14:27:04 | 13 | fork b: prompt records do lojista |
| 14:27:38 | 14 | fork c1: rascunho de casos e exemplos de intent |
| 14:27:39 | 14 | fork d: OBSERVABILITY (SLOs, métricas, painéis, alertas com limiar e ação, logs, traces) |
| 14:27:45 | 14 | fork o: prompts do domínio Getnet (papel, formato, recusa, citação, exemplos) |
| 14:27:57 | 14 | fork a1: 158 trechos (paginas de produto + blog BR) |
| 14:28:02 | 14 | spec: SPEC Getnet (IDs, 10 cenarios literais, taxonomia support x troubleshoot + general, tools congeladas), cases oficiais+replan 20+parallel+approval, heldout cego 24, ADR 0002/0003 |
| 14:28:14 | 14 | fork b: testes de contrato das tools (61) |
| 14:29:12 | 15 | fork c2: merge main (spec) |
| 14:29:14 | 15 | fork d: RUNBOOK (10 incidentes com confirmação e resposta) |
| 14:29:17 | 15 | fork a2: retrieval.d/a2 (28 com fonte, 15 negativos) e SOURCES_SUPORTE |
| 14:29:26 | 16 | fork a1: glossario pt-en (60) + 34 perguntas de retrieval |
| 14:29:33 | 16 | fork d: merge main (spec) |
| 14:29:34 | 16 | Merge branch 'main' into fork/a2 |
| 14:29:53 | 16 | fork c1: 97 casos (official-var, parallel, approval, memory, hard) |
| 14:30:04 | 16 | fork c1: merge main (spec) |
| 14:30:21 | 16 | fork e: 35 testes, um por controle do threat model (C-01..C-21) |
| 14:30:33 | 17 | fork e: merge main (spec) |
| 14:31:12 | 17 | fork d: README e ARCHITECTURE alinhados à SPEC (agentes faq/records, taxonomia, 6 tools) |
| 14:31:23 | 17 | fork c1: casos alinhados a SPEC (tools congeladas, support x troubleshoot) + hard extra |
| 14:31:25 | 17 | fork b: merge main (spec) |
| 14:31:58 | 18 | fork e: +9 casos de domínio (PII de terceiro, outro lojista cliente2024, fora de escopo, antecipação sem aprovação) = 34 |
| 14:32:06 | 18 | fork d: ADRs 0004-0007 (supervisor, RAG, checagem numérica, HITL) |
| 14:32:40 | 19 | fork d: ADRs só com afirmação sustentada por arquivo do repo |
| 14:32:51 | 19 | fork o: testes de domínio do router e do supervisor; chuva como conversa não vira general |
| 14:32:52 | 19 | fork a1: test_ingest + SOURCES.md + ruff |
| 14:33:09 | 19 | Merge branch 'main' into fork/o |
| 14:33:39 | 20 | Merge branch 'main' into fork/a1 |
| 14:33:49 | 20 | fork e: THREAT_MODEL STRIDE + OWASP LLM 2025, 22 controles com arquivo e teste |
| 14:33:59 | 20 | fork c1: extra pronto (+30 hard de parafrase e mistura de idiomas) |
| 14:36:17 | 22 | fork b: nomes congelados da SPEC (get_settlements, get_transactions, open_chargeback) |
| 14:36:17 | 22 | fork c2: 8 rótulos de web (4 positivos, 4 negativos) na calibração do juiz |
| 14:37:25 | 23 | fork a2: pronto |
| 14:37:46 | 24 | fork d: RUNBOOK rollback sem supor volume no compose |
| 14:38:45 | 25 | fork c1: reescreve 9 frases que repetiam 5 palavras do held-out/oficiais |
| 14:39:03 | 25 | fork e: extra pronto — carga 50 concorrentes (50/50 200; p50 15 s, p95 21 s offline) |
| 14:42:40 | 29 | fork d: ingestão descrita pelo ingest.py real do fork a1 |
| 14:44:28 | 31 | fork a1: pronto |
| 14:45:52 | 32 | fork d: links dos ADRs 0002/0004-0006 nas decisões; mermaid sem chaves duplas |
| 14:50:44 | 37 | fork o: intents da SPEC (knowledge/support), FALLBACK records->faq, general não captura produto Getnet, replan 20/20 |
| 14:51:30 | 38 | agents: Customer Support offline pelas tools da SPEC (suporte x troubleshoot, consulta antes de agir, contestacao so de aprovada) |
| 14:51:35 | 38 | merge fork/a1 |
| 14:51:43 | 38 | merge fork/a2 |
| 14:51:43 | 38 | fork b: pronto |
| 14:53:00 | 39 | fork d: merge main (onda 1) |
| 14:53:12 | 39 | fork c2: merge main |
| 14:53:52 | 40 | merge fork/o |
| 14:54:13 | 40 | merge fork/b |
| 14:54:27 | 41 | merge fork/c1 |
| 14:54:43 | 41 | merge fork/e |
| 14:54:55 | 41 | merge fork/c2 |
| 14:55:01 | 41 | merge fork/d |
| 14:57:12 | 43 | fork o: DEPENDS faq<-records (troubleshoot sequencial: faq lê o terminal) |
| 14:57:16 | 43 | fork o: pronto |
| 14:57:26 | 44 | fork e: pronto |
| 14:57:44 | 44 | fork c2: 42 rótulos humanos do juiz (rag 21, crm 11, web 8, handoff 2; 22 pos / 20 neg) |
| 14:58:33 | 45 | fork c2: pronto |
| 14:58:46 | 45 | onda 2: fork/o (DEPENDS faq<-records) integrado pelo maestro |
| 14:58:48 | 45 | fork c1: pronto (127 casos: 85 no gate + 42 hard; 52 exemplos de intent; check.py rodando apos este commit) |
| 14:58:50 | 45 | onda 2: fork/e (pronto) integrado pelo maestro |
| 14:59:38 | 46 | onda 3: fork/c2 (42 rótulos do juiz) integrado pelo maestro |
| 14:59:42 | 46 | onda 3: fork/c1 (pronto, 127 casos) integrado pelo maestro |
| 15:01:13 | 47 | onda 1: forks o, a1, a2, b, c1, e, c2, d integrados (posse OK); eval offline intent 82,5% (gate 90% FAIL), official 90%, heldout 62,5% |

Do primeiro ao último commit: **47 min**.
<!-- timeline:end -->

## 8. Scaffold declarado (kit) e o que foi feito no relógio

A infraestrutura genérica vem de um kit próprio, preparado antes do desafio e declarado no primeiro
commit (`chore: scaffold`):
- FastAPI, Docker, CI e lockfiles;
- runner de eval (offline, ao vivo por split com teto de US$, `--repeat` com pass^k, calibração do
  portão), checagem numérica e juiz calibrado (kappa, TPR/TNR);
- identidade JWT com expiração e revogação, operador com chave pessoal, rate limit compartilhado;
- memória com resumo rolante, fila humana com retomada imediata, aprovação de quatro olhos, SLA;
- supervisor que replaneja com agentes em paralelo, busca BM25/híbrida, guardrails com desofuscação;
- logs, métricas, alertas provisionados, custo, analytics e OpenTelemetry opcional.

**Por que um kit.** É a prática de engenharia de implantação (forward deployed): bibliotecas comuns e
automação do trabalho repetível, para o tempo do cliente ir para o problema dele (a16z, "Trading Margin
for Moat", 04/06/2025: "Build common software libraries" e "Build/buy tools to automate"). O que é
específico do desafio (spec, base de conhecimento, ferramentas do domínio, casos de avaliação, prompts,
regras do router e do supervisor) foi escrito no relógio. A medida, tirada do git:

<!-- kit:begin -->
| pasta | linhas do kit | + no relógio | − no relógio | arquivos do kit alterados |
|---|---:|---:|---:|---:|
| `.claude` | 84 | 0 | 0 | 0 |
| `.dockerignore` | 14 | 0 | 0 | 0 |
| `.env.example` | 28 | 0 | 0 | 0 |
| `.github` | 29 | 0 | 0 | 0 |
| `.gitignore` | 10 | 0 | 0 | 0 |
| `Dockerfile` | 48 | 0 | 0 | 0 |
| `ESTADO.md` | 0 | 5 | 0 | 0 |
| `Makefile` | 23 | 0 | 0 | 0 |
| `OWNERSHIP.json` | 63 | 0 | 0 | 0 |
| `README.md` | 137 | 168 | 33 | 1 |
| `data` | 34 | 59 | 7 | 1 |
| `data/crm` | 0 | 43 | 0 | 0 |
| `data/intent_examples.d` | 0 | 52 | 0 | 0 |
| `data/knowledge` | 0 | 288 | 0 | 0 |
| `docker-compose.yml` | 11 | 0 | 0 | 0 |
| `docs` | 32 | 854 | 16 | 1 |
| `docs/adr` | 20 | 136 | 0 | 0 |
| `evals` | 936 | 59 | 12 | 1 |
| `evals/cases.d` | 0 | 161 | 0 | 0 |
| `evals/judge_calibration.d` | 0 | 42 | 0 | 0 |
| `evals/results` | 0 | 21909 | 0 | 0 |
| `evals/retrieval.d` | 0 | 77 | 0 | 0 |
| `ops` | 55 | 0 | 0 | 0 |
| `pyproject.toml` | 44 | 0 | 0 | 0 |
| `requirements-dev.lock` | 248 | 0 | 0 | 0 |
| `requirements-hybrid.lock` | 278 | 0 | 0 | 0 |
| `requirements.lock` | 145 | 0 | 0 | 0 |
| `scripts` | 576 | 0 | 0 | 0 |
| `src/app` | 3474 | 799 | 84 | 11 |
| `tests` | 3433 | 934 | 0 | 0 |
| `tests/fixtures` | 49 | 0 | 0 | 0 |

Total: **9771** linhas do kit (commit `f0e500e`) e **25586** escritas no relógio (72% do total). Arquivos do kit alterados no relógio: 15.
<!-- kit:end -->

## 9. Limitações e próximos passos

| Limitação | Próximo passo |
|---|---|
| CRM fictício (lojistas `cliente1988` e `cliente2024`, datas relativas a hoje) | trocar `src/app/tools.py` por cliente HTTP da API real; o contrato das tools não muda |
| Rate limit, métricas e cache no processo/SQLite de um nó | Redis para limite e locks, Prometheus remoto, Postgres atrás de `Store` ([ADR 0002](docs/adr/0002-replicas-sqlite.md)) |
| Corpus é um retrato do site na data de coleta | reingestão agendada com diff por SHA-256 e alerta de página que sumiu |
| Held-out e rótulos humanos com um único autor | segundo rotulador e kappa entre humanos |
| Eval ao vivo cobre parte dos casos por custo | rodar o conjunto inteiro com `--repeat 3` no CI noturno com teto de US$ |
