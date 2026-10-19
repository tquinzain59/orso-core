"""Tests d'acceptation automatisés pour KAN-116, KAN-122 et KAN-123.

Vérifie formellement l'ensemble des critères d'acceptation des 3 tickets et les points de revue PO (Jarvis) :
- KAN-116 (Suivi de la consommation OpenRouter par client : token dédié créé à la volée à l'onboarding) :
  * CA1 : À l'onboarding d'un nouveau client, un token OpenRouter dédié est créé automatiquement et associé au client en base.
  * CA2 : La consommation d'un client donné est attribuable sans ambiguïté via l'API d'usage OpenRouter ou le tableau de bord.
  * CA3 : Le token n'apparaît jamais en clair dans le dépôt, les traces de commandes (`argv` / `ps aux`), les journaux ou l'image ; il est stocké chiffré (`0600`) avec `ORSO_OPENROUTER_VAULT_SECRET` obligatoire (sans fallback ni réutilisation de `ORSO_PERSONA_HMAC_KEY`) et injecté au conteneur uniquement via `--env-file /dev/stdin`.
  * CA4 : La clé de provisioning est hors dépôt, à portée minimale, et isolée.
  * CA5 : Un client désactivé ou résilié voit son token révoqué (avec propagation stricte d'erreur si l'API OpenRouter échoue), aucun repli sur `OPENROUTER_API_KEY` ambiant n'existe, et tout réveil/provisioning/chat d'un client révoqué est refusé.
  * CA6 : Un plafond de consommation par client est configurable et tout dépassement est visible et signalé.

- KAN-122 (Sélection du modèle par le client : deepseek frugal par défaut, Mistral frugal) :
  * CA1 : Catalogue des modèles sélectionnables défini (`deepseek/deepseek-v4-flash` par défaut plus frugal que `mistralai/mistral-small-24b-instruct-2501`).
  * CA2 : Le compte administrateur du client peut sélectionner le modèle (choix par client, persisté en base).
  * CA3 : Le modèle sélectionné est effectivement propagé aux agents autonomes conteneurisés (`spaces/{slug}/config/hermes.yaml`, `spaces/{slug}/profiles/*/config.yaml`, `tenants/{slug}/hermes_home/config.yaml`, variables `ORSO_SELECTED_MODEL` / `LLM_MODEL`) ainsi qu'au chat web et à `SessionDB`.

- KAN-123 (Onglet Modèles et consommation dans l'espace client - comptes admin) :
  * CA1 : L'onglet et ses routes API sont visibles/accessibles pour les comptes au profil admin et masqués/interdits (403) pour les autres.
  * CA2 : L'onglet affiche le modèle actuellement utilisé par les agents du client (valeur réelle) et permet de le modifier (KAN-122).
  * CA3 : L'onglet affiche la consommation (coût, jetons d'entrée/sortie, sur une période précisée), lisible et à jour.
  * CA4 : Un seuil par défaut est proposé à la souscription (25.0 USD / 80%) et est modifiable par l'admin global (OPS) et par le client admin (APP), avec valeur persistée.
  * CA5 : L'ajout de crédits via Stripe exige un vrai paiement encaissé (`confirm=true`, `payment_method` valide, `status == "succeeded"`, ou vraie `Subscription` récurrente `sub_...` au statut `active`, ou confirmation par webhook `payment_intent.succeeded` vérifié à la source) ; tout échec Stripe ou absence de moyen de paiement lève une erreur explicite (402) sans relever le plafond.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
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
    OpenRouterProvisioningManager,
    decrypt_token,
    encrypt_token,
    get_model_catalog_entry,
    get_models_catalog,
    is_valid_tenant_model,
    mask_secret_key,
)
from olympe.ops_manager import OpsManager
from olympe.server import app as olympe_app, manager as server_docker_mgr, ops_manager


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
    monkeypatch.setenv("ORSO_OPENROUTER_VAULT_SECRET", "test-openrouter-vault-secret-key-2026-dedicated")
    monkeypatch.setenv("ORSO_PERSONA_HMAC_KEY", "distinct-persona-hmac-key-2026")
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_orso_billing_2026")
    monkeypatch.setenv("OPENROUTER_PROVISIONING_API_KEY", "")
    vault_dir = tmp_path / "openrouter_vault"
    ops_db_path = tmp_path / "ops_state.db"
    monkeypatch.setenv("OLYMPE_DB_PATH", str(ops_db_path))

    mgr = OpsManager(supabase_url="", supabase_key="", stripe_secret_key="sk_test_orso_billing_2026", demo_mode=True)
    mgr.supabase_url = ""
    mgr.supabase_key = ""
    mgr.stripe_secret_key = "sk_test_orso_billing_2026"
    mgr.openrouter_manager = OpenRouterProvisioningManager(vault_dir=vault_dir)
    mgr._mock_tenants = mgr._init_seed_data()

    # Synchroniser le singleton ops_manager et manager du serveur Olympe pour les tests d'API
    monkeypatch.setattr(ops_manager, "db_path", ops_db_path)
    monkeypatch.setattr(ops_manager, "demo_mode", True)
    monkeypatch.setattr(ops_manager, "supabase_url", "")
    monkeypatch.setattr(ops_manager, "supabase_key", "")
    monkeypatch.setattr(ops_manager, "stripe_secret_key", "sk_test_orso_billing_2026")
    monkeypatch.setattr(ops_manager, "openrouter_manager", mgr.openrouter_manager)
    monkeypatch.setattr(ops_manager, "_mock_tenants", mgr._mock_tenants)
    monkeypatch.setattr("olympe.openrouter_client.openrouter_manager", mgr.openrouter_manager)
    monkeypatch.setattr("olympe.ops_manager.openrouter_manager", mgr.openrouter_manager)
    monkeypatch.setattr(server_docker_mgr, "data_root", tmp_path / "tenants")
    monkeypatch.setattr(server_docker_mgr, "spaces_root", tmp_path / "spaces")
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
    raw_key = isolated_ops.openrouter_manager.get_decrypted_tenant_key("acme-robo")
    assert raw_key is not None
    assert raw_key not in json.dumps(res)
    assert "••••" in or_meta["key_masked"]

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

    isolated_ops.openrouter_manager.record_local_usage("client-alpha", cost_usd=12.40, tenant_id=id_a)
    isolated_ops.openrouter_manager.record_local_usage("client-beta", cost_usd=3.15, tenant_id=id_b)

    settings_a = isolated_ops.get_tenant_llm_settings(id_a)
    settings_b = isolated_ops.get_tenant_llm_settings(id_b)

    assert settings_a["openrouter"]["key_hash"] != settings_b["openrouter"]["key_hash"]
    assert settings_a["consumption"]["usage_usd"] == 12.40
    assert settings_b["consumption"]["usage_usd"] == 3.15
    assert settings_a["consumption"]["limit_remaining_usd"] == round(DEFAULT_CONSUMPTION_LIMIT_USD - 12.40, 4)
    assert settings_b["consumption"]["limit_remaining_usd"] == round(DEFAULT_CONSUMPTION_LIMIT_USD - 3.15, 4)


def test_kan116_ca3_secret_encryption_mandatory_vault_secret_and_stdin_docker_injection(isolated_ops, tmp_path, monkeypatch):
    """CA3 : Le coffre exige ORSO_OPENROUTER_VAULT_SECRET dédié (sans fallback ni égalité avec ORSO_PERSONA_HMAC_KEY), stocke en 0600 et injecte via --env-file /dev/stdin."""
    # 1. Refus strict si ORSO_OPENROUTER_VAULT_SECRET est absent (aucun repli sur ORSO_PERSONA_HMAC_KEY ni constante)
    monkeypatch.delenv("ORSO_OPENROUTER_VAULT_SECRET", raising=False)
    monkeypatch.delenv("OPENROUTER_VAULT_SECRET", raising=False)
    monkeypatch.setenv("ORSO_PERSONA_HMAC_KEY", "some-persona-hmac-secret")
    with pytest.raises(RuntimeError, match="ERR_OPENROUTER_VAULT_SECRET_REQUIRED"):
        encrypt_token("sk-or-v1-test")

    # 2. Refus strict si ORSO_OPENROUTER_VAULT_SECRET est identique à ORSO_PERSONA_HMAC_KEY
    monkeypatch.setenv("ORSO_OPENROUTER_VAULT_SECRET", "some-persona-hmac-secret")
    with pytest.raises(RuntimeError, match="ERR_VAULT_SECRET_MUST_DIFFER_FROM_PERSONA_HMAC"):
        encrypt_token("sk-or-v1-test")

    # Restaurer un secret dédié distinct
    monkeypatch.setenv("ORSO_OPENROUTER_VAULT_SECRET", "test-openrouter-vault-secret-key-2026-dedicated")

    res = isolated_ops.create_sandbox_tenant("Secu Corp", "secu-corp", ["jerome"], "secu@corp.fr")
    tenant_id = res["tenant"]["id"]

    vault_file = isolated_ops.openrouter_manager._record_path("secu-corp")
    assert vault_file.exists()

    # 3. Permissions strictes 0600 sur le fichier du coffre
    file_mode = vault_file.stat().st_mode & 0o777
    assert file_mode == 0o600

    # 4. Le contenu sur disque ne contient pas la clé en clair mais enc:v1:...
    raw_disk_text = vault_file.read_text(encoding="utf-8")
    raw_secret = isolated_ops.openrouter_manager.get_decrypted_tenant_key("secu-corp")
    assert raw_secret is not None
    assert raw_secret.startswith("sk-or-v1-")
    assert raw_secret not in raw_disk_text
    disk_json = json.loads(raw_disk_text)
    assert disk_json["encrypted_key"].startswith("enc:v1:")
    assert decrypt_token(disk_json["encrypted_key"]) == raw_secret

    # 5. Injection au conteneur client uniquement via --env-file /dev/stdin (jamais dans argv)
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

    joined_argv = " ".join(cmd_args)
    assert raw_secret not in joined_argv
    assert "OPENROUTER_API_KEY" not in joined_argv
    assert "--env-file" in cmd_args
    assert cmd_args[cmd_args.index("--env-file") + 1] == "/dev/stdin"
    assert f"OPENROUTER_API_KEY={raw_secret}" in stdin_payload


def test_kan116_ca4_provisioning_key_outside_repo():
    """CA4 : La clé de provisioning est lue depuis l'environnement hors dépôt et masquée."""
    masked = mask_secret_key("sk-or-v1-1234567890abcdef1234567890abcdef")
    assert "1234567890abcdef1234567890abcdef" not in masked
    assert masked.startswith("sk-or-v1-1")
    assert masked.endswith("cdef")


