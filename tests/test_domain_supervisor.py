"""Domínio Getnet — supervisor: general nunca escala; troubleshoot roda em paralelo; sem fonte escala."""
import json

import pytest

from app import supervisor
from app.agents import AgentResult, Context
from app.config import ROOT
from app.router import classify_offline


def ctx(text_, intent):
    return Context(text=text_, language="pt", user_id="cliente1988", conversation_id="c1", intent=intent)


def test_general_insufficient_does_not_escalate(monkeypatch):
    monkeypatch.setitem(supervisor.AGENTS, "faq", lambda c: AgentResult("faq", "insufficient", reason="no_source"))
    out = supervisor.run(supervisor.PLANS["general"], ctx("Qual a cotação do euro?", "general"))
    assert out.route == ["faq"] and out.replans == []


def test_general_low_confidence_does_not_escalate(domain_data):
    out = supervisor.run(supervisor.PLANS["general"], ctx("Vai chover amanhã?", "general"), confidence=0.2)
    assert "escalation" not in out.route


def test_general_offline_answers_without_inventing_number(domain_data):
    out = supervisor.run(supervisor.PLANS["general"], ctx("Qual a cotação do euro hoje?", "general"))
    assert out.route == ["faq"] and out.results[0].status == "ok"
    assert not any(ch.isdigit() for ch in out.results[0].text)


def test_faq_no_source_escalates(monkeypatch):
    monkeypatch.setitem(supervisor.AGENTS, "faq", lambda c: AgentResult("faq", "insufficient", reason="no_source"))
    out = supervisor.run(supervisor.PLANS["knowledge"], ctx("Qual a capital da Mongólia?", "knowledge"))
    assert out.route == ["faq", "escalation"] and out.replans == ["faq:no_source->escalation"]


def test_troubleshoot_runs_records_then_faq(monkeypatch):
    batches = []
    real = supervisor.run_batch

    def spy(names, c):
        batches.append(list(names))
        return real(names, c)

    monkeypatch.setattr(supervisor, "run_batch", spy)
    monkeypatch.setitem(supervisor.AGENTS, "records", lambda c: AgentResult("records", "ok", text="terminal offline"))
    monkeypatch.setitem(supervisor.AGENTS, "faq", lambda c: AgentResult("faq", "ok", text="reinicie"))
    monkeypatch.setenv("SUPERVISOR_PARALLEL", "1")
    out = supervisor.run(supervisor.PLANS["troubleshoot"], ctx("A maquininha não conecta", "troubleshoot"))
    assert out.route == ["records", "faq"] and batches == [["records"], ["faq"]]  # DEPENDS: faq lê o terminal


def test_troubleshoot_tool_error_escalates_once(monkeypatch):
    monkeypatch.setitem(supervisor.AGENTS, "records", lambda c: AgentResult("records", "error", reason="tool_error"))
    monkeypatch.setitem(supervisor.AGENTS, "faq", lambda c: AgentResult("faq", "insufficient", reason="no_source"))
    out = supervisor.run(supervisor.PLANS["troubleshoot"], ctx("Erro na maquininha", "troubleshoot"))
    assert out.route.count("escalation") == 1 and out.route[-1] == "escalation"


def test_no_escalation_blocks_llm_escalation_tool():
    assert "general" in supervisor.NO_ESCALATION
    assert supervisor.next_step(AgentResult("faq", "insufficient"), ["faq"], "general") is None
    assert supervisor.next_step(AgentResult("faq", "insufficient"), ["faq"], "knowledge") == "escalation"


def test_support_tool_error_tries_knowledge_first(monkeypatch):
    monkeypatch.setitem(supervisor.AGENTS, "records", lambda c: AgentResult("records", "error", reason="tool_error"))
    monkeypatch.setitem(supervisor.AGENTS, "faq", lambda c: AgentResult("faq", "insufficient", reason="no_source"))
    out = supervisor.run(supervisor.PLANS["support"], ctx("Quanto vendi ontem?", "support"))
    assert out.route == ["records", "faq", "escalation"]
    assert out.replans == ["records:tool_error->faq", "faq:no_source->escalation"]


def _replan_cases():
    rows = [json.loads(line) for line in (ROOT / "evals" / "cases.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]
    return [r for r in rows if r.get("split") == "replan"]


def test_replan_split_routing_and_table(domain_data, monkeypatch):
    """Parte do fork O: intent certa e, quando o conhecimento não acha fonte, o supervisor desvia para humano."""
    monkeypatch.setitem(supervisor.AGENTS, "faq", lambda c: AgentResult("faq", "insufficient", reason="no_source"))
    cases = _replan_cases()
    assert len(cases) >= 20
    hits = 0
    for case in cases:
        d = classify_offline(case["message"], [])
        out = supervisor.run(d.plan, ctx(case["message"], d.intent), d.confidence)
        hits += d.intent == case["expect"]["intent"] and bool(out.replans) and out.route[-1] == "escalation"
    assert hits == len(cases), f"{hits}/{len(cases)}"


@pytest.mark.skipif(not (ROOT / "data" / "knowledge").exists(), reason="corpus Getnet (fork A) ainda não integrado")
def test_replan_split_offline(domain_data):
    """Ponta a ponta com o corpus real: depende do portão de cobertura do RAG (forks A1/A2)."""
    cases = _replan_cases()
    hits = 0
    for case in cases:
        d = classify_offline(case["message"], [])
        out = supervisor.run(d.plan, ctx(case["message"], d.intent), d.confidence)
        hits += d.intent == case["expect"]["intent"] and bool(out.replans) and out.route[-1] == "escalation"
    assert hits / len(cases) >= 0.9, f"{hits}/{len(cases)}"
