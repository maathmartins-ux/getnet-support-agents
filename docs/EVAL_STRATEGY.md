# Estratégia de avaliação

Como medimos se o sistema multiagente responde certo, de forma estável e sem inventar, e como isso
vira decisão: o CI barra a regressão, o juiz mede a fundamentação e a produção alerta antes do cliente.
Todo número citado no README sai de `evals/results/*.json`. Este documento não traz número: traz o método.

```text
            ┌────────────── offline (sem chave, determinístico) ──────────────┐
casos ──► run_evals ──► checagens por caso ──► métricas por split + IC de Wilson ──► GATE do CI
  │                                                                     │
  │         ┌──────────────── ao vivo (LLM real, teto em US$) ──────────┴───┐
  └──► run_evals --live --repeat 3 ──► pass@1, pass^3, instáveis ──► juiz (Opus) ──► grounded/helpful
                                                                         ▲
                                     rótulos humanos (judge_calibration*) ┘  TPR, TNR, κ: quanto confiar
```

## 1. Taxonomia: o que pode dar errado

Cada caso declara em `expect` o que precisa acontecer. Cada campo vira uma checagem independente
(`evals/run_evals.py::score`), e a matriz de falhas (`failure_matrix`) conta onde cada uma quebra, por
split. É a taxonomia de erros de Hamel Husain aplicada ao contrato: diz o que corrigir primeiro sem ler
caso a caso.

| Checagem | Pergunta que responde | Falha típica que pega |
|---|---|---|
| `intent` | o roteador escolheu o caminho certo? | pergunta de suporte tratada como FAQ; clima mandado ao RAG |
| `handoff` | escalou quando devia (e só quando devia)? | pedido explícito de humano ignorado; escalada à toa |
| `handoff_outcome` | os agentes obrigatórios foram chamados e nenhum proibido? | resposta certa pelo caminho errado (ver §6) |
| `tools` | as tools exigidas foram chamadas? | resposta de prazo de depósito sem consultar o CRM |
| `pending_action` | ação de risco ficou pendente de confirmação do dono? | antecipação executada sem "confirmo" |
| `replanned` | o supervisor desviou do plano quando a etapa falhou? | sem fonte → respondeu mesmo assim |
| `blocked` | o guardrail barrou injeção, PII de terceiro, fora de escopo? | jailbreak passa; pergunta legítima bloqueada |
| `language` | o TEXTO está no idioma da pergunta (não o campo declarado)? | pergunta em inglês respondida em português |
| `numbers` | todo número da resposta tem base em fonte, tool ou pergunta? | taxa ou prazo inventado (`app/grounding.py`) |
| `no_leak` | a resposta não vaza dado de outro lojista nem segredo? | `user_id` do modelo sobrescrevendo o do servidor |

Intents do domínio (definidas na SPEC): conhecimento de produto (RAG), suporte com dado do lojista
(CRM), solução de problema do terminal, pergunta geral com busca web (clima, câmbio), pedido de humano
e bloqueio. A regra de desempate suporte × solução de problema está na SPEC e tem casos dos dois lados.

## 2. Splits: cada conjunto responde uma pergunta diferente

| Split | Origem | Entra no gate? | Para que serve |
|---|---|---|---|
| `official` | os 10 cenários literais do enunciado | sim | o avaliador vai rodar exatamente estes |
| `replan` | etapa que falha de propósito (sem fonte, tool com erro, baixa confiança) | sim | prova que o supervisor replaneja, não só roteia |
| `approval` / `parallel` | ação de risco com confirmação; pergunta composta | sim | escrita segura e plano com dois agentes |
| casos dos forks (`cases.d/*.jsonl`) | pt/en, multi-turno (memória), guardrail | sim | cobertura da taxonomia |
| `hard` | paráfrase, mistura de idiomas, erro de digitação | **não** | mede o teto; gatear convidaria a decorar |
| `heldout` | escrito por autor cego (só enunciado + SPEC), commitado com a spec, nunca editado | **não** | estimativa honesta de generalização |

Regras que protegem o held-out:
- commitado no mesmo commit da SPEC, antes de qualquer código de domínio (o `git log` prova);
- nenhuma frase dele vira regra do roteador ou exemplo do k-NN: um teste de contaminação reprova;
- fica fora do gate (`UNGATED`): se gateado, o time ajustaria o sistema a ele e ele deixaria de medir.

A diferença entre a taxa nos splits gateados e no held-out é o indicador de sobreajuste. Diferença acima
de 10 pontos percentuais é tratada como defeito, não como ruído (com IC sobreposto, como ruído).

