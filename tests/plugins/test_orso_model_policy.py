"""KAN-127 — politique de modèle Orso : plafond, repli, conformité de route.

Contrats de comportement, exercés sur les vrais chemins (chaîne de middleware, transport
chat-completions, PluginManager, config livrée) contre un HERMES_HOME temporaire.
"""

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "orso_model_policy_check.py"


@pytest.fixture(scope="module")
def check():
    spec = importlib.util.spec_from_file_location("orso_model_policy_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def rt(check, tmp_path):
    now = [datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)]
    plugin, pol, policy, ledger, runtime = check._runtime(str(tmp_path), now)
    return plugin, pol, policy, ledger, runtime, now


def test_cap_blocks_the_provider_call_through_the_real_middleware_chain(rt, monkeypatch):
    """Au-delà du plafond, aucune requête n'atteint le fournisseur et le client reçoit le code de blocage ;
    la réponse synthétique est lue par le vrai transport chat-completions."""
    from hermes_cli.middleware import _run_execution_chain
    from agent.transports.chat_completions import ChatCompletionsTransport

    plugin, pol, policy, ledger, runtime, _ = rt
    monkeypatch.setattr(plugin, "_call_cost_usd", lambda *a, **k: policy.default_monthly_eur + 0.01)
    runtime.post_api_request(model=policy.primary_model, provider="openrouter", usage={"total_tokens": 1})

    sent = []
    manager_cb = [runtime.llm_execution]
    monkeypatch.setattr("hermes_cli.plugins.get_plugin_manager", lambda: type("M", (), {"_middleware": {"llm_execution": manager_cb}})())

    def provider(_req):
        sent.append(1)
        return "never"

    response = _run_execution_chain(
        "llm_execution", provider, request={"model": policy.primary_model}, original_request={},
        api_mode="chat_completions", model=policy.primary_model, session_id="s",
    )
    assert sent == []
    normalized = ChatCompletionsTransport().normalize_response(response)
    assert pol.CODE_CAP_BLOCKED in normalized.content
    assert any(e.get("code") == pol.CODE_CAP_BLOCKED and e.get("request_sent") is False for e in ledger.events())


def test_alert_then_block_thresholds_follow_the_policy_cap(rt):
    _, pol, policy, _, _, _ = rt
    cap = policy.default_monthly_eur
    assert cap == 20
    assert pol.evaluate_cap(policy, "c", cap * policy.alert_ratio - 0.01).status == pol.CAP_OK
    assert pol.evaluate_cap(policy, "c", cap * policy.alert_ratio).code == pol.CODE_CAP_ALERT
    assert pol.evaluate_cap(policy, "c", cap).code == pol.CODE_CAP_BLOCKED


def test_spend_resets_on_new_calendar_month(rt):
    _, _, policy, ledger, _, now = rt
    ledger.record_usage(provider="openrouter", model=policy.primary_model, cost_usd=19.0, usd_to_eur=1.0)
    assert ledger.spent_eur() == 19.0
    now[0] = datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)
    assert ledger.spent_eur() == 0.0


def test_fallback_is_traced_and_client_informed_once(rt):
    _, pol, policy, ledger, runtime, _ = rt
    runtime.pre_api_request(model=policy.primary_model, provider="openrouter", session_id="s")
    runtime.api_request_error(model=policy.primary_model, status_code=503, reason="down", session_id="s")
    runtime.pre_api_request(model=policy.fallback_model, provider="openrouter", session_id="s")
    first = runtime.transform_llm_output(response_text="ok", session_id="s", model=policy.fallback_model)
    assert pol.CODE_FALLBACK in first and policy.fallback_model in first
    assert runtime.transform_llm_output(response_text="ok", session_id="s", model=policy.fallback_model) is None
    codes = [e["code"] for e in ledger.events() if e["type"] == "event"]
    assert pol.CODE_PRIMARY_ERROR in codes and pol.CODE_FALLBACK in codes and pol.CODE_CLIENT_INFORMED in codes


def test_policy_rejects_non_frugal_or_local_routes(rt):
    _, pol, policy, _, _, _ = rt
    bad_fallback = {"model": {"provider": "openrouter", "default": policy.primary_model},
                    "fallback_model": {"provider": "openrouter", "model": "anthropic/claude-3-5-sonnet"}}
    assert any("hors politique" in p for p in pol.validate_hermes_config(policy, bad_fallback))
    local = {"model": {"provider": "ollama", "default": "mistralai/mistral-small"},
             "fallback_model": {"provider": "openrouter", "model": policy.fallback_model}}
    problems = pol.validate_hermes_config(policy, local)
    assert any("locale" in p for p in problems) and any("fournisseur" in p for p in problems)


def test_shipped_configs_and_policy_are_conformant(check, capsys):
    assert check.cmd_validate(None) == 0
    assert "CONFORME" in capsys.readouterr().out


def test_plugin_loads_through_the_real_plugin_manager(tmp_path, monkeypatch):
    """Le plugin livré s'active via plugins.enabled et enregistre ses hooks + son middleware."""
    home = Path(__import__("os").environ["HERMES_HOME"])
    (home / "config.yaml").write_text(yaml.safe_dump({"plugins": {"enabled": ["orso-model-policy"]}}), encoding="utf-8")
    monkeypatch.setenv("ORSO_CLIENT_ID", "client-test")
    from hermes_cli import plugins as pmod

    mgr = pmod.PluginManager()
    mgr.discover_and_load()
    loaded = mgr._plugins["orso-model-policy"]
    assert loaded.enabled, loaded.error
    assert mgr._middleware.get("llm_execution")
    for hook in ("pre_api_request", "api_request_error", "post_api_request", "transform_llm_output"):
        assert mgr._hooks.get(hook), hook
