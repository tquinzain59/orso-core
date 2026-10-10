"""Tests invariants et d'acceptation pour le Journal d'Activité Client (KAN-107).

Valide les critères d'acceptation CA1 à CA10 :
- CA1 : Consultation sur 30 jours sans solliciter le support, en français sans jargon
- CA2 : Date, agent, action en clair, source concernée et issue
- CA3 : Distinction nette entre faite, en attente de validation, et refusée
- CA4 : Motif explicite sur action refusée
- CA5 : Preuve contradictoire d'étanchéité multi-tenant
- CA6 : Immutabilité append-only et traçabilité d'une tentative de suppression
- CA7 : Non-régression de la vue exploitation superviseur (audit_events)
- CA8 : Absence de corps intégral de message
- CA9 : Export JSON et CSV étanche par organisation
- CA10 : Rétention et recherche jusqu'à dix ans
"""

import json
import sqlite3
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from olympe.activity_manager import ClientActivityManager
from olympe.autonomy_manager import AutonomyManager
from olympe.ops_manager import OpsManager


@pytest.fixture
def temp_activity(tmp_path):
    """Fixture créant une instance isolée de ClientActivityManager."""
    db_file = tmp_path / "test_activity.db"
    return ClientActivityManager(db_path=db_file)


@pytest.fixture
def temp_autonomy(tmp_path, temp_activity):
    """Fixture créant un AutonomyManager branché sur le gestionnaire d'activité isolé."""
    db_file = tmp_path / "test_autonomy.db"
    return AutonomyManager(db_path=db_file, activity_manager=temp_activity)


def test_kan107_ca1_and_ca2_french_plain_entries(temp_activity):
    """CA1 & CA2 : Consultation sur 30 jours, champs obligatoires en français sans jargon."""
    # Enregistrement d'actions types
    temp_activity.record_activity(
        tenant_slug="acme-corp",
        agent_id="jerome",
        action_type="send_reminder_email",
        source_type="Facture",
        source_ref="Facture FAC-2026-102 (Client Martin)",
        status="done",
    )

    activities = temp_activity.get_activities(tenant_slug="acme-corp", days=30)
    assert len(activities) == 1
    act = activities[0]

    # Vérification des 5 champs obligatoires (CA2)
    assert "timestamp" in act and act["timestamp"]
    assert act["agent_id"] == "jerome"
    assert "Jérôme" in act["agent_name"]
    # Action en clair sans jargon technique (CA1)
    assert act["action_label"] == "Envoi d'un email de relance"
    assert act["source_type"] == "Facture"
    assert "FAC-2026-102" in act["source_ref"]
    assert act["status"] == "Faite"
    assert act["status_code"] == "done"


def test_kan107_ca3_and_ca4_pending_and_rejected_with_reason(temp_activity, temp_autonomy):
    """CA3 & CA4 : Actions en attente, faites et refusées avec motif explicite."""
    # 1. Action mise en attente via le registre d'autonomie (ticket jumeau KAN-106)
    temp_autonomy.create_pending_action(
        action_id="act-relance-01",
        agent_id="jerome",
        action_type="send_message_third_party",
        tenant_slug="acme-corp",
        recipient="debiteur@client.fr",
        draft_content="Bonjour, merci de régler sous 48h.",
    )

    # 2. Action rejetée avec motif explicite
    temp_autonomy.create_pending_action(
        action_id="act-devis-02",
        agent_id="lucas",
        action_type="send_quote",
        tenant_slug="acme-corp",
        recipient="prospect@societe.fr",
        draft_content="Devis remisé 50%",
    )
    temp_autonomy.reject_action(
        action_id="act-devis-02",
        reviewer_id="direction_user",
        reason="Remise non autorisée (plafond 15%)",
    )

    # Consultation du journal d'activité
    acts = temp_activity.get_activities(tenant_slug="acme-corp", days=30)
    assert len(acts) >= 2

    # Validation CA3 : Une entrée "En attente de validation"
    pending_act = next((a for a in acts if a["action_id"] == "act-relance-01"), None)
    assert pending_act is not None
    assert pending_act["status"] == "En attente de validation"
    assert pending_act["status_code"] == "pending_validation"

    # Validation CA4 : Une entrée "Refusée" avec son motif
    rejected_act = next((a for a in acts if a["action_id"] == "act-devis-02" and a["status_code"] == "rejected"), None)
    assert rejected_act is not None
    assert rejected_act["status"] == "Refusée"
    assert rejected_act["rejection_reason"] == "Remise non autorisée (plafond 15%)"


