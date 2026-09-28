"""Module d'authentification et de contrôle d'accès IAM Superadmin pour Olympe Ops.

Valide les identifiants et les jetons JWT auprès de Supabase Auth (auth.users),
garantissant que seuls les utilisateurs dotés du rôle 'superadmin' peuvent
accéder au Cockpit Orso Ops (ops.orso-agents.fr) et à ses APIs.
"""

import hashlib
import hmac
import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Set
from fastapi import HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_log = logging.getLogger("orso.olympe.auth")
security_bearer = HTTPBearer(auto_error=False)

# Token et mot de passe factices pour les tests locaux automatisés
MOCK_SUPERADMIN_TOKEN = "mock-superadmin-session-token-9230"
MOCK_SUPERADMIN_PASSWORD = os.environ.get("ORSO_MOCK_SUPERADMIN_PASSWORD", "OrsoTestSuperadmin2026!")

# Token dédié et identité machine pour le drone de test (Client-X-Orso)
MOCK_DRONE_TOKEN = "mock-drone-token-clientx-9230"
DRONE_ROLE = "drone"
SUPERADMIN_ROLE = "superadmin"

# Whitelist stricte des tenants accessibles au drone de test
TEST_SANDBOX_SLUGS: Set[str] = {"clientx-orso"}

# Portées strictes autorisées pour le drone de test (L2)
DRONE_ALLOWED_SCOPES: Set[str] = {
    "tenants:read",
    "tenants:provision:sandbox",
    "tenants:teardown:sandbox",
    "agents:write:sandbox",
    "billing:read",
    "webhooks:read",
}

# Registre en mémoire des tokens révoqués
_REVOKED_TOKENS: Set[str] = set()


def revoke_token(token: str) -> None:
    """Révoque un jeton d'authentification avec effet immédiat (CA4)."""
    if token:
        _REVOKED_TOKENS.add(token)
        _TOKEN_CACHE.pop(token, None)
        _log.warning("[SECURITY] Jeton d'authentification révoqué : %s...", token[:12])


def is_token_revoked(token: str) -> bool:
    """Vérifie si un jeton a été révoqué."""
    return token in _REVOKED_TOKENS


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


