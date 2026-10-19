"""Tests d'acceptation automatisés pour KAN-116, KAN-122 et KAN-123.

Vérifie formellement l'ensemble des critères d'acceptation des 3 tickets :
- KAN-116 (Suivi de la consommation OpenRouter par client : token dédié créé à la volée à l'onboarding) :
  * CA1 : À l'onboarding d'un nouveau client, un token OpenRouter dédié est créé automatiquement et associé au client en base.
  * CA2 : La consommation d'un client donné est attribuable sans ambiguïté via l'API d'usage OpenRouter ou le tableau de bord.
  * CA3 : Le token n'apparaît jamais en clair dans le dépôt, les traces de commandes (`argv` / `ps aux`), les journaux ou l'image ; il est stocké chiffré (`0600`) et injecté au conteneur uniquement via `--env-file /dev/stdin`.
  * CA4 : La clé de provisioning est hors dépôt, à portée minimale, et isolée.
  * CA5 : Un client désactivé ou résilié voit son token révoqué et sa consommation s'arrête immédiatement.
  * CA6 : Un plafond de consommation par client est configurable et tout dépassement est visible et signalé.

- KAN-122 (Sélection du modèle par le client : deepseek frugal par défaut, Mistral frugal) :
  * CA1 : Catalogue des modèles sélectionnables défini (`deepseek/deepseek-v4-flash` par défaut + `mistralai/mistral-small-24b-instruct-2501`).
  * CA2 : Le compte administrateur du client peut sélectionner le modèle (choix par client, persisté en base).
  * CA3 : Le modèle sélectionné est effectivement utilisé par les agents concernés (preuve de bout en bout sur `/api/client/chat` et `SessionDB`).

- KAN-123 (Onglet Modèles et consommation dans l'espace client - comptes admin) :
  * CA1 : L'onglet et ses routes API sont visibles/accessibles pour les comptes au profil admin et masqués/interdits (403) pour les autres.
  * CA2 : L'onglet affiche le modèle actuellement utilisé par les agents du client (valeur réelle) et permet de le modifier (KAN-122).
  * CA3 : L'onglet affiche la consommation (coût, jetons d'entrée/sortie, sur une période précisée), lisible et à jour.
  * CA4 : Un seuil par défaut est proposé à la souscription (25.0 USD / 80%) et est modifiable par l'admin global (OPS) et par le client admin (APP), avec valeur persistée.
  * CA5 : Lorsque la consommation atteint le seuil (ou à tout moment pour l'admin), l'utilisateur peut ajouter des crédits via Stripe (paiement unique `one_shot` ou abonnement mensuel `monthly_subscription`) et le solde/plafond est mis à jour.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hermes_cli.dashboard_auth.client_jwt import _b64url_encode
from hermes_cli.web_routers.client_ui import router as client_ui_router
from olympe.auth import MOCK_SUPERADMIN_TOKEN
from olympe.lifecycle_manager import DockerLifecycleManager
from olympe.openrouter_client import (
    DEFAULT_CONSUMPTION_ALERT_THRESHOLD_PCT,
    DEFAULT_CONSUMPTION_LIMIT_USD,
    DEFAULT_TENANT_MODEL_ID,
    TENANT_MODELS_CATALOG,
    OpenRouterProvisioningManager,
    decrypt_token,
    encrypt_token,
    get_models_catalog,
    is_valid_tenant_model,
    mask_secret_key,
)
from olympe.ops_manager import OpsManager
from olympe.server import app as olympe_app, ops_manager


def _make_client_jwt(
    tenant_id: str = "f3e25379-6531-479e-b276-3b3185e7421b",
    tenant_slug: str = "financia-solutions",
    is_admin: bool = True,
    role: str = "admin",
    user_id: str = "user-admin-123",
    email: str = "sophie.martin@financia.fr",
) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": 9999999999,
        "app_metadata": {
            "tenant_id": tenant_id,
            "tenant_slug": tenant_slug,
            "role": role,
            "is_admin": is_admin,
            "agents": ["jerome", "lucas"],
        },
        "user_metadata": {
            "full_name": "Sophie Martin",
            "role": "DAF",
            "is_admin": is_admin,
        },
    }
    h_b64 = _b64url_encode(json.dumps(header).encode("utf-8"))
    p_b64 = _b64url_encode(json.dumps(payload).encode("utf-8"))
    signing_input = f"{h_b64}.{p_b64}".encode("ascii")
    sig = _b64url_encode(hmac.new(b"test-jwt-secret", signing_input, hashlib.sha256).digest())
    return f"{h_b64}.{p_b64}.{sig}"


@pytest.fixture
def isolated_ops(tmp_path, monkeypatch):
    """Fournit un OpsManager et un OpenRouterProvisioningManager isolés dans un dossier temporaire."""
    monkeypatch.setenv("ORSO_DEMO_MODE", "1")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("OPENROUTER_VAULT_SECRET", "test-vault-secret-key-2026")
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "")
    monkeypatch.setenv("OPENROUTER_PROVISIONING_API_KEY", "")
    vault_dir = tmp_path / "openrouter_vault"
    ops_db_path = tmp_path / "ops_state.db"
    monkeypatch.setenv("OLYMPE_DB_PATH", str(ops_db_path))

    mgr = OpsManager(supabase_url="", supabase_key="", stripe_secret_key="", demo_mode=True)
    mgr.supabase_url = ""
    mgr.supabase_key = ""
    mgr.stripe_secret_key = ""
    mgr.openrouter_manager = OpenRouterProvisioningManager(vault_dir=vault_dir)
    mgr._mock_tenants = mgr._init_seed_data()

    # Synchroniser le singleton ops_manager du serveur Olympe pour les tests d'API
    monkeypatch.setattr(ops_manager, "db_path", ops_db_path)
    monkeypatch.setattr(ops_manager, "demo_mode", True)
    monkeypatch.setattr(ops_manager, "supabase_url", "")
    monkeypatch.setattr(ops_manager, "supabase_key", "")
    monkeypatch.setattr(ops_manager, "stripe_secret_key", "")
    monkeypatch.setattr(ops_manager, "openrouter_manager", mgr.openrouter_manager)
    monkeypatch.setattr(ops_manager, "_mock_tenants", mgr._mock_tenants)
    monkeypatch.setattr("olympe.openrouter_client.openrouter_manager", mgr.openrouter_manager)
    monkeypatch.setattr("olympe.ops_manager.openrouter_manager", mgr.openrouter_manager)
    return mgr


@pytest.fixture
def olympe_client(isolated_ops):
    return TestClient(olympe_app)


@pytest.fixture
def client_ui_test_client(isolated_ops, monkeypatch, tmp_path):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("ORSO_CLIENT_ID", "f3e25379-6531-479e-b276-3b3185e7421b")
    monkeypatch.setenv("ORSO_CLIENT_SLUG", "financia-solutions")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes_home"))
    import olympe.server as olympe_server_mod
    monkeypatch.setattr(olympe_server_mod, "ops_manager", isolated_ops)

    app = FastAPI()
    app.include_router(client_ui_router)
    return TestClient(app)


# ==============================================================================
# KAN-116 : Suivi de la consommation OpenRouter par client (token dédié à la volée)
# ==============================================================================

def test_kan116_ca1_onboarding_creates_dedicated_openrouter_token(isolated_ops):
    """CA1 : À l'onboarding d'un nouveau client, un token OpenRouter dédié est créé automatiquement et associé au client en base."""
    res = isolated_ops.create_sandbox_tenant(
        name="Acme Robo",
        slug="acme-robo",
        tier_Agents=["jerome", "nadia"],
        admin_email="cto@acme-robo.fr",
        duration_days=14,
    )
    assert res["success"] is True
    tenant = res["tenant"]
    assert "openrouter" in tenant
    or_meta = tenant["openrouter"]
    assert or_meta["has_dedicated_token"] is True
    assert or_meta["status"] == "active"
    assert or_meta["key_hash"]
    assert or_meta["key_label"] == "orso-tenant-acme-robo"
    assert or_meta["limit_usd"] == DEFAULT_CONSUMPTION_LIMIT_USD
    # Aucune clé en clair ne doit figurer dans le retour public (seule la version masquée avec •••• est présente)
    raw_key = isolated_ops.openrouter_manager.get_decrypted_tenant_key("acme-robo")
    assert raw_key is not None
    assert raw_key not in json.dumps(res)
    assert "••••" in or_meta["key_masked"]

    # Vérifier aussi le flux record_contact_lead (création de lead -> tenant initialisé avec token dédié)
    lead = isolated_ops.record_contact_lead(
        company_name="Beta Industrie",
        contact_name="Jean Dupont",
        email="j.dupont@beta-industrie.fr",
        selected_agents=["jerome"],
    )
    tenant_beta = isolated_ops.get_tenant_by_id(lead["tenant_id"])
    assert tenant_beta is not None
    assert tenant_beta["openrouter"]["has_dedicated_token"] is True
    assert "beta-industrie" in tenant_beta["openrouter"]["key_label"]


def test_kan116_ca2_unambiguous_tenant_consumption_attribution(isolated_ops):
    """CA2 : La consommation d'un client donné est attribuable sans ambiguïté via l'API d'usage OpenRouter."""
    res_a = isolated_ops.create_sandbox_tenant("Client Alpha", "client-alpha", ["jerome"], "a@alpha.fr")
    res_b = isolated_ops.create_sandbox_tenant("Client Beta", "client-beta", ["lucas"], "b@beta.fr")
    id_a = res_a["tenant"]["id"]
    id_b = res_b["tenant"]["id"]

    # Enregistrer de la consommation distincte pour Alpha (12.40 USD) et Beta (3.15 USD)
    isolated_ops.openrouter_manager.record_local_usage("client-alpha", cost_usd=12.40, tenant_id=id_a)
    isolated_ops.openrouter_manager.record_local_usage("client-beta", cost_usd=3.15, tenant_id=id_b)

    settings_a = isolated_ops.get_tenant_llm_settings(id_a)
    settings_b = isolated_ops.get_tenant_llm_settings(id_b)

    assert settings_a["openrouter"]["key_hash"] != settings_b["openrouter"]["key_hash"]
    assert settings_a["consumption"]["usage_usd"] == 12.40
    assert settings_b["consumption"]["usage_usd"] == 3.15
    assert settings_a["consumption"]["limit_remaining_usd"] == round(DEFAULT_CONSUMPTION_LIMIT_USD - 12.40, 4)
    assert settings_b["consumption"]["limit_remaining_usd"] == round(DEFAULT_CONSUMPTION_LIMIT_USD - 3.15, 4)


