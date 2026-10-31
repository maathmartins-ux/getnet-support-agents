# ADR 0004 — Supervisor LLM com agentes como tools, tabela determinística como fallback

**Status:** aceito (31/10/2026)

## Contexto
O enunciado pede que o Router "gerencie o fluxo e os dados entre agentes". Plano fixo por intent não reage quando
um agente falha (sem fonte, tool com erro): o feedback da v2 pediu um supervisor que observa o resultado e replaneja.

## Decisão
- `src/app/supervisor.py` tem dois motores com a mesma saída (`Outcome`):
  - **llm**: Sonnet 5.5, effort low, loop manual de tool use; os especialistas são tools `strict`
    (`faq_agent`, `records_agent`, `escalation_agent`) e o modelo lê o `status` de cada um;
  - **table**: o mesmo laço com `PLANS`, `FALLBACK`, `ALLOWED` e `MAX_STEPS = 4`.
- Transição pedida pelo modelo fora de `ALLOWED` é recusada (`tests/test_supervisor.py::test_llm_disallowed_transition_is_refused`).
- Qualquer `LLMError` cai na tabela; o CI roda só a tabela.

## Alternativas descartadas
- **Só LLM:** CI dependente de chave e sem rede de segurança quando o provedor cai.
- **Só tabela:** não generaliza para combinações que a tabela não previu. A comparação offline × ao vivo do
  split `replan` está no README §5 (bloco Replanejamento, gerado de `evals/results/`).

## Consequências
Dois caminhos para manter em sincronia; os casos do split `replan` medem os dois.