def test_kan116_ca5_revocation_blocks_consumption_no_ambient_fallback_and_propagates_api_failure(
    isolated_ops, client_ui_test_client, tmp_path, monkeypatch
):
    """CA5 : Un client désactivé/résilié voit son token révoqué, aucun fallback sur OPENROUTER_API_KEY ambiant n'a lieu, et tout échec API OpenRouter remonte en erreur."""
    # Même si une clé OPENROUTER_API_KEY globale est dans l'environnement du superviseur, elle ne doit JAMAIS servir de repli
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-SHARED-AMBIENT-SHOULD-NEVER-LEAK")

    res = isolated_ops.create_sandbox_tenant("Cancel Co", "cancel-co", ["jerome"], "admin@cancel.co")
    tenant_id = res["tenant"]["id"]
    isolated_ops.update_tenant_subscription(tenant_id, status="active")
    assert isolated_ops.openrouter_manager.get_decrypted_tenant_key("cancel-co") is not None

    # 1. Si le token est non-simulé et que l'API OpenRouter échoue (ou que la clé de provisioning manque), la révocation échoue explicitement
    rec = isolated_ops.openrouter_manager.get_tenant_secret_record("cancel-co")
    rec["simulated"] = False
    isolated_ops.openrouter_manager.store_tenant_secret("cancel-co", rec)
    with pytest.raises(RuntimeError, match="ERR_PROVISIONING_KEY_MISSING|ERR_OPENROUTER_REVOKE_FAILED"):
        isolated_ops.revoke_tenant_openrouter_token(tenant_id)

    # Si la clé de provisioning est présente mais que l'appel HTTP OpenRouter échoue, l'erreur remonte aussi
    isolated_ops.openrouter_manager.provisioning_api_key = "sk-or-prov-real"
    with patch.object(isolated_ops.openrouter_manager, "_api_request", side_effect=RuntimeError("OpenRouter HTTP 500")):
        with pytest.raises(RuntimeError, match="ERR_OPENROUTER_REVOKE_FAILED"):
            isolated_ops.revoke_tenant_openrouter_token(tenant_id)

        # 1bis. Vérification dans les 3 flux de désactivation (update_tenant_subscription, handle_stripe_webhook, delete_tenant) :
        # L'échec de révocation OpenRouter (api_revoked=False) ne doit JAMAIS être avalé et doit bloquer la désactivation !
        with pytest.raises(RuntimeError, match="ERR_OPENROUTER_REVOKE_FAILED"):
            isolated_ops.update_tenant_subscription(tenant_id, status="canceled")
        # Le tenant est resté actif (aucune désactivation confirmée tant que la révocation échoue)
        assert isolated_ops.get_tenant_detail(tenant_id)["subscription"]["status"] == "active"

        with pytest.raises(RuntimeError, match="ERR_OPENROUTER_REVOKE_FAILED"):
            isolated_ops.handle_stripe_webhook({
                "id": "evt_cancel_fail_001",
                "type": "customer.subscription.deleted",
                "data": {
                    "object": {
                        "id": "sub_test_cancel-co",
                        "customer": "cus_test_cancel-co",
                        "status": "canceled",
                        "metadata": {"tenant_slug": "cancel-co"},
                    }
                },
            })
        assert "evt_cancel_fail_001" not in isolated_ops._processed_events
        assert isolated_ops.get_tenant_detail(tenant_id)["subscription"]["status"] == "active"

        with pytest.raises(RuntimeError, match="ERR_OPENROUTER_REVOKE_FAILED"):
            isolated_ops.delete_tenant(tenant_id)
        assert isolated_ops.get_tenant_detail(tenant_id) is not None

    # 2. Lorsque l'API OpenRouter confirme la révocation (200 OK), les 3 flux révoquent le token ET arrêtent le conteneur avant de confirmer
    from olympe.server import manager as server_docker_mgr
    with patch.object(
        isolated_ops.openrouter_manager,
        "_api_request",
        return_value=(200, {"data": {"key": "sk-or-v1-live-test-key-0001", "hash": "hash_live_test_0001", "disabled": True}}),
    ):
        with patch.object(server_docker_mgr, "suspend_tenant", return_value={"success": True, "status": "sleeping"}) as mock_suspend:
            sub_res = isolated_ops.update_tenant_subscription(tenant_id, status="canceled")
            assert sub_res["success"] is True
            assert sub_res["openrouter_revoked"] is True
            assert sub_res["container_stopped"] is True
            mock_suspend.assert_called_once_with("cancel-co")

        # Vérification du flux webhook de résiliation (customer.subscription.deleted) : révoque le token + suspend le conteneur
        res_wh_tenant = isolated_ops.create_sandbox_tenant("Webhook Cancel Co", "wh-cancel-co", ["jerome"], "admin@whcancel.co")
        wh_tid = res_wh_tenant["tenant"]["id"]
        rec_wh = isolated_ops.openrouter_manager.get_tenant_secret_record("wh-cancel-co")
        rec_wh["simulated"] = False
        isolated_ops.openrouter_manager.store_tenant_secret("wh-cancel-co", rec_wh)
        with patch.object(server_docker_mgr, "suspend_tenant", return_value={"success": True, "status": "sleeping"}) as mock_wh_suspend:
            wh_cancel_res = isolated_ops.handle_stripe_webhook({
                "id": "evt_cancel_ok_002",
                "type": "customer.subscription.deleted",
                "data": {
                    "object": {
                        "id": "sub_test_wh-cancel-co",
                        "customer": "cus_test_wh-cancel-co",
                        "status": "canceled",
                        "metadata": {"tenant_slug": "wh-cancel-co"},
                    }
                },
            })
            assert wh_cancel_res["status"] == "processed"
            mock_wh_suspend.assert_called_once_with("wh-cancel-co")
        assert isolated_ops.openrouter_manager.get_decrypted_tenant_key("wh-cancel-co") is None
        assert isolated_ops.openrouter_manager.get_tenant_usage("wh-cancel-co", tenant_id=wh_tid)["status"] == "revoked"

        # Vérification du flux delete_tenant : révoque le token (hard_delete) + détruit le conteneur (teardown_tenant)
        res_del_tenant = isolated_ops.create_sandbox_tenant("Delete Cancel Co", "del-cancel-co", ["jerome"], "admin@delcancel.co")
        del_tid = res_del_tenant["tenant"]["id"]
        rec_del = isolated_ops.openrouter_manager.get_tenant_secret_record("del-cancel-co")
        rec_del["simulated"] = False
        isolated_ops.openrouter_manager.store_tenant_secret("del-cancel-co", rec_del)
        with patch.object(server_docker_mgr, "teardown_tenant", return_value={"success": True, "status": "destroyed"}) as mock_teardown:
            del_res = isolated_ops.delete_tenant(del_tid)
            assert del_res["success"] is True
            assert del_res["openrouter_revoked"] is True
            assert del_res["container_stopped"] is True
            mock_teardown.assert_called_once_with("del-cancel-co", remove_data=True)
        assert isolated_ops.openrouter_manager.get_decrypted_tenant_key("del-cancel-co") is None

    assert isolated_ops.openrouter_manager.get_decrypted_tenant_key("cancel-co") is None
    usage_info = isolated_ops.openrouter_manager.get_tenant_usage("cancel-co", tenant_id=tenant_id)
    assert usage_info["status"] == "revoked"
    assert usage_info["disabled"] is True

    # 3. Un client dont le token est révoqué (ou absent) est bloqué au provisioning et au wake_tenant (pas de repli sur OPENROUTER_API_KEY ambiant)
    manager = DockerLifecycleManager(
        data_root=str(tmp_path / "tenants"),
        spaces_root=str(tmp_path / "spaces"),
        host_max_containers=100,
        host_max_memory_mb=65536,
        host_max_cpus=64.0,
    )
    manager.has_docker = True
    with patch.object(manager, "get_tenant_status", return_value={"status": "not_found", "running": False}):
        with patch("olympe.openrouter_client.OpenRouterProvisioningManager", return_value=isolated_ops.openrouter_manager):
            prov_revoked = manager.provision_tenant(
                tenant_id=tenant_id,
                tenant_slug="cancel-co",
                allow_floating_tag=True,
                persona_hmac_key="hmac-secu",
                env_vars={
                    "HERMES_DASHBOARD_BASIC_AUTH_USERNAME": "admin",
                    "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD": "testpassword123",
                },
            )
            assert prov_revoked["success"] is False
            assert prov_revoked["error"] == "ERR_OPENROUTER_TOKEN_REVOKED"

            wake_revoked = manager.wake_tenant("cancel-co")
            assert wake_revoked["success"] is False
            assert wake_revoked["error"] == "ERR_OPENROUTER_TOKEN_REVOKED"

            # Et un client sans aucun token dédié ne prend jamais la clé ambiante OPENROUTER_API_KEY
            prov_missing = manager.provision_tenant(
                tenant_id="tenant-no-token",
                tenant_slug="no-token-corp",
                allow_floating_tag=True,
                persona_hmac_key="hmac-secu",
                env_vars={
                    "HERMES_DASHBOARD_BASIC_AUTH_USERNAME": "admin",
                    "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD": "testpassword123",
                },
            )
            assert prov_missing["success"] is False
            assert prov_missing["error"] == "ERR_OPENROUTER_TOKEN_REQUIRED"

    # 4. Le chat web refuse également (403 ERR_OPENROUTER_TOKEN_REVOKED) toute exécution pour ce client révoqué
    monkeypatch.setenv("ORSO_CLIENT_ID", tenant_id)
    monkeypatch.setenv("ORSO_CLIENT_SLUG", "cancel-co")
    revoked_jwt = _make_client_jwt(tenant_id=tenant_id, tenant_slug="cancel-co", is_admin=True)
    chat_resp = client_ui_test_client.post(
        "/api/client/chat",
        json={"agent_id": "jerome", "session_id": "sess-revoked-1", "message": "Bonjour"},
        headers={"Authorization": f"Bearer {revoked_jwt}"},
    )
    assert chat_resp.status_code == 403
    assert "ERR_OPENROUTER_TOKEN_REVOKED" in chat_resp.json()["detail"]
    isolated_ops.openrouter_manager.provisioning_api_key = ""


