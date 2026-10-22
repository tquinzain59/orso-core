"""Tests d'acceptation KAN-128 : observabilité et reprise de l'exécution exposées au client.

- CA1 : une exécution produit une trace de haut niveau, datée, avec ses artefacts, consultable côté client.
- CA2 : un échec en cours d'exécution est rejoué automatiquement, puis signalé au client s'il persiste.
- CA3 : rien d'interne n'apparaît côté client (identifiants, étapes, erreurs techniques, modèle).
- CA4 : conservation 30 jours puis purge réelle.
- CA5 : aucun secret en clair dans les traces (désignation par emplacement).

Le moteur (``run_agent.AIAgent``) est simulé : on teste la couche maison, pas la boucle Hermès.
"""

import base64
import hashlib
import hmac
import json
import sqlite3
import sys
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hermes_cli.web_routers import client_run_replay
from hermes_cli.web_routers.client_run_replay import RunFailure, run_with_replay
from hermes_cli.web_routers.client_run_traces import (
    FAILURE_NOTICE,
    RETENTION_DAYS,
    STEP_CATALOG,
    RunRecorder,
    purge_expired_traces,
    read_internal_diagnostics,
    scrub_secrets,
)
from hermes_cli.web_routers.client_ui import router as client_ui_router

TENANT = "f3e25379-6531-479e-b276-3b3185e7421b"
INTERNAL_MODEL = "deepseek/deepseek-v4-flash"
INTERNAL_ERROR = "boom-erreur-interne-xyz"
DAY = 86400.0


