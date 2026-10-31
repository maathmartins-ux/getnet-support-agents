# Roteiro do vídeo (≈ 5,5 min, 14 cenas)

> **Aviso obrigatório (capa e primeira frase):** a narração foi gerada por IA a partir do meu roteiro;
> as telas, as respostas e os números são reais.

Regras deste roteiro:
- Nenhum número escrito à mão. Todo número aparece como `{chave}` e é preenchido pelo fork V a partir do
  arquivo indicado na tabela do fim. Chave sem arquivo na hora da gravação vira a frase "não medido".
- Na fala, número e sigla vão por extenso ("noventa e um por cento", "á-pê-í"); no slide e na legenda, a
  forma escrita ("91%", "API").
- Cada cena diz o ponto fraco junto com o forte, com o número.
- ≈ 950 palavras de narração (a voz faz ~176 palavras por minuto).

---

### Cena 1 — Capa (0:00–0:15)
**Tela:** título "Sistema multiagente de atendimento Getnet", nome, data, link do repositório, selo
"narração por IA; telas e números reais".
**Fala:** "A narração deste vídeo foi gerada por IA a partir do meu roteiro; as telas, as respostas e os
números são reais. Eu sou o Matheus, e vou mostrar como construí um sistema de atendimento com agentes
para a Getnet, e como medi se ele funciona."

### Cena 2 — O problema e o contrato (0:15–0:35)
**Tela:** o payload `{"message", "user_id"}` e os 10 cenários do enunciado, agrupados em quatro cores:
produto, dado do lojista, problema no terminal, pergunta geral.
**Fala:** "O enunciado pede um ponto de entrada HTTP que recebe uma mensagem e um identificador de
lojista. As dez perguntas de exemplo misturam quatro coisas diferentes: produto, dado do próprio lojista,
problema na maquininha e pergunta geral, como clima e câmbio. Cada uma pede um agente diferente."

### Cena 3 — Processo e relógio (0:35–0:55)
**Tela:** linha do tempo do `git log` (spec → g1 → ondas → g3), `{git.minutes}` minutos, `{git.forks}`
forks em worktrees. Nota: "infraestrutura genérica de um kit próprio, declarada no primeiro commit".
**Fala:** "Trabalhei contra o relógio: {git.minutes} minutos do primeiro ao último commit, com
{git.forks} frentes paralelas, cada uma num worktree do git com posse de arquivos verificada antes do
merge. A infraestrutura genérica veio de um kit meu, declarado no primeiro commit; o domínio Getnet foi
escrito dentro do relógio."

### Cena 4 — Arquitetura (0:55–1:30)
**Tela:** diagrama mermaid LR: guardrail → memória → Router (Haiku) → Supervisor (Sonnet) →
knowledge | support | escalation → máscara de PII.
**Fala:** "A mensagem passa primeiro por um guardrail em duas camadas e recebe o histórico da conversa.
O roteador, um modelo pequeno com saída em esquema estrito, decide a intenção e o plano. O supervisor
executa o plano chamando os especialistas como ferramentas: conhecimento, suporte e escalonamento. Cada
especialista devolve ok, insuficiente ou erro, e o supervisor replaneja dentro de uma tabela de transições
permitidas, com no máximo {code.max_steps} passos. Se o provedor de modelo cair, a mesma tabela roda de forma
determinística."

### Cena 5 — RAG (1:30–2:00)
**Tela:** pipeline ingestão → trechos literais → BM25 → rerank → portão "sem fonte" → resposta com
citação. Números: `{retrieval.recall_at_3}` sem rerank, `{retrieval.recall_at_3_rerank}` com rerank.
**Fala:** "O conhecimento vem de páginas brasileiras da Getnet, guardadas como trechos literais com URL,
data e hash. A busca é BM25 com glossário português-inglês, e um modelo pequeno reordena os {code.rerank_top}
primeiros. Medi isso: o Recall at três vai de {retrieval.recall_at_3} para {retrieval.recall_at_3_rerank}
com o rerank. Se nenhum trecho cobre a pergunta, um portão calibrado recusa em vez de inventar."

