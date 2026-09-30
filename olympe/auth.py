"""Module d'authentification et de contrôle d'accès IAM Superadmin pour Olympe Ops.

Valide les identifiants et les jetons JWT auprès de Supabase Auth (auth.users),
garantissant que seuls les utilisateurs dotés du rôle 'superadmin' peuvent
accéder au Cockpit Orso Ops (ops.orso-agents.fr) et à ses APIs.
"""

import datetime
import hashlib
import hmac
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from fastapi import HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_log = logging.getLogger("orso.olympe.auth")
security_bearer = HTTPBearer(auto_error=False)

# Token et mot de passe factices pour les tests locaux automatisés
MOCK_SUPERADMIN_TOKEN = "mock-superadmin-session-token-9230"
MOCK_SUPERADMIN_PASSWORD = os.environ.get("ORSO_MOCK_SUPERADMIN_PASSWORD", "OrsoTestSuperadmin2026!")

# Registre dynamique des mots de passe mis à jour en mode test/mock
_MOCK_PASSWORD_OVERRIDE: Dict[str, str] = {}

# Registre mémoire anti-bruteforce / rate limiting (horodatages des échecs récents)
_FAILED_ATTEMPTS: Dict[str, List[float]] = {}

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


def clear_revoked_tokens() -> None:
    """Vide le registre des tokens révoqués (utile lors des tests unitaires)."""
    _REVOKED_TOKENS.clear()


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
        expected_mock_pwd = _MOCK_PASSWORD_OVERRIDE.get(email, MOCK_SUPERADMIN_PASSWORD)
        if email in mock_allowed_emails and password == expected_mock_pwd:
            import secrets
            unique_token = f"{MOCK_SUPERADMIN_TOKEN}-{secrets.token_hex(4)}"
            return {
                "token": unique_token,
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
    if (token.startswith(MOCK_SUPERADMIN_TOKEN) or token == MOCK_DRONE_TOKEN) and not is_mock_auth_enabled():
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
        if token.startswith(MOCK_SUPERADMIN_TOKEN):
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


# ── Gestion Sécurité Mot de Passe & Audit IAM Superadmin (KAN-50) ────────────

def check_rate_limit(key: str, max_attempts: int = 5, window_seconds: float = 900.0) -> None:
    """Vérifie le rate-limiting anti-bruteforce (CA7).

    Lève HTTPException(429) si le nombre d'échecs consécutifs atteint max_attempts
    sur une fenêtre glissante de window_seconds (par défaut 15 minutes).
    """
    now = time.time()
    attempts = _FAILED_ATTEMPTS.get(key, [])
    recent = [t for t in attempts if now - t < window_seconds]
    _FAILED_ATTEMPTS[key] = recent
    if len(recent) >= max_attempts:
        retry_after = int(window_seconds - (now - recent[0])) if recent else int(window_seconds)
        mins = max(1, (retry_after + 59) // 60)
        _log.warning("[SECURITY] Rate limit atteint pour %s (%d tentatives). Verrouillage %d min.", key, len(recent), mins)
        raise HTTPException(
            status_code=429,
            detail=f"Trop de tentatives consécutives échouées. Compte temporairement verrouillé, réessayez dans {mins} minute(s).",
        )


def record_failed_attempt(key: str) -> None:
    """Enregistre un échec d'authentification pour le rate limiting (CA7)."""
    now = time.time()
    if key not in _FAILED_ATTEMPTS:
        _FAILED_ATTEMPTS[key] = []
    _FAILED_ATTEMPTS[key].append(now)


def clear_failed_attempts(key: str) -> None:
    """Réinitialise les tentatives échouées après un succès."""
    _FAILED_ATTEMPTS.pop(key, None)


def validate_password_policy(new_password: str, current_password: Optional[str] = None) -> Tuple[bool, str]:
    """Valide les critères stricts de sécurité du mot de passe (CA4)."""
    if len(new_password) < 12:
        return False, "Le nouveau mot de passe doit comporter au moins 12 caractères."
    if not re.search(r"[A-Z]", new_password):
        return False, "Le nouveau mot de passe doit contenir au moins une lettre majuscule."
    if not re.search(r"[a-z]", new_password):
        return False, "Le nouveau mot de passe doit contenir au moins une lettre minuscule."
    if not re.search(r"[0-9]", new_password):
        return False, "Le nouveau mot de passe doit contenir au moins un chiffre."
    if not re.search(r"[!@#$%^&*()_\-+=\[\]{}<>?,.:;~]", new_password):
        return False, "Le nouveau mot de passe doit contenir au moins un caractère spécial (!@#$%^&*...)."
    if current_password and new_password == current_password:
        return False, "Le nouveau mot de passe doit être différent de l'ancien mot de passe."

    trivial_patterns = [
        r"^admin",
        r"^password",
        r"^azerty",
        r"^qwerty",
        r"^orso",
        r"^olympe",
        r"123456",
    ]
    for pat in trivial_patterns:
        if re.search(pat, new_password, re.IGNORECASE):
            return False, "Le mot de passe ne doit pas contenir de termes ou séquences prévisibles (ex: admin, orso, 123456)."

    return True, "OK"


def append_auth_audit_event(
    action: str,
    account: str,
    ip: str,
    result: str,
    reason: Optional[str] = None,
) -> None:
    """Consigne un événement dans le journal d'audit sans aucun secret (CA9)."""
    try:
        from hermes_constants import get_hermes_home
        audit_file = get_hermes_home() / "ops_auth_audit.json"
    except Exception:
        home_env = os.environ.get("HERMES_HOME")
        audit_file = (Path(home_env) if home_env else Path.home() / ".hermes") / "ops_auth_audit.json"

    try:
        audit_file.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "action": action,
            "account": account,
            "ip": ip,
            "result": result,
            "reason": reason,
        }
        entries = []
        if audit_file.is_file():
            try:
                with open(audit_file, "r", encoding="utf-8") as f:
                    entries = json.load(f)
                    if not isinstance(entries, list):
                        entries = []
            except Exception:
                entries = []
        entries.append(entry)
        if len(entries) > 200:
            entries = entries[-200:]
        with open(audit_file, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)
    except Exception as e:
        _log.warning("Erreur lors de l'écriture du journal d'audit auth : %s", e)


def get_auth_audit_events(limit: int = 50) -> List[Dict[str, Any]]:
    """Retourne la liste des événements d'audit récents sans secrets (CA9)."""
    try:
        from hermes_constants import get_hermes_home
        audit_file = get_hermes_home() / "ops_auth_audit.json"
    except Exception:
        home_env = os.environ.get("HERMES_HOME")
        audit_file = (Path(home_env) if home_env else Path.home() / ".hermes") / "ops_auth_audit.json"

    if not audit_file.is_file():
        return []

    try:
        with open(audit_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                # Plus récents en premier
                return list(reversed(data))[:limit]
    except Exception as e:
        _log.warning("Erreur lecture journal audit : %s", e)
    return []


def change_superadmin_password(
    user_id: str,
    email: str,
    current_password: str,
    new_password: str,
    current_token: Optional[str] = None,
    client_ip: str = "127.0.0.1",
    supabase_url: Optional[str] = None,
    service_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Change le mot de passe du superadmin avec vérification stricte (CA3-CA7, CA9)."""
    # 1. Vérification anti-bruteforce (CA7)
    check_rate_limit(client_ip)
    check_rate_limit(email)

    # 2. Validation de la complexité du nouveau mot de passe (CA4)
    valid, msg = validate_password_policy(new_password, current_password=current_password)
    if not valid:
        append_auth_audit_event("password_change", email, client_ip, "failure", reason=msg)
        raise HTTPException(status_code=400, detail=msg)

    # 3. Vérification de l'ancien mot de passe (CA3)
    url, key = _get_supabase_config(supabase_url, service_key)

    if is_mock_auth_enabled():
        expected_pwd = _MOCK_PASSWORD_OVERRIDE.get(email, MOCK_SUPERADMIN_PASSWORD)
        if current_password != expected_pwd:
            record_failed_attempt(client_ip)
            record_failed_attempt(email)
            append_auth_audit_event("password_change", email, client_ip, "failure", reason="invalid_current_password")
            raise HTTPException(status_code=400, detail="L'ancien mot de passe est incorrect.")
        _MOCK_PASSWORD_OVERRIDE[email] = new_password
    else:
        if not url or not key:
            raise HTTPException(status_code=502, detail="Configuration Supabase Auth manquante.")

        # Vérification auprès de Supabase Auth
        token_url = f"{url}/auth/v1/token?grant_type=password"
        auth_req = urllib.request.Request(
            token_url,
            data=json.dumps({"email": email, "password": current_password}).encode("utf-8"),
            headers={"apikey": key, "Content-Type": "application/json", "User-Agent": "OrsoOlympeOps/1.0"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(auth_req, timeout=8.0) as resp:
                token_data = json.loads(resp.read().decode("utf-8"))
                if not token_data.get("access_token"):
                    raise ValueError("Pas de jeton retourné")
        except urllib.error.HTTPError:
            record_failed_attempt(client_ip)
            record_failed_attempt(email)
            append_auth_audit_event("password_change", email, client_ip, "failure", reason="invalid_current_password")
            raise HTTPException(status_code=400, detail="L'ancien mot de passe est incorrect.")
        except Exception as e:
            _log.error("Erreur validation mot de passe actuel : %s", e)
            record_failed_attempt(client_ip)
            record_failed_attempt(email)
            append_auth_audit_event("password_change", email, client_ip, "failure", reason=f"auth_error: {e}")
            raise HTTPException(status_code=400, detail="L'ancien mot de passe est incorrect ou rejeté par Supabase.")

        # 4. Mise à jour dans Supabase Auth (CA5 - 100% hashé, 0ms de redémarrage)
        update_url = f"{url}/auth/v1/admin/users/{user_id}"
        update_headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "OrsoOlympeOps/1.0",
        }
        update_req = urllib.request.Request(
            update_url,
            data=json.dumps({"password": new_password}).encode("utf-8"),
            headers=update_headers,
            method="PUT",
        )
        try:
            with urllib.request.urlopen(update_req, timeout=8.0) as resp:
                _ = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            _log.error("Erreur mise à jour mot de passe Supabase : %s", e)
            append_auth_audit_event("password_change", email, client_ip, "failure", reason=f"update_failed: {e}")
            raise HTTPException(status_code=500, detail="Erreur lors de la mise à jour du mot de passe dans Supabase.")

    # 5. Invalidation de session (CA6)
    if current_token:
        revoke_token(current_token)
    clear_token_cache()

    # 6. Réinitialisation des compteurs d'échec
    clear_failed_attempts(client_ip)
    clear_failed_attempts(email)

    # 7. Audit log succès (CA9)
    append_auth_audit_event("password_change", email, client_ip, "success")

    return {
        "success": True,
        "message": "Mot de passe modifié avec succès. Votre session a été invalidée, veuillez vous reconnecter.",
        "invalidated": True,
    }

