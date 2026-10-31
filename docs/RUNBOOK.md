# Runbook

Incidentes comuns, como confirmar e como responder. Cada seção corresponde a um alerta de `ops/alerts.yml`
(ver [OBSERVABILITY.md §4](OBSERVABILITY.md)). Comandos supõem o compose do repositório (`docker compose`).

**Primeiros 2 minutos, qualquer incidente:**
1. `curl -s localhost:8000/health` → `mode`, `auth_mode`, `retriever` efetivo, `insecure_defaults`, `data_files`.
2. `curl -s localhost:8000/metrics | grep -E "errors|fallback|ungrounded|handoffs"`.
3. `docker compose logs --since 15m api | grep '"level": "WARNING"'` e pegue um `trace_id`.
4. `docker compose logs api | grep <trace_id>` reconstrói o turno inteiro (spans `router`, `agent`, `tool`, `llm`).

## 1. Latência alta (`LatenciaAltaDoTurno`)

- **Confirmar:** `span_latency_ms_sum/count` por span em `/metrics`; `latency_ms.p95` em `/analytics`.
- **Causas prováveis:** provedor lento; laço de tools perto de `MAX_STEPS`; rerank em toda busca.
- **Responder:**
  - span `llm` dominante → baixe o effort do papel (`AGENT_EFFORT=low`) ou o modelo (`AGENT_MODEL`) e reinicie;
  - `replans_total` subindo junto → é qualidade, não infraestrutura: ver §4;
  - último recurso: `RERANK=off` (perde ordem do top-3, mede-se o efeito em `--compare-retrievers --rerank`).

## 2. Provedor de LLM com erro (`ErrosDoProvedorLLM`)

- **Confirmar:** `llm_errors_total{kind=...}` em `/metrics`.
- **O que o sistema já faz:** router, supervisor, agentes e retomada caem no caminho determinístico; o
  atendimento continua (`engine` na resposta indica `table`/determinístico).
- **Responder por `kind`:**
  - `rate_limited` → cota da conta; reduza tráfego ao vivo ou peça aumento;
  - `auth` → chave revogada ou errada: troque `ANTHROPIC_API_KEY` no `.env` e `docker compose up -d`;
  - `api_status` / `connection` → status do provedor; nada a fazer além de esperar, o fallback segura;
  - `config` → modelo inexistente em `*_MODEL`; volte ao padrão de `src/app/config.py`.

## 3. Número sem base (`NumeroSemBase`)

- **Confirmar:** `grep numeric_ungrounded` nos logs → `trace_id` e os números sinalizados.
- **Responder:** abra o turno; se o número está certo e a fonte mudou, reingira o corpus (`src/app/ingest.py`);
  se o modelo inventou, ajuste o prompt do agente; **sempre** transforme o caso em linha de `evals/cases.d/` para
  o gate pegar a regressão.

## 4. Escalonamento anormal (`EscalonamentoAnormal`)

- **Confirmar:** `GET /analytics` (com `X-Operator-Token`) → `worst_intents` e `escalation_rate`.
- **Causas prováveis:** página nova no site que o corpus não tem; limiar do portão alto demais; tool do CRM
  devolvendo `error`.
- **Responder:** `handoffs_total{reason}` diz o motivo, no formato `<agente>_<motivo>` (`src/app/supervisor.py`). `*_no_source` ou `*_not_in_sources` → reingestão ou ajuste do corpus e
  `python -m evals.run_evals --calibrate-gate` para recalibrar `COVERAGE_MIN_SCORE` (nunca baixe o limiar à mão);
  `*_error` ou `*_tool_loop_limit` → ver §8; `low_confidence` → router (casos de `data/intent_examples.d/`).

## 5. SLA humano vencido (`SLAVencido`)

- **Confirmar:** `GET /handoffs` (fila aberta, mais antigo primeiro); `sla_escalations_total`.
- **Responder:** abra `/operator`, responda o caso de prioridade alta. O re-escalonamento acontece **uma vez** por
  caso (`POST /handoffs/sla-check`); se a fila cresce, acione mais operadores (`OPERATOR_KEYS` com chave pessoal).

## 6. Rate limit indisponível (`ContadorDeLimiteIndisponivel`)

- **Efeito:** o limite **falha fechado**: clientes recebem 429. É de propósito (sem contador, sem proteção).
- **Responder:** `docker compose exec api df -h /app/var` (disco cheio?), permissão do volume, outro processo
  segurando lock do SQLite. Corrigido o volume, o contador volta sem reinício.

## 7. Gasto alto (`GastoPorHoraAlto`)

- **Confirmar:** `llm_cost_usd_total` e `llm_tokens_total` por modelo em `/metrics`; `cost_usd_per_resolved` em
  `/analytics`.
- **Causas prováveis:** laço de tools batendo em `MAX_STEPS`; tráfego anômalo (ver bloqueios e 429);
  `llm_unpriced_calls_total` > 0 (modelo fora da tabela de preço: o custo está sendo subcontado).
- **Responder:** identifique o papel caro; troque o modelo do papel; se for abuso, baixe `RATE_LIMIT_PER_MIN`.

## 8. Ferramenta do CRM falhando

- **Sintoma:** `handoffs_total{reason}` com `*_error` sobe; respostas de support caindo no humano.
- **Responder:** `docker compose logs api | grep '"span": "tool"'`; dado do lojista inexistente devolve
  `not_found` (esperado); erro de outro tipo é bug: reproduza com um teste em `tests/test_tools.py` antes de corrigir.

## 9. Suspeita de injeção ou vazamento

- **Sintoma:** `guardrail_blocks_total` em rajada; `poisoned_docs_dropped_total` > 0 depois de reingestão;
  `auth_failures_total` concentrado.
- **Responder:** trecho envenenado já fica fora do índice; remova-o do JSONL e investigue a origem. Token suspeito:
  `POST /auth/revoke` (revogação por `jti`). Segredo exposto: troque `AUTH_SECRET` (invalida todos os tokens) e
  `OPERATOR_KEYS`. Modelo de ameaças: [THREAT_MODEL.md](THREAT_MODEL.md).

## 10. Deploy e rollback

- **Deploy:** `python scripts/check.py --docker` verde → `docker compose up -d --build` → `curl /health`
  (`data_files` > 0) → um `/chat` de fumaça.
- **Rollback:** `git checkout <tag anterior> && docker compose up -d --build`. O SQLite fica em `/app/var/app.db` dentro do container: para o histórico sobreviver a `docker compose down`, monte um volume em `/app/var` (o compose do desafio não monta; ver README §9).
- **Mudança de prompt ou modelo** é deploy: passa pelo gate do eval antes, nunca direto em produção.