## 3. Gate do CI

- **Onde:** `scripts/check.py` (ruff → pytest → eval offline → build e smoke do container), no CI a cada push.
- **O quê:** acurácia de intent ≥ `EVAL_GATE` (0,9) nos splits gateados **e** zero crash.
- **Por que offline:** determinístico, sem chave e sem custo. O LLM real entra no ao vivo, que é evidência
  e não gate: um gate que depende de chave e de rede fica vermelho por motivo alheio ao código.
- **Isolamento:** cada caso (e cada repetição) roda num SQLite próprio; memória, tickets e ações não vazam
  entre casos. O relatório grava `isolation: db_per_case`.
- **Regra dura:** o gate nunca desce para fazer passar. Caso que falha fica publicado na matriz de falhas.

## 4. Confiabilidade: pass^k, não só pass@1

Agente de atendimento precisa acertar sempre, não em média. Ao vivo, cada caso roda 3 vezes (`--repeat 3`):

- **pass@1** = fração das execuções que passam (média por tentativa);
- **pass^3** = fração dos casos que passam nas três (Anthropic, "Demystifying evals for AI agents",
  09/01/2026: 75% por tentativa dá pass^3 ≈ 42%);
- **instáveis** = casos que passam às vezes. São a fila de correção: instabilidade é defeito de prompt,
  de schema ou de regra, nunca "azar do modelo" (os modelos 5.5 não têm `temperature`; a estabilidade vem
  de schema estrito, enum e código determinístico).

## 5. Incerteza: n e IC de Wilson em toda taxa

Toda taxa sai com `k`, `n` e intervalo de confiança de Wilson a 95% (`rate_ci`). Wilson e não a
aproximação normal porque, com n pequeno e taxa perto de 0% ou 100% (o caso típico de eval), o intervalo
normal sai de [0, 1] ou colapsa em largura zero.

Leitura prática:
- duas versões só são "diferentes" quando os intervalos não se sobrepõem, ou com teste pareado nos mesmos
  casos (McNemar);
- "100% em 10 casos" tem IC de cerca de 72–100%: é promissor, não é prova;
- pass@1 conta execuções repetidas do mesmo caso, que não são independentes, então o IC dele sai otimista;
  o IC de pass^k conta casos e é o honesto.

## 6. Handoff por desfecho

A checagem antiga (`handoff`) olha um flag. A nova (`handoff_outcome`) olha o caminho: os agentes
obrigatórios estão contidos nos agentes chamados e nenhum proibido foi chamado. As duas são publicadas
lado a lado, sem trocar uma pela outra, para que a melhora seja comparável com a versão anterior.

Exemplos:
- "quero falar com um atendente" → `escalation` obrigatório;
- "qual a previsão do tempo em Porto Alegre?" → `escalation` proibido (resposta honesta sem escalar);
- pergunta sem fonte no corpus → `knowledge` e depois `escalation` (o replanejamento aparece no caminho).

## 7. Juiz LLM calibrado contra rótulos humanos

**O que julga:** `grounded` (toda afirmação está nas fontes ou nos dados de ferramenta, ou a resposta só
encaminha, pede dado ou recusa) e `helpful` (atende à pergunta), com nota de 1 a 5 e motivo. Modelo: Opus
5.5, papel `judge` (`evals/judge.py`), com teto em US$ por execução.

**O que o juiz vê:** a pergunta, os trechos do RAG pelo id, as fontes web (título e URL), as tools chamadas
com argumentos e, quando o contrato traz, o texto da evidência (resultado da tool). Na tentativa anterior o
juiz só via os trechos do RAG e marcou 46 de 47 respostas como "não fundamentadas", porque elas usavam dado do
CRM ou da web. Daí a regra: **dado de ferramenta é fonte**. Cada veredito grava `saw_tool_data` e
`saw_tool_results`; "não grounded" sem esses dados é cegueira do juiz, não alucinação do agente.

**Calibração antes de usar a nota.** O juiz julga primeiro os rótulos humanos de
`evals/judge_calibration.jsonl` + `evals/judge_calibration.d/*.jsonl` e só depois as respostas ao vivo. O
relatório publica:

| Medida | Por que |
|---|---|
| concordância bruta | leitura direta, mas engana com classes desbalanceadas |
| κ de Cohen | desconta a concordância por acaso |
| **TPR** (acerto nos grounded) e **TNR** (acerto nos não grounded), com IC | juiz que aprova tudo tem concordância alta e TNR baixo; só TPR/TNR mostram |
| `misses` | ids que o juiz errou: a fila para melhorar o prompt do juiz |

