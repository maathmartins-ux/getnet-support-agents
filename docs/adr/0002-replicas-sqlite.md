# ADR 0002 — Estado em SQLite de um nó; réplicas fora do escopo

**Status:** aceito (31/10/2026, commit "spec")

## Contexto
Memória de conversa, resumo do lojista, fila de handoff e ações pendentes vivem em `store.py` (SQLite WAL, volume
no Compose). O feedback da v2 apontou "SQLite em um nó, sem estratégia testada para réplicas" e "lock da confirmação
em processo".

## Decisão
Manter SQLite de um nó no desafio. O contrato de persistência fica atrás de `store.Store`, então trocar o backend
não toca agentes nem API.

## Caminho para réplicas (não implementado, ordem de execução)
1. `Store` em PostgreSQL (mesmas tabelas; `SELECT ... FOR UPDATE` na confirmação de ação, que hoje é lock em processo).
2. Rate limit e idempotência da confirmação em Redis (`SET NX` com TTL), em vez de memória do processo.
3. Fila de handoff com `status` + `claimed_by` e `UPDATE ... WHERE status='open'` atômico.
4. Teste: dois processos uvicorn contra o mesmo banco confirmando a mesma ação → exatamente uma execução.

## Consequências
Uma réplica só. Escala vertical até a casa de dezenas de RPS (o gargalo é a latência do LLM, não o banco).
