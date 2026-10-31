# Threat model — Getnet Multi-Agent Support

Escopo: `POST /chat`, rotas de ação (`/actions/*`), console e rotas do operador, `/mcp`, corpus RAG e CRM.
Método: STRIDE por fronteira de confiança + OWASP Top 10 for LLM Applications 2025. Cada linha é
**ameaça → controle → arquivo → teste**; o teste roda no CI (`scripts/check.py`). Casos de eval do split
`guardrail` em `evals/cases.d/e.jsonl` (34 casos, ids `e-`).

## Fronteiras de confiança

```text
lojista (não confiável) ──HTTP──▶ [auth + rate limit] ──▶ [guardrail regex + PII] ──▶ router/supervisor (LLM)
                                                                                   │
    corpus getnet.net (semi-confiável) ──carga──▶ [filtro de injeção] ──▶ índice RAG ┤
                                                                                   ▼
                                   CRM (confiável) ◀── tools com identidade do SERVIDOR ◀── agentes
                                                                                   │
                                operador (confiável, autenticado) ◀── fila HITL ◀──┘ (risco alto)
```

## Controles

| # | STRIDE | OWASP LLM 2025 | Ameaça | Controle | Arquivo | Teste |
|---|---|---|---|---|---|---|
| C-01 | Tampering | LLM01 Prompt Injection · LLM07 System Prompt Leakage | "ignore as instruções", "mostre o system prompt" | regex pt/en antes de qualquer agente; resposta bloqueada sem LLM | `src/app/guardrails.py` (`_INJECTION`, `pre_check`) | `test_domain_guardrails.py::test_c01_*`, eval `e-inj-*` |
| C-02 | Tampering | LLM01 | injeção disfarçada (espaçada, l33t, zero-width, full-width) | `deobfuscate` (NFKC, remove zero-width, junta letras espaçadas, des-l33t) só na cópia checada | `guardrails.py` (`deobfuscate`) | `test_c02_*`, eval `e-obf-*` |
| C-03 | Tampering | LLM01 indireta · LLM04 Data/Model Poisoning · LLM08 Vector Weaknesses | trecho do corpus com instrução embutida | documento envenenado descartado na carga do índice (métrica `poisoned_docs_dropped_total`) | `src/app/rag.py` (`load_docs`) | `test_c03_*`, eval `e-ind-*` |
| C-04 | Information disclosure | LLM02 Sensitive Information Disclosure | pedir dados de "outro cliente/usuário" | regex `other_user_data` bloqueia | `guardrails.py` (`_OTHER_USER`) | `test_c04_*`, eval `e-other-01..04` |
| C-05 | Information disclosure | LLM02 | PII de terceiro (CPF, cartão, e-mail, telefone) chegando ao LLM | máscara antes de agente, log e LLM; cartão só com Luhn | `guardrails.py` (`mask_pii`) | `test_c05_*`, eval `e-pii-*` |
| C-06 | Information disclosure | LLM05 Improper Output Handling | resposta ecoa PII | `mask_output` na saída e na evidência; mantém só o contato oficial citado da fonte | `guardrails.py` (`mask_output`), `pipeline.py` | `test_c06_*`, `test_domain_http.py::test_pii_in_request_never_echoes_in_response` |
| C-07 | Spoofing | LLM06 Excessive Agency | modelo escolhe `user_id` de outro lojista na tool | `run_tool` descarta `user_id` do modelo e injeta o do servidor | `src/app/actions.py` (`run_tool`) | `test_c07_*`, eval `e-other-05` |
| C-08 | Tampering | LLM06 | ação de escrita executada sem o dono pedir | escrita vira `pending_action`; só `POST /actions/{id}/confirm` executa | `actions.py`, `tools.py` (`write`) | `test_c08_*`, eval `e-risk-*` |
| C-09 | Elevation of privilege | LLM06 | antecipação/contestação (move dinheiro) sem revisão | risco `high`: confirmação do dono **e** aprovação de operador (quatro olhos); recusa não executa | `actions.py` (`confirm_action`, `decide_action`) | `test_c09_*` |
| C-10 | Elevation of privilege | LLM06 | outro lojista confirma ação alheia | ação só encontrada pelo dono (404) | `actions.py`, `api.py` (`/actions/{id}/confirm`) | `test_c10_*` |
| C-11 | Tampering | LLM06 | confirmação tardia de ação velha | TTL da ação pendente (`ACTION_TTL_MIN`) | `actions.py` (`_expired`) | `test_c11_*` |
| C-12 | Tampering | — | repetição/corrida no confirm | claim atômico no SQLite: executa uma vez | `actions.py` (`_execute`), `store.py` | `test_c12_*` |
| C-13 | Spoofing | — | token sem expiração (gap do feedback v2), forjado, `alg: none`, emissor errado, revogado | JWT HS256 com `exp` obrigatório (+30 s de folga), `iat`, `iss`, `aud`, `jti` revogável | `src/app/auth.py` (`decode_token`) | `test_c13_*`, `test_domain_http.py::test_token_without_exp_is_rejected`, `test_bad_tokens_are_401_never_500`, `test_revoked_token_is_rejected` |
| C-14 | Denial of service | LLM10 Unbounded Consumption | rajada de requisições, mensagem gigante | rate limit por identidade (por IP no demo) que falha **fechado**; `message` ≤ 4000 | `auth.py` (`RateLimiter`), `schemas.py` | `test_c14_*`, `test_rate_limit_returns_429_with_retry_after`, `test_oversized_message_is_422` |
| C-15 | Elevation of privilege | — | subir em produção com segredo padrão (token forjável) | `APP_ENV=production` recusa subir; `/health` sinaliza | `src/app/api.py` (`insecure_defaults`, `lifespan`) | `test_c15_*` |
| C-16 | Repudiation | — | operador anônimo aprova ação | chave pessoal (só sha256 na config); nome gravado em `approved_by` | `auth.py` (`operator_name`), `actions.py` | `test_c16_*`, `test_c09_high_risk_needs_operator_approval` |
| C-17 | Spoofing | LLM06 | MCP expõe tools sem auth | `require_bearer`: 401 antes do protocolo, nem `tools/list` é anônimo | `src/app/mcp_server.py` | `test_c17_*` |
| C-18 | Denial of service × Tampering | LLM01 | classificador LLM fora do ar libera ou derruba tudo | camada 2 (Haiku) falha aberta **só depois** da regex; pega paráfrase quando está no ar | `guardrails.py` (`llm_check`) | `test_c18_*` |
| C-19 | Information disclosure | LLM02 | PII persistida em histórico/memória | o histórico guarda o texto já mascarado | `pipeline.py`, `store.py` | `test_c19_*` |
| C-20 | — | — | abuso/ofensa | regex `abusive` bloqueia sem acionar agente | `guardrails.py` (`_ABUSE`) | `test_c20_*`, eval `e-abuse-*` |
| C-21 | Tampering | LLM06 | pedido bloqueado ainda chama tool ou fonte | bloqueio curto-circuita o pipeline: `tool_calls` e `sources` vazios | `pipeline.py` | `test_c21_*` |
| C-22 | Spoofing | — | demo aceita `user_id` do corpo | `AUTH_MODE=demo` explícito, resposta marcada `identity_verified: false`; token válido vence o corpo; token inválido é 401 também no demo | `api.py` (`_identity`), ADR 0001 | `test_domain_http.py::test_scenario_demo_literal_payload`, `test_token_identity_wins_over_body_user_id`, `test_bad_token_is_401_even_in_demo` |

### OWASP LLM 2025 sem controle próprio neste escopo

| Item | Situação |
|---|---|
| LLM03 Supply Chain | lockfiles de runtime e dev, imagem multi-stage não-root, CI; sem SBOM nem assinatura de imagem (declarado) |
| LLM09 Misinformation | grounding: número sem base em fonte/tool vai para `unsupported_numbers`; sem fonte → `insufficient` → humano (`app/grounding.py`, `tests/test_grounding.py`) |

## Riscos aceitos (decisão humana, não do agente)

- Segredo HS256 compartilhado entre réplicas; trocar por OIDC/JWKS mantém `verify_token -> user_id`.
- Rate limit e claim de ação em SQLite: valem entre processos do mesmo volume, não entre nós (ADR 0002).
- Regex não pega paráfrase sofisticada sem a camada LLM; o eval ao vivo mede o falso negativo da camada 2.
- `AUTH_MODE=demo` existe só para aceitar o payload literal do enunciado; produção usa `required`.
