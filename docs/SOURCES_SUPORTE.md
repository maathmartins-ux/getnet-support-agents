# Fontes do corpus de suporte (fork A2)

Só Brasil: `site.getnet.com.br` (nunca getnet.net). Trechos literais de 300–800 caracteres, texto normalizado só em espaços;
menu e rodapé (linhas presentes em 4+ páginas) removidos. Arquivo: `data/knowledge/suporte/suporte.jsonl`.

Total: 130 trechos de 18 URLs, coletados em 2026-10-31.

| URL | trechos | ids | data |
|---|---|---|---|
| https://site.getnet.com.br/duvidas/ | 55 | `sup-duvidas-01 … sup-duvidas-56` | 2026-10-31 |
| https://site.getnet.com.br/boas-vindas/manual-maquinas/ | 1 | `sup-manual-maquinas-01` | 2026-10-31 |
| https://site.getnet.com.br/proteja-seu-negocio-e-venda-com-seguranca/ | 5 | `sup-seguranca-01 … sup-seguranca-05` | 2026-10-31 |
| https://site.getnet.com.br/duvidas/get-smart/ | 9 | `sup-get-smart-01 … sup-get-smart-09` | 2026-10-31 |
| https://site.getnet.com.br/duvidas/aluguel/ | 4 | `sup-aluguel-01 … sup-aluguel-04` | 2026-10-31 |
| https://site.getnet.com.br/duvidas/app-getnet/ | 3 | `sup-app-getnet-01 … sup-app-getnet-03` | 2026-10-31 |
| https://site.getnet.com.br/duvidas/bandeiras/ | 3 | `sup-bandeiras-01 … sup-bandeiras-03` | 2026-10-31 |
| https://site.getnet.com.br/duvidas/cancelamento-descredenciamento/ | 1 | `sup-cancelamento-01` | 2026-10-31 |
| https://site.getnet.com.br/duvidas/get-tap/ | 7 | `sup-get-tap-01 … sup-get-tap-07` | 2026-10-31 |
| https://site.getnet.com.br/duvidas/pix-mais-respostas/ | 16 | `sup-pix-respostas-01 … sup-pix-respostas-16` | 2026-10-31 |
| https://site.getnet.com.br/duvidas/operacional/ | 7 | `sup-operacional-01 … sup-operacional-07` | 2026-10-31 |
| https://site.getnet.com.br/duvidas/parcelado/ | 2 | `sup-parcelado-01 … sup-parcelado-02` | 2026-10-31 |
| https://site.getnet.com.br/duvidas/pix/ | 4 | `sup-pix-01 … sup-pix-04` | 2026-10-31 |
| https://site.getnet.com.br/duvidas/pre-autorizacao/ | 1 | `sup-pre-autorizacao-01` | 2026-10-31 |
| https://site.getnet.com.br/duvidas/tef-captura-pinpad/ | 1 | `sup-tef-01` | 2026-10-31 |
| https://site.getnet.com.br/duvidas/venda-com-cartao-de-credito-pre-pago/ | 6 | `sup-pre-pago-01 … sup-pre-pago-06` | 2026-10-31 |
| https://site.getnet.com.br/chargeback/ | 3 | `sup-chargeback-01 … sup-chargeback-03` | 2026-10-31 |
| https://site.getnet.com.br/ouvidoria/ | 2 | `sup-ouvidoria-01 … sup-ouvidoria-02` | 2026-10-31 |

## Lacunas conhecidas

- Tabela de **códigos de recusa** por número (ex.: 51, 05) não está publicada em site.getnet.com.br; a busca do site não indexa o blog. Cobertura parcial: motivos de contestação (`sup-operacional-03`), duplicidade, pré-pago sem saldo.
- Passo a passo de **Wi-Fi/4G** e troca de bobina está nos PDFs de manual (links em `sup-manual-maquinas-01`), não extraídos.
