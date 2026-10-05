"""Orso Client JWT & Tenant isolation guard.

Verifies Supabase JWT tokens statelessly in memory with cryptographic signature verification,
enforcing strict tenant isolation (ORSO_CLIENT_ID / ORSO_CLIENT_SLUG).
Supports ES256 (asymmetric EC P-256 via Supabase JWKS) and HS256 (symmetric HMAC via SUPABASE_JWT_SECRET).
Rejects any unverified or unsupported algorithm (none, RS256, etc.) by default (Fail-Closed).
Belongs to Zone B (Orso extensions), keeping the Sanctuary (Zone A) 100% intact.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request

_log = logging.getLogger("hermes_cli.client_jwt")

ALLOWED_ALGORITHMS = {"ES256", "HS256"}

# Cache mémoire pour les clés publiques JWKS
_JWKS_CACHE: Dict[str, Any] = {
    "url": None,
    "timestamp": 0.0,
    "keys": {},  # kid -> ECPublicKey
    "jwks": None,
}


def _b64url_decode(s: str) -> bytes:
    """Decode a base64url-encoded string with automatic padding."""
    padding = 4 - (len(s) % 4)
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s.encode("ascii"))


def _b64url_encode(data: bytes) -> str:
    """Encode bytes into a base64url string without trailing padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class JWTVerificationError(Exception):
    """Base exception for JWT verification errors."""


class JWTExpiredError(JWTVerificationError):
    """Token has expired."""


def get_jwks_url() -> Optional[str]:
    """Resolves JWKS URL from SUPABASE_JWKS_URL or SUPABASE_URL."""
    url = os.environ.get("SUPABASE_JWKS_URL", "").strip()
    if not url:
        supabase_url = os.environ.get("SUPABASE_URL", "").strip()
        if supabase_url:
            url = f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    return url or None


def fetch_jwks(jwks_url: str) -> dict:
    """Fetches the JWKS JSON object from the given URL."""
    import urllib.request
    req = urllib.request.Request(
        jwks_url,
        headers={"Accept": "application/json", "User-Agent": "Orso-Client-Guard/1.0"}
    )
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_signing_key_from_cache(kid: str, ttl: float = 300.0) -> Optional[Any]:
    """Retrieves a cached public signing key by kid if the cache has not expired (default TTL: 300s)."""
    now = time.time()
    cache_ts = _JWKS_CACHE.get("timestamp", 0.0)
    if now - cache_ts > ttl:
        return None
    return _JWKS_CACHE.get("keys", {}).get(kid)


def get_jwks_data(jwks_url: Optional[str] = None, force_refresh: bool = False, ttl: float = 300.0) -> dict:
    """Retrieves JWKS data, using a TTL memory cache (default 300s)."""
    url = jwks_url or get_jwks_url()
    if not url:
        raise JWTVerificationError(
            "URL JWKS non configurée (SUPABASE_JWKS_URL ou SUPABASE_URL requis pour la vérification ES256)"
        )

    now = time.time()
    if not force_refresh and _JWKS_CACHE.get("jwks") and (now - _JWKS_CACHE.get("timestamp", 0.0) < ttl):
        return _JWKS_CACHE["jwks"]

    data = fetch_jwks(url)
    _JWKS_CACHE["jwks"] = data
    _JWKS_CACHE["timestamp"] = now
    _JWKS_CACHE["url"] = url

    from jwt import PyJWK
    keys = {}
    for k in data.get("keys", []):
        kid = k.get("kid")
        if kid:
            try:
                keys[kid] = PyJWK(k).key
            except Exception as e:
                _log.warning("Impossible d'extraire la clé publique pour kid=%s: %s", kid, e)
    _JWKS_CACHE["keys"] = keys
    return data


