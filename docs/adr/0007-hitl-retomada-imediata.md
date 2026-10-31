# ADR 0007 — Handoff com retomada imediata e quatro olhos nas ações de risco

**Status:** aceito (31/10/2026)

## Contexto
Feedback da v2: "a resposta humana não retoma o plano, aparece só no próximo turno"; operador com token
compartilhado; sem SLA.

## Decisão
- Ao responder um caso (`POST /handoffs/{id}/reply`, console `/operator` ou Telegram), `src/app/resume.py` redige
  na hora a próxima mensagem ao lojista a partir da resposta humana, que é a autoridade; sem LLM, entrega a
  resposta literal identificada. A mensagem passa pela máscara de PII e pela checagem numérica.
- Claim atômico: duas respostas simultâneas, só uma vence (`tests/test_hitl.py::test_two_simultaneous_replies_only_one_wins`).
- Operador com chave pessoal (`OPERATOR_KEYS`): a auditoria grava quem respondeu.
- Ação de risco alto (`request_anticipation`, `open_chargeback`): o dono confirma e um operador aprova; executa uma
  vez; a ação pendente expira em `ACTION_TTL_MIN`.
- SLA por prioridade (`SLA_HIGH_MIN`, `SLA_NORMAL_MIN`) com re-escalonamento único.

## Alternativas descartadas
- **Só ticket:** o ciclo não fecha; o lojista teria de voltar e perguntar de novo para ver a resposta humana.
- **Retomar o plano do supervisor inteiro:** o humano já resolveu; replanejar por cima da resposta dele arrisca
  contradizê-la.

## Consequências
O lojista vê a resposta sem escrever de novo (`GET /conversations/{id}`). O caminho multi-réplica do claim está no
ADR 0002.
