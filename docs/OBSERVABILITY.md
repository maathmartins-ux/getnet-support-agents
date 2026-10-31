# Observabilidade

O que medir em produção, onde cada sinal nasce no código e o que fazer quando ele sai do normal.
Os sinais **existem** (métricas em `GET /metrics`, logs JSON no stdout, `GET /analytics`, regras em
`ops/alerts.yml` validadas por `tests/test_alerts.py`). Os **SLOs são metas de projeto**, não medidas:
os números medidos estão no README §5, gerados de `evals/results/`.

## 1. SLOs (metas)

| SLI | Como se mede | Meta (SLO) | Janela | Por que este número |
|---|---|---|---|---|
| Disponibilidade do `/chat` | respostas não-5xx / total | 99,5% | 30 dias | queda do LLM não conta como indisponibilidade: cai no determinístico |
| Latência do turno | p95 de `ms` em `GET /analytics` (`latency_ms.p95`) | ≤ 8 s com LLM; ≤ 300 ms offline | 1 dia | o turno com LLM faz várias chamadas de modelo em série; 8 s é o mesmo limiar do alerta `LatenciaAltaDoTurno` |
| Resolução automática | `resolution_rate` em `/analytics` (sem handoff, sem bloqueio, sem número sem base) | ≥ 60% | 7 dias | métrica de negócio: atendimento resolvido sem humano |
| Fidelidade numérica | `ungrounded_rate` em `/analytics` | ≤ 1% | 7 dias | número errado de liquidação ou tarifa é o erro mais caro do domínio |
| Escalonamento | `escalation_rate` em `/analytics` | ≤ 40% | 30 min | acima disso o corpus ou o portão estão errados (alerta `EscalonamentoAnormal`) |
| SLA humano | casos re-escalonados (`sla_escalations_total`) | 0 | 1 h | `SLA_HIGH_MIN` = 120 min, `SLA_NORMAL_MIN` = 480 min |
| Custo | `cost_usd_per_resolved` em `/analytics` e `llm_cost_usd_total` | ≤ US$ 5/h agregado | 1 h | teto do alerta `GastoPorHoraAlto` |

Orçamento de erro: 0,5% de 30 dias ≈ 3,6 h. Queimou metade em uma semana → congela mudança de prompt e de
modelo até voltar ao normal.

## 2. Métricas (`GET /metrics`, formato Prometheus)

| Família | Métricas | Onde nasce |
|---|---|---|
| Tráfego | `chat_requests_total{intent}`, `parallel_batches_total`, `mcp_calls_total` | `src/app/pipeline.py`, `src/app/supervisor.py`, `src/app/mcp_server.py` |
| Latência | `span_latency_ms_sum/count{span}` para `guardrails`, `router`, `agent`, `tool`, `llm`, `parallel`, `resume` | `src/app/observability.py::span` |
| Custo | `llm_cost_usd_total`, `llm_tokens_total`, `llm_unpriced_calls_total` (modelo fora da tabela de preço) | `src/app/observability.py::record_llm_usage` |
| Confiabilidade do LLM | `llm_errors_total`, `router_fallback_total`, `supervisor_fallback_total`, `rerank_fallback_total`, `guardrail_llm_unavailable_total` | `src/app/llm.py`, `src/app/router.py`, `src/app/supervisor.py`, `src/app/rag.py` |
| Orquestração | `replans_total`, `tool_calls_total`, `handoffs_total{reason}` | `src/app/supervisor.py`, `src/app/actions.py`, `src/app/pipeline.py` |
| Qualidade | `numeric_ungrounded_total`, `feedback_total{rating}` | `src/app/pipeline.py`, `src/app/api.py` |
| Segurança | `guardrail_blocks_total{reason}`, `poisoned_docs_dropped_total`, `auth_failures_total`, `operator_auth_failures_total`, `mcp_auth_failures_total`, `rate_limited_total`, `rate_limit_store_errors_total` | `src/app/guardrails.py`, `src/app/rag.py`, `src/app/auth.py` |
| HITL | `handoff_notifications_total`, `handoff_replies_total{channel}`, `handoff_resumed_total{engine}`, `sla_escalations_total`, `approvals_requested_total`, `approvals_decided_total`, `actions_expired_total` | `src/app/notify.py`, `src/app/api.py`, `src/app/resume.py`, `src/app/actions.py` |

`GET /analytics` (com `X-Operator-Token`) agrega do SQLite: `resolution_rate`, `escalation_rate`, `block_rate`,
`ungrounded_rate`, custo total, por request e por resolvido, `latency_ms` p50/p95/p99, 👍/👎 e `worst_intents`
(`src/app/analytics.py`).

## 3. Painéis