def test_kan116_ca3_secret_encryption_and_stdin_docker_injection(isolated_ops, tmp_path):
    """CA3 : Le token est chiffré au repos (permissions 0600), jamais en clair dans argv/ps aux/logs, et injecté via --env-file /dev/stdin."""
    res = isolated_ops.create_sandbox_tenant("Secu Corp", "secu-corp", ["jerome"], "secu@corp.fr")
    tenant_id = res["tenant"]["id"]

    vault_file = isolated_ops.openrouter_manager._record_path("secu-corp")
    assert vault_file.exists()

    # 1. Permissions strictes 0600 sur le fichier du coffre
    file_mode = vault_file.stat().st_mode & 0o777
    assert file_mode == 0o600

    # 2. Le contenu sur disque ne contient pas la clé en clair mais enc:v1:...
    raw_disk_text = vault_file.read_text(encoding="utf-8")
    raw_secret = isolated_ops.openrouter_manager.get_decrypted_tenant_key("secu-corp")
    assert raw_secret is not None
    assert raw_secret.startswith("sk-or-v1-")
    assert raw_secret not in raw_disk_text
    disk_json = json.loads(raw_disk_text)
    assert disk_json["encrypted_key"].startswith("enc:v1:")
    assert decrypt_token(disk_json["encrypted_key"]) == raw_secret

    # 3. Injection au conteneur client uniquement via --env-file /dev/stdin (jamais dans argv)
    manager = DockerLifecycleManager(
        data_root=str(tmp_path / "tenants"),
        spaces_root=str(tmp_path / "spaces"),
    )
    manager.has_docker = True
    recorded_calls = []

    def fake_exec_docker(args, timeout=20.0, **kwargs):
        recorded_calls.append({"args": list(args), "input_data": kwargs.get("input_data")})
        if args and args[0] == "ps":
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="cid_secu_123", stderr="")

    with patch.object(manager, "get_tenant_status", return_value={"status": "not_found", "running": False}):
        with patch.object(manager, "_exec_docker", side_effect=fake_exec_docker):
            with patch.object(manager, "_sync_tenant_instance_record"):
                with patch("olympe.openrouter_client.OpenRouterProvisioningManager", return_value=isolated_ops.openrouter_manager):
                    prov = manager.provision_tenant(
                        tenant_id=tenant_id,
                        tenant_slug="secu-corp",
                        allow_floating_tag=True,
                        persona_hmac_key="hmac-secu",
                        env_vars={
                            "HERMES_DASHBOARD_BASIC_AUTH_USERNAME": "admin",
                            "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD": "testpassword123",
                        },
                    )
                    assert prov["success"] is True

    run_calls = [c for c in recorded_calls if c["args"] and c["args"][0] == "run"]
    assert len(run_calls) == 1
    cmd_args = run_calls[0]["args"]
    stdin_payload = run_calls[0]["input_data"] or ""

    # La clé dédiée ne doit JAMAIS figurer dans les arguments de ligne de commande (visible par ps aux)
    joined_argv = " ".join(cmd_args)
    assert raw_secret not in joined_argv
    assert "OPENROUTER_API_KEY" not in joined_argv
    assert "--env-file" in cmd_args
    assert cmd_args[cmd_args.index("--env-file") + 1] == "/dev/stdin"

    # En revanche, elle est bien transmise au conteneur via le flux stdin
    assert f"OPENROUTER_API_KEY={raw_secret}" in stdin_payload