### Cena 6 — Demo: pergunta de produto (2:00–2:20)
**Tela:** curl real do cenário Get Clássica × Get Smart e a resposta com `sources` e citações [n].
**Fala:** "Primeiro cenário do enunciado: a diferença entre a Get Clássica e a Get Smart. A resposta cita
os trechos de onde tirou cada afirmação, e a lista de fontes vem no JSON."

### Cena 7 — Demo: dado do lojista com tools (2:20–2:45)
**Tela:** "quando cai o dinheiro das vendas de ontem?" → `tool_calls` (vendas, agenda de liquidação) → data
em dia útil.
**Fala:** "Agora uma pergunta sobre o próprio lojista. O agente de suporte chama as ferramentas do CRM com
a identidade do servidor, nunca a que o modelo sugerir, e calcula a liquidação em dias úteis, com
feriados. A resposta mostra quais ferramentas foram chamadas."

### Cena 8 — Demo: ação de risco com confirmação (2:45–3:05)
**Tela:** pedido de antecipação → `pending_action` → confirmação do dono → executada.
**Fala:** "Ações que mexem em dinheiro, como antecipar recebíveis ou contestar uma venda, nunca rodam
direto. O agente propõe, o sistema guarda uma ação pendente, e só o dono confirma. Outro lojista que tente
confirmar recebe não encontrado."

### Cena 9 — Demo: handoff humano e guardrail (3:05–3:30)
**Tela:** pedido de atendente → ticket → console do operador → resposta volta à conversa. Em seguida, uma
injeção de prompt bloqueada.
**Fala:** "Quando o sistema não resolve, ou o lojista pede, o caso vira ticket com o histórico. O operador
responde pelo console, e a resposta volta para a conversa. E uma tentativa de injeção de prompt é barrada
antes de chegar a qualquer agente."

### Cena 10 — Como avalio: taxonomia e gate (3:30–3:55)
**Tela:** tabela de checagens (intent, handoff por desfecho, tools, ação pendente, replanejamento,
idioma do texto, números sem base) e os splits; gate `{eval.gate}` → `{eval.verdict}`.
**Fala:** "Cada caso de teste declara o que precisa acontecer, e cada item vira uma checagem separada.
São {eval.cases} casos em vários conjuntos. O CI roda tudo offline, sem chave, a cada push, e reprova se a
acurácia de intenção ficar abaixo de {eval.gate}. Hoje está em {eval.intent_acc}, com intervalo de
confiança de {eval.intent_ci_lo} a {eval.intent_ci_hi}."

### Cena 11 — Held-out cego e casos difíceis (3:55–4:20)
**Tela:** commit da spec com `heldout_blind.jsonl`; held-out `{eval.heldout_intent}` e handoff
`{eval.heldout_handoff}`; hard `{eval.hard_intent}`; matriz de falhas.
**Fala:** "O conjunto cego foi escrito por um autor que só viu o enunciado e a especificação, e entrou
no mesmo commit da spec, antes do código. Ele fica fora do gate para não ser decorado. Nele, a intenção
acerta {eval.heldout_intent} e o handoff {eval.heldout_handoff}. Os casos difíceis ficam em
{eval.hard_intent}: são publicados mesmo falhando, porque mostram onde melhorar."

### Cena 12 — Ao vivo: pass^3 (4:20–4:45)
**Tela:** `{live.cases}` casos × 3 rodadas; pass@1 `{live.pass_at_1}`, pass^3 `{live.pass_hat_3}`, instáveis
`{live.unstable}`; custo `{live.spent_usd}` e `{live.usd_per_request}` por request; p95 `{live.p95_s}` s.
**Fala:** "Com o modelo real, cada caso roda três vezes, porque atendimento precisa acertar sempre, não em
média. O pass at one é {live.pass_at_1}; o pass três, que exige acertar nas três, é {live.pass_hat_3}. Os
casos instáveis são a fila de correção. Cada request custou em média {live.usd_per_request} dólar, com
latência de percentil noventa e cinco de {live.p95_s} segundos."