**Composição dos rótulos** (`judge_calibration.d/c2.jsonl`, autor: fork C2, a partir de respostas reais
do sistema offline): positivos e negativos equilibrados, cobrindo os três tipos de evidência que o juiz
precisa ler — trechos do RAG, dados do CRM (tools do lojista) e fontes web. Os negativos são os erros que
importam no atendimento: número trocado (prazo, taxa, valor), afirmação além da fonte, dado do CRM de
outro dia ou de outra transação, promessa sem base ("o dinheiro cai hoje"), e resposta que ignora a tool
que falhou. Os positivos incluem encaminhamento, pedido de dado e recusa, que são fundamentados por
definição.

**Limiar de confiança:** a nota do juiz só entra no README como métrica se TPR e TNR ≥ 0,8 na calibração.
Abaixo disso, o juiz é publicado como "não confiável" com os `misses`, e a correção é no prompt do juiz,
nunca nos rótulos.

**Limite declarado:** os rótulos têm um único autor humano. Em produção, dois rotuladores independentes em
uma amostra comum, com κ entre eles, mediriam o teto de concordância possível.

## 8. RAG medido separado do roteador

`evals/retrieval.jsonl` + `retrieval.d/*.jsonl`: perguntas rotuladas olhando a fonte, com os ids relevantes.
Mede Recall@3, MRR e hit@3 (com IC) do retriever sozinho, sem o roteador no meio, e compara BM25, BM25 +
rerank do top-20 (Haiku) e híbrido (`--compare-retrievers --rerank`). Os negativos (`relevant: []`) calibram
o portão "sem fonte" (`--calibrate-gate`): o limiar escolhido é o que mais responde com fonte mantendo a
recusa dos sem fonte ≥ 85%, e o limiar efetivo é gravado no relatório.

## 9. Monitoramento em produção

O eval offline protege contra regressão de código; a produção pega o que o eval não previu. Sinais (já
expostos em `/metrics` e no log JSON com `trace_id`):

| Sinal | Fonte | Alerta (com histerese: 2 janelas seguidas) | Ação |
|---|---|---|---|
| taxa de escalonamento para humano | contador de handoff / requests | > 2× a média de 7 dias | ver intents que mais escalam; corpus sem fonte? |
| recusa do portão "sem fonte" | contador do portão | +50% sobre 7 dias | pergunta nova sem documento → ingestão |
| erro de tool / provedor LLM | `llm_errors_total`, erro por tool | > 5% em 10 min | fallback determinístico já assume; abrir incidente |
| p95 de latência por turno | histograma | > SLO do OBSERVABILITY.md | ver qual etapa (span) cresceu |
| custo por request | `usage.cost_usd` | > 2× o medido no eval ao vivo | prompt cresceu? laço do supervisor? |
| bloqueios do guardrail | contador por motivo | pico de injeção | revisar logs (PII já mascarada) |
| `unsupported_numbers` > 0 | grounding na resposta | qualquer ocorrência sobe amostra | amostra para revisão humana |

**Amostragem com o juiz em produção:** 2% das conversas por dia (todas as escaladas e todas com
`unsupported_numbers`), julgadas pelo juiz calibrado. Queda de `grounded_rate` fora do IC da semana anterior
abre investigação. As conversas que o juiz reprova e um humano confirma viram casos novos no eval
(`cases.d/`), fechando o ciclo produção → eval.

## 10. Como aprovar uma mudança de prompt (ou de modelo)

1. **Hipótese escrita** no PR: qual falha da matriz a mudança corrige.
2. **Offline:** `scripts/check.py` verde (gate ≥ 0,9, zero crash). Nenhum split gateado pode cair.
3. **Ao vivo, pareado:** `run_evals --live --repeat 3 --max-usd <teto>` antes e depois, nos mesmos casos.
   Critério: pass^3 não cai; os instáveis não aumentam; a falha-alvo some.
4. **Juiz:** `grounded_rate` e `helpful_rate` não caem além do IC; a calibração do juiz não mudou (se mudou
   o prompt do juiz, refaz TPR/TNR primeiro).
5. **Held-out:** olhado só no fim, uma vez. Se o held-out cai enquanto os gateados sobem, a mudança decorou
   os casos: rejeita.
6. **Custo e latência:** p95 e US$/request dentro de 20% do anterior, ou a melhora justifica no PR.
7. **Produção:** canário em 5% do tráfego por 24 h com os alertas do §9; promove se nenhum disparar.

Mudança aprovada vira commit pequeno com o relatório antes/depois anexado (`evals/results/*.json`).
