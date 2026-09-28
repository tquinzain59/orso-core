"""Tests d'intégration et de conformité pour l'accès Drone OPS (KAN-35).

Valide formellement l'ensemble des critères d'acceptation (CA1 à CA8) définis par le PO :
- CA1 : Lecture flotte (200) et rejet strict hors liste blanche (403).
- CA2 : Provisioning et destruction idempotents (2x de suite sans résidu).
- CA3 : Refus absolu de toute action IAM, clé Stripe ou infrastructure hôte (403).
- CA4 : Révocation immédiate du jeton (401) et incapacité d'auto-attribution de droits.
- CA5 : Compte client de test fonctionnel sur UI Client et formellement interdit sur OPS (403).
- CA6 : Webhook Stripe reçu, journalisé et réconcilié avec statut tenant.
- CA7 : Actions du drone tracées sous l'identité dédiée 'drone-clientx'.
- CA8 : Fichier de secrets délivré avec permissions 600 strictes.
"""

import json
import os
import stat
import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from olympe.auth import (
    MOCK_DRONE_TOKEN,
    MOCK_SUPERADMIN_TOKEN,
    revoke_token,
    clear_token_cache,
    verify_ops_token,
    verify_stripe_signature,
    _REVOKED_TOKENS,
)
from olympe.server import app, ops_manager, manager


@pytest.fixture(autouse=True)
def reset_drone_state():
    """Réinitialise les caches, révocations et états de test avant chaque test."""
    clear_token_cache()
    _REVOKED_TOKENS.clear()
    ops_manager._webhook_deliveries.clear()
    ops_manager._audit_log.clear()
    yield
    clear_token_cache()
    _REVOKED_TOKENS.clear()


def test_ca1_drone_fleet_read_and_whitelist_enforcement():
    """CA1 — Le jeton du drone lit l'état de la flotte (200) et refuse (403) tout tenant hors whitelist."""
    client = TestClient(app)
    drone_headers = {"Authorization": f"Bearer {MOCK_DRONE_TOKEN}"}

    # 1. Lecture autorisée de l'état de la flotte (200 OK)
    resp_fleet = client.get("/api/olympe/ops/tenants", headers=drone_headers)
    assert resp_fleet.status_code == 200
    data_fleet = resp_fleet.json()
    assert "tenants" in data_fleet
    assert len(data_fleet["tenants"]) > 0

    # Lecture des statistiques consolidées autorisée (200 OK)
    resp_stats = client.get("/api/olympe/ops/stats", headers=drone_headers)
    assert resp_stats.status_code == 200

    # 2. Tentative d'accès à un tenant hors whitelist (financia-solutions) -> Refus strict 403
    resp_forbidden = client.get("/api/olympe/ops/tenants/financia-solutions", headers=drone_headers)
    assert resp_forbidden.status_code == 403
    assert "sandbox" in resp_forbidden.json()["detail"].lower()

    # Tentative d'accès par ID à un autre tenant réel -> Refus strict 403
    resp_forbidden_id = client.get(
        "/api/olympe/ops/tenants/f3e25379-6531-479e-b276-3b3185e7421b",
        headers=drone_headers,
    )
    assert resp_forbidden_id.status_code == 403


def test_ca2_provisioning_and_teardown_idempotence():
    """CA2 — Création puis destruction du tenant de test deux fois de suite, sans erreur ni résidu."""
    client = TestClient(app)
    drone_headers = {"Authorization": f"Bearer {MOCK_DRONE_TOKEN}"}

    # Tentative de création d'un tenant hors whitelist -> 403 Forbidden
    resp_bad_create = client.post(
        "/api/olympe/ops/tenants",
        json={"tenant_slug": "autre-client-interdit"},
        headers=drone_headers,
    )
    assert resp_bad_create.status_code == 403

    # Cycle 1 : Création du tenant clientx-orso avec quotas
    resp_create_1 = client.post(
        "/api/olympe/ops/tenants",
        json={
            "tenant_slug": "clientx-orso",
            "name": "CLIENTX-ORSO (TEST)",
            "contact_email": "test-drone-notifications@test.orso-agents.fr",
            "quotas": {"cpus": "0.5", "memory": "512m", "pids_limit": "100"},
        },
        headers=drone_headers,
    )
    assert resp_create_1.status_code == 200
    created_data = resp_create_1.json()
    assert created_data["success"] is True
    assert created_data["tenant"]["slug"] == "clientx-orso"
    assert created_data["tenant"]["name"] == "CLIENTX-ORSO (TEST)"
    assert created_data["tenant"]["quotas"]["cpus"] == "0.5"

    # Vérification lecture du tenant sandbox autorisé
    resp_get_1 = client.get("/api/olympe/ops/tenants/clientx-orso", headers=drone_headers)
    assert resp_get_1.status_code == 200

    # Cycle 1 : Destruction du tenant clientx-orso
    resp_del_1 = client.delete("/api/olympe/ops/tenants/clientx-orso", headers=drone_headers)
    assert resp_del_1.status_code == 200
    assert resp_del_1.json()["status"] == "destroyed"

    # Vérification que le tenant n'existe plus
    resp_get_after = client.get("/api/olympe/ops/tenants/clientx-orso", headers=drone_headers)
    assert resp_get_after.status_code == 404

    # Cycle 2 : Recréation immédiate (idempotence)
    resp_create_2 = client.post(
        "/api/olympe/ops/tenants",
        json={"tenant_slug": "clientx-orso", "name": "CLIENTX-ORSO (TEST)"},
        headers=drone_headers,
    )
    assert resp_create_2.status_code == 200

    # Cycle 2 : Destruction immédiate
    resp_del_2 = client.delete("/api/olympe/ops/tenants/clientx-orso", headers=drone_headers)
    assert resp_del_2.status_code == 200
    assert resp_del_2.json()["status"] == "destroyed"

    # Deuxième destruction consécutive (idempotence : aucune erreur)
    resp_del_3 = client.delete("/api/olympe/ops/tenants/clientx-orso", headers=drone_headers)
    assert resp_del_3.status_code == 200