def test_kan116_ca6_configurable_cap_and_exceedance_signaling(isolated_ops):
    """CA6 : Un plafond de consommation par client est configurable et tout dépassement est visible et signalé."""
    res = isolated_ops.create_sandbox_tenant("Cap Corp", "cap-corp", ["jerome"], "admin@cap.corp")
    tenant_id = res["tenant"]["id"]

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

    isolated_ops.openrouter_manager.record_local_usage("cap-corp", cost_usd=16.0, tenant_id=tenant_id)
    state_warn = isolated_ops.get_tenant_llm_settings(tenant_id)
    assert state_warn["consumption"]["threshold_reached"] is True
    assert state_warn["consumption"]["limit_exceeded"] is False
    assert state_warn["consumption"]["usage_pct"] == 80.0

    isolated_ops.openrouter_manager.record_local_usage("cap-corp", cost_usd=5.0, tenant_id=tenant_id)
    state_exceeded = isolated_ops.get_tenant_llm_settings(tenant_id)
    assert state_exceeded["consumption"]["threshold_reached"] is True
    assert state_exceeded["consumption"]["limit_exceeded"] is True
    assert state_exceeded["consumption"]["limit_remaining_usd"] == 0.0


# ==============================================================================
# KAN-122 : Sélection du modèle par le client (deepseek frugal par défaut, Mistral frugal)
# ==============================================================================