def verify_ops_token(
    token: str,
    supabase_url: Optional[str] = None,
    service_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Valide un jeton d'authentification (Superadmin humain ou Drone machine) auprès de Supabase Auth."""
    # 0. Vérification révocation immédiate (CA4)
    if is_token_revoked(token):
        raise HTTPException(status_code=401, detail="Jeton d'authentification révoqué.")

    # En mode réel / production, les jetons mocks statiques sont formellement interdits
    if token in (MOCK_SUPERADMIN_TOKEN, MOCK_DRONE_TOKEN) and not is_mock_auth_enabled():
        raise HTTPException(status_code=401, detail="Jeton de session non autorisé.")

    now = time.time()

    # 1. Vérification dans le cache mémoire TTL (ultra-rapide, évite les allers-retours HTTP)
    if token in _TOKEN_CACHE:
        cached_time, cached_actor = _TOKEN_CACHE[token]
        if now - cached_time < _TOKEN_CACHE_TTL:
            return cached_actor
        _TOKEN_CACHE.pop(token, None)

    # 2. Mode mock autorisé (tests unitaires ou dev local)
    if is_mock_auth_enabled():
        if token == MOCK_SUPERADMIN_TOKEN:
            admin_mock = {
                "id": "mock-admin-id-001",
                "actor": "admin@orso-agents.fr",
                "email": "admin@orso-agents.fr",
                "full_name": "Thibaut Quinzain",
                "role": SUPERADMIN_ROLE,
                "actor_type": "human",
                "scopes": ["*"],
            }
            _TOKEN_CACHE[token] = (now, admin_mock)
            return admin_mock

        if token == MOCK_DRONE_TOKEN:
            drone_mock = {
                "id": "drone-clientx-001",
                "actor": "drone-clientx",
                "email": "drone-clientx@test.orso-agents.fr",
                "full_name": "Drone Test Client-X",
                "role": DRONE_ROLE,
                "actor_type": "machine",
                "scopes": list(DRONE_ALLOWED_SCOPES),
                "sandbox_slugs": list(TEST_SANDBOX_SLUGS),
            }
            _TOKEN_CACHE[token] = (now, drone_mock)
            return drone_mock

    # 3. Vérification du token statique d'environnement drone en production (secret 600)
    configured_drone_token = os.environ.get("ORSO_DRONE_API_TOKEN", "").strip()
    if configured_drone_token and token == configured_drone_token:
        actor_name = os.environ.get("ORSO_DRONE_ACTOR", "drone-clientx").strip()
        drone_actor = {
            "id": f"drone-{actor_name}",
            "actor": actor_name,
            "email": f"{actor_name}@test.orso-agents.fr",
            "full_name": f"Drone Service ({actor_name})",
            "role": DRONE_ROLE,
            "actor_type": "machine",
            "scopes": list(DRONE_ALLOWED_SCOPES),
            "sandbox_slugs": list(TEST_SANDBOX_SLUGS),
        }
        _TOKEN_CACHE[token] = (now, drone_actor)
        return drone_actor

    url, key = _get_supabase_config(supabase_url, service_key)
    if not url or not key:
        raise HTTPException(status_code=401, detail="Service d'authentification non configuré.")

    # 4. Validation du jeton auprès de Supabase Auth
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

    if user_role == SUPERADMIN_ROLE:
        admin_profile = {
            "id": user.get("id"),
            "actor": user.get("email") or "superadmin",
            "email": user.get("email"),
            "full_name": user_meta.get("full_name") or "Administrateur Orso",
            "role": SUPERADMIN_ROLE,
            "actor_type": "human",
            "scopes": ["*"],
        }
        _TOKEN_CACHE[token] = (now, admin_profile)
        return admin_profile

    if user_role == DRONE_ROLE:
        actor_name = app_meta.get("actor") or user_meta.get("actor") or "drone-clientx"
        drone_profile = {
            "id": user.get("id"),
            "actor": actor_name,
            "email": user.get("email") or f"{actor_name}@test.orso-agents.fr",
            "full_name": user_meta.get("full_name") or f"Drone Service ({actor_name})",
            "role": DRONE_ROLE,
            "actor_type": "machine",
            "scopes": app_meta.get("scopes") or list(DRONE_ALLOWED_SCOPES),
            "sandbox_slugs": app_meta.get("sandbox_slugs") or list(TEST_SANDBOX_SLUGS),
        }
        _TOKEN_CACHE[token] = (now, drone_profile)
        return drone_profile

    # Utilisateur client standard ou rôle inconnu : rejet strict en 403 pour OPS
    _log.warning("[SECURITY] Accès OPS refusé à l'utilisateur non autorisé %s (rôle: %s)", user.get("email"), user_role)
    raise HTTPException(status_code=403, detail="Accès refusé : Ce compte ne possède pas les habilitations pour Orso Ops.")


def verify_superadmin_token(
    token: str,
    supabase_url: Optional[str] = None,
    service_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Valide un jeton de session et garantit strictement le rôle 'superadmin'."""
    actor = verify_ops_token(token, supabase_url=supabase_url, service_key=service_key)
    if actor.get("role") != SUPERADMIN_ROLE:
        raise HTTPException(status_code=403, detail="Accès refusé : habilitation Superadmin requise.")
    return actor


async def require_superadmin(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_bearer),
) -> Dict[str, Any]:
    """Dépendance FastAPI pour protéger les routes strictement réservées au superadmin humain."""
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Jeton d'authentification Bearer manquant.")
    return verify_superadmin_token(credentials.credentials)


def require_ops_actor(required_scope: Optional[str] = None):
    """Dépendance FastAPI pour protéger les routes Ops avec contrôle de rôle et de scope."""
    async def _dependency(
        credentials: Optional[HTTPAuthorizationCredentials] = Security(security_bearer),
    ) -> Dict[str, Any]:
        if not credentials or not credentials.credentials:
            raise HTTPException(status_code=401, detail="Jeton d'authentification Bearer manquant.")

        actor = verify_ops_token(credentials.credentials)

        # 1. Le superadmin humain dispose de tous les droits
        if actor.get("role") == SUPERADMIN_ROLE:
            return actor

        # 2. Le drone machine est strictement validé par scope (L2)
        if actor.get("role") == DRONE_ROLE:
            if required_scope:
                scopes = actor.get("scopes", [])
                if required_scope not in scopes and "*" not in scopes:
                    _log.warning("[SECURITY] Drone '%s' a tenté d'utiliser une portée non accordée : %s", actor.get("actor"), required_scope)
                    raise HTTPException(
                        status_code=403,
                        detail=f"Accès refusé : portée '{required_scope}' non autorisée pour ce drone.",
                    )
            return actor

        raise HTTPException(status_code=403, detail="Accès refusé : habilitation insuffisante pour Orso Ops.")

    return _dependency


def check_sandbox_tenant_access(actor: Dict[str, Any], tenant_slug_or_id: str, ops_mgr: Optional[Any] = None) -> None:
    """Vérifie que si l'acteur est un drone machine, il n'accède qu'aux tenants de test autorisés."""
    if actor.get("role") == DRONE_ROLE:
        allowed = set(actor.get("sandbox_slugs") or TEST_SANDBOX_SLUGS)
        target = tenant_slug_or_id.strip().lower()
        if target in allowed:
            return
        if ops_mgr is not None:
            detail = ops_mgr.get_tenant_detail(tenant_slug_or_id)
            if detail and detail.get("slug", "").strip().lower() in allowed:
                return

        _log.warning("[SECURITY] Refus 403 : drone '%s' hors liste blanche pour le tenant '%s'", actor.get("actor"), tenant_slug_or_id)
        raise HTTPException(
            status_code=403,
            detail=f"Accès refusé : le drone n'est habilité que sur le périmètre sandbox de test {sorted(list(allowed))}.",
        )


def verify_stripe_signature(payload_bytes: bytes, sig_header: str, secret: str, tolerance: int = 300) -> bool:
    """Valide l'en-tête Stripe-Signature (t=...,v1=...) avec HMAC-SHA256."""
    try:
        items = dict(item.split("=", 1) for item in sig_header.split(","))
        timestamp = int(items.get("t", 0))
        signature = items.get("v1", "")
        if not timestamp or not signature:
            return False
        # Vérification tolérance d'horloge
        if abs(time.time() - timestamp) > tolerance:
            return False
        signed_payload = f"{timestamp}.".encode("utf-8") + payload_bytes
        expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
    except Exception as e:
        _log.error("Erreur vérification signature Stripe : %s", e)
        return False