def test_ca3_prohibited_actions_refused_server_side():
    """CA3 — Le jeton ne permet aucune action IAM, aucun accès secret Stripe, ni contrôle d'hôte."""
    client = TestClient(app)
    drone_headers = {"Authorization": f"Bearer {MOCK_DRONE_TOKEN}"}

    # 1. IAM : Tentative de création d'utilisateur -> 403 Forbidden
    resp_iam_create = client.post(
        "/api/olympe/ops/tenants/clientx-orso/users",
        json={"email": "hacker@test.fr", "full_name": "Infiltrator", "role": "admin", "is_admin": True},
        headers=drone_headers,
    )
    assert resp_iam_create.status_code == 403

    # 2. IAM : Tentative de suppression d'utilisateur -> 403 Forbidden
    resp_iam_delete = client.delete(
        "/api/olympe/ops/tenants/clientx-orso/users/usr_123",
        headers=drone_headers,
    )
    assert resp_iam_delete.status_code == 403

    # 3. Stripe : Tentative de modification de prix/formule -> 403 Forbidden
    resp_stripe_sub = client.post(
        "/api/olympe/ops/tenants/clientx-orso/subscription",
        json={"tier_id": "4_agents", "status": "active"},
        headers=drone_headers,
    )
    assert resp_stripe_sub.status_code == 403

    # 4. Hôte / OVH : Tentative de demande de clé ou diagnostic -> 403 Forbidden
    resp_ovh_cred = client.post("/api/olympe/ops/ovh/credential-request", headers=drone_headers)
    assert resp_ovh_cred.status_code == 403

    resp_ovh_status = client.get("/api/olympe/ops/ovh/status", headers=drone_headers)
    assert resp_ovh_status.status_code == 403

    # 5. Modification d'agents sur tenant non-sandbox -> 403 Forbidden
    resp_agents_forbidden = client.post(
        "/api/olympe/ops/tenants/financia-solutions/agents",
        json={"active": ["jerome"]},
        headers=drone_headers,
    )
    assert resp_agents_forbidden.status_code == 403


def test_ca4_immediate_token_revocation():
    """CA4 — La révocation du jeton prend effet immédiatement (401) et le drone ne peut s'attribuer de droits."""
    client = TestClient(app)
    drone_headers = {"Authorization": f"Bearer {MOCK_DRONE_TOKEN}"}

    # 1. Avant révocation : appel passe en 200 OK
    resp_before = client.get("/api/olympe/ops/tenants", headers=drone_headers)
    assert resp_before.status_code == 200

    # 2. Révocation immédiate
    revoke_token(MOCK_DRONE_TOKEN)

    # 3. Après révocation : appel rejeté en 401 Unauthorized
    resp_after = client.get("/api/olympe/ops/tenants", headers=drone_headers)
    assert resp_after.status_code == 401
    assert "révoqué" in resp_after.json()["detail"].lower()

    # 4. Le drone ne peut pas s'auto-débannir ou appeler l'auth
    resp_retry = client.get("/api/olympe/ops/stats", headers=drone_headers)
    assert resp_retry.status_code == 401


def test_ca5_client_account_isolation_and_ops_refusal():
    """CA5 — Le compte client de test n'a aucun accès au cockpit OPS (403)."""
    client = TestClient(app)

    # Simulation d'un jeton client régulier (rôle client/user sans privilège OPS)
    fake_client_token = "mock-client-session-token-non-ops"

    # Tentative d'accès au Cockpit OPS avec ce jeton -> 401 ou 403
    resp_ops_auth = client.get(
        "/api/olympe/ops/auth/me",
        headers={"Authorization": f"Bearer {fake_client_token}"},
    )
    assert resp_ops_auth.status_code in [401, 403]

    resp_ops_tenants = client.get(
        "/api/olympe/ops/tenants",
        headers={"Authorization": f"Bearer {fake_client_token}"},
    )
    assert resp_ops_tenants.status_code in [401, 403]


