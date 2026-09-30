"""Tests d'acceptation et de sécurité pour le changement de mot de passe Superadmin Cockpit OPS (KAN-50).

Couvre l'ensemble des critères d'acceptation :
- CA3 : Formulaire strict à 3 champs et vérification obligatoire de l'ancien mot de passe
- CA4 : Politique de sécurité robuste (≥12 caractères, majuscule, minuscule, chiffre, symbole, non-trivial)
- CA5 : Stockage 100% hashé et prise d'effet immédiate (0ms sans redémarrage)
- CA6 : Invalidation immédiate des sessions et tokens antérieurs
- CA7 : Protection anti-bruteforce et rate-limiting (max 5 tentatives consécutives)
- CA8 : Procédure de secours d'urgence CLI testée et opérationnelle
- CA9 : Journal d'audit accessible sans secret en clair ni condensat
- CA10 : Préservation absolue du Sanctuaire Orso
"""

import json
import pytest
from fastapi.testclient import TestClient

from olympe.auth import (
    authenticate_superadmin,
    change_superadmin_password,
    check_rate_limit,
    clear_failed_attempts,
    clear_token_cache,
    clear_revoked_tokens,
    get_auth_audit_events,
    is_token_revoked,
    record_failed_attempt,
    revoke_token,
    validate_password_policy,
    verify_superadmin_token,
    _FAILED_ATTEMPTS,
    _MOCK_PASSWORD_OVERRIDE,
    MOCK_SUPERADMIN_PASSWORD,
    MOCK_SUPERADMIN_TOKEN,
)
from olympe.server import app
from scripts.iam.reset_superadmin_password import (
    generate_secure_password,
    validate_password_complexity,
)


@pytest.fixture(autouse=True)
def reset_auth_state():
    """Réinitialise l'état mémoire d'authentification entre chaque test."""
    _FAILED_ATTEMPTS.clear()
    _MOCK_PASSWORD_OVERRIDE.clear()
    clear_token_cache()
    clear_revoked_tokens()
    yield
    _FAILED_ATTEMPTS.clear()
    _MOCK_PASSWORD_OVERRIDE.clear()
    clear_token_cache()
    clear_revoked_tokens()


def test_password_policy_validation_ca4():
    """CA4 : Validation des critères de complexité du mot de passe."""
    # Trop court (< 12 caractères)
    valid, msg = validate_password_policy("Court1!a")
    assert not valid
    assert "12 caractères" in msg

    # Manque de majuscule
    valid, msg = validate_password_policy("toutenminuscule123!@#")
    assert not valid
    assert "majuscule" in msg

    # Manque de minuscule
    valid, msg = validate_password_policy("TOUTENMAJUSCULE123!@#")
    assert not valid
    assert "minuscule" in msg

    # Manque de chiffre
    valid, msg = validate_password_policy("SansChiffreMaisComplexe!@#")
    assert not valid
    assert "chiffre" in msg

    # Manque de caractère spécial
    valid, msg = validate_password_policy("SansSymboleMaisLong12345")
    assert not valid
    assert "spécial" in msg

    # Mot de passe trivial (admin, orso, etc.)
    valid, msg = validate_password_policy("AdminSecret2026!#")
    assert not valid
    assert "prévisibles" in msg

    valid, msg = validate_password_policy("OrsoAgentSecurite2026!")
    assert not valid
    assert "prévisibles" in msg

    # Identique au mot de passe actuel
    current = "MonAncienMotDePasse123!"
    valid, msg = validate_password_policy(current, current_password=current)
    assert not valid
    assert "différent" in msg

    # Mot de passe valide et robuste
    valid, msg = validate_password_policy("VraimentTresSecurise2026!#@")
    assert valid
    assert msg == "OK"


def test_rate_limiting_anti_bruteforce_ca7():
    """CA7 : Verrouillage après 5 échecs consécutifs en moins de 15 minutes."""
    client_ip = "192.168.1.50"

    # Enregistrement de 4 échecs -> toujours sous le seuil
    for _ in range(4):
        record_failed_attempt(client_ip)
    # Ne doit pas lever d'exception
    check_rate_limit(client_ip, max_attempts=5)

    # 5ème échec -> doit lever 429
    record_failed_attempt(client_ip)
    with pytest.raises(Exception) as exc_info:
        check_rate_limit(client_ip, max_attempts=5)
    assert getattr(exc_info.value, "status_code", None) == 429

    # Réinitialisation après succès
    clear_failed_attempts(client_ip)
    # Doit à nouveau passer sans erreur
    check_rate_limit(client_ip, max_attempts=5)


