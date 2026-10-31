from pathlib import Path

import pytest

from app import notify
from app.auth import LIMITER
from app.config import ROOT
from app.observability import configure_otel
from evals import judge, run_evals

# Dados do kit: os testes do kit nunca leem o que o domínio troca no relógio (data/, retrieval, calibração).
# Getnet v3 (31/10/2026): trocar só os dados quebrava 24 de 187 testes e atrasou o G1 em 17 min (regra D2).
KIT_DATA = Path(__file__).parent / "fixtures" / "kit_data"


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    # Cada teste com banco próprio, modo offline, sem rede e segredos conhecidos: nada vaza entre testes.
    monkeypatch.setenv("DATA_DIR", str(KIT_DATA / "data"))
    monkeypatch.setattr(run_evals, "RETRIEVAL", KIT_DATA / "retrieval.jsonl")
    monkeypatch.setattr(judge, "CALIBRATION", KIT_DATA / "judge_calibration.jsonl")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("LLM_PROVIDER", "offline")
    monkeypatch.setenv("AUTH_MODE", "required")
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("OPERATOR_TOKEN", "test-operator")
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "1000")
    monkeypatch.setenv("RETRIEVER", "bm25")
    monkeypatch.setenv("SLA_CHECK_SECONDS", "0")  # sem laço de SLA em segundo plano nos servidores de teste
    for var in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_WEBHOOK_SECRET", "OTEL_EXPORTER",
                "SUPERVISOR_PARALLEL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(notify, "_transport", None)
    LIMITER.reset()
    yield
    LIMITER.reset()
    configure_otel(None)  # desliga o exportador se algum teste ligou


@pytest.fixture
def domain_data(monkeypatch):
    """Para testes do DOMÍNIO (escritos no relógio): usa data/ e evals/ reais em vez da fixture do kit."""
    monkeypatch.setenv("DATA_DIR", str(ROOT / "data"))
    monkeypatch.setattr(run_evals, "RETRIEVAL", ROOT / "evals" / "retrieval.jsonl")
    monkeypatch.setattr(judge, "CALIBRATION", ROOT / "evals" / "judge_calibration.jsonl")
