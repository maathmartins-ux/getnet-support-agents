"""Contrato das tools do lojista (fork B): entrada, saída, erro e dono errado, sobre data/crm real.

"Hoje" fica fixo em 31/10/2026 (sábado; 02/11 é Finados), para a liquidação em dias úteis ser verificável.
"""
from __future__ import annotations

from datetime import date

import pytest

from app import tools
from app.actions import confirm_action, decide_action, run_tool, tool_specs

TODAY = date(2026, 10, 31)
OWNERS = ("cliente1988", "cliente2024")
READS = ("get_receivables_schedule", "get_sales_summary", "list_transactions", "get_terminal_status")


@pytest.fixture(autouse=True)
def crm(domain_data, monkeypatch):
    monkeypatch.setattr(tools, "_today", lambda: TODAY)


# --- calendário ------------------------------------------------------------------------------
@pytest.mark.parametrize("start,n,expected", [
    (date(2026, 10, 30), 1, date(2026, 11, 3)),   # sexta → pula fim de semana e Finados
    (date(2026, 10, 31), 0, date(2026, 11, 3)),   # D0 no sábado → próximo dia útil
    (date(2026, 11, 3), 0, date(2026, 11, 3)),    # D0 em dia útil = mesmo dia
    (date(2026, 11, 19), 1, date(2026, 11, 23)),  # 20/11 Consciência Negra (sexta)
    (date(2026, 2, 13), 1, date(2026, 2, 18)),    # Carnaval 16 e 17/02/2026
    (date(2026, 12, 24), 1, date(2026, 12, 28)),  # Natal na sexta
])
def test_add_business_days(start, n, expected):
    assert tools.add_business_days(start, n) == expected


def test_holidays_mobile_2026():
    h = tools.holidays(2026)
    assert {date(2026, 4, 3), date(2026, 6, 4), date(2026, 2, 16), date(2026, 2, 17)} <= h  # Páscoa 05/04


def test_dates_are_relative_to_today(monkeypatch):
    monkeypatch.setattr(tools, "_today", lambda: date(2027, 3, 10))
    txs = tools._transactions("cliente1988")["data"]["transactions"]
    assert max(t["sale_date"] for t in txs) == "2027-03-10"


# --- contrato comum --------------------------------------------------------------------------
def test_specs_valid_and_high_risk_set():
    names = {s["name"] for s in tool_specs()}
    assert set(READS) | {"restart_terminal", "request_anticipation", "contest_transaction"} <= names
    for name, t in tools.DOMAIN_TOOLS.items():
        assert t["input_schema"]["type"] == "object" and t["input_schema"]["additionalProperties"] is False
        assert t["description"] and callable(t["fn"]), name
    risk = {n: t.get("risk", "normal") for n, t in tools.DOMAIN_TOOLS.items() if t["write"]}
    assert risk == {"restart_terminal": "normal", "request_anticipation": "high", "contest_transaction": "high"}


@pytest.mark.parametrize("name", READS)
@pytest.mark.parametrize("user", ["cliente0000", "u1", "_doc", ""])
def test_unknown_merchant_is_not_found(name, user):
    assert tools.TOOLS[name]["fn"](user_id=user) == {"ok": False, "error": "not_found"}


@pytest.mark.parametrize("name", READS)
@pytest.mark.parametrize("user", OWNERS)
def test_reads_ok(name, user):
    result, call = run_tool(name, {}, user)
    assert result["ok"] is True and call.ok


def test_user_id_from_model_is_ignored():
    result, call = run_tool("list_transactions", {"user_id": "cliente2024"}, "cliente1988")
    ids = {t["transaction_id"] for t in result["data"]["transactions"]}
    assert ids and all(i.startswith("TX1") for i in ids) and "user_id" not in call.args


