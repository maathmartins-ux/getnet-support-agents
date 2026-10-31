"""Criação concorrente do banco: N threads abrindo o MESMO banco novo ao mesmo tempo.

Getnet v3 (31/10/2026): `_store_for` (lru_cache sem trava) deixou 4 threads do eval ao vivo criarem o Store
juntas; `PRAGMA journal_mode=WAL` exige lock exclusivo e devolveu "database is locked" para as perdedoras.
Caíram 7 respostas e o gate do split approval reprovou. Dois testes, duas causas:
- get_store() em paralelo: uma instância só por caminho (trava no cache, dentro do processo);
- Store(path) em paralelo: cobre réplicas/processos, onde trava de thread não alcança (retry no PRAGMA).
"""
import threading

import pytest

from app import store as store_mod
from app.store import Store, get_store

REPEATS = 20


def _race(n: int, fn) -> tuple[list, list[BaseException]]:
    barrier = threading.Barrier(n)
    results, errors = [], []
    lock = threading.Lock()

    def worker():
        try:
            barrier.wait()
            value = fn()
            with lock:
                results.append(value)
        except BaseException as exc:  # noqa: BLE001 - o teste quer ver qualquer erro
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    return results, errors


@pytest.mark.parametrize("threads", [4, 8])
def test_get_store_from_many_threads_on_a_new_db_never_fails(tmp_path, monkeypatch, threads):
    for i in range(REPEATS):
        monkeypatch.setenv("DB_PATH", str(tmp_path / f"race-{threads}-{i}.db"))
        store_mod._store_for.cache_clear()
        results, errors = _race(threads, get_store)
        assert errors == [], f"repetição {i}: {errors[:3]}"
        assert len({id(s) for s in results}) == 1  # uma instância por caminho, não uma por thread


@pytest.mark.parametrize("threads", [4, 8])
def test_store_constructor_from_many_threads_on_a_new_db_never_fails(tmp_path, threads):
    for i in range(REPEATS):
        path = tmp_path / f"ctor-{threads}-{i}.db"
        results, errors = _race(threads, lambda p=path: Store(p))
        assert errors == [], f"repetição {i}: {errors[:3]}"
        assert len(results) == threads
        results[0].add_message("c1", "u1", "user", "oi")  # o banco ficou utilizável
        assert results[-1].history("c1")[0]["content"] == "oi"
