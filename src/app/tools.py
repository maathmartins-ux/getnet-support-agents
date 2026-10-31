"""Ferramentas do domínio: o registro TOOLS (descrição, JSON Schema, função, `write`, `risk`).

Só o que muda por desafio mora aqui. A mecânica (identidade do servidor, confirmação do dono, aprovação do
operador, TTL, execução única) está em `actions.py` e não muda. Contrato de cada função: recebe os
argumentos do schema + `user_id` (sempre o autenticado, injetado pelo servidor) e devolve
{ok, data} ou {ok: False, error}. Mesma resposta para registro inexistente e de outro dono.

Domínio Getnet (lojista): `data/crm/merchants.json`, um lojista por `user_id`, com datas RELATIVAS
(`days_ago`). Tudo que é data sai de `_today()` + calendário bancário nacional:
- liquidação: pix D0, débito D+1, crédito D+30, todos em DIAS ÚTEIS (sem sábado, domingo e feriado);
- feriados: os nacionais fixos, mais Carnaval (seg e ter), Sexta-feira Santa e Corpus Christi, que não
  têm expediente bancário (calendário Febraban).
Escrita: reiniciar terminal = risco normal; antecipação e contestação = risco alto (dono confirma e um
operador aprova). Contestação só de transação APROVADA (`agents.ELIGIBLE_STATUS`), checado também na
execução: uma aprovação humana errada não abre chargeback de transação recusada.

Ligação com o sistema de registro (CRM): `merchants()` é o adaptador. Em produção, troque o corpo por uma
chamada à API do CRM, mantendo a assinatura (contrato testado em tests/test_tools.py).
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from functools import lru_cache

from .config import data_dir

SETTLEMENT_DAYS = {"pix": 0, "debito": 1, "credito": 30}  # dias úteis depois da venda
CONTESTABLE = {"aprovada"}  # padrão se agents.ELIGIBLE_STATUS não tiver a entrada


def _today() -> date:
    return date.today()  # ponto único de "hoje": os testes fixam a data aqui


# --- calendário bancário ---------------------------------------------------------------------
def _easter(year: int) -> date:
    """Domingo de Páscoa (algoritmo gregoriano anônimo, Meeus/Jones/Butcher)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return date(year, month, day + 1)


@lru_cache(maxsize=16)
def holidays(year: int) -> frozenset[date]:
    fixed = [(1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2), (11, 15), (11, 20), (12, 25)]
    easter = _easter(year)
    mobile = [easter - timedelta(days=48), easter - timedelta(days=47),  # Carnaval
              easter - timedelta(days=2), easter + timedelta(days=60)]  # Sexta-feira Santa, Corpus Christi
    return frozenset([date(year, mo, d) for mo, d in fixed] + mobile)


def is_business_day(d: date) -> bool:
    return d.weekday() < 5 and d not in holidays(d.year)


def add_business_days(d: date, n: int) -> date:
    """D+n em dias úteis. D0 num dia não útil cai no próximo dia útil."""
    if n == 0:
        while not is_business_day(d):
            d += timedelta(days=1)
        return d
    while n > 0:
        d += timedelta(days=1)
        if is_business_day(d):
            n -= 1
    return d


# --- adaptador do CRM ------------------------------------------------------------------------
@lru_cache(maxsize=4)
def _merchants(path: str) -> dict:
    return json.loads(open(path, encoding="utf-8").read())


def merchants() -> dict:
    return _merchants(str(data_dir() / "crm" / "merchants.json"))


_NOT_FOUND = {"ok": False, "error": "not_found"}


def _merchant(user_id: str) -> dict | None:
    if not isinstance(user_id, str) or user_id.startswith("_"):
        return None
    try:
        return merchants().get(user_id)
    except FileNotFoundError:  # DATA_DIR sem CRM (fixture do kit): ninguém é lojista
        return None