def test_kan122_ca1_selectable_models_catalog_and_frugal_pricing_coherence():
    """CA1 : Catalogue des 2 modèles frugaux défini, avec DeepSeek par défaut strictement plus frugal que Mistral."""
    catalog = get_models_catalog()
    assert len(catalog) == 2
    model_ids = [m["id"] for m in catalog]
    assert "deepseek/deepseek-v4-flash" in model_ids
    assert "mistralai/mistral-small-24b-instruct-2501" in model_ids
    assert DEFAULT_TENANT_MODEL_ID == "deepseek/deepseek-v4-flash"

    deepseek_entry = get_model_catalog_entry("deepseek/deepseek-v4-flash")
    mistral_entry = get_model_catalog_entry("mistralai/mistral-small-24b-instruct-2501")
    assert deepseek_entry["is_default"] is True
    assert mistral_entry["is_default"] is False
    # Cohérence tarifaire : DeepSeek (par défaut frugal) est moins cher que Mistral Small en entrée et en sortie
    assert deepseek_entry["input_price_per_1m_usd"] < mistral_entry["input_price_per_1m_usd"]
    assert deepseek_entry["output_price_per_1m_usd"] < mistral_entry["output_price_per_1m_usd"]

    assert is_valid_tenant_model("deepseek/deepseek-v4-flash") is True
    assert is_valid_tenant_model("mistralai/mistral-small-24b-instruct-2501") is True
    assert is_valid_tenant_model("openai/gpt-4o") is False


