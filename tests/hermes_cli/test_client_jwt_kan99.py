"""Acceptance and regression tests for KAN-99: Client JWT signature verification.

Validates that:
- CA1: Unverifiable tokens are rejected (HS256 unknown key, ES256 fake, RS256 fake, none)
- CA2: Legitimate ES256 tokens signed with EC key in JWKS are accepted
- CA3: Tenant isolation (403) holds even with legitimately signed tokens
- CA4: Fail-closed behavior when JWKS is unavailable (without cache), and cache hit behavior
- CA6: Explicit coverage of the 3 canonical cases (HS256 unknown rejected, ES256 invalid rejected, ES256 valid accepted)
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any, Dict
from unittest.mock import patch, MagicMock

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
import jwt

from hermes_cli.dashboard_auth.client_jwt import (
    decode_and_verify_jwt,
    verify_client_access,
    JWTVerificationError,
)
from fastapi import Request, HTTPException


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _generate_ec_key_pair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()
    public_numbers = public_key.public_numbers()
    
    # JWK representation
    x_bytes = public_numbers.x.to_bytes(32, byteorder="big")
    y_bytes = public_numbers.y.to_bytes(32, byteorder="big")
    jwk = {
        "kty": "EC",
        "crv": "P-256",
        "alg": "ES256",
        "use": "sig",
        "kid": "test-kid-1",
        "x": _b64url(x_bytes),
        "y": _b64url(y_bytes),
    }
    return private_key, public_key, jwk


@pytest.fixture
def ec_key_setup():
    private_key, public_key, jwk = _generate_ec_key_pair()
    jwks = {"keys": [jwk]}
    return {
        "private_key": private_key,
        "public_key": public_key,
        "jwk": jwk,
        "jwks": jwks,
        "kid": "test-kid-1",
    }


def _make_payload(tenant_id="f3e25379-6531-479e-b276-3b3185e7421b", tenant_slug="financia-solutions"):
    return {
        "sub": "user-test-kan99",
        "email": "user@financia-solutions.fr",
        "tenant": {
            "tenant_id": tenant_id,
            "tenant_slug": tenant_slug,
            "role": "admin",
            "is_admin": True,
            "agents": ["jerome", "lucas", "clara", "victor"],
        },
        "exp": int(time.time()) + 3600,
    }


# ==============================================================================
# CA6: Le test à trois cas requis par le ticket KAN-99
# ==============================================================================
def test_ca6_three_core_cases(ec_key_setup, monkeypatch):
    """CA6: Le test qui doit rougir sur le code d'avant correction.
    1. HS256 à clé inconnue -> REFUSÉ
    2. ES256 à signature invalide -> REFUSÉ
    3. ES256 signé par la clé en service -> ACCEPTÉ
    """
    secret = "secret-officiel-recette-32-chars-ok"
    monkeypatch.setenv("SUPABASE_JWT_SECRET", secret)
    
    payload = _make_payload()
    
    # 1. HS256 signé avec une clé inconnue
    token_hs256_unknown = jwt.encode(payload, "cle-inconnue-aleatoire", algorithm="HS256")
    with pytest.raises(JWTVerificationError):
        decode_and_verify_jwt(token_hs256_unknown, secret=secret)
        
    # 2. ES256 avec signature invalide (remplissage ou clé différente)
    token_es256_valid = jwt.encode(
        payload,
        ec_key_setup["private_key"],
        algorithm="ES256",
        headers={"kid": ec_key_setup["kid"]},
    )
    # Corrompre la signature
    parts = token_es256_valid.split(".")
    token_es256_corrupt = f"{parts[0]}.{parts[1]}.{_b64url(b'invalid-signature-padding-bytes-here!')}"
    
    # Doit être REFUSÉ (sur le code d'avant, passe silencieusement sans contrôle !)
    with pytest.raises(JWTVerificationError):
        decode_and_verify_jwt(token_es256_corrupt, secret=secret, jwks_data=ec_key_setup["jwks"])
        
    # 3. ES256 signé par la clé en service
    decoded = decode_and_verify_jwt(token_es256_valid, secret=secret, jwks_data=ec_key_setup["jwks"])
    assert decoded["sub"] == "user-test-kan99"
    assert decoded["tenant"]["tenant_slug"] == "financia-solutions"


# ==============================================================================
# CA2: Jeton ES256 légitime accepté sur instance locale
# ==============================================================================
@pytest.mark.asyncio
async def test_ca2_es256_legitimate_token_accepted(ec_key_setup, monkeypatch):
    """CA2: Un jeton ES256 légitimement signé par la clé présente dans le JWKS est accepté."""
    secret = "secret-officiel-recette-32-chars-ok"
    monkeypatch.setenv("SUPABASE_JWT_SECRET", secret)
    monkeypatch.setenv("ORSO_CLIENT_ID", "f3e25379-6531-479e-b276-3b3185e7421b")
    monkeypatch.setenv("ORSO_CLIENT_SLUG", "financia-solutions")

    payload = _make_payload()
    token = jwt.encode(
        payload,
        ec_key_setup["private_key"],
        algorithm="ES256",
        headers={"kid": ec_key_setup["kid"]},
    )

    request = MagicMock(spec=Request)
    request.headers = {"Authorization": f"Bearer {token}"}
    request.cookies = {}
    request.state = MagicMock()

    with patch("hermes_cli.dashboard_auth.client_jwt.get_jwks_data", return_value=ec_key_setup["jwks"]):
        result = await verify_client_access(request)
        assert result["sub"] == "user-test-kan99"
        assert result["email"] == "user@financia-solutions.fr"
        assert result["tenant"]["tenant_slug"] == "financia-solutions"
        assert result["tenant"]["role"] == "admin"
        assert result["tenant"]["is_admin"] is True



# ==============================================================================
# CA1: Rejet des jetons invérifiables (4 cas)
# ==============================================================================
def test_ca1_unverifiable_tokens_rejected(ec_key_setup, monkeypatch):
    """CA1: Un jeton dont la signature n'est pas vérifiable est refusé.
    - HS256 à clé inconnue
    - ES256 à signature de remplissage
    - RS256 à signature de remplissage
    - none sans signature
    """
    secret = "secret-officiel-recette-32-chars-ok"
    monkeypatch.setenv("SUPABASE_JWT_SECRET", secret)
    payload = _make_payload()
    
    h_b64 = _b64url(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    p_b64 = _b64url(json.dumps(payload).encode())
    
    # 1. HS256 inconnu
    t_hs = jwt.encode(payload, "bad-key", algorithm="HS256")
    with pytest.raises(JWTVerificationError):
        decode_and_verify_jwt(t_hs, secret=secret, jwks_data=ec_key_setup["jwks"])
        
    # 2. ES256 remplissage
    t_es = f"{_b64url(json.dumps({'alg': 'ES256', 'kid': 'test-kid-1'}).encode())}.{p_b64}.{_b64url(b'x'*64)}"
    with pytest.raises(JWTVerificationError):
        decode_and_verify_jwt(t_es, secret=secret, jwks_data=ec_key_setup["jwks"])
        
    # 3. RS256 remplissage
    t_rs = f"{_b64url(json.dumps({'alg': 'RS256', 'kid': 'test-kid-1'}).encode())}.{p_b64}.{_b64url(b'x'*256)}"
    with pytest.raises(JWTVerificationError):
        decode_and_verify_jwt(t_rs, secret=secret, jwks_data=ec_key_setup["jwks"])
        
    # 4. none
    t_none = f"{h_b64}.{p_b64}."
    with pytest.raises(JWTVerificationError):
        decode_and_verify_jwt(t_none, secret=secret, jwks_data=ec_key_setup["jwks"])


# ==============================================================================
# CA3: Isolation multi-tenant préservée (403)
# ==============================================================================
@pytest.mark.asyncio
async def test_ca3_tenant_isolation_maintained_with_valid_signature(ec_key_setup, monkeypatch):
    """CA3: Un jeton légitimement signé mais pour un autre tenant rend 403."""
    secret = "secret-officiel-recette-32-chars-ok"
    monkeypatch.setenv("SUPABASE_JWT_SECRET", secret)
    monkeypatch.setenv("ORSO_CLIENT_ID", "f3e25379-6531-479e-b276-3b3185e7421b")
    monkeypatch.setenv("ORSO_CLIENT_SLUG", "financia-solutions")
    
    # Jeton valide mais portant un autre tenant (eurotech-conseil)
    payload_other_tenant = _make_payload(tenant_id="other-id-999", tenant_slug="eurotech-conseil")
    token_other = jwt.encode(
        payload_other_tenant,
        ec_key_setup["private_key"],
        algorithm="ES256",
        headers={"kid": ec_key_setup["kid"]},
    )
    
    request = MagicMock(spec=Request)
    request.headers = {"Authorization": f"Bearer {token_other}"}
    request.cookies = {}
    request.state = MagicMock()
    
    with patch("hermes_cli.dashboard_auth.client_jwt.get_jwks_data", return_value=ec_key_setup["jwks"]):
        with pytest.raises(HTTPException) as exc_info:
            await verify_client_access(request)
        assert exc_info.value.status_code == 403
        assert "Accès interdit" in exc_info.value.detail


# ==============================================================================
# CA4: Fail-closed si JWKS indisponible sans cache, et hit avec cache
# ==============================================================================
def test_ca4_fail_closed_when_jwks_unavailable_and_cache_behavior(ec_key_setup, monkeypatch):
    """CA4:
    - Sans clé en cache et source JWKS indisponible -> Refus strict 401 (Fail-Closed).
    - Avec clé en cache valide -> Accepté.
    """
    payload = _make_payload()
    token = jwt.encode(
        payload,
        ec_key_setup["private_key"],
        algorithm="ES256",
        headers={"kid": ec_key_setup["kid"]},
    )
    
    # Cas A: JWKS indisponible sans cache (fonction lève une exception de transport / renvoie None)
    with patch("hermes_cli.dashboard_auth.client_jwt.fetch_jwks", side_effect=Exception("Connection refused")):
        with pytest.raises(JWTVerificationError) as exc_info:
            decode_and_verify_jwt(token, force_jwks_refresh=True)
        assert "impossible de vérifier" in str(exc_info.value).lower() or "indisponible" in str(exc_info.value).lower()
        
    # Cas B: Clé présente dans le cache
    with patch("hermes_cli.dashboard_auth.client_jwt.get_signing_key_from_cache", return_value=ec_key_setup["public_key"]):
        decoded = decode_and_verify_jwt(token)
        assert decoded["sub"] == "user-test-kan99"