def test_kit_without_crm_is_not_found(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert tools._terminals("cliente1988") == {"ok": False, "error": "not_found"}


# --- leitura ---------------------------------------------------------------------------------
def test_schedule_business_days_and_total():
    data = tools._schedule("cliente1988")["data"]
    first = data["upcoming"][0]
    assert first["deposit_date"] == "2026-11-03"  # débitos de sex 30/10 e sáb 31/10 caem na ter (Finados)
    assert first["total"] == 61.40 and {i["transaction_id"] for i in first["items"]} == {"TX1001", "TX1003"}
    assert data["available_for_anticipation"] == 2640.00  # 350 + 1200 + 480 + 610 (crédito previsto)
    assert data["total_to_receive"] == round(sum(d["total"] for d in data["upcoming"]), 2)
    assert all(d["deposit_date"] > TODAY.isoformat() for d in data["upcoming"])


def test_schedule_never_lists_declined():
    items = [i["transaction_id"] for d in tools._schedule("cliente1988")["data"]["upcoming"] for i in d["items"]]
    assert not {"TX1002", "TX1005", "TX1008", "TX1011"} & set(items)


def test_sales_by_day_and_brand():
    data = tools._sales("cliente1988", days=7)["data"]
    assert data["since"] == "2026-10-25" and data["until"] == "2026-10-31"
    assert data["approved_total"] == 2149.40  # 18,50 + 42,90 + 350 + 25 + 1200 + 480 + 33
    assert data["approved_count"] == 7 and data["declined_count"] == 4
    assert data["by_brand"] == {"Visa": 401.50, "Elo": 522.90, "Mastercard": 1200.00, "Pix": 25.00}
    assert sum(r["total"] for r in data["by_day_brand"]) == pytest.approx(data["approved_total"])


@pytest.mark.parametrize("days", [0, 31, "7", None])
def test_sales_invalid_days(days):
    assert tools._sales("cliente1988", days=days) == {"ok": False, "error": "invalid_days"}


def test_transactions_declined_have_code_and_reason():
    txs = tools._transactions("cliente1988", status="recusada")["data"]["transactions"]
    assert {t["transaction_id"]: t["code"] for t in txs} == {"TX1002": "51", "TX1005": "54", "TX1008": "55",
                                                              "TX1011": "57"}
    assert all(t["reason"] and not t["contestable"] and "deposit_date" not in t for t in txs)


def test_transactions_approved_are_contestable():
    txs = tools._transactions("cliente2024", status="aprovada")["data"]["transactions"]
    assert txs and all(t["contestable"] and t["code"] == "00" for t in txs)


def test_transactions_invalid_status():
    assert tools._transactions("cliente1988", status="pendente")["error"] == "invalid_status"


def test_terminals_scenarios():
    t1 = {t["terminal_id"]: t for t in tools._terminals("cliente1988")["data"]["terminals"]}
    assert t1["T1988A"]["online"] and t1["T1988B"]["status"] == "sem_sinal" and not t1["T1988B"]["online"]
    t2 = tools._terminals("cliente2024")["data"]["terminals"]
    assert [t["paper"] for t in t2] == ["sem_bobina"]


# --- escrita: proposta passa pela mecânica do kit --------------------------------------------
def test_restart_is_normal_risk_and_needs_confirmation():
    result, _ = run_tool("restart_terminal", {"terminal_id": "T1988B"}, "cliente1988")
    assert result["needs_confirmation"] and result["risk"] == "normal" and result["args"] == {"terminal_id": "T1988B"}
    assert confirm_action(result["action_id"], "cliente1988")["data"]["status"] == "restart_sent"


def test_restart_other_owner_terminal_not_found():
    assert tools._restart("cliente2024", "T1988A") == {"ok": False, "error": "not_found"}


def test_anticipation_high_risk_carries_amount_and_needs_operator():
    result, _ = run_tool("request_anticipation", {"amount": 2640.00}, "cliente1988")
    assert result["risk"] == "high" and result["args"] == {"amount": 2640.00}
    assert confirm_action(result["action_id"], "cliente1988")["awaiting_operator"]
    done = decide_action(result["action_id"], "op1", approve=True)
    assert done["result"]["data"]["gross_amount"] == 2640.00 and done["result"]["data"]["net_amount"] == 2587.46


def test_anticipation_without_amount_uses_total_available():
    data = tools._anticipate("cliente2024")["data"]
    assert data["gross_amount"] == 665.00  # 95 + 310 + 260
    assert data["fee_amount"] == 16.56 and data["credit_date"] == "2026-11-03"


@pytest.mark.parametrize("amount,error", [(5000.0, "amount_exceeds_available"), (0, "invalid_amount"),
                                          (-1, "invalid_amount"), ("100", "invalid_amount"), (True, "invalid_amount")])
def test_anticipation_invalid_amount(amount, error):
    assert tools._anticipate("cliente1988", amount)["error"] == error


def test_anticipation_unknown_merchant():
    assert tools._anticipate("cliente0000") == {"ok": False, "error": "not_found"}


def test_contest_only_approved():
    assert tools._contest("cliente1988", "TX1004")["data"] == {"transaction_id": "TX1004", "amount": 350.00,
                                                               "status": "contest_opened", "reason": ""}
    assert tools._contest("cliente1988", "TX1002") == {"ok": False, "error": "not_eligible", "status": "recusada"}


def test_contest_other_owner_same_as_missing():
    assert tools._contest("cliente2024", "TX1004") == tools._contest("cliente2024", "TX9999") == {
        "ok": False, "error": "not_found"}


def test_approved_contest_of_declined_never_executes():
    """Chargeback de recusada (falha da v3): mesmo com o operador aprovando, a execução recusa."""
    result, _ = run_tool("contest_transaction", {"transaction_id": "TX1002"}, "cliente1988")
    assert result["risk"] == "high" and result["args"] == {"transaction_id": "TX1002"}
    confirm_action(result["action_id"], "cliente1988")
    done = decide_action(result["action_id"], "op1", approve=True)
    assert done["result"] == {"ok": False, "error": "not_eligible", "status": "recusada"}
    assert done["action"]["status"] == "failed"


def test_eligibility_follows_agents_eligible_status(monkeypatch):
    from app import agents

    monkeypatch.setitem(agents.ELIGIBLE_STATUS, "contest_transaction", {"aprovada"})
    assert tools._contest("cliente1988", "TX1002")["error"] == "not_eligible"
    monkeypatch.setitem(agents.ELIGIBLE_STATUS, "contest_transaction", set())
    assert tools._contest("cliente1988", "TX1004")["error"] == "not_eligible"


def test_schema_rejects_bad_ids():
    import re

    tx = tools.DOMAIN_TOOLS["contest_transaction"]["input_schema"]["properties"]["transaction_id"]["pattern"]
    term = tools.DOMAIN_TOOLS["restart_terminal"]["input_schema"]["properties"]["terminal_id"]["pattern"]
    assert re.match(tx, "TX1004") and not re.match(tx, "1004")
    assert re.match(term, "T1988A") and not re.match(term, "T1988")
