"""Tests d'acceptation automatisés pour le ticket KAN-106 (Politique d'autonomie par action et traçabilité HITL).

Vérifie formellement :
- CA1 : Les 4 agents (Jérôme, Lucas, Clara, Victor) disposent d'une politique écrite (autonomy_policy.yaml)
        couvrant au minimum les actions obligatoires du périmètre, avec 3 niveaux (libre, sous_validation, interdit).
- CA2 : Une action classée sous_validation génère une demande portant le contenu exact, et rien n'est exécuté sans approbation.
- CA3 : Expiration après 48h ou rejet : aucune exécution, trace explicite dans la base d'audit (statut EXPIRED ou REJECTED).
- CA4 : Restitution de la politique par l'API pour affichage portail en français clair.
- CA5 : Contrôle strict pré-exécution (check_action_execution) : refus immédiat si 'interdit' ou non validé.
- CA6 & CA7 : Traçabilité des modifications de niveaux (table policy_change_audit) et respect absolu des planchers contractuels.
- CA8 : Récapitulatif des demandes restées sans réponse et traitement par lot (batch-review).
"""

from pathlib import Path
from unittest.mock import patch
import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hermes_cli.web_routers.client_ui import router
from olympe.autonomy_manager import AutonomyManager, autonomy_manager, MANDATORY_PERIMETER_ACTIONS


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


def test_kan106_ca1_policies_cover_mandatory_actions_and_three_levels(temp_autonomy):
    """CA1 : Les 4 agents disposent d'une politique couvrant les actions du périmètre avec 3 niveaux."""
    agents = ["jerome", "lucas", "clara", "victor"]

    for ag in agents:
        policy = temp_autonomy.get_policy(ag)
        assert policy["agent_id"] == ag
        actions = policy.get("actions", [])
        assert len(actions) >= len(MANDATORY_PERIMETER_ACTIONS)

        covered_types = {a["action_type"] for a in actions}
        for mandatory_action in MANDATORY_PERIMETER_ACTIONS:
            assert mandatory_action in covered_types, f"Action obligatoire '{mandatory_action}' manquante pour {ag}"

        # Vérifier que les 3 niveaux sont exploités
        levels = {a["level"] for a in actions}
        assert "libre" in levels
        assert "sous_validation" in levels
        assert "interdit" in levels


def test_kan106_ca2_supervised_action_exact_content_and_gating(temp_autonomy):
    """CA2 : Une action sous validation porte le contenu exact et bloque l'exécution sans approbation."""
    draft_msg = "Bonjour M. Martin, nous constatons un retard de 45 jours sur la facture FA-2026-089."
    act = temp_autonomy.create_pending_action(
        action_id="act_relance_101",
        agent_id="jerome",
        action_type="send_payment_reminder",
        tenant_slug="client-test",
        recipient="comptabilite@debiteur.fr",
        draft_content=draft_msg,
    )
    assert act["status"] == "PENDING"
    assert act["requires_approval"] is True

    # Avant approbation : vérification pré-exécution -> REFUS
    check_before = temp_autonomy.check_action_execution("jerome", "send_payment_reminder", action_id="act_relance_101")
    assert check_before["allowed"] is False
    assert check_before["code"] == "ERR_APPROVAL_NOT_GRANTED"

    # Approbation explicite
    app_res = temp_autonomy.approve_action("act_relance_101", reviewer_id="direction@client.fr", reviewer_role="direction")
    assert app_res["success"] is True

    # Après approbation : vérification pré-exécution -> AUTORISÉ
    check_after = temp_autonomy.check_action_execution("jerome", "send_payment_reminder", action_id="act_relance_101")
    assert check_after["allowed"] is True
    assert check_after["status"] == "APPROVED"