def test_kan107_ca5_tenant_isolation_proof(temp_activity):
    """CA5 : Preuve contradictoire d'étanchéité multi-tenant absolue."""
    # Tenant A
    temp_activity.record_activity(
        tenant_slug="tenant-a",
        agent_id="jerome",
        action_type="send_reminder_email",
        source_type="Facture",
        source_ref="FAC-A-01",
        status="done",
    )

    # Tenant B
    temp_activity.record_activity(
        tenant_slug="tenant-b",
        agent_id="lucas",
        action_type="send_quote",
        source_type="Devis",
        source_ref="DEV-B-99",
        status="done",
    )

    # Requête contradictoire pour Tenant A
    acts_a = temp_activity.get_activities(tenant_slug="tenant-a")
    assert len(acts_a) == 1
    assert acts_a[0]["source_ref"] == "FAC-A-01"
    assert not any("DEV-B-99" in a["source_ref"] for a in acts_a)

    # Requête contradictoire pour Tenant B
    acts_b = temp_activity.get_activities(tenant_slug="tenant-b")
    assert len(acts_b) == 1
    assert acts_b[0]["source_ref"] == "DEV-B-99"
    assert not any("FAC-A-01" in a["source_ref"] for a in acts_b)


def test_kan107_ca6_append_only_prevent_delete_and_trace(temp_activity, monkeypatch, tmp_path):
    """CA6 : Immutabilité append-only absolue, tentative de suppression impossible et tracée."""
    entry = temp_activity.record_activity(
        tenant_slug="acme-corp",
        agent_id="jerome",
        action_type="book_accounting_entry",
        source_type="Comptabilité",
        source_ref="Écriture #8912",
        status="done",
    )
    entry_id = entry["id"]

    # Tentative directe de DELETE SQL bloquée par le trigger SQLite
    with pytest.raises((sqlite3.OperationalError, sqlite3.IntegrityError)) as exc_sql:
        with sqlite3.connect(str(temp_activity.db_path)) as conn:
            conn.execute("DELETE FROM client_activity_log WHERE id = ?;", (entry_id,))
            conn.commit()
    assert "APPEND_ONLY_VIOLATION" in str(exc_sql.value)

    # Tentative directe d'UPDATE SQL bloquée par le trigger SQLite
    with pytest.raises((sqlite3.OperationalError, sqlite3.IntegrityError)) as exc_upd:
        with sqlite3.connect(str(temp_activity.db_path)) as conn:
            conn.execute("UPDATE client_activity_log SET status = 'deleted' WHERE id = ?;", (entry_id,))
            conn.commit()
    assert "APPEND_ONLY_VIOLATION" in str(exc_upd.value)

    # Tentative via l'API / méthode dédiée avec traçabilité d'audit
    ops_db = tmp_path / "ops_test.db"
    monkeypatch.setenv("OLYMPE_DB_PATH", str(ops_db))
    ops = OpsManager(demo_mode=False)
    monkeypatch.setattr("olympe.ops_manager.OpsManager", lambda *a, **kw: ops)

    with pytest.raises(PermissionError) as exc_perm:
        temp_activity.attempt_delete_entry(
            entry_id=entry_id,
            tenant_slug="acme-corp",
            actor={"actor": "malicious_actor@acme.com", "role": "client"},
        )
    assert "APPEND_ONLY_VIOLATION" in str(exc_perm.value)

    # Vérification que l'incident d'audit a bien été consigné
    audit_events = ops.get_audit_events()
    sec_event = next((e for e in audit_events if e["action"] == "security:unauthorized_deletion_attempt"), None)
    assert sec_event is not None
    assert sec_event["actor"] == "malicious_actor@acme.com"


def test_kan107_ca7_ops_view_not_degraded(tmp_path, monkeypatch):
    """CA7 : La vue d'exploitation conserve sa granularité technique inchangée."""
    ops_db = tmp_path / "ops_audit.db"
    monkeypatch.setenv("OLYMPE_DB_PATH", str(ops_db))
    ops = OpsManager(demo_mode=False)

    # Enregistrement d'événements techniques superviseur
    ops.record_audit_event(
        actor={"actor": "drone-x", "role": "drone"},
        action="tenant:provision:sandbox",
        target="tenant-sandbox-01",
        details={"memory_mb": 512, "cpus": 1.0},
    )

    events = ops.get_audit_events()
    assert len(events) == 1
    assert events[0]["action"] == "tenant:provision:sandbox"
    assert events[0]["details"]["memory_mb"] == 512


