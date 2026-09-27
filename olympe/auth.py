"""Module d'authentification et de contrôle d'accès IAM Superadmin pour Olympe Ops.

Valide les identifiants et les jetons JWT auprès de Supabase Auth (auth.users),
garantissant que seuls les utilisateurs dotés du rôle 'superadmin' peuvent
accéder au Cockpit Orso Ops (ops.orso-agents.fr) et à ses APIs.
"""

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional
from fastapi import HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_log = logging.getLogger("orso.olympe.auth")
security_bearer = HTTPBearer(auto_error=False)

# Token et mot de passe factices pour les tests locaux automatisés
MOCK_SUPERADMIN_TOKEN = "mock-superadmin-session-token-9230"
MOCK_SUPERADMIN_PASSWORD = os.environ.get("ORSO_MOCK_SUPERADMIN_PASSWORD", "OrsoTestSuperadmin2026!")


def is_mock_auth_enabled() -> bool:
    """Indique si le mode d'authentification mockée est autorisé.

    Sécurité stricte :
    - Strictement INTERDIT en environnement de production (APP_ENV=production ou ENVIRONMENT=production).
    - En dehors de la production, actif uniquement si ORSO_ALLOW_LOCAL_MOCK_AUTH=1/true ou lors des tests pytest (PYTEST_CURRENT_TEST).
    - Désactivé par défaut.
    """
    env = (os.environ.get("APP_ENV") or os.environ.get("ENVIRONMENT") or "").strip().lower()
    if env in ("production", "prod"):
        return False
    if os.environ.get("ORSO_ALLOW_LOCAL_MOCK_AUTH", "").strip().lower() in ("1", "true", "yes"):
        return True
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    return False

# Cache mémoire TTL pour éviter les requêtes HTTP redondantes vers Supabase /auth/v1/user
_TOKEN_CACHE: Dict[str, tuple[float, Dict[str, Any]]] = {}
_TOKEN_CACHE_TTL = 60.0  # 60 secondes de validité en cache


def clear_token_cache(token: Optional[str] = None) -> None:
    """Vide le cache de validation de token (sur logout ou globalement)."""
    if token:
        _TOKEN_CACHE.pop(token, None)
    else:
        _TOKEN_CACHE.clear()


def _get_supabase_config(
    supabase_url: Optional[str] = None,
    service_key: Optional[str] = None,
) -> tuple[str, str]:
    url = (supabase_url or os.environ.get("SUPABASE_URL", "")).rstrip("/")
    key = service_key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    return url, key