def _tx(t: dict, today: date) -> dict:
    """Transação com datas absolutas calculadas a partir de hoje (o JSON só guarda days_ago)."""
    sale = today - timedelta(days=t["days_ago"])
    out = {k: v for k, v in t.items() if k != "days_ago"}
    out["sale_date"] = sale.isoformat()
    if t["status"] == "aprovada":
        dep = add_business_days(sale, SETTLEMENT_DAYS[t["modality"]])
        out["deposit_date"] = dep.isoformat()
        out["settlement"] = "liquidada" if dep <= today else "prevista"
    out["contestable"] = t["status"] in _contestable()
    return out


def _contestable() -> set[str]:
    from .agents import ELIGIBLE_STATUS  # import tardio: agents importa actions, que importa este módulo

    return set(ELIGIBLE_STATUS.get("contest_transaction", CONTESTABLE))


def _all_tx(m: dict) -> list[dict]:
    today = _today()
    return [_tx(t, today) for t in sorted(m["transactions"], key=lambda t: (-t["days_ago"], t["time"]))]


def _money(x: float) -> float:
    return round(x + 0.0, 2)


def _available(m: dict) -> float:
    """Antecipável = crédito aprovado ainda não liquidado."""
    return _money(sum(t["amount"] for t in _all_tx(m)
                      if t.get("settlement") == "prevista" and t["modality"] == "credito"))


# --- leitura ---------------------------------------------------------------------------------
def _schedule(user_id: str) -> dict:
    m = _merchant(user_id)
    if not m:
        return _NOT_FOUND
    by_day: dict[str, dict] = {}
    for t in _all_tx(m):
        if t.get("settlement") != "prevista":
            continue
        day = by_day.setdefault(t["deposit_date"], {"deposit_date": t["deposit_date"], "total": 0.0, "items": []})
        day["total"] = _money(day["total"] + t["amount"])
        day["items"].append({"transaction_id": t["transaction_id"], "modality": t["modality"],
                             "amount": t["amount"], "sale_date": t["sale_date"]})
    upcoming = sorted(by_day.values(), key=lambda d: d["deposit_date"])
    return {"ok": True, "data": {
        "today": _today().isoformat(), "rule": "pix D0, débito D+1, crédito D+30 em dias úteis",
        "upcoming": upcoming, "total_to_receive": _money(sum(d["total"] for d in upcoming)),
        "available_for_anticipation": _available(m), "anticipation_fee_pct": m["anticipation_fee_pct"]}}


def _sales(user_id: str, days: int = 7) -> dict:
    m = _merchant(user_id)
    if not m:
        return _NOT_FOUND
    if not isinstance(days, int) or not 1 <= days <= 30:
        return {"ok": False, "error": "invalid_days"}
    since = (_today() - timedelta(days=days - 1)).isoformat()
    rows: dict[tuple[str, str], dict] = {}
    declined = 0
    for t in _all_tx(m):
        if t["sale_date"] < since:
            continue
        if t["status"] != "aprovada":
            declined += 1
            continue
        row = rows.setdefault((t["sale_date"], t["brand"]),
                              {"date": t["sale_date"], "brand": t["brand"], "count": 0, "total": 0.0})
        row["count"] += 1
        row["total"] = _money(row["total"] + t["amount"])
    by_day = sorted(rows.values(), key=lambda r: (r["date"], r["brand"]))
    brands: dict[str, float] = {}
    for r in by_day:
        brands[r["brand"]] = _money(brands.get(r["brand"], 0.0) + r["total"])
    return {"ok": True, "data": {
        "since": since, "until": _today().isoformat(), "by_day_brand": by_day, "by_brand": brands,
        "approved_count": sum(r["count"] for r in by_day), "approved_total": _money(sum(brands.values())),
        "declined_count": declined}}


def _transactions(user_id: str, status: str | None = None, days: int = 30) -> dict:
    m = _merchant(user_id)
    if not m:
        return _NOT_FOUND
    if status not in (None, "aprovada", "recusada"):
        return {"ok": False, "error": "invalid_status"}
    since = (_today() - timedelta(days=days - 1)).isoformat()
    txs = [t for t in _all_tx(m) if t["sale_date"] >= since and (status is None or t["status"] == status)]
    return {"ok": True, "data": {"transactions": txs, "count": len(txs)}}


