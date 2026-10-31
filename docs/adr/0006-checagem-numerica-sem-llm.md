# ADR 0006 — Todo número da resposta conferido sem LLM

**Status:** aceito (31/10/2026)

## Contexto
No domínio de um lojista, o erro mais caro é um número: data de depósito, valor a receber, tarifa, número de
parcelas. Um juiz LLM em todo turno custaria dinheiro e latência e ainda erraria às vezes.

## Decisão
`src/app/grounding.py::unsupported_numbers` extrai os números da resposta (com leituras pt/en de decimal e data)
e confere cada um contra a evidência do turno: trechos citados, retorno das tools, templates do sistema, a pergunta
e falas anteriores do cliente. Número sem base vai para `unsupported_numbers` na resposta, para o log
(`numeric_ungrounded`) e para a métrica `numeric_ungrounded_total`, com alerta `NumeroSemBase`.

## Alternativas descartadas
- **Juiz LLM em todo turno:** custo e latência; o juiz calibrado fica no eval.
- **Bloquear a resposta:** um falso positivo derrubaria resposta correta; sinalizar e medir é o passo seguro.

## Consequências
Roda em 100% dos turnos, de graça. Formatos de número fora das leituras previstas podem gerar falso positivo; cada
um vira caso de teste em `tests/test_grounding.py`.