def _resolve_es256_key(
    kid: Optional[str],
    jwks_url: Optional[str] = None,
    jwks_data: Optional[dict] = None,
    force_refresh: bool = False,
    ttl: float = 300.0,
) -> Any:
    """Resolves an ES256 public key by kid from jwks_data, cache, or remote fetch (with TTL)."""
    if not kid:
        raise JWTVerificationError("En-tête de jeton sans 'kid' requis pour l'algorithme ES256")

    from jwt import PyJWK

    # Cas où jwks_data est fourni directement (tests, mocks)
    if jwks_data:
        for k in jwks_data.get("keys", []):
            if k.get("kid") == kid:
                return PyJWK(k).key
        raise JWTVerificationError(f"Clé de signature introuvable dans JWKS pour kid: {kid}")

    # Consultation du cache si non forcé et non expiré (< 300s)
    if not force_refresh:
        cached = get_signing_key_from_cache(kid, ttl=ttl)
        if cached is not None:
            return cached

    # Récupération / rafraîchissement depuis la source JWKS (cache vide, expiré ou rafraîchissement forcé)
    try:
        data = get_jwks_data(jwks_url=jwks_url, force_refresh=True, ttl=ttl)
        if data and "keys" in data:
            for k in data.get("keys", []):
                if k.get("kid") == kid:
                    return PyJWK(k).key
        cached = get_signing_key_from_cache(kid, ttl=ttl)
        if cached is not None:
            return cached
        raise JWTVerificationError(f"Clé de signature introuvable dans JWKS pour kid: {kid}")
    except JWTVerificationError:
        raise
    except Exception as e:
        # Si la source est indisponible, tolérer une clé en cache valide sous son TTL si force_refresh n'était pas imposé
        cached = get_signing_key_from_cache(kid, ttl=ttl)
        if cached is not None and not force_refresh:
            return cached
        raise JWTVerificationError(f"Source de clés JWKS indisponible : {e}")


def decode_and_verify_jwt(
    token: str,
    secret: Optional[str] = None,
    *,
    jwks_url: Optional[str] = None,
    jwks_data: Optional[dict] = None,
    force_jwks_refresh: bool = False,
    ttl: float = 300.0,
) -> Dict[str, Any]:
    """Decodes and cryptographically verifies a JWT token.
    Supports ES256 (via Supabase JWKS) and HS256 (via SUPABASE_JWT_SECRET).
    Refuses any unsupported algorithm (none, RS256, etc.) with JWTVerificationError.
    """
    secret = secret or os.environ.get("SUPABASE_JWT_SECRET", "").strip()

    parts = token.strip().split(".")
    if len(parts) != 3:
        raise JWTVerificationError("Format de jeton invalide (3 parties requises)")

    header_b64, payload_b64, signature_b64 = parts

    # 1. Décoder le header
    try:
        header = json.loads(_b64url_decode(header_b64).decode("utf-8"))
    except Exception as e:
        raise JWTVerificationError(f"Header de jeton illisible: {e}")

    alg = header.get("alg")
    if not alg:
        raise JWTVerificationError("Algorithme manquant dans l'en-tête du jeton")

    # Refus strict par défaut des algorithmes non pris en charge
    if alg not in ALLOWED_ALGORITHMS:
        raise JWTVerificationError(f"Algorithme non supporté : {alg}")

    # 2. Vérification cryptographique selon l'algorithme imposé
    kid = header.get("kid")

    if alg == "ES256":
        key = _resolve_es256_key(
            kid=kid,
            jwks_url=jwks_url,
            jwks_data=jwks_data,
            force_refresh=force_jwks_refresh,
            ttl=ttl,
        )
        try:
            import jwt
            payload = jwt.decode(
                token,
                key,
                algorithms=["ES256"],
                options={"verify_exp": False, "verify_aud": False, "verify_signature": True},
            )
        except jwt.InvalidSignatureError as e:
            raise JWTVerificationError(f"Signature du jeton non valide : {e}")
        except jwt.PyJWTError as e:
            raise JWTVerificationError(f"Erreur de validation cryptographique du jeton : {e}")

    elif alg == "HS256":
        if not secret:
            raise JWTVerificationError("Secret JWT manquant (SUPABASE_JWT_SECRET requis pour HS256)")

        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        expected_sig = hmac.new(
            secret.encode("utf-8"), signing_input, hashlib.sha256
        ).digest()
        try:
            actual_sig = _b64url_decode(signature_b64)
        except Exception as e:
            raise JWTVerificationError(f"Signature invalide: {e}")

        if not hmac.compare_digest(expected_sig, actual_sig):
            raise JWTVerificationError("Signature du jeton non valide")

        # Décoder le payload pour HS256
        try:
            payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        except Exception as e:
            raise JWTVerificationError(f"Payload de jeton illisible: {e}")

    # 3. Vérifier l'expiration (exp)
    exp = payload.get("exp")
    if exp is not None:
        now = int(time.time())
        # Marge de tolérance d'horloge de 30 secondes (clock skew)
        if now > exp + 30:
            raise JWTExpiredError(f"Jeton expiré depuis {now - exp} secondes")

    return payload