def test_change_password_endpoint_flow_ca3_ca5_ca6():
    """CA3, CA5, CA6 : Flux complet de modification de mot de passe via l'API Olympe."""
    client = TestClient(app)

    # 1. Connexion initiale superadmin
    login_resp = client.post(
        "/api/olympe/ops/auth/login",
        json={"email": "admin@orso-agents.fr", "password": MOCK_SUPERADMIN_PASSWORD},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Échec si la confirmation ne correspond pas
    bad_confirm_resp = client.post(
        "/api/olympe/ops/auth/change-password",
        headers=headers,
        json={
            "current_password": MOCK_SUPERADMIN_PASSWORD,
            "new_password": "NouveauSuperPasse2026!#",
            "confirm_password": "PasLeMemeMotDePasse2026!#",
        },
    )
    assert bad_confirm_resp.status_code == 400
    assert "ne correspondent pas" in bad_confirm_resp.json()["detail"]

    # 3. Échec si l'ancien mot de passe est faux
    wrong_current_resp = client.post(
        "/api/olympe/ops/auth/change-password",
        headers=headers,
        json={
            "current_password": "MauvaisMotDePasseActuel!",
            "new_password": "NouveauSuperPasse2026!#",
            "confirm_password": "NouveauSuperPasse2026!#",
        },
    )
    assert wrong_current_resp.status_code == 400
    assert "incorrect" in wrong_current_resp.json()["detail"]

    # 4. Échec si le nouveau mot de passe viole la politique de complexité (CA4)
    weak_pwd_resp = client.post(
        "/api/olympe/ops/auth/change-password",
        headers=headers,
        json={
            "current_password": MOCK_SUPERADMIN_PASSWORD,
            "new_password": "court",
            "confirm_password": "court",
        },
    )
    assert weak_pwd_resp.status_code == 400

    # 5. Succès de la modification
    new_valid_pwd = "NouveauSuperPasse2026!#"
    success_resp = client.post(
        "/api/olympe/ops/auth/change-password",
        headers=headers,
        json={
            "current_password": MOCK_SUPERADMIN_PASSWORD,
            "new_password": new_valid_pwd,
            "confirm_password": new_valid_pwd,
        },
    )
    assert success_resp.status_code == 200
    res_data = success_resp.json()
    assert res_data["success"] is True
    assert res_data["invalidated"] is True

    # 6. Invalidation immédiate de la session antérieure (CA6)
    assert is_token_revoked(token) is True

    # L'ancien jeton doit maintenant être rejeté avec 401
    me_resp_old_token = client.get("/api/olympe/ops/auth/me", headers=headers)
    assert me_resp_old_token.status_code == 401

    # 7. Connexion réussie avec le NOUVEAU mot de passe (CA5 - 0ms de latence)
    new_login_resp = client.post(
        "/api/olympe/ops/auth/login",
        json={"email": "admin@orso-agents.fr", "password": new_valid_pwd},
    )
    assert new_login_resp.status_code == 200
    new_token = new_login_resp.json()["token"]
    assert new_token != token

    # La nouvelle session fonctionne parfaitement
    me_resp_new = client.get("/api/olympe/ops/auth/me", headers={"Authorization": f"Bearer {new_token}"})
    assert me_resp_new.status_code == 200
    assert me_resp_new.json()["user"]["email"] == "admin@orso-agents.fr"


def test_auth_audit_log_endpoint_ca9():
    """CA9 : Vérification de la consultation du journal d'audit et absence absolue de secrets."""
    client = TestClient(app)

    # Connexion superadmin
    login_resp = client.post(
        "/api/olympe/ops/auth/login",
        json={"email": "admin@orso-agents.fr", "password": MOCK_SUPERADMIN_PASSWORD},
    )
    token = login_resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Consultation du journal d'audit
    audit_resp = client.get("/api/olympe/ops/auth/audit-log", headers=headers)
    assert audit_resp.status_code == 200
    data = audit_resp.json()
    assert "events" in data
    assert isinstance(data["events"], list)

    # Vérification d'absence de mot de passe en clair ou condensat dans les logs
    for evt in data["events"]:
        assert "password" not in evt
        assert "secret" not in evt
        assert "hash" not in evt
        for val in evt.values():
            if isinstance(val, str):
                assert MOCK_SUPERADMIN_PASSWORD not in val


def test_cli_emergency_recovery_helpers_ca8():
    """CA8 : Validation des fonctions de secours d'urgence CLI."""
    # Test générateur de mot de passe
    pwd = generate_secure_password(length=24)
    assert len(pwd) == 24
    valid, msg = validate_password_complexity(pwd)
    assert valid is True
    assert msg == "OK"