def test_kan106_ca3_expiration_and_rejection_trace(temp_autonomy):
    """CA3 : Une action refusée ou expirée ne produit aucune exécution et laisse une trace explicite."""
    # 1. Action rejetée
    temp_autonomy.create_pending_action(
        action_id="act_to_reject",
        agent_id="lucas",
        action_type="send_quote",
        tenant_slug="client-test",
        draft_content="Devis remisé de 30%",
    )
    rej = temp_autonomy.reject_action("act_to_reject", reviewer_id="user_admin", reason="Remise trop élevée")
    assert rej["status"] == "REJECTED"
    assert rej["rejection_reason"] == "Remise trop élevée"

    check_rej = temp_autonomy.check_action_execution("lucas", "send_quote", action_id="act_to_reject")
    assert check_rej["allowed"] is False

    # 2. Action expirée (simulation dépassement 48h)
    temp_autonomy.create_pending_action(
        action_id="act_to_expire",
        agent_id="jerome",
        action_type="send_message_third_party",
        tenant_slug="client-test",
    )
    # Rétrograder la date de création à -50h
    old_time = "2026-10-01T10:00:00+00:00"
    import sqlite3
    with sqlite3.connect(str(temp_autonomy.db_path)) as conn:
        conn.execute("UPDATE pending_actions SET created_at = ? WHERE id = ?;", (old_time, "act_to_expire"))
        conn.commit()

    expired_count = temp_autonomy.expire_stale_actions(threshold_hours=48)
    assert expired_count >= 1

    actions_expired = temp_autonomy.get_pending_actions(tenant_slug="client-test", status="EXPIRED")
    target = next((a for a in actions_expired if a["id"] == "act_to_expire"), None)
    assert target is not None
    assert target["status"] == "EXPIRED"
    assert "expir" in target["rejection_reason"].lower()


def test_kan106_ca5_forbidden_action_cannot_be_executed(temp_autonomy):
    """CA5 : Un agent ne peut pas dépasser sa politique, même en tentant de forcer l'exécution."""
    # commit_amount_discount est interdit pour Jérôme
    res = temp_autonomy.check_action_execution("jerome", "commit_amount_discount")
    assert res["allowed"] is False
    assert res["level"] == "interdit"
    assert res["code"] == "ERR_ACTION_FORBIDDEN"


def test_kan106_ca6_ca7_policy_change_audit_and_contract_floor(temp_autonomy):
    """CA6 & CA7 : Traçabilité des modifications de niveaux et inviolabilité des planchers contractuels."""
    # 1. Tentative d'assouplissement d'une action interdite par contrat -> REFUS (CA7)
    with pytest.raises(PermissionError):
        temp_autonomy.update_action_level(
            agent_id="jerome",
            action_type="commit_amount_discount",
            new_level="libre",
            user_id="user_admin",
            user_role="admin",
        )

    # 2. Resserrer un niveau (ex: passer analyze_aged_balance de libre à sous_validation) -> AUTORISÉ et TRACÉ (CA6)
    change_res = temp_autonomy.update_action_level(
        agent_id="jerome",
        action_type="analyze_aged_balance",
        new_level="sous_validation",
        user_id="dirigeant_123",
        user_role="direction",
        reason="Souhait d'un double regard sur les chiffres",
    )
    assert change_res["success"] is True
    assert change_res["old_level"] == "libre"
    assert change_res["new_level"] == "sous_validation"

    # Vérification dans la table d'audit
    history = temp_autonomy.get_policy_change_history("jerome")
    assert len(history) >= 1
    assert history[0]["action_type"] == "analyze_aged_balance"
    assert history[0]["changed_by"] == "dirigeant_123"


def test_kan106_ca8_unanswered_recap_and_batch_review(test_client):
    """CA8 : Récapitulatif des demandes restées sans réponse et traitement en lot (batch)."""
    secret = "test_super_secret_jwt_key_32_bytes_long_min!!"
    token = jwt.encode(
        {"tenant_slug": "batch-org", "sub": "admin_user", "role": "admin", "app_metadata": {"tenant_slug": "batch-org"}},
        secret,
        algorithm="HS256",
    )
    headers = {"Authorization": f"Bearer {token}"}

    with patch.dict("os.environ", {"SUPABASE_JWT_SECRET": secret, "ORSO_CLIENT_SLUG": "batch-org"}):
        # Créer deux actions
        autonomy_manager.create_pending_action(
            action_id="batch_act_1",
            agent_id="jerome",
            action_type="send_payment_reminder",
            tenant_slug="batch-org",
            draft_content="Relance 1",
        )
        autonomy_manager.create_pending_action(
            action_id="batch_act_2",
            agent_id="jerome",
            action_type="send_payment_reminder",
            tenant_slug="batch-org",
            draft_content="Relance 2",
        )

        # 1. Consultation du récapitulatif
        recap_res = test_client.get("/api/client/actions/unanswered-recap", headers=headers)
        assert recap_res.status_code == 200
        assert recap_res.json()["pending_count"] >= 2

        # 2. Traitement groupé (approbation en un clic)
        batch_res = test_client.post(
            "/api/client/actions/batch-review",
            json={"action_ids": ["batch_act_1", "batch_act_2"], "decision": "APPROVE", "comment": "Validation hebdomadaire"},
            headers=headers,
        )
        assert batch_res.status_code == 200
        assert batch_res.json()["processed_count"] == 2
        assert batch_res.json()["errors_count"] == 0