async def verify_client_access(request: Request) -> Dict[str, Any]:
    """FastAPI dependency: extracts and validates the client JWT,
    enforcing that the tenant matches this container instance (ORSO_CLIENT_ID).
    """
    # Mode dev si explicitement désactivé
    if os.environ.get("ORSO_AUTH_DISABLED") == "1":
        dev_payload = {
            "sub": "dev-user",
            "email": "dev@orso-agents.fr",
            "tenant": {
                "tenant_id": os.environ.get("ORSO_CLIENT_ID", "dev-tenant"),
                "tenant_slug": os.environ.get("ORSO_CLIENT_SLUG", "dev-tenant"),
                "role": "admin",
                "is_admin": True,
                "agents": ["jerome", "lucas", "clara", "victor"],
            },
        }
        request.state.tenant = dev_payload["tenant"]
        request.state.user_id = dev_payload["sub"]
        return dev_payload

    # 1. Extraction du jeton depuis Header Authorization ou Cookie
    token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
    elif "sb-access-token" in request.cookies:
        token = request.cookies["sb-access-token"]

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Authentification requise : Jeton d'accès manquant.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 2. Vérification cryptographique
    try:
        payload = decode_and_verify_jwt(token)
    except JWTExpiredError as e:
        raise HTTPException(
            status_code=401,
            detail=f"Session expirée : {e}",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )
    except JWTVerificationError as e:
        raise HTTPException(
            status_code=401,
            detail=f"Jeton d'authentification invalide : {e}",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )

    # 3. Contrôle d'isolation Tenant (Instance Matching)
    expected_client_id = os.environ.get("ORSO_CLIENT_ID", "").strip()
    expected_client_slug = os.environ.get("ORSO_CLIENT_SLUG", "").strip()

    token_tenant = payload.get("tenant") or payload.get("app_metadata") or {}
    token_tenant_id = token_tenant.get("tenant_id")
    token_tenant_slug = token_tenant.get("tenant_slug")

    if expected_client_id or expected_client_slug:
        matched = True
        if expected_client_id and token_tenant_id != expected_client_id:
            matched = False
        if expected_client_slug and token_tenant_slug != expected_client_slug:
            matched = False

        if not matched:
            _log.warning(
                "Tentative d'accès cross-tenant bloquée: token=(id:%s, slug:%s) vs container=(id:%s, slug:%s)",
                token_tenant_id,
                token_tenant_slug,
                expected_client_id,
                expected_client_slug,
            )
            raise HTTPException(
                status_code=403,
                detail="Accès interdit : Vous n'êtes pas autorisé à accéder aux agents de cette instance.",
            )

    # 4. Attachement à l'état de la requête
    request.state.tenant = token_tenant
    request.state.user_id = payload.get("sub")
    request.state.user_email = payload.get("email")

    return payload