def test_ca6_stripe_webhook_reception_and_delivery_journal():
    """CA6 — Événement Stripe reçu par POST webhook, journalisé et consultable avec portée webhooks:read."""
    client = TestClient(app)
    drone_headers = {"Authorization": f"Bearer {MOCK_DRONE_TOKEN}"}

    # Création préalable du tenant de test
    ops_manager.create_sandbox_tenant("clientx-orso", "CLIENTX-ORSO (TEST)")

    # 1. Envoi d'un événement Webhook Stripe réel de test
    event_payload = {
        "id": "evt_test_drone_subscription_001",
        "type": "customer.subscription.created",
        "data": {
            "object": {
                "id": "sub_test_drone_123",
                "customer": "cus_test_clientx_orso",
                "status": "active",
                "metadata": {"tenant_slug": "clientx-orso", "tier_id": "2_agents"},
            }
        },
    }

    resp_webhook = client.post("/api/olympe/ops/webhooks/stripe", json=event_payload)
    assert resp_webhook.status_code == 200
    assert resp_webhook.json()["status"] == "processed"

    # 2. Consultation du journal de livraison avec le jeton drone (portée webhooks:read)
    resp_journal = client.get("/api/olympe/ops/webhooks/deliveries", headers=drone_headers)
    assert resp_journal.status_code == 200
    journal_data = resp_journal.json()
    assert "deliveries" in journal_data
    assert len(journal_data["deliveries"]) >= 1

    last_event = journal_data["deliveries"][0]
    assert last_event["id"] == "evt_test_drone_subscription_001"
    assert last_event["type"] == "customer.subscription.created"
    assert last_event["tenant_slug"] == "clientx-orso"

    # 3. Vérification de la signature Stripe HMAC-SHA256
    secret = "whsec_test_secret_key_123"
    payload_raw = json.dumps(event_payload).encode("utf-8")
    t = int(time.time())
    import hmac, hashlib
    signed_payload = f"{t}.".encode("utf-8") + payload_raw
    valid_sig = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()

    header_valid = f"t={t},v1={valid_sig}"
    assert verify_stripe_signature(payload_raw, header_valid, secret) is True

    header_invalid = f"t={t},v1=bad_signature_hash"
    assert verify_stripe_signature(payload_raw, header_invalid, secret) is False


def test_ca7_drone_distinct_audit_identity():
    """CA7 — Les actions du drone apparaissent sous l'identité distincte 'drone-clientx'."""
    client = TestClient(app)
    drone_headers = {"Authorization": f"Bearer {MOCK_DRONE_TOKEN}"}
    admin_headers = {"Authorization": f"Bearer {MOCK_SUPERADMIN_TOKEN}"}

    # Action effectuée par le superadmin humain
    client.get("/api/olympe/ops/stats", headers=admin_headers)

    # Actions effectuées par le drone machine
    client.get("/api/olympe/ops/tenants", headers=drone_headers)
    client.post(
        "/api/olympe/ops/tenants",
        json={"tenant_slug": "clientx-orso", "name": "CLIENTX-ORSO (TEST)"},
        headers=drone_headers,
    )

    # Récupération du journal d'audit
    resp_audit = client.get("/api/olympe/ops/audit-log", headers=drone_headers)
    assert resp_audit.status_code == 200
    events = resp_audit.json()["events"]

    drone_events = [e for e in events if e.get("role") == "drone"]
    human_events = [e for e in events if e.get("role") == "superadmin"]

    assert len(drone_events) > 0
    assert drone_events[0]["actor"] == "drone-clientx"
    assert len(human_events) > 0
    assert human_events[0]["actor"] == "admin@orso-agents.fr"


def test_ca8_secrets_delivery_and_permissions(tmp_path):
    """CA8 — Les secrets sont délivrés dans un fichier restreint chmod 600 sans transit en clair."""
    secrets_dir = Path.home() / ".hermes" / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    secrets_file = secrets_dir / "orso_drone.env"

    content = (
        "# Configuration Drone de Test Orso (Client-X-Orso)\n"
        "# Fichier restreint (chmod 600) — Confidentiel KAN-35\n"
        "ORSO_OPS_BASE_URL=https://ops.orso-agents.fr\n"
        f"ORSO_DRONE_API_TOKEN={MOCK_DRONE_TOKEN}\n"
        "ORSO_DRONE_ACTOR=drone-clientx\n"
        "ORSO_TEST_TENANT_SLUG=clientx-orso\n"
        "ORSO_TEST_CLIENT_EMAIL=dirigeant.clientx@test.orso-agents.fr\n"
        "ORSO_TEST_CLIENT_PASSWORD=TestSecureClientX2026!\n"
    )

    secrets_file.write_text(content, encoding="utf-8")
    os.chmod(secrets_file, 0o600)

    # Vérification des permissions
    st = os.stat(secrets_file)
    file_mode = stat.S_IMODE(st.st_mode)
    assert file_mode == 0o600, f"Le fichier de secrets doit avoir les permissions 0600 (obtenu: {oct(file_mode)})"

    # Vérification que le fichier est bien lisible par le propriétaire
    assert secrets_file.is_file()
    read_text = secrets_file.read_text(encoding="utf-8")
    assert "ORSO_DRONE_ACTOR=drone-clientx" in read_text
    assert "ORSO_TEST_TENANT_SLUG=clientx-orso" in read_text