| Painel | Gráficos | Pergunta que responde |
|---|---|---|
| **Atendimento (negócio)** | resolução automática, escalonamento e bloqueio por hora; `by_intent`; 👍/👎 | o sistema está resolvendo o problema do lojista? |
| **Qualidade da resposta** | `numeric_ungrounded_total`, `replans_total` por motivo, intents piores, `poisoned_docs_dropped_total` | onde o conteúdo ou o prompt estão falhando? |
| **Latência e confiabilidade** | p95 por span (`router`, `agent`, `tool`, `llm`), `llm_errors_total`, fallbacks por papel | o provedor está saudável? quanto do tráfego está no determinístico? |
| **Custo** | US$ por hora, por request e por resolvido; tokens por papel; `llm_unpriced_calls_total` | quanto custa um atendimento resolvido? |
| **Fila humana** | casos abertos, idade do mais antigo, `handoff_replies_total` por canal, `sla_escalations_total`, aprovações pendentes | o operador está dando conta? |
| **Segurança** | bloqueios por motivo, falhas de auth por origem, 429 do rate limit | há ataque ou abuso em curso? |

## 4. Alertas (provisionados em `ops/alerts.yml`)

Cada alerta exige ação humana e tem histerese (`for:`) para não oscilar.

| Alerta | Limiar | Por quanto tempo | Severidade | Ação |
|---|---|---|---|---|
| `LatenciaAltaDoTurno` | média do span `agent` > 8.000 ms | 10 min | warning | ver `llm_errors_total` e o provedor; effort ou modelo menor no papel `agent` ([RUNBOOK §1](RUNBOOK.md)) |
| `ErrosDoProvedorLLM` | > 0,1 erro de LLM por segundo | 5 min | critical | status do provedor, cota (`rate_limited`) e chave (`auth`) ([RUNBOOK §2](RUNBOOK.md)) |
| `NumeroSemBase` | > 5 respostas com número sem base em 1 h | 15 min | warning | ler os traces `numeric_ungrounded`; corrigir fonte ou prompt; virar caso de eval ([RUNBOOK §3](RUNBOOK.md)) |
| `EscalonamentoAnormal` | handoffs / requests > 40% | 30 min | warning | `/analytics` → `worst_intents`; conferir corpus e portão ([RUNBOOK §4](RUNBOOK.md)) |
| `SLAVencido` | qualquer re-escalonamento por SLA em 1 h | 1 min | critical | abrir `/operator` e responder o caso de prioridade alta ([RUNBOOK §5](RUNBOOK.md)) |
| `ContadorDeLimiteIndisponivel` | qualquer erro do contador do rate limit em 5 min | 2 min | critical | volume do SQLite: disco, permissão, lock; o limite falha fechado (429) ([RUNBOOK §6](RUNBOOK.md)) |
| `GastoPorHoraAlto` | > US$ 5 em 1 h | 10 min | warning | custo por papel em `/metrics`; laço de tools (`MAX_STEPS`) ([RUNBOOK §7](RUNBOOK.md)) |

Propostos, **não provisionados** (dependem de dado que só existe com tráfego real): queda de `approval_rate` do
👍/👎 abaixo de 70% em 24 h; `poisoned_docs_dropped_total` > 0 depois de uma reingestão.

## 5. Logs estruturados

Uma linha JSON por evento no stdout (`src/app/observability.py::JsonFormatter`):

```json
{"ts": 1793456789.123, "level": "INFO", "msg": "span", "trace_id": "9f1c...", "span": "agent", "ms": 812.4, "agent": "knowledge", "status": "ok"}
```

- `trace_id` em toda linha (contextvar, propagado às threads dos agentes paralelos) e devolvido na resposta do
  `/chat`: o lojista que reclama manda o `trace_id` e o suporte acha o turno inteiro.
- Eventos com nome próprio: `numeric_ungrounded` (números), `unverified_identity` (modo demo),
  `poisoned_doc_dropped` (corpus), `resume_llm_failed`, `analytics_log_failed`.
- **Sem PII:** o texto chega ao log já mascarado pelo guardrail 1; `log_request` grava métricas do turno, não o
  conteúdo. O logger do `httpx` fica em WARNING porque a URL do Telegram carrega o token do bot.

## 6. Traces

- Sem dependência extra, cada `span()` vira uma linha de log com `span`, `ms` e o desfecho (ex.: status do agente),
  ligada pelo `trace_id`: dá para reconstruir a árvore do turno com um `grep`.
- Com `OTEL_EXPORTER=console|otlp` (extra `.[otel]`), os mesmos spans viram spans OpenTelemetry com o atributo
  `app.trace_id`, prontos para Jaeger, Tempo ou Honeycomb (`tests/test_otel.py`).
- Árvore típica: `guardrails` → (`router` ‖ guardrail 2) → `parallel` → `agent` (knowledge) ‖ `agent` (support →
  `tool` × n) → `llm` dentro de cada agente.

## 7. Qualidade contínua (eval em produção)

- **Gate no CI:** `python scripts/check.py` roda o eval offline com gate por split a cada push.
- **Ao vivo:** `scripts/live_eval.ps1` / `scripts/live_eval.sh` com teto de US$ e `--repeat` (pass^k).
- **Amostragem:** 👎 do lojista e todo `numeric_ungrounded` viram candidatos a caso de eval; o juiz calibrado
  (`evals/judge.py`) roda sobre a amostra. Estratégia completa em [EVAL_STRATEGY.md](EVAL_STRATEGY.md).