def authenticate_superadmin(
    email: str,
    password: str,
    supabase_url: Optional[str] = None,
    service_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Authentifie un utilisateur auprès de Supabase Auth et vérifie le rôle 'superadmin'.

    Lève HTTPException(401) si les identifiants sont invalides.
    Lève HTTPException(403) si l'utilisateur est valide mais n'a pas le rôle 'superadmin'.
    """
    url, key = _get_supabase_config(supabase_url, service_key)

    # 0. Habilitation Superadmin directe uniquement si le mode mock est explicitement activé (interdit en prod)
    if is_mock_auth_enabled():
        mock_allowed_emails = {"admin@orso-agents.fr", "tquinzain@gmail.com"}
        if email in mock_allowed_emails and password == MOCK_SUPERADMIN_PASSWORD:
            return {
                "token": MOCK_SUPERADMIN_TOKEN,
                "refresh_token": "mock-refresh",
                "expires_in": 3600,
                "user": {
                    "id": "mock-admin-id-001",
                    "email": email,
                    "full_name": "Thibaut Quinzain",
                    "role": "superadmin",
                },
            }

    # Mode hors-ligne / tests unitaires sans clés distantes
    if not url or not key:
        raise HTTPException(status_code=401, detail="Identifiants administrateur invalides.")

    # 1. Appel API Supabase Auth Token (grant_type=password)
    token_url = f"{url}/auth/v1/token?grant_type=password"
    body = {"email": email, "password": password}
    req = urllib.request.Request(
        token_url,
        data=json.dumps(body).encode("utf-8"),
        headers={"apikey": key, "Content-Type": "application/json", "User-Agent": "OrsoOlympeOps/1.0"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=7.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_msg = "Identifiants incorrects."
        try:
            err_data = json.loads(e.read().decode("utf-8"))
            err_msg = err_data.get("error_description") or err_data.get("msg") or err_msg
        except Exception:
            pass
        raise HTTPException(status_code=401, detail=f"Échec d'authentification : {err_msg}")
    except Exception as e:
        _log.error("Erreur connexion Supabase Auth : %s", e)
        raise HTTPException(status_code=502, detail="Impossible de joindre le serveur d'authentification.")

    access_token = data.get("access_token")
    user = data.get("user") or {}
    app_meta = user.get("app_metadata") or {}
    user_meta = user.get("user_metadata") or {}

    # 2. Vérification stricte du rôle 'superadmin'
    user_role = app_meta.get("role") or user_meta.get("role")
    if user_role != "superadmin":
        _log.warning("Tentative de connexion non autorisée au Cockpit Ops par %s (rôle: %s)", email, user_role)
        raise HTTPException(
            status_code=403,
            detail="Accès refusé : Ce compte ne possède pas les habilitations Superadmin pour Orso Ops.",
        )

    return {
        "token": access_token,
        "refresh_token": data.get("refresh_token"),
        "expires_in": data.get("expires_in", 3600),
        "user": {
            "id": user.get("id"),
            "email": user.get("email"),
            "full_name": user_meta.get("full_name") or "Administrateur Orso",
            "role": "superadmin",
        },
    }


def verify_superadmin_token(
    token: str,
    supabase_url: Optional[str] = None,
    service_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Valide un jeton de session auprès de Supabase Auth et garantit le rôle 'superadmin'."""
    # En mode réel / production, le jeton mock statique est formellement interdit
    if token == MOCK_SUPERADMIN_TOKEN and not is_mock_auth_enabled():
        raise HTTPException(status_code=401, detail="Jeton de session non autorisé.")

    now = time.time()

    # 1. Vérification dans le cache mémoire TTL (ultra-rapide, évite les allers-retours HTTP)
    if token in _TOKEN_CACHE:
        cached_time, cached_user = _TOKEN_CACHE[token]
        if now - cached_time < _TOKEN_CACHE_TTL:
            return cached_user
        _TOKEN_CACHE.pop(token, None)

    url, key = _get_supabase_config(supabase_url, service_key)

    # Mode secours / token factice uniquement si le mode mock est autorisé (interdit en prod)
    if is_mock_auth_enabled() and token == MOCK_SUPERADMIN_TOKEN:
        user_mock = {
            "id": "mock-admin-id-001",
            "email": "admin@orso-agents.fr",
            "full_name": "Thibaut Quinzain",
            "role": "superadmin",
        }
        _TOKEN_CACHE[token] = (now, user_mock)
        return user_mock

    if not url or not key:
        raise HTTPException(status_code=401, detail="Service d'authentification non configuré.")

    # 2. Validation du jeton auprès de Supabase Auth
    req = urllib.request.Request(
        f"{url}/auth/v1/user",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {token}",
            "User-Agent": "OrsoOlympeOps/1.0",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            user = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise HTTPException(status_code=401, detail="Session expirée ou jeton invalide.")
    except Exception as e:
        _log.error("Erreur vérification token Supabase: %s", e)
        raise HTTPException(status_code=502, detail="Erreur lors de la validation de session.")

    app_meta = user.get("app_metadata") or {}
    user_meta = user.get("user_metadata") or {}
    user_role = app_meta.get("role") or user_meta.get("role")

    if user_role != "superadmin":
        raise HTTPException(status_code=403, detail="Accès refusé : habilitation Superadmin requise.")

    admin_profile = {
        "id": user.get("id"),
        "email": user.get("email"),
        "full_name": user_meta.get("full_name") or "Administrateur Orso",
        "role": "superadmin",
    }
    _TOKEN_CACHE[token] = (now, admin_profile)
    return admin_profile


async def require_superadmin(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_bearer),
) -> Dict[str, Any]:
    """Dépendance FastAPI pour protéger les routes d'administration."""
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Jeton d'authentification Bearer manquant.")
    return verify_superadmin_token(credentials.credentials)
