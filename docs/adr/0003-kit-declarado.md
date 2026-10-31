# ADR 0003 — Kit genérico declarado no primeiro commit; domínio feito no relógio

**Status:** aceito (31/10/2026, commit "spec")

## Contexto
O desafio tem 60 min. A infraestrutura genérica (FastAPI, auth, rate limit, memória, fila de handoff, supervisor por
tabela + LLM, RAG BM25/híbrido/rerank, guardrails, observabilidade, runner de eval com gate, juiz, CI, Docker) é a
mesma para qualquer sistema de agentes de suporte.

## Decisão
- O primeiro commit (`chore: scaffold from entregar-desafio-cronometrado kit v3.6.0`) é o kit, sem nenhum dado de
  domínio. Tudo o que é Getnet — SPEC, corpus, glossário, CRM, tools, regras do router, planos do supervisor,
  prompts, casos, held-out, calibração do juiz — é escrito depois de T+0 e aparece no `git log`.
- Os nomes de agente do kit (`faq`, `records`, `escalation`) ficam no contrato (`schemas.AgentName`): trocá-los
  com 8 forks em paralelo custaria a integração. A SPEC mapeia `faq` = Knowledge Agent e `records` = Customer
  Support Agent; respostas e documentação usam os nomes do enunciado.
- Trabalho paralelo em `git worktree` por fork, com posse de arquivos verificada antes de cada merge
  (`scripts/check_ownership.py`).

## Consequências
O avaliador separa o que é kit do que é desafio pelo `git log` e pelo diff a partir do primeiro commit.