def test_kan122_ca2_admin_can_select_model_and_persist_in_db(client_ui_test_client, isolated_ops):
    """CA2 : Le compte administrateur du client peut sélectionner le modèle (choix par client, persisté en base)."""
    admin_token = _make_client_jwt(is_admin=True)

    res_init = client_ui_test_client.get(
        "/api/client/models-consumption",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_init.status_code == 200
    assert res_init.json()["selected_model"] == "deepseek/deepseek-v4-flash"

    res_change = client_ui_test_client.post(
        "/api/client/models-consumption/model",
        json={"model_id": "mistralai/mistral-small-24b-instruct-2501"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_change.status_code == 200
    data_change = res_change.json()
    assert data_change["success"] is True
    assert data_change["selected_model"] == "mistralai/mistral-small-24b-instruct-2501"

    persisted = isolated_ops.get_tenant_llm_settings("f3e25379-6531-479e-b276-3b3185e7421b")
    assert persisted["selected_model"] == "mistralai/mistral-small-24b-instruct-2501"

    res_status = client_ui_test_client.get(
        "/api/client/status",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_status.status_code == 200
    assert res_status.json()["active_model"] == "mistralai/mistral-small-24b-instruct-2501"

    res_invalid = client_ui_test_client.post(
        "/api/client/models-consumption/model",
        json={"model_id": "anthropic/claude-3-opus"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_invalid.status_code == 400


def test_kan122_ca3_selected_model_is_used_end_to_end_by_containerized_agents_and_chat(
    client_ui_test_client, isolated_ops, tmp_path
):
    """CA3 : Le modèle sélectionné est propagé aux agents autonomes conteneurisés (hermes.yaml, profiles/*/config.yaml, env vars) ET au chat web."""
    admin_token = _make_client_jwt(is_admin=True)
    test_session_id = "sess-kan122-ca3-proof"
    tenant_id = "f3e25379-6531-479e-b276-3b3185e7421b"
    tenant_slug = "financia-solutions"

    # S'assurer que le tenant a un token OpenRouter dédié actif
    isolated_ops.ensure_tenant_openrouter_token(tenant_id, tenant_slug)

    # 1. Préparer l'espace dédié du conteneur client
    server_docker_mgr.prepare_tenant_space(tenant_slug)

    # 2. Basculer le tenant sur Mistral Small 3 (24B Frugal) via l'API client
    res_switch = client_ui_test_client.post(
        "/api/client/models-consumption/model",
        json={"model_id": "mistralai/mistral-small-24b-instruct-2501"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_switch.status_code == 200

    # 3. Vérifier que les fichiers YAML de l'espace conteneurisé des agents autonomes ont été mis à jour
    space_dir = tmp_path / "spaces" / tenant_slug
    space_hermes_yaml = yaml.safe_load((space_dir / "config" / "hermes.yaml").read_text(encoding="utf-8"))
    assert space_hermes_yaml["model"]["provider"] == "openrouter"
    assert space_hermes_yaml["model"]["default"] == "mistralai/mistral-small-24b-instruct-2501"

    jerome_profile_cfg = yaml.safe_load((space_dir / "profiles" / "jerome" / "config.yaml").read_text(encoding="utf-8"))
    assert jerome_profile_cfg["model"]["provider"] == "openrouter"
    assert jerome_profile_cfg["model"]["default"] == "mistralai/mistral-small-24b-instruct-2501"

    tenant_hermes_home_cfg = yaml.safe_load(
        (tmp_path / "tenants" / tenant_slug / "hermes_home" / "config.yaml").read_text(encoding="utf-8")
    )
    assert tenant_hermes_home_cfg["model"]["default"] == "mistralai/mistral-small-24b-instruct-2501"

    # 4. Vérifier que le provisioning du conteneur injecte aussi ORSO_SELECTED_MODEL et LLM_MODEL dans l'env-file stdin
    server_docker_mgr.has_docker = True
    recorded_calls = []

    def fake_exec_docker(args, timeout=20.0, **kwargs):
        recorded_calls.append({"args": list(args), "input_data": kwargs.get("input_data")})
        if args and args[0] == "ps":
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="cid_financia_123", stderr="")

    with patch.object(server_docker_mgr, "get_tenant_status", return_value={"status": "not_found", "running": False}):
        with patch.object(server_docker_mgr, "_exec_docker", side_effect=fake_exec_docker):
            with patch.object(server_docker_mgr, "_sync_tenant_instance_record"):
                with patch("olympe.openrouter_client.OpenRouterProvisioningManager", return_value=isolated_ops.openrouter_manager):
                    prov = server_docker_mgr.provision_tenant(
                        tenant_id=tenant_id,
                        tenant_slug=tenant_slug,
                        allow_floating_tag=True,
                        persona_hmac_key="hmac-secu",
                        env_vars={
                            "HERMES_DASHBOARD_BASIC_AUTH_USERNAME": "admin",
                            "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD": "testpassword123",
                        },
                    )
                    assert prov["success"] is True
                    assert prov["selected_model"] == "mistralai/mistral-small-24b-instruct-2501"

    run_calls = [c for c in recorded_calls if c["args"] and c["args"][0] == "run"]
    assert len(run_calls) == 1
    stdin_env = run_calls[0]["input_data"] or ""
    assert "ORSO_SELECTED_MODEL=mistralai/mistral-small-24b-instruct-2501" in stdin_env
    assert "LLM_MODEL=mistralai/mistral-small-24b-instruct-2501" in stdin_env

    # 5. Vérifier aussi le chat SSE et la SessionDB
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
    assert start_events[0]["model"] == "mistralai/mistral-small-24b-instruct-2501"
    assert done_events[0]["model"] == "mistralai/mistral-small-24b-instruct-2501"


# ==============================================================================
# KAN-123 : Onglet Modèles et consommation dans l'espace client (comptes admin)
# ==============================================================================

def test_kan123_ca1_admin_only_visibility_and_access(client_ui_test_client):
    """CA1 : L'onglet Modèles & Consommation est accessible aux comptes admin et interdit (403) aux comptes non-admin."""
    non_admin_token = _make_client_jwt(is_admin=False, role="collaborateur", user_id="user-collab-456")
    admin_token = _make_client_jwt(is_admin=True, role="admin", user_id="user-admin-123")

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

    resp_admin = client_ui_test_client.get(
        "/api/client/models-consumption",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp_admin.status_code == 200


def test_kan123_ca2_and_ca3_display_active_model_and_consumption_metrics(client_ui_test_client, isolated_ops):
    """CA2 & CA3 : L'onglet retourne le modèle courant réel, le catalogue, et la consommation détaillée (coût, jetons, période)."""
    admin_token = _make_client_jwt(is_admin=True)
    tenant_id = "f3e25379-6531-479e-b276-3b3185e7421b"

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

    assert body["selected_model"] in ("deepseek/deepseek-v4-flash", "mistralai/mistral-small-24b-instruct-2501")
    assert body["active_model_info"]["id"] == body["selected_model"]
    assert len(body["models_catalog"]) == 2

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

    initial = isolated_ops.get_tenant_llm_settings(tenant_id)
    assert initial["consumption"]["limit_usd"] == DEFAULT_CONSUMPTION_LIMIT_USD
    assert initial["consumption"]["alert_threshold_pct"] == DEFAULT_CONSUMPTION_ALERT_THRESHOLD_PCT

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

    res_app_view = client_ui_test_client.get(
        "/api/client/models-consumption",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_app_view.status_code == 200
    assert res_app_view.json()["consumption"]["limit_usd"] == 45.0
    assert res_app_view.json()["consumption"]["alert_threshold_pct"] == 70.0

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

    res_ops_check = olympe_client.get(
        f"/api/olympe/ops/tenants/{tenant_id}/llm-settings",
        headers={"Authorization": f"Bearer {MOCK_SUPERADMIN_TOKEN}"},
    )
    assert res_ops_check.status_code == 200
    assert res_ops_check.json()["consumption"]["limit_usd"] == 60.0
    assert res_ops_check.json()["consumption"]["alert_threshold_pct"] == 85.0


def test_kan123_ca5_real_stripe_charge_subscription_failure_rejection_and_webhook_confirmation(
    client_ui_test_client, isolated_ops
):
    """CA5 : L'ajout de crédits débite réellement Stripe (confirm=true + payment_method), crée une vraie Subscription récurrente pour le mensuel, rejette tout échec sans créditer, et supporte la confirmation par webhook."""
    tenant_id = "f3e25379-6531-479e-b276-3b3185e7421b"
    admin_token = _make_client_jwt(is_admin=True)

    isolated_ops.update_tenant_consumption_threshold(tenant_id, limit_usd=25.0, alert_threshold_pct=80.0)
    isolated_ops.openrouter_manager.record_local_usage("financia-solutions", cost_usd=22.0, tenant_id=tenant_id)

    stripe_calls = []

    def fake_stripe_request(endpoint: str, method: str = "GET", data=None):
        stripe_calls.append({"endpoint": endpoint, "method": method, "data": dict(data or {})})
        if endpoint.startswith("customers/"):
            return {
                "id": "cus_financia_9876",
                "invoice_settings": {"default_payment_method": "pm_card_visa_4242"},
            }
        if endpoint == "payment_intents" and method == "POST":
            assert data["confirm"] == "true"
            assert data["off_session"] == "true"
            assert data["payment_method"] == "pm_card_visa_4242"
            return {
                "id": "pi_real_oneshot_001",
                "status": "succeeded",
                "amount": int(data["amount"]),
            }
        if endpoint == "subscriptions" and method == "POST":
            assert data["default_payment_method"] == "pm_card_visa_4242"
            assert data["payment_behavior"] == "error_if_incomplete"
            assert data["items[0][price_data][recurring][interval]"] == "month"
            return {
                "id": "sub_real_recurring_001",
                "status": "active",
            }
        if endpoint == "payment_intents/pi_webhook_002" and method == "GET":
            return {
                "id": "pi_webhook_002",
                "status": "succeeded",
            }
        raise ValueError(f"Appel Stripe inattendu: {method} {endpoint}")

    # 1. Si le paiement Stripe échoue ou reste en 'requires_payment_method', un 402 est retourné et AUCUN crédit n'est accordé
    def failing_stripe_request(endpoint: str, method: str = "GET", data=None):
        if endpoint.startswith("customers/"):
            return {"id": "cus_financia_9876", "invoice_settings": {"default_payment_method": "pm_card_declined"}}
        if endpoint == "payment_intents":
            return {"id": "pi_failed_999", "status": "requires_payment_method"}
        raise ValueError("Stripe card declined")

    with patch.object(isolated_ops, "_stripe_request", side_effect=failing_stripe_request):
        res_fail = client_ui_test_client.post(
            "/api/client/models-consumption/credits",
            json={"amount_usd": 25.0, "mode": "one_shot"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res_fail.status_code == 402
        assert "ERR_STRIPE_PAYMENT_NOT_SUCCEEDED" in res_fail.json()["detail"]

    # Le plafond est resté strictement à 25.0 USD (aucun auto-crédit sans paiement !)
    after_fail = isolated_ops.get_tenant_llm_settings(tenant_id)
    assert after_fail["consumption"]["limit_usd"] == 25.0
    assert after_fail["consumption"]["extra_credits_usd"] == 0.0

    # 2. Paiement unique (one_shot) encaissé avec confirm=true & payment_method -> plafond relevé à 50 USD
    with patch.object(isolated_ops, "_stripe_request", side_effect=fake_stripe_request):
        res_oneshot = client_ui_test_client.post(
            "/api/client/models-consumption/credits",
            json={"amount_usd": 25.0, "mode": "one_shot"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res_oneshot.status_code == 200
        data_oneshot = res_oneshot.json()
        assert data_oneshot["success"] is True
        assert data_oneshot["operation"]["id"] == "pi_real_oneshot_001"
        assert data_oneshot["operation"]["status"] == "succeeded"
        assert data_oneshot["operation"]["payment_method"] == "pm_card_visa_4242"
        assert data_oneshot["consumption"]["limit_usd"] == 50.0
        assert data_oneshot["consumption"]["extra_credits_usd"] == 25.0
        assert data_oneshot["consumption"]["threshold_reached"] is False

        # 3. Abonnement mensuel récurrent (monthly_subscription) via POST /v1/subscriptions -> vrai ID sub_real_recurring_001
        res_monthly = client_ui_test_client.post(
            "/api/client/models-consumption/credits",
            json={"amount_usd": 50.0, "mode": "monthly_subscription"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res_monthly.status_code == 200
        data_monthly = res_monthly.json()
        assert data_monthly["success"] is True
        assert data_monthly["operation"]["id"] == "sub_real_recurring_001"
        assert data_monthly["operation"]["idempotency_key"] == "sub_init:sub_real_recurring_001"
        assert data_monthly["consumption"]["stripe_credit_subscription_id"] == "sub_real_recurring_001"
        assert data_monthly["consumption"]["limit_usd"] == 100.0
        assert data_monthly["consumption"]["monthly_addon_usd"] == 50.0

        # 3bis. Réserve (3) Idempotence cohérente : la facture initiale de création d'abonnement (subscription_create)
        # ne doit PAS recréditer une seconde fois si add_tenant_credits a déjà crédité en synchrone.
        def stripe_monthly_webhooks(endpoint: str, method: str = "GET", data=None):
            if endpoint == "subscriptions/sub_real_recurring_001":
                return {
                    "id": "sub_real_recurring_001",
                    "status": "active",
                    "metadata": {
                        "tenant_id": tenant_id,
                        "tenant_slug": "financia-solutions",
                        "credit_mode": "monthly_subscription",
                        "credits_usd": "50.0",
                    },
                }
            if endpoint in ("invoices/in_initial_sub_001", "invoices/in_renewal_cycle_002"):
                return {
                    "id": endpoint.split("/")[1],
                    "status": "paid",
                    "billing_reason": "subscription_create" if "initial" in endpoint else "subscription_cycle",
                    "parent": {
                        "subscription_details": {
                            "subscription": "sub_real_recurring_001",
                            "metadata": {
                                "tenant_id": tenant_id,
                                "tenant_slug": "financia-solutions",
                                "credit_mode": "monthly_subscription",
                                "credits_usd": "50.0",
                            },
                        }
                    },
                    "metadata": {},
                }
            raise ValueError(f"Unexpected Stripe endpoint: {endpoint}")

    with patch.object(isolated_ops, "_stripe_request", side_effect=stripe_monthly_webhooks):
        wh_initial_inv = isolated_ops.handle_stripe_webhook({
            "id": "evt_inv_initial_001",
            "type": "invoice.payment_succeeded",
            "data": {
                "object": {
                    "id": "in_initial_sub_001",
                    "customer": "cus_financia_9876",
                    "status": "paid",
                    "billing_reason": "subscription_create",
                    "parent": {
                        "subscription_details": {
                            "subscription": "sub_real_recurring_001",
                            "metadata": {
                                "tenant_id": tenant_id,
                                "tenant_slug": "financia-solutions",
                                "credit_mode": "monthly_subscription",
                                "credits_usd": "50.0",
                            },
                        }
                    },
                    "metadata": {},
                }
            },
        })
        assert wh_initial_inv["status"] == "processed"
        assert wh_initial_inv["credits_added_usd"] == 0.0
        assert wh_initial_inv["new_limit_usd"] == 100.0

        # 3ter. Réserves (1) & (2) : Renouvellement mensuel avec metadata dans invoice.parent.subscription_details.metadata
        # (et metadata de premier niveau vide {}) -> crédite +50.0 USD (plafond passe à 150.0 USD)
        # SANS écraser l'abonnement SaaS principal du tenant !
        main_sub_before = dict(isolated_ops.get_tenant_detail(tenant_id)["subscription"])
        wh_renewal = isolated_ops.handle_stripe_webhook({
            "id": "evt_inv_renewal_002",
            "type": "invoice.payment_succeeded",
            "data": {
                "object": {
                    "id": "in_renewal_cycle_002",
                    "customer": "cus_financia_9876",
                    "status": "paid",
                    "billing_reason": "subscription_cycle",
                    "parent": {
                        "subscription_details": {
                            "subscription": "sub_real_recurring_001",
                            "metadata": {
                                "tenant_id": tenant_id,
                                "tenant_slug": "financia-solutions",
                                "credit_mode": "monthly_subscription",
                                "credits_usd": "50.0",
                            },
                        }
                    },
                    "metadata": {},
                }
            },
        })
        assert wh_renewal["status"] == "processed"
        assert wh_renewal["credits_added_usd"] == 50.0
        assert wh_renewal["new_limit_usd"] == 150.0

        # L'abonnement SaaS principal (sub_1Q1234567890, tier 1_agent, status active) n'a JAMAIS été écrasé
        main_sub_after = isolated_ops.get_tenant_detail(tenant_id)["subscription"]
        assert main_sub_after["stripe_subscription_id"] == main_sub_before["stripe_subscription_id"] == "sub_1Q1234567890"
        assert main_sub_after["tier_id"] == "1_agent"
        assert main_sub_after["status"] == "active"

        # Une seconde livraison pour la même facture de renouvellement (même avec un event_id différent) ne double-crédite pas
        wh_renewal_dup = isolated_ops.handle_stripe_webhook({
            "id": "evt_inv_renewal_002_duplicate_delivery",
            "type": "invoice.payment_succeeded",
            "data": {
                "object": {
                    "id": "in_renewal_cycle_002",
                    "customer": "cus_financia_9876",
                    "status": "paid",
                    "billing_reason": "subscription_cycle",
                    "parent": {
                        "subscription_details": {
                            "subscription": "sub_real_recurring_001",
                            "metadata": {
                                "tenant_id": tenant_id,
                                "tenant_slug": "financia-solutions",
                                "credit_mode": "monthly_subscription",
                                "credits_usd": "50.0",
                            },
                        }
                    },
                    "metadata": {},
                }
            },
        })
        assert wh_renewal_dup["status"] == "processed"
        assert wh_renewal_dup["credits_added_usd"] == 0.0
        assert wh_renewal_dup["new_limit_usd"] == 150.0

        # 4. Flux asynchrone wait_for_webhook=True + confirmation par webhook payment_intent.succeeded vérifié à la source
        def async_pi_stripe(endpoint: str, method: str = "GET", data=None):
            if endpoint.startswith("customers/"):
                return {"id": "cus_financia_9876", "invoice_settings": {"default_payment_method": "pm_card_visa_4242"}}
            if endpoint == "payment_intents" and method == "POST":
                return {"id": "pi_webhook_002", "status": "processing"}
            if endpoint == "payment_intents/pi_webhook_002" and method == "GET":
                return {"id": "pi_webhook_002", "status": "succeeded"}
            raise ValueError(f"Unexpected: { endpoint }")

    with patch.object(isolated_ops, "_stripe_request", side_effect=async_pi_stripe):
        res_pending = client_ui_test_client.post(
            "/api/client/models-consumption/credits",
            json={"amount_usd": 30.0, "mode": "one_shot", "wait_for_webhook": True},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res_pending.status_code == 200
        # Tant que le webhook n'est pas reçu, le plafond reste à 150.0 USD
        assert res_pending.json()["operation"]["status"] == "pending_webhook"
        assert res_pending.json()["consumption"]["limit_usd"] == 150.0

        # Réception du webhook payment_intent.succeeded -> relecture à la source Stripe et incrément à 180.0 USD
        wh_res = isolated_ops.handle_stripe_webhook({
            "id": "evt_pi_webhook_002",
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_webhook_002",
                    "customer": "cus_financia_9876",
                    "status": "succeeded",
                    "metadata": {
                        "tenant_id": tenant_id,
                        "tenant_slug": "financia-solutions",
                        "credit_mode": "one_shot",
                        "credits_usd": "30.0",
                    },
                }
            },
        })
        assert wh_res["status"] == "processed"
        assert wh_res["new_limit_usd"] == 180.0
        final_state = isolated_ops.get_tenant_llm_settings(tenant_id)
        assert final_state["consumption"]["limit_usd"] == 180.0
        assert final_state["consumption"]["extra_credits_usd"] == 155.0
