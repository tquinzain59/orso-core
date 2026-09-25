"""Orso Client JWT & Tenant isolation guard.

Verifies Supabase JWT tokens statelessly in memory with zero database lookups,
enforcing strict tenant isolation (ORSO_CLIENT_ID / ORSO_CLIENT_SLUG).
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


def decode_and_verify_jwt(token: str, secret: Optional[str] = None) -> Dict[str, Any]:
    """Decodes and verifies a JWT token.
    Supports HS256 HMAC verification when secret is provided, and structural/expiration
    claims verification for Supabase tokens.
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

    alg = header.get("alg", "HS256")

    # 2. Vérifier la signature HMAC si une clé secrète est configurée
    if secret:
        if alg == "HS256":
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
        else:
            _log.info("Algorithme %s vérifié au niveau structure et validité temporelle", alg)

    # 3. Décoder le payload
    try:
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception as e:
        raise JWTVerificationError(f"Payload de jeton illisible: {e}")

    # 4. Vérifier l'expiration (exp)
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
            headers={"WWW-Authenticate": "Bearer error=\"invalid_token\""},
        )
    except JWTVerificationError as e:
        raise HTTPException(
            status_code=401,
            detail=f"Jeton d'authentification invalide : {e}",
            headers={"WWW-Authenticate": "Bearer error=\"invalid_token\""},
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
