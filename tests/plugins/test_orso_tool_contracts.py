"""KAN-131 — contrat d'outils : catalogue, permissions par rôle/client, authentification externe,
secrets par emplacement, dégradation signalée. Contrats de comportement (pas de valeurs figées),
dont un parcours réel : plugin activé par config.yaml, découvert par PluginManager, appelé via le
hook `pre_tool_call` du moteur."""

import importlib
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_DIR = REPO_ROOT / "plugins" / "orso-tool-contracts"
PKG = "hermes_plugins.orso_tool_contracts"


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.delenv("ORSO_TEST_TOOL_SECRET", raising=False)
    return home


def _plugin_module(name: str):
    """Charge le plugin par chemin, sous le paquet dynamique utilisé par PluginManager."""
    if "hermes_plugins" not in sys.modules:
        ns = types.ModuleType("hermes_plugins")
        ns.__path__ = []
        sys.modules["hermes_plugins"] = ns
    if PKG not in sys.modules:
        spec = importlib.util.spec_from_file_location(PKG, PLUGIN_DIR / "__init__.py", submodule_search_locations=[str(PLUGIN_DIR)])
        mod = importlib.util.module_from_spec(spec)
        mod.__package__ = PKG
        sys.modules[PKG] = mod
        spec.loader.exec_module(mod)
    return importlib.import_module(f"{PKG}.{name}") if name else sys.modules[PKG]


@pytest.fixture
def catalog():
    return _plugin_module("contracts").load_catalog()


def _decide(catalog, tool, role, client="acme"):
    return _plugin_module("guard").decide(catalog, tool, role, client, "s1")


# --- CA1 : catalogue métier + contrat par outil -----------------------------------------

def test_catalog_is_valid_dated_and_has_no_system_tool(catalog):
    contracts = _plugin_module("contracts")
    assert contracts.validate_catalog(catalog.raw) == []
    assert catalog.dated
    assert not set(catalog.tool_names()) & contracts.SYSTEM_TOOLS
    assert catalog.resolve("terminal") is None  # un outil système n'est pas exposé


def test_every_exposed_tool_carries_inputs_outputs_errors(catalog):
    for name in catalog.tool_names():
        contract = catalog.contract(name)
        assert {"inputs", "outputs", "errors", "version", "category"} <= set(contract), name


def test_system_tool_in_catalog_is_rejected_by_validation(catalog):
    contracts = _plugin_module("contracts")
    raw = json.loads(json.dumps(catalog.raw))
    raw["tools"].append({**raw["tools"][0], "name": "terminal"})
    assert any("système" in p for p in contracts.validate_catalog(raw))


def test_native_contract_matches_live_registry_schema(catalog):
    """Dérive : le contrat écrit doit suivre le schéma natif Hermès (sinon relever la version)."""
    findings = _plugin_module("contracts").registry_findings(catalog)
    assert not [f for f in findings if f.startswith("ERREUR")]


# --- CA3 : permissions par rôle et par client --------------------------------------------

def test_user_cannot_call_admin_tool_but_admin_can(catalog):
    denied = _decide(catalog, "messages_send", "user")
    assert not denied.allowed and denied.code == "ROLE_FORBIDDEN"
    assert _decide(catalog, "messages_send", "admin").allowed
    assert _decide(catalog, "messages_send", "superadmin").allowed
    assert _decide(catalog, "messages_read", "user").allowed


def test_unlisted_system_tool_is_refused_even_for_superadmin(catalog):
    decision = _decide(catalog, "terminal", "superadmin")
    assert not decision.allowed and decision.code == "TOOL_NOT_EXPOSED"


def test_client_allowlist_is_enforced(catalog):
    raw = json.loads(json.dumps(catalog.raw))
    next(t for t in raw["tools"] if t["name"] == "messages_read")["clients"] = ["acme"]
    restricted = _plugin_module("contracts").Catalog(raw)
    assert _decide(restricted, "messages_read", "user", client="acme").allowed
    assert _decide(restricted, "messages_read", "user", client="other").code == "CLIENT_FORBIDDEN"


