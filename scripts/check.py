"""Check único do projeto: lint + testes + gate do eval [+ build e smoke do container].

Uso:
  python scripts/check.py            # rápido, a cada merge de fork (~10 s)
  python scripts/check.py --docker   # completo: imagem, /health com dados, eval via HTTP
  python scripts/check.py --docker --extras hybrid   # imagem com a busca híbrida (modelo embutido)

Funciona sem `make` (Windows). Sai com código 1 se qualquer etapa falhar e imprime o resumo.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
IMAGE = "app-check"
# Módulos que NÃO podem estar na imagem: dev (pytest/ruff) e extras opcionais (híbrido, OTel SDK) não pedidos.
FORBIDDEN_IN_IMAGE = ["pytest", "ruff", "fastembed", "opentelemetry.sdk"]
EXTRA_MODULES = {"hybrid": "fastembed", "otel": "opentelemetry.sdk"}
# Console do Windows é cp1252: sem isto, subprocesso que imprime acento/seta quebra com UnicodeEncodeError.
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


def sh(cmd: list[str], env: dict | None = None, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, check=False, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", env={**ENV, **(env or {})}, **kw)


def pytest_workers() -> list[str]:
    # 4 processos com pytest-xdist (extra dev); venv antiga sem ele roda em série em vez de quebrar o check.
    has_xdist = sh([PY, "-c", "import xdist"]).returncode == 0
    return ["-n", os.getenv("CHECK_WORKERS", "4")] if has_xdist else []


def step(name: str, cmd: list[str], env: dict | None = None) -> tuple[str, bool, float, str]:
    t0 = time.perf_counter()
    r = sh(cmd, env)
    out = (r.stdout + r.stderr).strip()
    return name, r.returncode == 0, time.perf_counter() - t0, out


def free_port() -> int:
    """Porta livre do sistema: nunca colide com um `docker compose up` na 8000 nem com outro check em paralelo."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_health(url: str, timeout_s: float = 60) -> dict | None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                return json.loads(resp.read())
        except Exception:
            time.sleep(1)
    return None


CHECK_SECRET = "check-secret-only-for-the-container-smoke"  # o container do smoke sobe com este AUTH_SECRET


def mcp_smoke(port: int) -> tuple[str, bool, float, str]:
    """/mcp no container: sem token → 401; com JWT → initialize responde com o nome do servidor."""
    t0 = time.perf_counter()
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "check", "version": "1"}}}).encode()
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}

    def post(extra: dict) -> tuple[int, str]:
        req = urllib.request.Request(f"http://localhost:{port}/mcp/", data=body, headers={**headers, **extra})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")

    anon, _ = post({})
    status, text = post({"Authorization": f"Bearer {_token()}"})
    ok = anon == 401 and status == 200 and "support-agents" in text
    return "mcp no container (401 sem token, initialize com JWT)", ok, time.perf_counter() - t0, \
        f"anônimo {anon}; autenticado {status}: {text[:200]}"


def _token() -> str:
    r = subprocess.run([PY, "-c", "from app.auth import issue_token; print(issue_token('u1'))"], cwd=ROOT / "src",
                       capture_output=True, text=True, env={**ENV, "AUTH_SECRET": CHECK_SECRET})
    return r.stdout.strip()


def docker_steps(extras: str = "") -> list[tuple[str, bool, float, str]]:
    build = ["docker", "build", "-q", "-t", IMAGE, "."]
    if extras:
        build[2:2] = ["--build-arg", f"EXTRAS={extras}"]
    results = [step("docker build" + (f" ({extras})" if extras else ""), build)]
    if not results[-1][1]:
        return results
    probe = ("import importlib.util as u, sys; bad = [m for m in sys.argv[1:] if u.find_spec(m)]; "
             "print('presentes:', bad or 'nenhum'); sys.exit(1 if bad else 0)")
    forbidden = [m for m in FORBIDDEN_IN_IMAGE if m != EXTRA_MODULES.get(extras)]
    results.append(step("imagem sem dev/extras", ["docker", "run", "--rm", IMAGE, "python", "-c", probe,
                                                   *forbidden]))
    sh(["docker", "rm", "-f", IMAGE])
    port = free_port()
    # O eval manda dezenas de requests/min como um só usuário; com o limite de produção (30/min) o próprio
    # rate limiter (correto) devolveria 429. O smoke sobe o container com limite alto.
    env = ["-e", "RATE_LIMIT_PER_MIN=1000", "-e", f"AUTH_SECRET={CHECK_SECRET}"] + (
        ["-e", "RETRIEVER=hybrid"] if extras == "hybrid" else [])
    run = step("docker run", ["docker", "run", "-d", "--name", IMAGE, *env, "-p", f"{port}:8000", IMAGE])
    results.append(run)
    if not run[1]:
        return results
    try:
        t0 = time.perf_counter()
        health = wait_health(f"http://localhost:{port}/health")
        ok = bool(health) and health.get("data_files", 0) > 0 and (
            extras != "hybrid" or health.get("retriever") == "hybrid")
        logs = "" if health else sh(["docker", "logs", IMAGE]).stdout[-2000:]
        detail = json.dumps(health) if health else f"sem resposta em 60 s: {logs}"
        results.append(("container /health com dados", ok, time.perf_counter() - t0, detail))
        if ok:
            # o token do eval é assinado com o mesmo segredo do container (senão 401)
            results.append(step("eval via HTTP", [PY, "-m", "evals.run_evals", "--url", f"http://localhost:{port}"],
                                env={"AUTH_SECRET": CHECK_SECRET}))
            results.append(mcp_smoke(port))
    finally:
        sh(["docker", "rm", "-f", IMAGE])
    return results


def main() -> int:
    for stream in (sys.stdout, sys.stderr):  # console cp1252 do Windows quebra acentos
        stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--docker", action="store_true", help="inclui build e smoke do container")
    ap.add_argument("--extras", default="", choices=["", "hybrid"], help="extra embutido na imagem")
    args = ap.parse_args()

    results = [
        step("ruff", [PY, "-m", "ruff", "check", "."]),
        step("pytest", [PY, "-m", "pytest", "-q", *pytest_workers()]),
        step("eval gate", [PY, "-m", "evals.run_evals"]),
    ]
    if args.docker:
        results += docker_steps(args.extras)

    failed = [r for r in results if not r[1]]
    for name, _ok, _, out in failed:
        print(f"\n=== {name} FALHOU ===\n{out[-3000:]}")
    print("\n| etapa | resultado | s |\n|---|---|---:|")
    for name, ok, secs, _ in results:
        print(f"| {name} | {'PASS' if ok else 'FAIL'} | {secs:.1f} |")
    print(f"\nCHECK {'VERDE' if not failed else 'VERMELHO'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
