"""Ingestão (fork A1): extração literal, tamanho dos trechos, só Brasil, e integridade do corpus commitado."""

import hashlib
import json
from pathlib import Path

import pytest

from app.ingest import MAX_CHARS, MIN_CHARS, chunk, extract, fetch, is_allowed, records

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data" / "knowledge" / "produtos"
EVALS = ROOT / "evals" / "retrieval.d" / "a1.jsonl"


def _corpus() -> list[dict]:
    return [json.loads(line) for f in sorted(CORPUS.glob("*.jsonl")) for line in f.read_text("utf-8").splitlines()]


def test_only_brazil_hosts():
    assert is_allowed("https://site.getnet.com.br/pix/")
    assert not is_allowed("https://www.getnet.net/pt/")  # Portugal
    assert not is_allowed("https://getnet.com.br.evil.example/")
    with pytest.raises(ValueError):
        fetch("https://www.getnet.net/pt/particulares")


def test_extract_drops_chrome_and_scripts():
    html = "<html><title>T</title><nav>Menu</nav><script>x=1</script><p>Texto <b>visível</b></p><footer>F</footer>"
    title, lines = extract(html)
    assert title == "T"
    assert lines == ["Texto visível"]


def test_chunk_respects_bounds_and_is_literal():
    lines = [f"Frase número {i} sobre a maquininha Getnet e o Pix." for i in range(60)]
    joined = " ".join(lines)
    chunks = chunk(lines)
    assert chunks
    for c in chunks:
        assert MIN_CHARS <= len(c) <= MAX_CHARS
        assert c in joined  # recorte literal, sem reescrita


def test_chunk_splits_long_line_by_sentence():
    long_line = " ".join(f"Sentença {i} do texto longo." for i in range(80))
    for c in chunk([long_line]):
        assert MIN_CHARS <= len(c) <= MAX_CHARS
        assert c in long_line


def test_records_shape():
    (r,) = records("pix", "https://site.getnet.com.br/pix/", "Pix", ["a" * 300], "2026-10-31T17:00:00+00:00")
    assert r["id"] == "prod-pix-01"
    assert r["sha256"] == hashlib.sha256(("a" * 300).encode()).hexdigest()
    assert set(r) == {"id", "title", "url", "text", "fetched_at", "sha256"}


def test_committed_corpus_integrity():
    docs = _corpus()
    assert len(docs) >= 80
    ids = [d["id"] for d in docs]
    assert len(ids) == len(set(ids))
    for d in docs:
        assert is_allowed(d["url"]), d["url"]
        assert MIN_CHARS <= len(d["text"]) <= MAX_CHARS, d["id"]
        assert d["sha256"] == hashlib.sha256(d["text"].encode("utf-8")).hexdigest(), d["id"]


def test_eval_questions_point_to_existing_ids():
    ids = {d["id"] for d in _corpus()}
    rows = [json.loads(line) for line in EVALS.read_text("utf-8").splitlines() if line.strip()]
    assert len(rows) >= 25
    for row in rows:
        assert row["relevant"] and set(row["relevant"]) <= ids, row["question"]


def test_glossary_has_domain_terms():
    gloss = json.loads((ROOT / "data" / "glossary.json").read_text("utf-8"))
    terms = {k: v for k, v in gloss.items() if not k.startswith("_")}
    assert len(terms) >= 30
    assert all(isinstance(v, list) and v for v in terms.values())
