"""Tests d'acceptation automatisés pour le ticket KAN-106 (Politique d'autonomie par action et piste d'audit).

Vérifie formellement :
- Le chargement des fichiers autonomy_policy.yaml pour chaque persona.
- Les garde-fous HITL inscrits dans profiles/jerome/SOUL.md.
- L'interception et le cycle de vie des actions sensibles dans data/pending_actions.db.
- Les endpoints d'approbation et de rejet : POST /api/client/actions/{id}/approve & reject.
"""

from pathlib import Path
from unittest.mock import patch
import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hermes_cli.web_routers.client_ui import router
from olympe.autonomy_manager import AutonomyManager, autonomy_manager


@pytest.fixture
def temp_autonomy(tmp_path):
    """Instancie un AutonomyManager avec base de données SQLite temporaire."""
    db_file = tmp_path / "test_pending_actions.db"
    return AutonomyManager(db_path=db_file)


@pytest.fixture
def test_client(tmp_path, monkeypatch):
    """Client API FastAPI configuré avec base temporaire pour AutonomyManager."""
    db_file = tmp_path / "test_api_actions.db"
    monkeypatch.setattr(autonomy_manager, "db_path", db_file)
    autonomy_manager._init_db()

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_kan106_autonomy_policies_and_rules(temp_autonomy):
    """Vérifie le chargement des politiques d'autonomie par agent et l'exigence d'approbation."""
    # 1. Vérification pour Jérôme
    policy_jerome = temp_autonomy.get_policy("jerome")
    assert policy_jerome["agent_id"] == "jerome"
    assert policy_jerome["autonomy_level"] == "supervised"

    # Actions supervisées requérant approbation
    assert temp_autonomy.is_approval_required("jerome", "send_email") is True
    assert temp_autonomy.is_approval_required("jerome", "send_sms") is True
    assert temp_autonomy.is_approval_required("jerome", "apply_discount") is True

    # Actions autonomes sans approbation
    assert temp_autonomy.is_approval_required("jerome", "analyze_aged_balance") is False
    assert temp_autonomy.is_approval_required("jerome", "score_siren") is False

    # 2. Vérification pour Lucas, Clara et Victor
    assert temp_autonomy.is_approval_required("lucas", "send_quote") is True
    assert temp_autonomy.is_approval_required("lucas", "search_prospects") is False

    assert temp_autonomy.is_approval_required("clara", "issue_refund") is True
    assert temp_autonomy.is_approval_required("clara", "read_ticket") is False

    assert temp_autonomy.is_approval_required("victor", "submit_bid") is True
    assert temp_autonomy.is_approval_required("victor", "monitor_boamp") is False


def test_kan106_jerome_soul_safeguards():
    """Vérifie la présence des garde-fous explicites HITL dans profiles/jerome/SOUL.md."""
    soul_file = Path("profiles/jerome/SOUL.md")
    assert soul_file.is_file()
    content = soul_file.read_text(encoding="utf-8")

    assert "autonomy_policy.yaml" in content
    assert "JAMAIS envoyer d'email" in content
    assert "ActionCard" in content
    assert "remise commerciale" in content or "abandonner une créance" in content


def test_kan106_pending_actions_lifecycle(temp_autonomy):
    """Vérifie la persistance et les transitions d'états d'une action sensible."""
    # 1. Création de l'action en attente
    act = temp_autonomy.create_pending_action(
        action_id="act_relance_456",
        agent_id="jerome",
        action_type="send_email",
        tenant_slug="client-acme",
        recipient="debiteur@client.fr",
        draft_content="Bonjour, merci de régler la facture...",
    )
    assert act["status"] == "PENDING"
    assert act["requires_approval"] is True

    # Vérification dans la liste des actions en attente
    pending_list = temp_autonomy.get_pending_actions(tenant_slug="client-acme", status="PENDING")
    assert len(pending_list) == 1
    assert pending_list[0]["id"] == "act_relance_456"

    # 2. Approbation formelle
    app_res = temp_autonomy.approve_action(
        action_id="act_relance_456",
        reviewer_id="daf@acme.fr",
        reviewer_role="daf",
        comment="Validation accordée pour relance amiable niveau 1",
    )
    assert app_res["success"] is True
    assert app_res["status"] == "APPROVED"

    # 3. Exécution effective
    exec_res = temp_autonomy.mark_executed("act_relance_456", result={"sent": True, "provider": "brevo"})
    assert exec_res["status"] == "EXECUTED"


def test_kan106_action_rejection(temp_autonomy):
    """Vérifie le rejet d'une action sensible avec motif."""
    temp_autonomy.create_pending_action(
        action_id="act_discount_789",
        agent_id="jerome",
        action_type="apply_discount",
        tenant_slug="client-acme",
        draft_content="Remise de 10%",
    )

    rej_res = temp_autonomy.reject_action(
        action_id="act_discount_789",
        reviewer_id="direction@acme.fr",
        reviewer_role="direction",
        reason="Dépassement du seuil autorisé",
    )
    assert rej_res["success"] is True
    assert rej_res["status"] == "REJECTED"
    assert rej_res["rejection_reason"] == "Dépassement du seuil autorisé"


def test_kan106_api_endpoints_approve_reject(test_client):
    """Vérifie les endpoints REST d'approbation et de rejet."""
    secret = "test_super_secret_jwt_key_32_bytes_long_min!!"
    token = jwt.encode(
        {
            "tenant_slug": "api-acme",
            "sub": "admin_user",
            "role": "admin",
            "app_metadata": {"tenant_slug": "api-acme"},
            "user_metadata": {"role": "admin"},
        },
        secret,
        algorithm="HS256",
    )
    headers = {"Authorization": f"Bearer {token}"}

    with patch.dict("os.environ", {"SUPABASE_JWT_SECRET": secret, "ORSO_CLIENT_SLUG": "api-acme"}):
        # Créer une action
        autonomy_manager.create_pending_action(
            action_id="card_relance_999",
            agent_id="jerome",
            action_type="send_email",
            tenant_slug="api-acme",
            recipient="compta@prospect.fr",
        )

        # 1. Lister les actions en attente
        list_res = test_client.get("/api/client/actions/pending", headers=headers)
        assert list_res.status_code == 200
        assert list_res.json()["count"] >= 1

        # 2. Approuver
        approve_res = test_client.post(
            "/api/client/actions/card_relance_999/approve",
            json={"comment": "OK pour expédition"},
            headers=headers,
        )
        assert approve_res.status_code == 200
        assert approve_res.json()["status"] == "APPROVED"

        # 3. Rejeter une autre action
        autonomy_manager.create_pending_action(
            action_id="card_relance_888",
            agent_id="jerome",
            action_type="send_sms",
            tenant_slug="api-acme",
        )
        reject_res = test_client.post(
            "/api/client/actions/card_relance_888/reject",
            json={"reason": "Le client a promis un virement demain"},
            headers=headers,
        )
        assert reject_res.status_code == 200
        assert reject_res.json()["status"] == "REJECTED"