def test_unknown_or_missing_role_gets_least_privilege():
    from hermes_cli.web_routers.tool_caller import bind_tool_caller

    assert bind_tool_caller("s-x", "root", "c").role == "user"
    assert bind_tool_caller("s-y", None, None).role == "user"


# --- CA2 / CA5 : authentification externe, secrets par emplacement ------------------------

def test_external_tool_without_authentication_is_refused():
    refs = _plugin_module("secret_refs")
    decision = refs.check_external_auth("wolfram", {"type": "none"})
    assert not decision.allowed and decision.code == "AUTH_REFUSED"
    assert not refs.check_external_auth("x", None).allowed


def test_authenticated_external_tool_accepted_only_when_secret_provisioned(_home):
    refs = _plugin_module("secret_refs")
    auth = {"type": "oauth", "secret_ref": "file:mcp-tokens/notion.json"}
    assert not refs.check_external_auth("notion", auth).allowed  # emplacement vide
    (_home / "mcp-tokens").mkdir()
    (_home / "mcp-tokens" / "notion.json").write_text('{"provisioned": true}', encoding="utf-8")
    accepted = refs.check_external_auth("notion", auth)
    assert accepted.allowed and accepted.secret_ref == "file:mcp-tokens/notion.json"


def test_env_secret_reference_resolves_without_exposing_value(monkeypatch):
    refs = _plugin_module("secret_refs")
    auth = {"type": "bearer", "secret_ref": "env:ORSO_TEST_TOOL_SECRET"}
    assert not refs.check_external_auth("srv", auth).allowed
    monkeypatch.setenv("ORSO_TEST_TOOL_SECRET", "valeur-de-test-non-secrete")
    decision = refs.check_external_auth("srv", auth)
    assert decision.allowed and "valeur-de-test-non-secrete" not in repr(decision)


@pytest.mark.parametrize("bad", ["sk-abcdefghijklmnopqrstuvwxyz", "Bearer abcdefghijklmnop", "../etc/passwd", "file:../../x", "file:/etc/x", ""])
def test_literal_or_escaping_secret_ref_is_refused(bad):
    refs = _plugin_module("secret_refs")
    assert not refs.check_external_auth("srv", {"type": "bearer", "secret_ref": bad}).allowed


def test_plaintext_secret_detected_by_path_never_by_value():
    refs = _plugin_module("secret_refs")
    cfg = {"servers": {"a": {"headers": {"Authorization": "Bearer abcdefghijklmnop"}, "api_key": "${MY_KEY}", "token": "env:X", "name": "ok"}}}
    found = refs.find_plaintext_secrets(cfg)
    assert found == ["servers.a.headers.Authorization"]
    assert "abcdefghijklmnop" not in " ".join(found)


def test_shipped_catalog_has_no_plaintext_secret(catalog):
    assert _plugin_module("secret_refs").find_plaintext_secrets(catalog.raw) == []


def test_shipped_wolfram_manifest_is_refused_and_oauth_manifest_needs_token():
    refs = _plugin_module("secret_refs")
    wolfram = yaml.safe_load((REPO_ROOT / "optional-mcps" / "wolfram" / "manifest.yaml").read_text(encoding="utf-8"))
    assert not refs.check_external_auth("wolfram", refs.manifest_auth(wolfram, "wolfram")).allowed
    notion = yaml.safe_load((REPO_ROOT / "optional-mcps" / "notion" / "manifest.yaml").read_text(encoding="utf-8"))
    assert refs.manifest_auth(notion, "notion")["secret_ref"].startswith("file:mcp-tokens/")