def _jwt(user_id: str, tenant_id: str = TENANT) -> str:
    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode().rstrip("=")

    payload = {
        "sub": user_id,
        "exp": int(time.time()) + 3600,
        "tenant": {"tenant_id": tenant_id, "tenant_slug": "financia", "role": "admin", "agents": ["jerome"]},
    }
    head = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = b64(json.dumps(payload).encode())
    sig = hmac.new(b"test-secret", f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{b64(sig)}"


def _auth(user_id: str = "sophie-martin", tenant_id: str = TENANT) -> dict:
    return {"Authorization": f"Bearer {_jwt(user_id, tenant_id)}"}


def _sse(body: str) -> list:
    events = []
    for block in body.strip().split("\n\n"):
        lines = block.split("\n")
        name = next(line[7:] for line in lines if line.startswith("event: "))
        data = next(line[6:] for line in lines if line.startswith("data: "))
        events.append((name, json.loads(data)))
    return events


class _ScriptedAgent:
    """Faux AIAgent : chaque instanciation consomme un comportement du script."""

    script: list = []
    calls = 0

    def __init__(self, **kwargs):
        type(self).calls += 1
        self._behavior = type(self).script.pop(0) if type(self).script else "ok"

    def run_conversation(self, user_message, conversation_history, stream_callback):
        if self._behavior == "raise":
            stream_callback("texte partiel ")
            raise RuntimeError(INTERNAL_ERROR)
        if self._behavior == "empty":
            return {"final_response": ""}
        text = "Voici votre balance âgée : 3 factures en retard." if self._behavior == "ok" else self._behavior
        stream_callback(text)
        return {"final_response": text}


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret")
    monkeypatch.setenv("ORSO_CLIENT_ID", TENANT)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-clef-openrouter-secrete-0123456789")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("ORSO_TEST_MODE", raising=False)
    monkeypatch.setattr(
        "hermes_cli.web_routers.client_ui._get_client_sessions_db_path",
        lambda: tmp_path / "client_chat_sessions.db",
    )
    monkeypatch.setattr("hermes_cli.web_routers.client_ui.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(client_run_replay, "REPLAY_BACKOFF_SECONDS", ())
    _ScriptedAgent.script = []
    _ScriptedAgent.calls = 0
    monkeypatch.setitem(sys.modules, "run_agent", SimpleNamespace(AIAgent=_ScriptedAgent))
    app = FastAPI()
    app.include_router(client_ui_router)
    return TestClient(app), tmp_path


def _chat(client, session_id="session-kan128", user="sophie-martin", message="Analyse la balance"):
    res = client.post(
        "/api/client/chat",
        json={"agent_id": "jerome", "message": message, "session_id": session_id},
        headers=_auth(user),
    )
    assert res.status_code == 200
    return _sse(res.text)


def _trace_id(events) -> str:
    return next(d["trace_id"] for n, d in events if n == "done")


def _traces_db(tmp_path):
    return sqlite3.connect(str(tmp_path / "client_run_traces.db"))


# ── Rejeu (unité) ────────────────────────────────────────────────────────────


def test_replay_succeeds_after_transient_failure():
    seen = []

    def attempt(n):
        if n < 3:
            raise RunFailure(f"échec {n}")
        return "ok"

    out = run_with_replay(attempt, max_replays=2, on_replay=lambda n, e: seen.append(n), sleep=lambda s: None)
    assert (out.result, out.failed, out.attempts, out.replays, seen) == ("ok", False, 3, 2, [1, 2])


def test_replay_gives_up_after_max_replays():
    out = run_with_replay(lambda n: (_ for _ in ()).throw(RunFailure("x")), max_replays=2, sleep=lambda s: None)
    assert out.failed and out.attempts == 3 and len(out.errors) == 3 and out.result is None


# ── CA1 ──────────────────────────────────────────────────────────────────────


def test_ca1_run_produces_dated_high_level_trace_with_artifacts(env):
    client, _ = env
    events = _chat(client)
    assert [n for n, _ in events if n in ("start", "done")] == ["start", "done"]
    trace_id = _trace_id(events)
    assert trace_id == next(d["trace_id"] for n, d in events if n == "start")

    res = client.get(f"/api/client/runs/{trace_id}", headers=_auth())
    assert res.status_code == 200
    trace = res.json()
    assert trace["status"] == "completed" and trace["replays"] == 0
    assert [s["label"] for s in trace["steps"]] == [
        STEP_CATALOG["run_started"],
        STEP_CATALOG["response_prepared"],
        STEP_CATALOG["run_completed"],
    ]
    assert all(s["at"].endswith("+00:00") for s in trace["steps"]) and trace["started_at"] and trace["ended_at"]
    assert [a["name"] for a in trace["artifacts"]] == ["reponse.txt"]

    art = client.get(f"/api/client/runs/{trace_id}/artifacts/reponse.txt", headers=_auth()).json()
    assert "3 factures en retard" in art["content"]

    listing = client.get("/api/client/runs", headers=_auth()).json()
    assert [r["trace_id"] for r in listing["runs"]] == [trace_id]


def test_ca1_action_card_is_an_artifact(env):
    client, _ = env
    card = '```action_card\n{"id": "a1", "agentId": "jerome", "title": "Relance", "type": "invoice_reminder"}\n```'
    _ScriptedAgent.script = [f"Je prépare la relance.\n{card}"]
    trace = client.get(f"/api/client/runs/{_trace_id(_chat(client))}", headers=_auth()).json()
    assert {a["name"] for a in trace["artifacts"]} == {"reponse.txt", "carte_action.json"}
    assert STEP_CATALOG["action_proposed"] in [s["label"] for s in trace["steps"]]


# ── CA2 ──────────────────────────────────────────────────────────────────────


def test_ca2_transient_failure_is_replayed_without_client_alert(env):
    client, _ = env
    _ScriptedAgent.script = ["raise", "ok"]
    events = _chat(client)
    names = [n for n, _ in events]
    assert names.count("run_retry") == 1 and "run_failed" not in names
    assert _ScriptedAgent.calls == 2
    assert "3 factures en retard" in next(d["full_text"] for n, d in events if n == "done")
    trace = client.get(f"/api/client/runs/{_trace_id(events)}", headers=_auth()).json()
    assert trace["status"] == "completed" and trace["replays"] == 1 and trace["failure_notice"] is None
    assert STEP_CATALOG["run_replayed"] in [s["label"] for s in trace["steps"]]


def test_ca2_persistent_failure_is_replayed_then_reported_to_client(env):
    client, tmp_path = env
    _ScriptedAgent.script = ["raise", "empty", "raise"]
    events = _chat(client)
    names = [n for n, _ in events]
    assert _ScriptedAgent.calls == 3  # 1 tentative + 2 rejeux automatiques
    assert names.count("run_retry") == 2
    failed = [d for n, d in events if n == "run_failed"]
    assert failed == [{"message": FAILURE_NOTICE}]
    assert names.index("run_retry") < names.index("run_failed") < names.index("done")

    trace = client.get(f"/api/client/runs/{_trace_id(events)}", headers=_auth()).json()
    assert trace["status"] == "failed" and trace["replays"] == 2 and trace["failure_notice"] == FAILURE_NOTICE
    assert trace["steps"][-1]["label"] == STEP_CATALOG["run_failed"]
    assert trace["artifacts"] == []

    diag = read_internal_diagnostics(trace["trace_id"])
    assert [d["attempt"] for d in diag] == [1, 2, 3]
    assert INTERNAL_ERROR in diag[0]["error_detail"]


def test_ca2_failed_runs_filterable_by_status(env):
    client, _ = env
    _ScriptedAgent.script = ["raise", "raise", "raise"]
    _chat(client, session_id="s-fail")
    _chat(client, session_id="s-ok")
    failed = client.get("/api/client/runs?status=failed", headers=_auth()).json()["runs"]
    assert len(failed) == 1 and failed[0]["status"] == "failed"


# ── CA3 ──────────────────────────────────────────────────────────────────────


def test_ca3_client_trace_contains_nothing_internal(env):
    client, _ = env
    _ScriptedAgent.script = ["raise", "raise", "raise"]
    events = _chat(client, session_id="session-secret-interne", user="sophie-martin")
    trace_id = _trace_id(events)
    raw = client.get(f"/api/client/runs/{trace_id}", headers=_auth()).text
    raw += client.get("/api/client/runs", headers=_auth()).text
    for forbidden in (
        TENANT,
        "financia",
        "sophie-martin",
        "session-secret-interne",
        INTERNAL_ERROR,
        INTERNAL_MODEL,
        "openrouter",
        "RuntimeError",
        "tool_call",
        "attempt",
    ):
        assert forbidden not in raw, forbidden


def test_ca3_trace_view_keys_are_a_closed_whitelist(env):
    client, _ = env
    trace = client.get(f"/api/client/runs/{_trace_id(_chat(client))}", headers=_auth()).json()
    assert set(trace) == {
        "trace_id", "agent", "status", "status_label", "started_at", "ended_at",
        "replays", "failure_notice", "expires_at", "steps", "artifacts",
    }
    assert all(set(s) == {"at", "label"} for s in trace["steps"])


def test_ca3_step_outside_client_catalog_is_refused(env):
    client, _ = env
    recorder = RunRecorder(TENANT, "u", "jerome", "s")
    with pytest.raises(ValueError):
        recorder.step("turn_preflight")
    with pytest.raises(ValueError):
        recorder.artifact("x.txt", "tool_trace", "contenu")


def test_ca3_traces_are_isolated_per_user_and_tenant(env):
    client, _ = env
    trace_id = _trace_id(_chat(client, user="sophie-martin"))
    assert client.get(f"/api/client/runs/{trace_id}", headers=_auth("paul-durand")).status_code == 404
    assert client.get(f"/api/client/runs/{trace_id}/artifacts/reponse.txt", headers=_auth("paul-durand")).status_code == 404
    assert client.get("/api/client/runs", headers=_auth("paul-durand")).json()["runs"] == []
    assert client.get(f"/api/client/runs/{trace_id}").status_code == 401


# ── CA4 ──────────────────────────────────────────────────────────────────────


def _age_trace(tmp_path, trace_id, days):
    with _traces_db(tmp_path) as conn:
        conn.execute("UPDATE client_run_traces SET started_at = ? WHERE trace_id = ?", (time.time() - days * DAY, trace_id))


def test_ca4_trace_readable_before_30_days_absent_after(env, monkeypatch):
    client, tmp_path = env
    recent = _trace_id(_chat(client, session_id="s-recent"))
    old = _trace_id(_chat(client, session_id="s-old"))
    _age_trace(tmp_path, recent, RETENTION_DAYS - 1)
    _age_trace(tmp_path, old, RETENTION_DAYS + 1)
    # Même sans purge exécutée, une trace de plus de 30 jours n'est plus servie.
    monkeypatch.setattr("hermes_cli.web_routers.client_run_traces.purge_expired_traces", lambda *a, **k: 0)
    assert client.get(f"/api/client/runs/{recent}", headers=_auth()).status_code == 200
    assert client.get(f"/api/client/runs/{old}", headers=_auth()).status_code == 404
    assert [r["trace_id"] for r in client.get("/api/client/runs", headers=_auth()).json()["runs"]] == [recent]


def test_ca4_purge_physically_deletes_every_table(env):
    client, tmp_path = env
    _ScriptedAgent.script = ["raise", "raise", "raise"]
    old = _trace_id(_chat(client, session_id="s-old"))
    keep = _trace_id(_chat(client, session_id="s-keep"))
    _age_trace(tmp_path, old, RETENTION_DAYS + 1)
    assert purge_expired_traces() == 1
    with _traces_db(tmp_path) as conn:
        for table in ("client_run_traces", "client_run_steps", "client_run_artifacts", "client_run_internal"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE trace_id = ?", (old,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM client_run_traces WHERE trace_id = ?", (keep,)).fetchone()[0] == 1
    assert read_internal_diagnostics(old) == []


# ── CA5 ──────────────────────────────────────────────────────────────────────


def test_ca5_secrets_are_designated_by_location_never_in_clear(env):
    client, tmp_path = env
    env_secret = "sk-or-v1-clef-openrouter-secrete-0123456789"
    leaked = (
        f"Clé {env_secret} ; en-tête Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345 ; "
        "password=Sup3rMotDePasse! ; jeton eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4eHh4eHh4eHgifQ.c2lnbmF0dXJlc2lnbmF0dXJl"
    )
    _ScriptedAgent.script = [leaked]
    trace_id = _trace_id(_chat(client))
    art = client.get(f"/api/client/runs/{trace_id}/artifacts/reponse.txt", headers=_auth()).json()["content"]
    trace = client.get(f"/api/client/runs/{trace_id}", headers=_auth()).text
    assert "[SECRET:env:OPENROUTER_API_KEY]" in art
    for clear in (env_secret, "abcdefghijklmnopqrstuvwxyz012345", "Sup3rMotDePasse", "eyJhbGciOiJIUzI1NiJ9", "c2lnbmF0dXJl"):
        assert clear not in art and clear not in trace
    # Preuve brute côté stockage : aucune valeur secrète dans le fichier de base lui-même.
    assert env_secret.encode() not in (tmp_path / "client_run_traces.db").read_bytes()


def test_ca5_internal_diagnostics_are_scrubbed_too(env, monkeypatch):
    client, _ = env
    recorder = RunRecorder(TENANT, "u", "jerome", "s")
    recorder.internal_error(1, RuntimeError("401 avec api_key=sk-live-abcdefghijklmnop0123 refusée"))
    detail = read_internal_diagnostics(recorder.trace_id)[0]["error_detail"]
    assert "sk-live-abcdefghijklmnop0123" not in detail and "[SECRET:" in detail


def test_ca5_scrub_secrets_leaves_ordinary_text_untouched():
    text = "Relance de la facture FAC-2026-014 pour 1 250 € (échéance 15/08/2026)."
    assert scrub_secrets(text) == text