def _get_tx(user_id: str, transaction_id: str) -> dict:
    m = _merchant(user_id)
    found = next((t for t in _all_tx(m) if t["transaction_id"] == transaction_id), None) if m else None
    return {"ok": True, "data": found} if found else _NOT_FOUND


def _terminals(user_id: str) -> dict:
    m = _merchant(user_id)
    if not m:
        return _NOT_FOUND
    return {"ok": True, "data": {"terminals": [{**t, "online": t["status"] == "online"} for t in m["terminals"]]}}


# --- escrita (só roda depois da confirmação, e da aprovação quando risk = high) -----------------
def _restart(user_id: str, terminal_id: str) -> dict:
    m = _merchant(user_id)
    term = next((t for t in m["terminals"] if t["terminal_id"] == terminal_id), None) if m else None
    if not term:
        return _NOT_FOUND
    if term["status"] == "bloqueado":
        return {"ok": False, "error": "terminal_blocked"}  # reiniciar não desbloqueia: é caso de atendente
    return {"ok": True, "data": {"terminal_id": terminal_id, "status": "restart_sent", "previous": term["status"]}}


def _anticipate(user_id: str, amount: float | None = None) -> dict:
    m = _merchant(user_id)
    if not m:
        return _NOT_FOUND
    available = _available(m)
    if available <= 0:
        return {"ok": False, "error": "nothing_to_anticipate"}
    gross = available if amount is None else amount
    if not isinstance(gross, (int, float)) or isinstance(gross, bool) or gross <= 0:
        return {"ok": False, "error": "invalid_amount"}
    if gross > available + 0.005:
        return {"ok": False, "error": "amount_exceeds_available", "available_for_anticipation": available}
    fee = _money(gross * m["anticipation_fee_pct"] / 100)
    return {"ok": True, "data": {
        "status": "anticipation_requested", "gross_amount": _money(gross), "fee_pct": m["anticipation_fee_pct"],
        "fee_amount": fee, "net_amount": _money(gross - fee),
        "credit_date": add_business_days(_today(), 1).isoformat()}}


def _contest(user_id: str, transaction_id: str, reason: str = "") -> dict:
    found = _get_tx(user_id, transaction_id)
    if not found["ok"]:
        return found
    tx = found["data"]
    if not tx["contestable"]:  # recusada nunca virou dinheiro: não há o que contestar
        return {"ok": False, "error": "not_eligible", "status": tx["status"]}
    return {"ok": True, "data": {"transaction_id": transaction_id, "amount": tx["amount"],
                                 "status": "contest_opened", "reason": reason}}


