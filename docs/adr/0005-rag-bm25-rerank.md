# ADR 0005 — BM25 + glossário pt↔en + rerank do top-20 pelo Haiku; híbrido atrás de flag

**Status:** aceito (31/10/2026)

## Contexto
O corpus é um retrato literal do site Getnet Brasil, em português; parte das perguntas do enunciado é em inglês.
Medido antes do relógio no corpus real da tentativa anterior (884 trechos, 45 perguntas; comentário em
`src/app/config.py`): o BM25 acha a fonte no **top-20 em 90,4%** e no **top-3 em 70,8%**. O gargalo é a ordem,
não o recall.

## Decisão
- BM25 próprio (k1 1,5, b 0,75, título com peso 2) como padrão: auditável e sem dependência na imagem.
- Glossário pt↔en (`data/glossary.json`) expande a consulta: a pergunta em inglês encontra o trecho em português.
- Com LLM, `RerankRetriever` reordena o top-20 com Haiku low; resposta inválida ou erro do provedor caem na ordem
  do BM25 (`rerank_fallback_total`).
- Híbrido (BM25 + embeddings multilíngues por RRF, k = 60) fica atrás de `RETRIEVER=hybrid` e do extra `.[hybrid]`.

## Alternativas descartadas
- **Embeddings desde o início:** dependência pesada na imagem para atacar o recall, que não é o gargalo.
- **Prefixo do caminho da URL no BM25:** medido antes do relógio, R@3 0,708 → 0,712, dentro do ruído com n = 45.
- **Traduzir a pergunta com LLM:** custo e latência em todo turno para um mapeamento fixo de termos.

## Consequências
Os números deste corpus (Recall@3 e MRR por retriever, com e sem rerank) saem de
`python -m evals.run_evals --compare-retrievers --rerank` para `evals/results/` e entram no README §5.
