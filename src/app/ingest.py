"""Ingestão do corpus: baixa páginas do site da Getnet Brasil e grava trechos literais em JSONL.

Uso: .venv/Scripts/python.exe -m app.ingest [--out data/knowledge/produtos]

Cada linha: {id, title, url, text, fetched_at, sha256}. `text` é recorte literal do HTML (só texto visível,
sem menu/rodapé), agrupado em trechos de 300–800 caracteres. Linha que se repete em metade das páginas ou mais é chrome do
site (menu, banner de cookie) e sai. Só domínios do Brasil: getnet.net/pt é Portugal e fica de fora.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

ALLOWED_HOSTS = {"site.getnet.com.br", "getnet.com.br", "www.getnet.com.br"}
MIN_CHARS, MAX_CHARS = 300, 800

# slug -> URL. Páginas de produto (maquininhas, Pix, link, crediário, antecipação, tarifas, conta).
PRODUCT_PAGES = {
    "todas-as-maquininhas": "https://site.getnet.com.br/todas-as-maquininhas/",
    "maquininha-de-cartao": "https://site.getnet.com.br/maquininha-de-cartao/",
    "get-tap": "https://site.getnet.com.br/get-tap/",
    "pix": "https://site.getnet.com.br/pix/",
    "link-de-pagamento": "https://site.getnet.com.br/link-de-pagamento/",
    "crediario": "https://site.getnet.com.br/crediario/",
    "antecipacao": "https://site.getnet.com.br/get-ajuda-reserva-financeira/antecipacao-reserva-financeira/",
    "taxas": "https://site.getnet.com.br/taxas/",
    "conta-digital": "https://site.getnet.com.br/conta-digital/",
    "getcheckout": "https://site.getnet.com.br/getcheckout/",
    "tef": "https://site.getnet.com.br/tef/solucao-tef/",
    "home": "https://site.getnet.com.br/",
    # Artigos do blog Getnet BR sobre os mesmos produtos (detalhe que a página de venda não traz).
    "blog-melhor-maquininha": "https://site.getnet.com.br/melhor-maquininha-para-o-seu-negocio/",
    "blog-funcionalidades-maquininha": "https://site.getnet.com.br/5-funcionalidades-da-maquininha-getnet-para-vender-mais/",
    "blog-tap-on-phone": "https://site.getnet.com.br/tap-on-phone-maquininha-no-celular/",
    "blog-get-tap": "https://site.getnet.com.br/get-tap-maquininha-de-cartao/",
    "blog-pix-maquininha": "https://site.getnet.com.br/pix-na-maquininha-getnet/",
    "blog-pix-aproximacao": "https://site.getnet.com.br/pix-por-aproximacao/",
    "blog-link-pagamento": "https://site.getnet.com.br/link-de-pagamento-getnet/",
    "blog-whatsapp": "https://site.getnet.com.br/vender-pelo-whatsapp/",
    "blog-antecipar": "https://site.getnet.com.br/quando-vale-a-pena-antecipar-as-suas-vendas-no-cartao/",
    "blog-conta-digital": "https://site.getnet.com.br/conta-digital-getnet/",
}

SKIP_TAGS = {"script", "style", "noscript", "svg", "header", "footer", "nav", "template", "iframe", "form"}
BLOCK_TAGS = {
    "p", "div", "section", "article", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "br", "tr",
    "td", "th", "table", "dt", "dd", "button", "a", "span_block", "summary", "details", "main", "aside",
}


def is_allowed(url: str) -> bool:
    return urlparse(url).hostname in ALLOWED_HOSTS


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._buf: list[str] = []
        self._skip = 0
        self.title = ""
        self._in_title = False

    def _flush(self) -> None:
        line = re.sub(r"\s+", " ", "".join(self._buf)).strip()
        if line:
            self.lines.append(line)
        self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        if tag in BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        if tag in BLOCK_TAGS:
            self._flush()

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self._buf.append(data)

    def close(self):
        super().close()
        self._flush()


def extract(html: str) -> tuple[str, list[str]]:
    p = _TextExtractor()
    p.feed(html)
    p.close()
    title = re.sub(r"\s+", " ", p.title).strip()
    return title, p.lines


def chunk(lines: list[str], lo: int = MIN_CHARS, hi: int = MAX_CHARS) -> list[str]:
    """Agrupa linhas consecutivas em trechos de lo..hi caracteres; linha maior que hi é cortada em frase."""
    pieces: list[str] = []
    for line in lines:
        if len(line) <= hi:
            pieces.append(line)
            continue
        cur = ""
        for sent in re.split(r"(?<=[.!?])\s+", line):
            if cur and len(cur) + 1 + len(sent) > hi:
                pieces.append(cur)
                cur = sent
            else:
                cur = f"{cur} {sent}".strip()
        if cur:
            pieces.append(cur[:hi])
    out: list[str] = []
    cur = ""
    for piece in pieces:
        if cur and len(cur) + 1 + len(piece) > hi:
            if len(cur) >= lo:
                out.append(cur)
                cur = piece
                continue
            cur = ""  # sobra curta que não cabe com a próxima peça: descarta (abaixo do mínimo)
        cur = f"{cur} {piece}".strip()
        if len(cur) >= lo and piece.endswith((".", "!", "?", ":")):
            out.append(cur)
            cur = ""
    if len(cur) >= lo:
        out.append(cur)
    elif cur and out and len(out[-1]) + 1 + len(cur) <= hi:
        out[-1] = f"{out[-1]} {cur}"
    return [c for c in out if lo <= len(c) <= hi]


def records(slug: str, url: str, title: str, chunks: list[str], fetched_at: str) -> list[dict]:
    return [
        {
            "id": f"prod-{slug}-{i:02d}",
            "title": title,
            "url": url,
            "text": text,
            "fetched_at": fetched_at,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
        for i, text in enumerate(chunks, 1)
    ]


def fetch(url: str) -> str:
    if not is_allowed(url):
        raise ValueError(f"domínio fora do Brasil: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (getnet-support-agents ingest)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def build(pages: dict[str, str], out_dir: Path) -> dict[str, list[dict]]:
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    parsed = {slug: (url, *extract(fetch(url))) for slug, url in pages.items()}
    freq = Counter(line for _, _, lines in parsed.values() for line in set(lines))
    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, list[dict]] = {}
    seen: set[str] = set()
    for slug, (url, title, lines) in parsed.items():
        body = [ln for ln in lines if freq[ln] < max(3, len(parsed) // 2) and len(ln) >= 15]
        recs = []
        for r in records(slug, url, title, chunk(body), fetched_at):
            if r["sha256"] not in seen:
                seen.add(r["sha256"])
                recs.append(r)
        result[slug] = recs
        with (out_dir / f"{slug}.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
            for r in recs:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/knowledge/produtos")
    args = ap.parse_args()
    result = build(PRODUCT_PAGES, Path(args.out))
    for slug, recs in result.items():
        print(f"{slug}: {len(recs)} trechos")
    print(f"total: {sum(len(r) for r in result.values())}")


if __name__ == "__main__":
    main()
