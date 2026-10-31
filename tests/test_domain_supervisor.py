"""Domínio Getnet — supervisor: general nunca escala; troubleshoot roda em paralelo; sem fonte escala."""
from app import supervisor
from app.agents import AgentResult, Context


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
    out = supervisor.run(supervisor.PLANS["faq"], ctx("Qual a capital da Mongólia?", "faq"))
    assert out.route == ["faq", "escalation"] and out.replans == ["faq:no_source->escalation"]


def test_troubleshoot_runs_both_in_one_batch(monkeypatch):
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
    assert out.route == ["records", "faq"] and batches[0] == ["records", "faq"]


def test_troubleshoot_tool_error_escalates_once(monkeypatch):
    monkeypatch.setitem(supervisor.AGENTS, "records", lambda c: AgentResult("records", "error", reason="tool_error"))
    monkeypatch.setitem(supervisor.AGENTS, "faq", lambda c: AgentResult("faq", "insufficient", reason="no_source"))
    out = supervisor.run(supervisor.PLANS["troubleshoot"], ctx("Erro na maquininha", "troubleshoot"))
    assert out.route.count("escalation") == 1 and out.route[-1] == "escalation"


def test_no_escalation_blocks_llm_escalation_tool():
    assert "general" in supervisor.NO_ESCALATION
    assert supervisor.next_step(AgentResult("faq", "insufficient"), ["faq"], "general") is None
    assert supervisor.next_step(AgentResult("faq", "insufficient"), ["faq"], "faq") == "escalation"
