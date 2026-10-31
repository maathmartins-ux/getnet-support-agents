"""Domínio Getnet — router offline: taxonomia da SPEC (knowledge, general, support, troubleshoot, multi, human_request).

Frases: os 10 cenários do enunciado + paráfrases próprias. Nenhuma vem do held-out.
"""
import pytest

from app.router import SCHEMA, classify_offline
from app.supervisor import PLANS

ENUNCIADO = [
    ("What's the difference between the Get Clássica and the Get Smart?", "knowledge"),
    ("What's the weather forecast in Porto Alegre tomorrow?", "general"),
    ("When will the money from yesterday's sales be deposited?", "support"),
    ("Do I need a bank account to receive my sales via Pix?", "knowledge"),
    ("My card machine won't connect to the internet, what should I do?", "troubleshoot"),
    ("How does receivables advance (antecipação) work with Getnet?", "knowledge"),
    ("What's the euro exchange rate today?", "general"),
    ("My card machine is showing a transaction decline error.", "troubleshoot"),
    ("How many installments can I split a sale into with the crediário?", "knowledge"),
    ("Can I sell through WhatsApp using the Payment Link?", "knowledge"),
]

PROPRIAS = [
    ("Qual a cotação do dólar agora?", "general", "pt"),
    ("Vai chover em Salvador amanhã?", "general", "pt"),
    ("Quando cai na conta o dinheiro das vendas de ontem?", "support", "pt"),
    ("Quero ver minhas transações recusadas", "support", "pt"),
    ("A maquininha não conecta no Wi-Fi", "troubleshoot", "pt"),
    ("Deu erro de recusa na máquina", "troubleshoot", "pt"),
    ("Preciso de conta bancária para receber minhas vendas via Pix?", "knowledge", "pt"),
    ("Quero falar com um atendente", "human_request", "pt"),
    ("I want to speak to a real person", "human_request", "en"),
]


@pytest.mark.parametrize("message,intent", ENUNCIADO)
def test_enunciado_scenarios(domain_data, message, intent):
    d = classify_offline(message, [])
    assert d.intent == intent, message
    assert d.plan == PLANS[intent]
    assert d.language == "en"


@pytest.mark.parametrize("message,intent,lang", PROPRIAS)
def test_own_paraphrases(domain_data, message, intent, lang):
    d = classify_offline(message, [])
    assert (d.intent, d.language) == (intent, lang), message


def test_general_plan_is_knowledge_with_web():
    assert PLANS["general"] == ["faq"]  # o agente de conhecimento faz a busca web quando intent == general


def test_troubleshoot_runs_records_and_faq():
    assert PLANS["troubleshoot"] == ["records", "faq"]


def test_schema_enum_covers_every_intent():
    assert set(SCHEMA["properties"]["intent"]["enum"]) == set(PLANS)


def test_human_wins_over_troubleshoot(domain_data):
    d = classify_offline("Minha maquininha não liga, quero falar com um atendente", [])
    assert d.intent == "human_request" and d.plan == ["escalation"]


def test_followup_inherits_troubleshoot(domain_data):
    history = [{"role": "user", "content": "A maquininha não conecta no Wi-Fi", "intent": "troubleshoot"},
               {"role": "assistant", "content": "Reinicie o roteador.", "intent": "troubleshoot"}]
    assert classify_offline("E se isso não resolver?", history).intent == "troubleshoot"


def test_general_and_records_in_one_message_is_multi(domain_data):
    d = classify_offline("Qual a cotação do euro? E quando cai o dinheiro das vendas de ontem?", [])
    assert d.intent == "multi"
