"""Tests d'acceptation KAN-53 : gouvernance des clés d'API LLM par tenant.

Chaque test vérifie un contrat de comportement (CA1 à CA6), sur une vraie base SQLite
temporaire et une horloge injectée, sans mock du code testé.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from olympe.llm_key_governance import GovernanceError, LLMGovernance

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "scripts" / "iam" / "llm_key_governance_cli.py"

# Valeurs factices générées pour les tests, jamais des secrets réels.
OLD_VALUE = "test-old-" + "a1b2c3d4" * 3
NEW_VALUE = "test-new-" + "e5f6a7b8" * 3


class Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


@pytest.fixture
def clock():
    return Clock(datetime(2026, 10, 17, 9, 0, 0, tzinfo=timezone.utc))


@pytest.fixture
def alerts_seen():
    return []


@pytest.fixture
def gov(tmp_path, clock, alerts_seen):
    return LLMGovernance(tmp_path / "gov.db", clock=clock, alert_sink=alerts_seen.append)


def _register(gov, key_value=OLD_VALUE):
    return gov.register_key(
        "openrouter-acme", "OpenRouter", "acme", "env:OPENROUTER_API_KEY@orso-client-acme",
        "svc-orso-ops", key_value=key_value, last_rotation="2026-10-01T00:00:00+00:00",
    )


def test_ca1_inventory_lists_fields_and_never_a_value(gov, tmp_path):
    _register(gov)
    gov.register_key("openai-shared", "openai", "*", "env:OPENAI_API_KEY@olympe", "svc-orso-ops")
    rows = gov.inventory()
    assert {r["key_id"] for r in rows} == {"openrouter-acme", "openai-shared"}
    assert set(rows[0]) == {"key_id", "provider", "tenant_slug", "location", "owner", "last_rotation"}
    table = gov.inventory_markdown()
    assert "mutualisée" in table and "openrouter" in table
    assert OLD_VALUE not in table and OLD_VALUE not in json.dumps(rows)
    # CA5 : même la base ne contient pas la valeur en clair
    assert OLD_VALUE.encode() not in (tmp_path / "gov.db").read_bytes()


@pytest.mark.parametrize("bad", ["sk-" + "x" * 30, "AIza" + "Z" * 30, "a1" * 20])
def test_ca5_inventory_refuses_secret_like_fields(gov, bad):
    with pytest.raises(GovernanceError):
        gov.register_key("k1", "openai", "acme", bad, "svc-orso-ops")
    assert gov.inventory() == []


def test_ca2_cap_refuses_and_raises_timestamped_alert(gov, clock, alerts_seen):
    gov.set_policy("acme", 10.0, mode="refuse")
    assert gov.authorize("acme", "openrouter", "m-1", 2.0)["allowed"] is True
    gov.record_call("acme", "openrouter", "m-1", 9.5)
    decision = gov.authorize("acme", "openrouter", "m-1", 2.0)
    assert decision["allowed"] is False
    assert decision["reason"] == "cap_exceeded"
    assert decision["cap_usd"] == 10.0 and decision["spent_usd"] == 9.5
    cap_alerts = [a for a in alerts_seen if a["kind"] == "cap_exceeded"]
    assert len(cap_alerts) == 1
    assert cap_alerts[0]["ts"] == "2026-10-17T09:00:00+00:00" and cap_alerts[0]["refused"] is True
    refused = [c for c in gov.audit("acme") if c["decision"] == "refused"]
    assert len(refused) == 1 and refused[0]["cost_usd"] == 0.0
    # une dépense refusée ne consomme pas le plafond
    assert gov.period_spend("acme") == 9.5


def test_ca2_exhausted_budget_refuses_even_without_estimate(gov):
    gov.set_policy("acme", 5.0)
    gov.record_call("acme", "openrouter", "m-1", 5.0)
    assert gov.authorize("acme", "openrouter", "m-1")["allowed"] is False


def test_cap_is_per_tenant_and_resets_next_month(gov, clock):
    gov.set_policy("acme", 5.0)
    gov.record_call("acme", "openrouter", "m-1", 5.0)
    assert gov.authorize("globex", "openrouter", "m-1", 4.0)["allowed"] is True
    clock.now = datetime(2026, 11, 1, 0, 0, 1, tzinfo=timezone.utc)
    assert gov.authorize("acme", "openrouter", "m-1", 4.0)["allowed"] is True


def test_alert_only_mode_allows_but_alerts(gov, alerts_seen):
    gov.set_policy("acme", 5.0, mode="alert_only")
    gov.record_call("acme", "openrouter", "m-1", 5.0)
    decision = gov.authorize("acme", "openrouter", "m-1", 1.0)
    assert decision["allowed"] is True and decision["reason"] == "cap_exceeded"
    assert any(a["kind"] == "cap_exceeded" and a["refused"] is False for a in alerts_seen)


def test_default_policy_applies_to_unconfigured_tenants(gov):
    gov.set_policy("*", 3.0)
    gov.record_call("newco", "openrouter", "m-1", 3.0)
    assert gov.get_policy("newco")["source"] == "default"
    assert gov.authorize("newco", "openrouter", "m-1")["allowed"] is False


def test_ca3_threshold_alerts_fire_once_with_configured_threshold(gov, alerts_seen):
    gov.set_policy("acme", 100.0, thresholds=[0.5, 0.8])
    gov.record_call("acme", "openrouter", "m-1", 40.0)
    assert alerts_seen == []
    gov.record_call("acme", "openrouter", "m-1", 15.0)
    gov.record_call("acme", "openrouter", "m-1", 1.0)
    thr = [a for a in alerts_seen if a["kind"] == "threshold"]
    assert len(thr) == 1
    assert thr[0]["threshold_ratio"] == 0.5 and thr[0]["threshold_usd"] == 50.0
    assert thr[0]["spent_usd"] == 55.0 and thr[0]["ts"].startswith("2026-10-17T09:00:00")
    gov.record_call("acme", "openrouter", "m-1", 30.0)
    assert [a["threshold_ratio"] for a in alerts_seen if a["kind"] == "threshold"] == [0.5, 0.8]


def test_ca3_drift_alert_when_today_exceeds_baseline(gov, clock, alerts_seen):
    gov.set_policy("acme", None)
    for _ in range(7):
        clock.advance(days=-1)
        gov.record_call("acme", "openrouter", "m-1", 2.0)
    clock.now = datetime(2026, 10, 17, 9, 0, 0, tzinfo=timezone.utc)
    alerts_seen.clear()
    gov.record_call("acme", "openrouter", "m-1", 3.0)  # sous le seuil absolu de dérive
    assert alerts_seen == []
    gov.record_call("acme", "openrouter", "m-1", 20.0)
    drift = [a for a in alerts_seen if a["kind"] == "drift"]
    assert len(drift) == 1 and drift[0]["today_usd"] == 23.0 and drift[0]["drift_factor"] == 3.0
    gov.record_call("acme", "openrouter", "m-1", 5.0)
    assert len([a for a in alerts_seen if a["kind"] == "drift"]) == 1


def test_failing_alert_sink_never_blocks_the_call(tmp_path, clock):
    def boom(_event):
        raise RuntimeError("canal HS")

    gov = LLMGovernance(tmp_path / "g.db", clock=clock, alert_sink=boom)
    gov.set_policy("acme", 1.0)
    gov.record_call("acme", "openrouter", "m-1", 1.0)
    assert len(gov.alerts("acme")) >= 1


def test_ca6_audit_log_is_queryable_and_exportable(gov, clock):
    gov.record_call("acme", "OpenRouter", "m-1", 0.25, 100, 50, key_id="openrouter-acme", session_id="s1")
    clock.advance(hours=2)
    gov.record_call("globex", "openai", "m-2", 1.5, 10, 5)
    only_acme = gov.audit("acme")
    assert len(only_acme) == 1
    row = only_acme[0]
    assert (row["tenant_slug"], row["provider"], row["model"], row["cost_usd"]) == ("acme", "openrouter", "m-1", 0.25)
    assert row["ts"] == "2026-10-17T09:00:00+00:00" and row["decision"] == "allowed"
    assert len(gov.audit(since="2026-10-17T10:00:00+00:00")) == 1
    csv_text = gov.audit_csv()
    assert csv_text.splitlines()[0].startswith("ts,tenant_slug,provider,model,cost_usd")
    assert "globex" in csv_text and "acme" in csv_text


def test_ca4_rotation_grace_then_old_key_refused(gov, clock, tmp_path):
    _register(gov)
    assert gov.verify_key("openrouter-acme", OLD_VALUE)["status"] == "active"
    result = gov.rotate_key("openrouter-acme", NEW_VALUE, "svc-orso-rotation", grace_seconds=600)
    assert result["grace_until"] == "2026-10-17T09:10:00+00:00"
    assert gov.get_key("openrouter-acme")["last_rotation"] == "2026-10-17T09:00:00+00:00"
    assert gov.verify_key("openrouter-acme", NEW_VALUE)["status"] == "active"
    # fenêtre de grâce : une session ouverte avec l'ancienne valeur n'est pas coupée
    during = gov.verify_key("openrouter-acme", OLD_VALUE)
    assert during["status"] == "grace" and during["accepted"] is True
    clock.advance(minutes=10, seconds=1)
    after = gov.verify_key("openrouter-acme", OLD_VALUE)
    assert after["status"] == "revoked" and after["accepted"] is False
    assert gov.verify_key("openrouter-acme", NEW_VALUE)["accepted"] is True
    assert gov.verify_key("openrouter-acme", "valeur-inconnue-xyz")["status"] == "unknown"
    events = [e["event"] for e in gov.rotation_log("openrouter-acme")]
    assert events == ["rotation_started", "new_key_activated", "old_key_grace_open",
                      "old_key_revoked", "verification_refused", "verification_refused"]
    assert all(e["ts"] for e in gov.rotation_log())
    dump = json.dumps(gov.rotation_log()) + (tmp_path / "gov.db").read_bytes().decode("latin-1")
    assert OLD_VALUE not in dump and NEW_VALUE not in dump


def test_ca4_rotation_with_zero_grace_refuses_old_value_immediately(gov):
    _register(gov)
    gov.rotate_key("openrouter-acme", NEW_VALUE, "svc-orso-rotation", grace_seconds=0)
    assert gov.verify_key("openrouter-acme", OLD_VALUE)["status"] == "revoked"


def test_two_successive_rotations_keep_every_old_value_refused(gov, clock):
    _register(gov)
    gov.rotate_key("openrouter-acme", NEW_VALUE, "svc-orso-rotation", grace_seconds=60)
    third = "test-3rd-" + "c9d8e7f6" * 3
    clock.advance(minutes=5)
    gov.rotate_key("openrouter-acme", third, "svc-orso-rotation", grace_seconds=60)
    clock.advance(minutes=5)
    for old in (OLD_VALUE, NEW_VALUE):
        assert gov.verify_key("openrouter-acme", old)["accepted"] is False
    assert gov.verify_key("openrouter-acme", third)["accepted"] is True


def test_rotation_requires_service_account_and_a_different_value(gov):
    _register(gov)
    for actor in ("thibaut@example.com", "", "X"):
        with pytest.raises(GovernanceError):
            gov.rotate_key("openrouter-acme", NEW_VALUE, actor)
    with pytest.raises(GovernanceError):
        gov.rotate_key("openrouter-acme", OLD_VALUE, "svc-orso-rotation")
    assert gov.rotation_log() == []
    assert gov.verify_key("openrouter-acme", OLD_VALUE)["status"] == "active"


def _cli(args, db, env_extra=None, stdin=None):
    env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(CLI), "--db", str(db), *args],
        capture_output=True, text=True, env=env, input=stdin, cwd=str(REPO_ROOT), timeout=60,
    )


def test_cli_end_to_end_cap_and_rotation_exit_codes(tmp_path):
    db = tmp_path / "cli.db"
    reg = _cli(["register", "--key-id", "k-acme", "--provider", "openrouter", "--tenant", "acme",
                "--location", "env:OPENROUTER_API_KEY@orso-client-acme", "--owner", "svc-orso-ops",
                "--key-env", "TEST_KEY_VALUE"], db, {"TEST_KEY_VALUE": OLD_VALUE})
    assert reg.returncode == 0, reg.stderr
    assert _cli(["set-policy", "--tenant", "acme", "--cap-usd", "1"], db).returncode == 0
    assert _cli(["record", "--tenant", "acme", "--provider", "openrouter", "--model", "m",
                 "--cost-usd", "1"], db).returncode == 0
    refused = _cli(["authorize", "--tenant", "acme", "--provider", "openrouter", "--model", "m"], db)
    assert refused.returncode == 3
    assert json.loads(refused.stdout)["reason"] == "cap_exceeded"
    rot = _cli(["rotate", "--key-id", "k-acme", "--actor", "svc-orso-rotation", "--new-key-stdin",
                "--grace-seconds", "0"], db, stdin=NEW_VALUE + "\n")
    assert rot.returncode == 0, rot.stderr
    old = _cli(["verify", "--key-id", "k-acme", "--key-env", "TEST_KEY_VALUE"], db, {"TEST_KEY_VALUE": OLD_VALUE})
    assert old.returncode == 4 and json.loads(old.stdout)["status"] == "revoked"
    new = _cli(["verify", "--key-id", "k-acme", "--key-stdin"], db, stdin=NEW_VALUE + "\n")
    assert new.returncode == 0
    everything = reg.stdout + rot.stdout + old.stdout + new.stdout + _cli(["rotation-log"], db).stdout
    assert OLD_VALUE not in everything and NEW_VALUE not in everything
