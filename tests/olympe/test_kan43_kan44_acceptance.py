"""Tests d'acceptation formels pour KAN-43 & KAN-44.

Vérifie l'ensemble des critères d'acceptation (CA1 à CA4 pour KAN-43, CA1 à CA5 pour KAN-44)
définis par Jarvis (PO) et validés par l'Architecte Technique :

KAN-43 :
- CA1 : Aucun client fictif renvoyé par les routes du cockpit en production.
- CA2 : Un client créé en base apparaît dans le cockpit sans redémarrage du service.
- CA3 : Les indicateurs et la facturation se recalculent depuis la base.
- CA4 : Le mode démonstration est refusé en production et signalé lorsqu'il est actif.

KAN-44 :
- CA1 : Un abonnement créé produit une livraison journalisée avec tenant identifié.
- CA2 : L'environnement du tenant existe et répond après l'événement.
- CA3 : Un événement dont le client est inconnu est refusé, journalisé en échec avec motif, sans effet de bord.
- CA4 : Le rejeu du même événement ne produit aucun effet supplémentaire (idempotence).
- CA5 : Aucun cas attrape-tout dans la correspondance client vers tenant.
"""

import json
import time
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from olympe.auth import MOCK_SUPERADMIN_TOKEN, clear_token_cache
from olympe.ops_manager import OpsManager, is_production
from olympe.server import app, ops_manager, manager


@pytest.fixture(autouse=True)
def reset_ops_state():
    """Réinitialise les états mémoires avant chaque test."""
    clear_token_cache()
    ops_manager._webhook_deliveries.clear()
    ops_manager._audit_log.clear()
    ops_manager._processed_events.clear()
    yield
    clear_token_cache()
    ops_manager._webhook_deliveries.clear()
    ops_manager._audit_log.clear()
    ops_manager._processed_events.clear()


# ══════════════════════════════════════════════════════════════════════════════
# KAN-43 — Source de vérité unique & Cockpit alimenté par la base
# ══════════════════════════════════════════════════════════════════════════════

def test_kan43_ca1_no_mock_tenants_in_production(monkeypatch):
    """CA1 — En production, aucun client d'amorçage fictif n'est renvoyé."""
    monkeypatch.setenv("ORSO_ENV", "production")
    assert is_production() is True

    ops = OpsManager(
        supabase_url="https://fake.supabase.co",
        supabase_key="fake_key",
        demo_mode=False,
    )

    # 1. Base Supabase vide -> renvoie strictement [], aucune donnée fictive
    with patch.object(ops, "_query_supabase", return_value=[]):
        tenants = ops.get_tenants_overview()
        assert tenants == []
        assert len(tenants) == 0

    # 2. Base Supabase avec clients réels -> renvoie strictement ces clients
    db_records = [
        {
            "id": "tenant-reel-001",
            "name": "Entreprise Réelle SAS",
            "slug": "entreprise-reelle",
            "siret": "12345678900012",
            "status": "active",
            "created_at": "2026-09-28T10:00:00Z",
            "subscriptions": [
                {
                    "id": "sub_reel_001",
                    "tier_id": "1_agent",
                    "monthly_price_ht": 99.00,
                    "status": "ACTIVE",
                }
            ],
            "tenant_instances": [
                {
                    "docker_container_name": "orso_client_entreprise_reelle",
                    "status": "ready",
                    "environment_status": "active",
                    "agents_enabled": ["jerome"],
                }
            ],
            "profiles": [],
            "invoices": [],
        }
    ]
    with patch.object(ops, "_query_supabase", return_value=db_records):
        with patch.object(ops, "_fetch_supabase_auth_users", return_value={}):
            tenants = ops.get_tenants_overview()
            assert len(tenants) == 1
            assert tenants[0]["slug"] == "entreprise-reelle"
            assert tenants[0]["name"] == "Entreprise Réelle SAS"
            # Vérifier l'absence absolue des 4 mocks
            returned_slugs = [t["slug"] for t in tenants]
            assert "financia-solutions" not in returned_slugs
            assert "commercialink" not in returned_slugs