### Cena 13 — Juiz calibrado (4:45–5:10)
**Tela:** calibração com `{judge.cal_cases}` rótulos humanos: TPR `{judge.tpr}`, TNR `{judge.tnr}`, κ
`{judge.kappa}`; depois, grounded `{judge.grounded_rate}` e helpful `{judge.helpful_rate}` nas respostas ao
vivo.
**Fala:** "Para medir se a resposta inventa, um modelo maior julga cada resposta. Mas um juiz só vale se
concordar com humanos. Antes de julgar, ele passa por {judge.cal_cases} rótulos meus, com respostas de
produto, de dados do lojista e de busca na web. Ele acerta {judge.tpr} das fundamentadas e {judge.tnr} das
não fundamentadas. Só então julgamos as respostas ao vivo: {judge.grounded_rate} fundamentadas."

### Cena 14 — Limites e próximo passo (5:10–5:35)
**Tela:** três limites com número e o próximo passo de cada um; link do repositório.
**Fala:** "Três limites que eu declaro. Os rótulos humanos têm um único autor; o próximo passo é um
segundo rotulador e o kappa entre nós. O estado mora em SQLite num nó só; para réplicas, Postgres e fila.
E o held-out ainda está em {eval.heldout_intent}; o próximo ganho vem dos casos que ele erra. O código, os
testes e todos estes números estão no repositório. Obrigado."

---

## Chaves → origem

| Chave | Arquivo | Caminho no JSON / comando |
|---|---|---|
| `code.max_steps` | `src/app/supervisor.py` | constante `MAX_STEPS` |
| `code.rerank_top` | `src/app/rag.py` | tamanho do top-N do `RerankRetriever` |
| `git.minutes` | `git log` | minutos entre o 1º e o último commit dentro do relógio |
| `git.forks` | `git log --merges` | número de branches `fork/*` mescladas |
| `eval.cases` | `evals/results/latest.json` | `metrics.ALL.cases` |
| `eval.gate` | idem | `gate` |
| `eval.intent_acc` | idem | `intent_acc` |
| `eval.intent_ci_lo` / `_hi` | idem | `intent_ci.lo` / `intent_ci.hi` |
| `eval.verdict` | idem | `passed` (PASS/FAIL) |
| `eval.heldout_intent` | idem | `metrics.heldout.intent_acc` |
| `eval.heldout_handoff` | idem | `metrics.heldout.handoff_outcome_acc` |
| `eval.hard_intent` | idem | `metrics.hard.intent_acc` |
| `retrieval.recall_at_3` | idem | `retrieval["recall@3"]` (ou `retrieval_compare.bm25`) |
| `retrieval.recall_at_3_rerank` | relatório `--compare-retrievers --rerank` | `retrieval_compare["bm25+rerank"]["recall@3"]` |
| `live.cases` | `evals/results/live_*.json` | `metrics.ALL.cases` ÷ `stability.runs` |
| `live.pass_at_1` / `live.pass_hat_3` | idem | `stability.pass_at_1` / `stability.pass_hat_k` |
| `live.unstable` | idem | `len(stability.unstable)` |
| `live.spent_usd` | idem | `spent_usd` |
| `live.usd_per_request` | idem | `spent_usd` ÷ número de linhas em `rows` |
| `live.p95_s` | idem | `metrics.ALL.p95_ms` ÷ 1000 |
| `judge.cal_cases` | `evals/results/judge.json` | `calibration.cases` |
| `judge.tpr` / `judge.tnr` | idem | `calibration.tpr` / `calibration.tnr` |
| `judge.kappa` | idem | `calibration.cohen_kappa` |
| `judge.grounded_rate` / `judge.helpful_rate` | idem | `grounded_rate` / `helpful_rate` |

Se `judge.json` tiver `status: skipped` ou TPR/TNR < 0,8, a cena 13 troca a última frase por: "o juiz ainda
não passou no limiar de confiança, então a nota dele não entra como métrica."