def test_kan107_ca8_privacy_and_no_full_message_body(temp_activity):
    """CA8 : Aucune copie intégrale du corps des messages dans le journal."""
    long_body = "Ceci est un long texte confidentiel contenant des données personnelles " * 10
    entry = temp_activity.record_activity(
        tenant_slug="acme-corp",
        agent_id="jerome",
        action_type="send_reminder_email",
        source_type="Facture",
        source_ref="FAC-2026-999",
        status="done",
        metadata={
            "recipient": "client@secret.com",
            "body": long_body,
            "draft_content": long_body,
        },
    )

    meta = entry["metadata"]
    # Vérification que ni body ni draft_content brut complet ne subsiste
    assert "body" not in meta
    assert "draft_content" not in meta
    # Seul un résumé tronqué ou des métadonnées légitimes sont conservés
    if "body_summary" in meta:
        assert len(meta["body_summary"]) <= 125


def test_kan107_ca9_export_json_and_csv_isolated(temp_activity):
    """CA9 : Export du journal en JSON et CSV avec étanchéité multi-tenant."""
    temp_activity.record_activity(
        tenant_slug="org-alpha",
        agent_id="jerome",
        action_type="send_reminder_email",
        source_type="Facture",
        source_ref="FAC-001",
        status="done",
    )
    temp_activity.record_activity(
        tenant_slug="org-beta",
        agent_id="lucas",
        action_type="send_quote",
        source_type="Devis",
        source_ref="DEV-002",
        status="done",
    )

    # Export JSON
    json_export = temp_activity.export_activities("org-alpha", export_format="json")
    data = json.loads(json_export)
    assert data["tenant_slug"] == "org-alpha"
    assert len(data["entries"]) == 1
    assert data["entries"][0]["source_ref"] == "FAC-001"
    assert "DEV-002" not in json_export

    # Export CSV
    csv_export = temp_activity.export_activities("org-alpha", export_format="csv")
    assert "Date;Agent;Action en clair;Source concernée;Issue" in csv_export
    assert "FAC-001" in csv_export
    assert "DEV-002" not in csv_export


def test_kan107_ca10_ten_year_retention_lookup(temp_activity):
    """CA10 : Rétention dix ans et recherche sur une période ancienne."""
    now = datetime.now(timezone.utc)
    # Entrée créée il y a 9 ans (simulant une pièce comptable archivée)
    nine_years_ago = (now - timedelta(days=365 * 9)).isoformat()
    temp_activity.record_activity(
        tenant_slug="acme-corp",
        agent_id="jerome",
        action_type="book_accounting_entry",
        source_type="Écriture",
        source_ref="Écriture Comptable #2017-098",
        status="done",
        created_at=nine_years_ago,
    )

    # 1. Requête standard sur 30 jours -> l'entrée ancienne n'apparaît pas
    recent_acts = temp_activity.get_activities(tenant_slug="acme-corp", days=30)
    assert len(recent_acts) == 0

    # 2. Requête élargie à 10 ans (3650 jours) -> l'entrée ancienne est retrouvée intacte (CA10)
    historical_acts = temp_activity.get_activities(tenant_slug="acme-corp", days=3650)
    assert len(historical_acts) == 1
    target = historical_acts[0]
    assert target["source_ref"] == "Écriture Comptable #2017-098"
    assert target["timestamp"] == nine_years_ago


def test_kan107_api_endpoints_integration(temp_activity, monkeypatch):
    """Validation de l'intégration HTTP des routes API /api/client/activity."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from hermes_cli.web_routers.client_ui import router, verify_client_access
    import hermes_cli.web_routers.client_ui as client_ui_mod

    monkeypatch.setattr(client_ui_mod, "activity_manager", temp_activity)

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_client_access] = lambda: {
        "tenant": {"tenant_slug": "api-client"},
        "email": "dirigeant@api-client.fr",
        "role": "admin",
    }
    client = TestClient(app)

    # 1. Enregistrement d'activité via POST /api/client/activity
    post_res = client.post(
        "/api/client/activity",
        json={
            "agent_id": "jerome",
            "action_type": "send_reminder_email",
            "source_type": "Facture",
            "source_ref": "FAC-API-101",
            "status": "done",
        },
    )
    assert post_res.status_code == 200
    entry_id = post_res.json()["entry"]["id"]

    # 2. Consultation via GET /api/client/activity
    get_res = client.get("/api/client/activity?days=30")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["success"] is True
    assert data["total_count"] >= 1
    assert data["entries"][0]["source_ref"] == "FAC-API-101"

    # 3. Export CSV et JSON (CA9)
    exp_csv = client.get("/api/client/activity/export?format=csv")
    assert exp_csv.status_code == 200
    assert "FAC-API-101" in exp_csv.text

    exp_json = client.get("/api/client/activity/export?format=json")
    assert exp_json.status_code == 200
    assert "FAC-API-101" in exp_json.text

    # 4. Tentative de suppression bloquée (403 append-only CA6)
    del_res = client.delete(f"/api/client/activity/{entry_id}")
    assert del_res.status_code == 403
    assert "APPEND_ONLY_VIOLATION" in str(del_res.json())