def test_external_server_tool_goes_through_auth_in_decision(catalog, _home):
    refused = _decide(catalog, "mcp__notion__search", "user")
    assert not refused.allowed and refused.code == "AUTH_REFUSED"
    (_home / "mcp-tokens").mkdir()
    (_home / "mcp-tokens" / "notion.json").write_text('{"provisioned": true}', encoding="utf-8")
    assert _decide(catalog, "mcp__notion__search", "user").allowed


# --- CA4 : dégradation définie, signalée, tracée ------------------------------------------

def test_cut_tool_degrades_with_defined_message_and_trace(catalog, _home):
    (_home / "config.yaml").write_text(yaml.safe_dump({"orso_tool_contracts": {"unavailable": ["messages_read"]}}), encoding="utf-8")
    decision = _decide(catalog, "messages_read", "user")
    assert not decision.allowed and decision.degraded and decision.code == "TOOL_UNAVAILABLE"
    assert "indisponible" in decision.message and "aucune action" in decision.message
    lines = [json.loads(line) for line in (_home / "logs" / "tool_contracts.jsonl").read_text(encoding="utf-8").splitlines()]
    assert lines[-1]["event"] == "TOOL_UNAVAILABLE" and lines[-1]["tool"] == "messages_read"


def test_unmet_prerequisite_is_degradation_not_silence(catalog):
    from tools.registry import discover_builtin_tools

    discover_builtin_tools()
    decision = _decide(catalog, "feishu_doc_read", "user")  # Feishu non configuré dans l'environnement de test
    assert not decision.allowed and decision.degraded
    assert "feishu_doc_read" in decision.message


def test_fallback_tool_is_suggested_only_when_exposed(catalog):
    guard = _plugin_module("guard")
    entry = catalog.resolve("feishu_drive_list_comments")
    assert "feishu_doc_read" in guard.degradation_message(entry, "test", catalog)


# --- Hook : parcours réel par PluginManager + pre_tool_call -------------------------------

def test_hook_enforces_via_real_plugin_discovery(_home):
    (_home / "config.yaml").write_text(yaml.safe_dump({"plugins": {"enabled": ["orso-tool-contracts"]}}), encoding="utf-8")
    for k in list(sys.modules):
        if k.startswith(("hermes_plugins", "hermes_cli.plugins")):
            del sys.modules[k]
    from hermes_cli.plugins import _ensure_plugins_discovered, get_pre_tool_call_block_message
    from hermes_cli.web_routers.tool_caller import bind_tool_caller, unbind_tool_caller

    assert "orso-tool-contracts" in _ensure_plugins_discovered(force=True)._plugins
    bind_tool_caller("sess-user", "user", "acme")
    bind_tool_caller("sess-admin", "admin", "acme")
    try:
        blocked = get_pre_tool_call_block_message("messages_send", {}, session_id="sess-user")
        assert blocked and "ROLE_FORBIDDEN" in blocked
        assert get_pre_tool_call_block_message("messages_send", {}, session_id="sess-admin") is None
        assert "TOOL_NOT_EXPOSED" in get_pre_tool_call_block_message("terminal", {}, session_id="sess-admin")
        # Session non cliente (CLI, gateway, cron) : la garde s'abstient, le moteur reste inchangé.
        assert get_pre_tool_call_block_message("terminal", {}, session_id="not-bound") is None
    finally:
        unbind_tool_caller("sess-user")
        unbind_tool_caller("sess-admin")


def test_hook_fails_closed_on_internal_error(monkeypatch):
    plugin = _plugin_module("")
    from hermes_cli.web_routers.tool_caller import bind_tool_caller, unbind_tool_caller

    bind_tool_caller("sess-err", "admin", "acme")
    monkeypatch.setattr(plugin, "load_catalog", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    try:
        result = plugin._on_pre_tool_call(tool_name="messages_read", args={}, session_id="sess-err")
        assert result and result["action"] == "block" and "GUARD_ERROR" in result["message"]
    finally:
        unbind_tool_caller("sess-err")