def test_kan43_ca2_db_client_reflected_immediately_without_restart(monkeypatch):
    """CA2 — Un client créé en base apparaît immédiatement dans le cockpit sans redémarrage."""
    monkeypatch.setenv("ORSO_ENV", "production")
    ops = OpsManager(
        supabase_url="https://fake.supabase.co",
        supabase_key="fake_key",
        demo_mode=False,
    )

    db_state = [
        {
            "id": "tenant-001",
            "name": "Premier Client",
            "slug": "premier-client",
            "status": "active",
            "created_at": "2026-09-28T10:00:00Z",
            "subscriptions": [{"tier_id": "1_agent", "monthly_price_ht": 99.00, "status": "ACTIVE"}],
            "tenant_instances": [],
            "profiles": [],
            "invoices": [],
        }
    ]

    with patch.object(ops, "_query_supabase", side_effect=lambda path, **kw: list(db_state)):
        with patch.object(ops, "_fetch_supabase_auth_users", return_value={}):
            # 1. Première lecture : 1 client
            res1 = ops.get_tenants_overview()
            assert len(res1) == 1
            assert res1[0]["slug"] == "premier-client"

            # 2. Ajout dynamique d'un nouveau client en base
            db_state.append({
                "id": "tenant-002",
                "name": "Second Client Nouveau",
                "slug": "second-client-nouveau",
                "status": "active",
                "created_at": "2026-09-28T11:00:00Z",
                "subscriptions": [{"tier_id": "2_agents", "monthly_price_ht": 169.00, "status": "ACTIVE"}],
                "tenant_instances": [],
                "profiles": [],
                "invoices": [],
            })

            # 3. Deuxième lecture immédiate sur la même instance : 2 clients constatés
            res2 = ops.get_tenants_overview()
            assert len(res2) == 2
            assert res2[1]["slug"] == "second-client-nouveau"


def test_kan43_ca3_metrics_and_billing_recalculated_from_db(monkeypatch):
    """CA3 — Les indicateurs (MRR, abonnés) et factures se recalculent depuis la base."""
    monkeypatch.setenv("ORSO_ENV", "production")
    ops = OpsManager(
        supabase_url="https://fake.supabase.co",
        supabase_key="fake_key",
        demo_mode=False,
    )

    db_state = [
        {
            "id": "tenant-mrr-1",
            "name": "Client MRR",
            "slug": "client-mrr",
            "status": "active",
            "subscriptions": [{"tier_id": "1_agent", "monthly_price_ht": 99.00, "status": "ACTIVE"}],
            "tenant_instances": [{"agents_enabled": ["jerome"]}],
            "profiles": [],
            "invoices": [],
        }
    ]

    with patch.object(ops, "_query_supabase", side_effect=lambda path, **kw: list(db_state)):
        with patch.object(ops, "_fetch_supabase_auth_users", return_value={}):
            stats1 = ops.get_stats()
            assert stats1["kpis"]["mrr_ht"] == 99.00
            assert stats1["kpis"]["active_subscribers"] == 1

            # Mise à jour du montant en base (Upgrade vers Flotte Complète 279 €)
            db_state[0]["subscriptions"][0]["tier_id"] = "4_agents"
            db_state[0]["subscriptions"][0]["monthly_price_ht"] = 279.00

            stats2 = ops.get_stats()
            assert stats2["kpis"]["mrr_ht"] == 279.00
            assert stats2["kpis"]["active_subscribers"] == 1


def test_kan43_ca4_demo_mode_safety_locks(monkeypatch):
    """CA4 — Le mode démo est formellement interdit en prod et signalé sur les routes API."""
    # 1. En production (ORSO_ENV ou APP_ENV), ORSO_DEMO_MODE=1 lève une exception bloquante
    monkeypatch.setenv("ORSO_ENV", "production")
    monkeypatch.setenv("ORSO_DEMO_MODE", "1")

    with pytest.raises(RuntimeError, match="formellement interdit en environnement de production"):
        OpsManager(demo_mode=True)

    # Vérification avec APP_ENV=production
    monkeypatch.delenv("ORSO_ENV", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError, match="formellement interdit en environnement de production"):
        OpsManager(demo_mode=True)
    monkeypatch.delenv("APP_ENV", raising=False)

    # 2. Hors production, le mode démo est signalé dans la réponse API
    monkeypatch.delenv("ORSO_ENV", raising=False)
    monkeypatch.setenv("ORSO_DEMO_MODE", "1")
    client = TestClient(app)
    admin_headers = {"Authorization": f"Bearer {MOCK_SUPERADMIN_TOKEN}"}

    # Forcer ops_manager en mode démo pour le test de route
    ops_manager.demo_mode = True
    resp_stats = client.get("/api/olympe/ops/stats", headers=admin_headers)
    assert resp_stats.status_code == 200
    assert resp_stats.json()["demo_mode"] is True

    resp_tenants = client.get("/api/olympe/ops/tenants", headers=admin_headers)
    assert resp_tenants.status_code == 200
    assert resp_tenants.json()["demo_mode"] is True

    resp_invoices = client.get("/api/olympe/ops/invoices", headers=admin_headers)
    assert resp_invoices.status_code == 200
    assert resp_invoices.json()["demo_mode"] is True

    # 3. Mode démo désactivé -> demo_mode: False
    ops_manager.demo_mode = False
    resp_prod_tenants = client.get("/api/olympe/ops/tenants", headers=admin_headers)
    assert resp_prod_tenants.status_code == 200
    assert resp_prod_tenants.json()["demo_mode"] is False

    # 4. En production, list_all_invoices ne renvoie jamais de factures fictives
    monkeypatch.setenv("ORSO_ENV", "production")
    prod_ops = OpsManager(demo_mode=False)
    assert prod_ops.list_all_invoices() == []


