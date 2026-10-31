fase: spec congelada (14:28) → G1 bloqueado no gate de intent até o fork O (router é dele); principal adaptando agents.py
último marco: spec: 01f9d02 (SPEC + taxonomia + tools + cases 35 + heldout cego 24 + ADR 0002/0003)
forks integrados: nenhum
pendências: URGENTE → fork B: renomear tools para os nomes CONGELADOS da SPEC (o heldout cego usa eles): get_receivables_schedule→get_settlements, list_transactions→get_transactions, contest_transaction→open_chargeback (ELIGIBLE_STATUS["open_chargeback"]); get_sales_summary pode ficar. → fork O: intents knowledge/support/troubleshoot/general/multi/human_request; PLANS troubleshoot=["records","faq"], DEPENDS={"faq":{"records"}}; pronto ASAP (G1 depende do router)
próximo marco: g1: assim que fork O pronto (vira onda 1 junto)