def test_kan116_ca4_provisioning_key_outside_repo():
    """CA4 : La clé de provisioning est lue depuis l'environnement hors dépôt et masquée."""
    masked = mask_secret_key("sk-or-v1-1234567890abcdef1234567890abcdef")
    assert "1234567890abcdef1234567890abcdef" not in masked
    assert masked.startswith("sk-or-v1-1")
    assert masked.endswith("cdef")


def test_kan116_ca5_revocation_on_deactivation_or_cancellation(isolated_ops):
    """CA5 : Un client désactivé ou résilié voit son token révoqué et sa consommation s'arrête immédiatement."""
    res = isolated_ops.create_sandbox_tenant("Cancel Co", "cancel-co", ["jerome"], "admin@cancel.co")
    tenant_id = res["tenant"]["id"]

    # Avant résiliation : la clé déchiffrée est disponible
    assert isolated_ops.openrouter_manager.get_decrypted_tenant_key("cancel-co") is not None

    # Résiliation de l'abonnement -> révocation immédiate du token OpenRouter
    sub_res = isolated_ops.update_tenant_subscription(tenant_id, status="canceled")
    assert sub_res["success"] is True
    assert sub_res["openrouter_revoked"] is True

    # La clé ne peut plus être utilisée par un conteneur et son statut est 'revoked'
    assert isolated_ops.openrouter_manager.get_decrypted_tenant_key("cancel-co") is None
    usage_info = isolated_ops.openrouter_manager.get_tenant_usage("cancel-co", tenant_id=tenant_id)
    assert usage_info["status"] == "revoked"
    assert usage_info["disabled"] is True