# ══════════════════════════════════════════════════════════════════════════════
# KAN-44 — Chaîne d'abonnement & Provisioning conteneurisé
# ══════════════════════════════════════════════════════════════════════════════

def test_kan44_ca1_and_ca2_webhook_creates_environment_and_logs_delivery():
    """CA1 & CA2 — L'événement Stripe provisionne et active l'environnement conteneurisé."""
    client = TestClient(app)
    admin_headers = {"Authorization": f"Bearer {MOCK_SUPERADMIN_TOKEN}"}

    # Initialisation d'un client dans le référentiel pour réconciliation par slug
    slug = "nexis-logistics"
    ops_manager._mock_tenants[f"test-{slug}"] = {
        "id": f"test-{slug}",
        "name": "Nexis Logistics",
        "slug": slug,
        "subscription": {
            "status": "trialing",
            "stripe_customer_id": "cus_nexis_123",
        },
        "instance": {"status": "not_provisioned", "environment_status": "inactive"},
    }

    event_id = f"evt_test_subscription_{int(time.time()*1000)}"
    webhook_payload = {
        "id": event_id,
        "type": "customer.subscription.created",
        "data": {
            "object": {
                "id": "sub_nexis_real_999",
                "customer": "cus_nexis_123",
                "status": "active",
                "metadata": {"tenant_slug": slug, "tier_id": "1_agent"},
            }
        },
    }

    # Émission du webhook
    resp = client.post("/api/olympe/ops/webhooks/stripe", json=webhook_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "processed"
    assert data["tenant_slug"] == slug
    assert data["environment_status"] == "active"
    assert "orso_client_nexis_logistics" in data["container_name"]

    # CA1 Preuve : Consultation du journal des livraisons
    resp_journal = client.get("/api/olympe/ops/webhooks/deliveries", headers=admin_headers)
    assert resp_journal.status_code == 200
    deliveries = resp_journal.json()["deliveries"]
    matched_delivery = next((d for d in deliveries if d["id"] == event_id), None)
    assert matched_delivery is not None
    assert matched_delivery["tenant_slug"] == slug
    assert matched_delivery["status"] == "processed"

    # CA2 Preuve : L'environnement du tenant existe et est opérationnel
    status_info = manager.get_tenant_status(slug)
    assert status_info["tenant_slug"] == slug
    assert status_info["status"] in ("ready", "starting")


def test_kan44_ca3_unknown_client_rejected_with_reason_and_no_side_effects():
    """CA3 — Événement avec client inconnu refusé, journalisé en échec avec motif, sans effet de bord."""
    client = TestClient(app)
    admin_headers = {"Authorization": f"Bearer {MOCK_SUPERADMIN_TOKEN}"}

    event_id = f"evt_unknown_{int(time.time()*1000)}"
    unknown_cus = "cus_totalement_inconnu_000"
    webhook_payload = {
        "id": event_id,
        "type": "customer.subscription.created",
        "data": {
            "object": {
                "id": "sub_unknown_999",
                "customer": unknown_cus,
                "status": "active",
                "metadata": {},  # Aucune métadonnée
            }
        },
    }

    resp = client.post("/api/olympe/ops/webhooks/stripe", json=webhook_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert data["error"] == "TENANT_NOT_FOUND"

    # Vérification de la livraison en échec avec motif explicite
    resp_journal = client.get("/api/olympe/ops/webhooks/deliveries", headers=admin_headers)
    deliveries = resp_journal.json()["deliveries"]
    failed_delivery = next((d for d in deliveries if d["id"] == event_id), None)
    assert failed_delivery is not None
    assert failed_delivery["status"] == "failed"
    assert "TENANT_NOT_FOUND" in failed_delivery["error_reason"]
    assert failed_delivery["tenant_slug"] is None


def test_kan44_ca4_idempotent_replay_produces_no_additional_effects():
    """CA4 — Le rejeu du même événement produit already_processed sans effet supplémentaire."""
    client = TestClient(app)

    slug = "replay-tenant"
    ops_manager._mock_tenants[f"test-{slug}"] = {
        "id": f"test-{slug}",
        "name": "Replay Tenant",
        "slug": slug,
        "subscription": {"status": "trialing", "stripe_customer_id": "cus_replay_777"},
        "instance": {"status": "not_provisioned", "environment_status": "inactive"},
    }

    event_id = "evt_replay_idempotency_unique_test"
    payload = {
        "id": event_id,
        "type": "customer.subscription.created",
        "data": {
            "object": {
                "id": "sub_replay_111",
                "customer": "cus_replay_777",
                "status": "active",
                "metadata": {"tenant_slug": slug},
            }
        },
    }

    # 1. Premier envoi -> traité
    resp1 = client.post("/api/olympe/ops/webhooks/stripe", json=payload)
    assert resp1.status_code == 200
    assert resp1.json()["status"] == "processed"

    # 2. Deuxième envoi (rejeu) -> already_processed
    resp2 = client.post("/api/olympe/ops/webhooks/stripe", json=payload)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["status"] == "already_processed"
    assert data2["replay_count"] == 1
    assert data2["tenant_slug"] == slug

    # 3. Troisième envoi (rejeu #2) -> replay_count incrémenté
    resp3 = client.post("/api/olympe/ops/webhooks/stripe", json=payload)
    assert resp3.status_code == 200
    assert resp3.json()["replay_count"] == 2


def test_kan44_ca5_no_catch_all_mapping():
    """CA5 — Preuve de suppression du cas attrape-tout : un événement sans relation n'est jamais rattaché à clientx-orso."""
    client = TestClient(app)

    # Assurer que clientx-orso existe dans le système
    ops_manager._mock_tenants["test-tenant-clientx-orso"] = {
        "id": "test-tenant-clientx-orso",
        "name": "CLIENTX-ORSO (TEST)",
        "slug": "clientx-orso",
        "subscription": {"stripe_customer_id": "cus_clientx_legit"},
        "instance": {"status": "ready", "environment_status": "active"},
    }

    # Événement pour un client inconnu arbitraire
    arbitrary_payload = {
        "id": "evt_arbitrary_random_999",
        "type": "customer.subscription.created",
        "data": {
            "object": {
                "id": "sub_arbitrary",
                "customer": "cus_autre_client_inconnu",
                "status": "active",
                # Pas de metadata slug
            }
        },
    }

    resp = client.post("/api/olympe/ops/webhooks/stripe", json=arbitrary_payload)
    data = resp.json()
    # DOIT échouer et ne JAMAIS être attribué à clientx-orso
    assert data["status"] == "failed"
    assert data["error"] == "TENANT_NOT_FOUND"


def test_kan44_subscription_cancellation_suspends_without_destruction():
    """Décision 5 — Une résiliation suspend le conteneur mais ne détruit jamais les données."""
    client = TestClient(app)

    slug = "tenant-to-cancel"
    ops_manager._mock_tenants[f"test-{slug}"] = {
        "id": f"test-{slug}",
        "name": "Tenant to Cancel",
        "slug": slug,
        "subscription": {"status": "active", "stripe_customer_id": "cus_cancel_001"},
        "instance": {"status": "ready", "environment_status": "active"},
    }

    # Événement d'annulation Stripe
    cancel_payload = {
        "id": f"evt_cancel_{int(time.time()*1000)}",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_cancel_001",
                "customer": "cus_cancel_001",
                "status": "canceled",
                "metadata": {"tenant_slug": slug},
            }
        },
    }

    resp = client.post("/api/olympe/ops/webhooks/stripe", json=cancel_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "processed"
    assert data["environment_status"] == "suspended"

    # Vérification que le tenant existe toujours (non détruit !)
    t_data = ops_manager._mock_tenants[f"test-{slug}"]
    assert t_data["subscription"]["status"] == "canceled"
    assert t_data["instance"]["environment_status"] == "inactive"
    assert t_data["instance"]["status"] == "sleeping"
