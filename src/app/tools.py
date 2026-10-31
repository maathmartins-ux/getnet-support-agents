"""Ferramentas do domínio: o registro TOOLS (descrição, JSON Schema, função, `write`, `risk`).

Só o que muda por desafio mora aqui. A mecânica (identidade do servidor, confirmação do dono, aprovação do
operador, TTL, execução única) está em `actions.py` e não muda. Contrato de cada função: recebe os
argumentos do schema + `user_id` (sempre o autenticado, injetado pelo servidor) e devolve
{ok, data} ou {ok: False, error}. Mesma resposta para registro inexistente e de outro dono.

Ligação com o sistema de registro (CRM): `records()` é o adaptador. Hoje lê data/records.json; em produção,
troque o corpo por uma chamada à API do CRM, mantendo a assinatura (contrato testado em tests/test_tools.py).
"""
from __future__ import annotations

import json
from functools import lru_cache

from .config import data_dir

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
TOOLS = {
    "lookup_record": {"description": "Consulta um registro do cliente autenticado.", "write": False,
                      "input_schema": _ONE_ID, "fn": _lookup},
    "cancel_record": {"description": "Solicita cancelamento. Exige confirmação do cliente.", "write": True,
                      "input_schema": _ONE_ID, "fn": _cancel},
    # risco alto: move dinheiro → confirmação do dono E aprovação de um operador (actions.py)
    "refund_record": {"description": "Solicita estorno. Exige confirmação do cliente e aprovação de um atendente.",
                      "write": True, "risk": "high", "input_schema": _ONE_ID, "fn": _refund},
}