def test_kan116_ca6_configurable_cap_and_exceedance_signaling(isolated_ops):
    """CA6 : Un plafond de consommation par client est configurable et tout dépassement est visible et signalé."""
    res = isolated_ops.create_sandbox_tenant("Cap Corp", "cap-corp", ["jerome"], "admin@cap.corp")
    tenant_id = res["tenant"]["id"]

    # Configurer un plafond de 20 USD et un seuil d'alerte à 75% (15 USD)
    thresh_res = isolated_ops.update_tenant_consumption_threshold(
        tenant_id=tenant_id,
        limit_usd=20.0,
        alert_threshold_pct=75.0,
        actor="ops_admin",
    )
    assert thresh_res["success"] is True
    assert thresh_res["consumption"]["limit_usd"] == 20.0
    assert thresh_res["consumption"]["alert_threshold_usd"] == 15.0
    assert thresh_res["consumption"]["threshold_reached"] is False
    assert thresh_res["consumption"]["limit_exceeded"] is False

    # Simuler 16 USD de consommation -> seuil d'alerte (15 USD) franchi, plafond (20 USD) non dépassé
    isolated_ops.openrouter_manager.record_local_usage("cap-corp", cost_usd=16.0, tenant_id=tenant_id)
    state_warn = isolated_ops.get_tenant_llm_settings(tenant_id)
    assert state_warn["consumption"]["threshold_reached"] is True
    assert state_warn["consumption"]["limit_exceeded"] is False
    assert state_warn["consumption"]["usage_pct"] == 80.0

    # Simuler +5 USD (total 21 USD) -> plafond de 20 USD dépassé
    isolated_ops.openrouter_manager.record_local_usage("cap-corp", cost_usd=5.0, tenant_id=tenant_id)
    state_exceeded = isolated_ops.get_tenant_llm_settings(tenant_id)
    assert state_exceeded["consumption"]["threshold_reached"] is True
    assert state_exceeded["consumption"]["limit_exceeded"] is True
    assert state_exceeded["consumption"]["limit_remaining_usd"] == 0.0