_TX_ID = {"type": "string", "pattern": r"^TX\d{4}$", "description": "Identificador da transação (ex.: TX1004)"}
_TERM_ID = {"type": "string", "pattern": r"^T\d{4}[A-Z]$", "description": "Identificador do terminal (ex.: T1988A)"}
_NONE = {"type": "object", "properties": {}, "additionalProperties": False}
DOMAIN_TOOLS = {
    "get_receivables_schedule": {
        "description": "Agenda de recebimento do lojista: valores previstos por data de depósito (pix D0, débito "
                       "D+1, crédito D+30, em dias úteis), total a receber e o total disponível para antecipação.",
        "write": False, "input_schema": _NONE, "fn": _schedule},
    "get_sales_summary": {
        "description": "Vendas aprovadas por dia e por bandeira nos últimos `days` dias (1 a 30, padrão 7), com "
                       "totais e a quantidade de recusadas.",
        "write": False, "fn": _sales,
        "input_schema": {"type": "object", "additionalProperties": False,
                         "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 30}}}},
    "list_transactions": {
        "description": "Transações do lojista (aprovadas e recusadas, com código e motivo da recusa, data de "
                       "depósito e se pode ser contestada). Filtro opcional por status.",
        "write": False, "fn": _transactions,
        "input_schema": {"type": "object", "additionalProperties": False,
                         "properties": {"status": {"type": "string", "enum": ["aprovada", "recusada"]},
                                        "days": {"type": "integer", "minimum": 1, "maximum": 30}}}},
    "get_terminal_status": {
        "description": "Status das maquininhas do lojista: online, sem sinal, sem bobina ou bloqueada; conexão, "
                       "sinal e último contato.",
        "write": False, "input_schema": _NONE, "fn": _terminals},
    "restart_terminal": {
        "description": "Envia comando de reinício remoto para uma maquininha. Exige confirmação do lojista.",
        "write": True, "fn": _restart,
        "input_schema": {"type": "object", "properties": {"terminal_id": _TERM_ID}, "required": ["terminal_id"],
                         "additionalProperties": False}},
    # risco alto: move dinheiro → confirmação do dono E aprovação de um operador (actions.py)
    "request_anticipation": {
        "description": "Solicita antecipação de recebíveis de crédito. Informe `amount`; sem valor do cliente, use "
                       "o total disponível da agenda. Exige confirmação do lojista e aprovação de um atendente.",
        "write": True, "risk": "high", "fn": _anticipate,
        "input_schema": {"type": "object", "additionalProperties": False,
                         "properties": {"amount": {"type": "number", "exclusiveMinimum": 0,
                                                   "description": "Valor bruto em reais"}}}},
    "contest_transaction": {
        "description": "Abre contestação (estorno) de uma transação APROVADA. Transação recusada não pode ser "
                       "contestada. Exige confirmação do lojista e aprovação de um atendente.",
        "write": True, "risk": "high", "fn": _contest,
        "input_schema": {"type": "object", "additionalProperties": False, "required": ["transaction_id"],
                         "properties": {"transaction_id": _TX_ID, "reason": {"type": "string", "maxLength": 200}}}},
}


# --- ferramentas genéricas do kit (data/records.json) -----------------------------------------
# Mantidas enquanto o caminho offline de agents.records_agent e os testes da mecânica as usam.
_ID = {"type": "string", "pattern": r"^\d{4}$", "description": "Número do registro (4 dígitos)"}


@lru_cache(maxsize=4)
def _records(path: str) -> dict:
    return json.loads(open(path, encoding="utf-8").read())


def records() -> dict:
    return _records(str(data_dir() / "records.json"))


def _lookup(record_id: str, user_id: str) -> dict:
    rec = records().get(record_id)
    if not rec or rec["owner"] != user_id:  # mesma resposta para inexistente e de outro dono
        return {"ok": False, "error": "not_found"}
    return {"ok": True, "data": {"record_id": record_id, **{k: v for k, v in rec.items() if k != "owner"}}}


def _cancel(record_id: str, user_id: str) -> dict:
    found = _lookup(record_id, user_id)
    if not found["ok"]:
        return found
    return {"ok": True, "data": {"record_id": record_id, "status": "cancel_requested"}}


def _refund(record_id: str, user_id: str) -> dict:
    found = _lookup(record_id, user_id)
    if not found["ok"]:
        return found
    return {"ok": True, "data": {"record_id": record_id, "status": "refund_issued"}}


_ONE_ID = {"type": "object", "properties": {"record_id": _ID}, "required": ["record_id"],
           "additionalProperties": False}
KIT_TOOLS = {
    "lookup_record": {"description": "Consulta um registro do cliente autenticado.", "write": False,
                      "input_schema": _ONE_ID, "fn": _lookup},
    "cancel_record": {"description": "Solicita cancelamento. Exige confirmação do cliente.", "write": True,
                      "input_schema": _ONE_ID, "fn": _cancel},
    "refund_record": {"description": "Solicita estorno. Exige confirmação do cliente e aprovação de um atendente.",
                      "write": True, "risk": "high", "input_schema": _ONE_ID, "fn": _refund},
}
TOOLS = {**DOMAIN_TOOLS, **KIT_TOOLS}