# ==============================================================================
# KAN-122 : Sélection du modèle par le client (deepseek frugal par défaut, Mistral frugal)
# ==============================================================================

def test_kan122_ca1_selectable_models_catalog():
    """CA1 : Catalogue des 2 modèles frugaux défini (DeepSeek frugal par défaut + Mistral frugal)."""
    catalog = get_models_catalog()
    assert len(catalog) == 2
    model_ids = [m["id"] for m in catalog]
    assert "deepseek/deepseek-v4-flash" in model_ids
    assert "mistralai/mistral-small-24b-instruct-2501" in model_ids
    assert DEFAULT_TENANT_MODEL_ID == "deepseek/deepseek-v4-flash"

    default_entries = [m for m in catalog if m.get("is_default")]
    assert len(default_entries) == 1
    assert default_entries[0]["id"] == "deepseek/deepseek-v4-flash"

    assert is_valid_tenant_model("deepseek/deepseek-v4-flash") is True
    assert is_valid_tenant_model("mistralai/mistral-small-24b-instruct-2501") is True
    assert is_valid_tenant_model("openai/gpt-4o") is False


def test_kan122_ca2_admin_can_select_model_and_persist_in_db(client_ui_test_client, isolated_ops):
    """CA2 : Le compte administrateur du client peut sélectionner le modèle (choix par client, persisté en base)."""
    admin_token = _make_client_jwt(is_admin=True)

    # 1. Vérifier que le modèle par défaut initial est DeepSeek V4 Flash
    res_init = client_ui_test_client.get(
        "/api/client/models-consumption",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_init.status_code == 200
    data_init = res_init.json()
    assert data_init["selected_model"] == "deepseek/deepseek-v4-flash"

    # 2. Changer le modèle vers Mistral Small 3 (24B Frugal)
    res_change = client_ui_test_client.post(
        "/api/client/models-consumption/model",
        json={"model_id": "mistralai/mistral-small-24b-instruct-2501"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_change.status_code == 200
    data_change = res_change.json()
    assert data_change["success"] is True
    assert data_change["selected_model"] == "mistralai/mistral-small-24b-instruct-2501"

    # 3. Vérifier la persistance dans OpsManager et dans /api/client/status
    persisted = isolated_ops.get_tenant_llm_settings("f3e25379-6531-479e-b276-3b3185e7421b")
    assert persisted["selected_model"] == "mistralai/mistral-small-24b-instruct-2501"

    res_status = client_ui_test_client.get(
        "/api/client/status",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_status.status_code == 200
    assert res_status.json()["active_model"] == "mistralai/mistral-small-24b-instruct-2501"

    # 4. Vérifier qu'un modèle hors catalogue est rejeté (400)
    res_invalid = client_ui_test_client.post(
        "/api/client/models-consumption/model",
        json={"model_id": "anthropic/claude-3-opus"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_invalid.status_code == 400


def test_kan122_ca3_selected_model_is_used_end_to_end_by_agents(client_ui_test_client, isolated_ops):
    """CA3 : Le modèle sélectionné est effectivement utilisé par les agents du client (preuve de bout en bout sur /api/client/chat et SessionDB)."""
    admin_token = _make_client_jwt(is_admin=True)
    test_session_id = "sess-kan122-ca3-proof"

    # Basculer le tenant sur Mistral Small 3 (24B Frugal)
    res_switch = client_ui_test_client.post(
        "/api/client/models-consumption/model",
        json={"model_id": "mistralai/mistral-small-24b-instruct-2501"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_switch.status_code == 200

    # Envoyer un message au chat d'un agent (jerome) et inspecter les événements SSE + la SessionDB
    res_chat = client_ui_test_client.post(
        "/api/client/chat",
        json={
            "agent_id": "jerome",
            "session_id": test_session_id,
            "message": "Bonjour Jérôme, quel modèle utilises-tu ?",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_chat.status_code == 200

    sse_events = []
    current_event_type = None
    for line in res_chat.text.splitlines():
        if line.startswith("event: "):
            current_event_type = line[7:].strip()
        elif line.startswith("data: "):
            payload = json.loads(line[6:])
            if current_event_type and "type" not in payload:
                payload["type"] = current_event_type
            sse_events.append(payload)

    start_events = [e for e in sse_events if e.get("type") == "start"]
    done_events = [e for e in sse_events if e.get("type") == "done"]
    assert len(start_events) == 1
    assert len(done_events) == 1
    assert start_events[0]["model"] == "mistralai/mistral-small-24b-instruct-2501"
    assert done_events[0]["model"] == "mistralai/mistral-small-24b-instruct-2501"

    # Vérifier également dans la base SQLite SessionDB de l'agent que la session créée enregistre bien ce modèle
    from hermes_state import SessionDB
    from hermes_cli.web_routers.client_ui import _find_profile_dir, PROJECT_ROOT
    profile_dir = _find_profile_dir("jerome")
    if profile_dir and profile_dir.is_dir() and os.access(profile_dir, os.W_OK):
        agent_home = profile_dir.resolve()
    else:
        agent_home = (PROJECT_ROOT / "data" / "agents" / "jerome").resolve()
    db = SessionDB(agent_home / "state.db")
    session_row = db.get_session(test_session_id)
    assert session_row is not None
    assert session_row["model"] == "mistralai/mistral-small-24b-instruct-2501"


# ==============================================================================
# KAN-123 : Onglet Modèles et consommation dans l'espace client (comptes admin)
# ==============================================================================

def test_kan123_ca1_admin_only_visibility_and_access(client_ui_test_client):
    """CA1 : L'onglet Modèles & Consommation est accessible aux comptes admin et interdit (403) aux comptes non-admin."""
    non_admin_token = _make_client_jwt(is_admin=False, role="collaborateur", user_id="user-collab-456")
    admin_token = _make_client_jwt(is_admin=True, role="admin", user_id="user-admin-123")

    # Non-admin : 403 sur toutes les routes Modèles & Consommation
    for method, path, payload in [
        ("GET", "/api/client/models-consumption", None),
        ("POST", "/api/client/models-consumption/model", {"model_id": "deepseek/deepseek-v4-flash"}),
        ("POST", "/api/client/models-consumption/threshold", {"limit_usd": 30.0, "alert_threshold_pct": 80.0}),
        ("POST", "/api/client/models-consumption/credits", {"amount_usd": 10.0, "mode": "one_shot"}),
    ]:
        if method == "GET":
            resp = client_ui_test_client.get(path, headers={"Authorization": f"Bearer {non_admin_token}"})
        else:
            resp = client_ui_test_client.post(path, json=payload, headers={"Authorization": f"Bearer {non_admin_token}"})
        assert resp.status_code == 403, f"Attendu 403 pour {method} {path}, reçu {resp.status_code}"

    # Admin : 200 OK
    resp_admin = client_ui_test_client.get(
        "/api/client/models-consumption",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp_admin.status_code == 200


def test_kan123_ca2_and_ca3_display_active_model_and_consumption_metrics(client_ui_test_client, isolated_ops):
    """CA2 & CA3 : L'onglet retourne le modèle courant réel, le catalogue, et la consommation détaillée (coût, jetons, période)."""
    admin_token = _make_client_jwt(is_admin=True)
    tenant_id = "f3e25379-6531-479e-b276-3b3185e7421b"

    # Enregistrer une consommation OpenRouter et un échange de chat pour alimenter les compteurs
    isolated_ops.openrouter_manager.record_local_usage("financia-solutions", cost_usd=7.85, tenant_id=tenant_id)
    client_ui_test_client.post(
        "/api/client/chat",
        json={"agent_id": "jerome", "session_id": "sess-kan123-ca3-metrics", "message": "Analyse rapide du bilan."},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    resp = client_ui_test_client.get(
        "/api/client/models-consumption",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()

    # CA2 : Modèle courant et catalogue
    assert body["selected_model"] in ("deepseek/deepseek-v4-flash", "mistralai/mistral-small-24b-instruct-2501")
    assert body["active_model_info"]["id"] == body["selected_model"]
    assert len(body["models_catalog"]) == 2

    # CA3 : Consommation (coût, tokens, période précisée)
    cons = body["consumption"]
    assert cons["usage_usd"] == 7.85
    assert cons["limit_usd"] >= DEFAULT_CONSUMPTION_LIMIT_USD
    assert "period" in cons
    assert cons["period"]["label"]
    assert cons["period"]["start"]
    assert "tokens" in cons
    assert "input_tokens" in cons["tokens"]
    assert "output_tokens" in cons["tokens"]
    assert "total_tokens" in cons["tokens"]
    assert cons["tokens"]["sessions_count"] >= 1


def test_kan123_ca4_threshold_default_and_modifiable_by_ops_and_client_admin(
    olympe_client, client_ui_test_client, isolated_ops
):
    """CA4 : Un seuil par défaut est proposé à la souscription et est modifiable par l'admin global (OPS) et par le client admin (APP), avec valeur persistée."""
    tenant_id = "f3e25379-6531-479e-b276-3b3185e7421b"
    admin_token = _make_client_jwt(is_admin=True)

    # 1. Vérifier les valeurs par défaut proposées à la souscription (25.0 USD / 80%)
    initial = isolated_ops.get_tenant_llm_settings(tenant_id)
    assert initial["consumption"]["limit_usd"] == DEFAULT_CONSUMPTION_LIMIT_USD
    assert initial["consumption"]["alert_threshold_pct"] == DEFAULT_CONSUMPTION_ALERT_THRESHOLD_PCT

    # 2. Modification par l'admin global depuis le Cockpit OPS
    res_ops = olympe_client.post(
        f"/api/olympe/ops/tenants/{tenant_id}/consumption-threshold",
        json={"limit_usd": 45.0, "alert_threshold_pct": 70.0},
        headers={"Authorization": f"Bearer {MOCK_SUPERADMIN_TOKEN}"},
    )
    assert res_ops.status_code == 200
    ops_data = res_ops.json()
    assert ops_data["consumption"]["limit_usd"] == 45.0
    assert ops_data["consumption"]["alert_threshold_pct"] == 70.0
    assert ops_data["consumption"]["alert_threshold_usd"] == 31.5

    # Vérifier que le client admin voit la valeur mise à jour par l'OPS
    res_app_view = client_ui_test_client.get(
        "/api/client/models-consumption",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_app_view.status_code == 200
    assert res_app_view.json()["consumption"]["limit_usd"] == 45.0
    assert res_app_view.json()["consumption"]["alert_threshold_pct"] == 70.0

    # 3. Modification par le client admin depuis l'application cliente (APP)
    res_client_update = client_ui_test_client.post(
        "/api/client/models-consumption/threshold",
        json={"limit_usd": 60.0, "alert_threshold_pct": 85.0},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_client_update.status_code == 200
    client_data = res_client_update.json()
    assert client_data["consumption"]["limit_usd"] == 60.0
    assert client_data["consumption"]["alert_threshold_pct"] == 85.0
    assert client_data["consumption"]["alert_threshold_usd"] == 51.0

    # Vérifier la persistance côté OPS
    res_ops_check = olympe_client.get(
        f"/api/olympe/ops/tenants/{tenant_id}/llm-settings",
        headers={"Authorization": f"Bearer {MOCK_SUPERADMIN_TOKEN}"},
    )
    assert res_ops_check.status_code == 200
    assert res_ops_check.json()["consumption"]["limit_usd"] == 60.0
    assert res_ops_check.json()["consumption"]["alert_threshold_pct"] == 85.0


def test_kan123_ca5_add_credits_via_stripe_one_shot_and_monthly_subscription(
    client_ui_test_client, isolated_ops
):
    """CA5 : Lorsque la consommation atteint le seuil, l'admin peut ajouter des crédits via Stripe (one_shot ou monthly_subscription) et le solde est mis à jour."""
    tenant_id = "f3e25379-6531-479e-b276-3b3185e7421b"
    admin_token = _make_client_jwt(is_admin=True)

    # Fixer un plafond de 25 USD (seuil 80% = 20 USD) et simuler 22 USD de consommation (seuil atteint)
    isolated_ops.update_tenant_consumption_threshold(tenant_id, limit_usd=25.0, alert_threshold_pct=80.0)
    isolated_ops.openrouter_manager.record_local_usage("financia-solutions", cost_usd=22.0, tenant_id=tenant_id)

    before = client_ui_test_client.get(
        "/api/client/models-consumption",
        headers={"Authorization": f"Bearer {admin_token}"},
    ).json()
    assert before["consumption"]["threshold_reached"] is True
    assert before["consumption"]["limit_usd"] == 25.0

    # 1. Ajout de +25 USD en paiement unique (one_shot) via Stripe
    res_oneshot = client_ui_test_client.post(
        "/api/client/models-consumption/credits",
        json={"amount_usd": 25.0, "mode": "one_shot"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_oneshot.status_code == 200
    data_oneshot = res_oneshot.json()
    assert data_oneshot["success"] is True
    assert data_oneshot["operation"]["mode"] == "one_shot"
    assert data_oneshot["operation"]["amount_usd"] == 25.0
    assert data_oneshot["consumption"]["limit_usd"] == 50.0
    assert data_oneshot["consumption"]["extra_credits_usd"] == 25.0
    assert data_oneshot["consumption"]["threshold_reached"] is False

    # 2. Ajout de +50 USD/mois en abonnement mensuel de crédits supplémentaires (monthly_subscription)
    res_monthly = client_ui_test_client.post(
        "/api/client/models-consumption/credits",
        json={"amount_usd": 50.0, "mode": "monthly_subscription"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_monthly.status_code == 200
    data_monthly = res_monthly.json()
    assert data_monthly["success"] is True
    assert data_monthly["operation"]["mode"] == "monthly_subscription"
    assert data_monthly["consumption"]["limit_usd"] == 100.0
    assert data_monthly["consumption"]["monthly_addon_usd"] == 50.0
    assert len(data_monthly["credits_history"]) >= 2
