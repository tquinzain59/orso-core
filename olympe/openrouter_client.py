"""Client et Gestionnaire Souverain OpenRouter pour Orso Agents (KAN-116, KAN-122, KAN-123).

Gère :
- Le provisionnement à la volée des tokens dédiés par client via l'API Management OpenRouter (`POST /api/v1/keys`).
- La révocation / désactivation immédiate des tokens (`PATCH /api/v1/keys/{hash}` / `DELETE /api/v1/keys/{hash}`).
- La pose et la modification de plafonds de consommation (`limit`, `limit_reset`) et le suivi d'usage (`GET /api/v1/keys/{hash}` & `GET /api/v1/key`).
- Le stockage chiffré et à permissions restreintes (`0600`) des tokens clients hors dépôt, sans jamais exposer le secret en clair dans les traces, journaux ou réponses d'API.
- Le catalogue officiel des modèles frugaux sélectionnables par tenant (KAN-122) :
  * DeepSeek frugal par défaut : `deepseek/deepseek-v4-flash`
  * Mistral frugal : `mistralai/mistral-small-24b-instruct-2501`
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_log = logging.getLogger("orso.olympe.openrouter")

OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"

# Seuil/plafond de consommation par défaut proposé à la souscription (KAN-116 CA6 / KAN-123 CA4)
DEFAULT_CONSUMPTION_LIMIT_USD = 25.0
DEFAULT_CONSUMPTION_ALERT_THRESHOLD_PCT = 80.0
DEFAULT_LIMIT_RESET = "monthly"

# Catalogue officiel des modèles sélectionnables par le client (KAN-122 CA1)
# Arbitrage Thibaut (18/10/2026) : Deepseek (modèle le plus frugal, par défaut) + Mistral (modèle le plus frugal)
DEFAULT_TENANT_MODEL_ID = "deepseek/deepseek-v4-flash"

TENANT_MODELS_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "deepseek/deepseek-v4-flash",
        "name": "DeepSeek V4 Flash (Frugal • Par défaut)",
        "provider": "DeepSeek",
        "openrouter_id": "deepseek/deepseek-v4-flash",
        "is_default": True,
        "tier": "frugal",
        "description": "Modèle haute vélocité et ultra-frugal optimisé pour le recouvrement, la qualification et les relances métier.",
        "input_price_per_1m_usd": 0.091,
        "output_price_per_1m_usd": 0.182,
        "pricing_per_m_tokens": {
            "prompt_usd": 0.091,
            "completion_usd": 0.182,
        },
        "context_length": 128000,
    },
    {
        "id": "mistralai/mistral-small-24b-instruct-2501",
        "name": "Mistral Small 3 24B (Frugal Européen)",
        "provider": "Mistral AI",
        "openrouter_id": "mistralai/mistral-small-24b-instruct-2501",
        "is_default": False,
        "tier": "frugal",
        "description": "Modèle frugal souverain européen (Mistral AI) offrant une excellente maîtrise du français juridique et commercial.",
        "input_price_per_1m_usd": 0.050,
        "output_price_per_1m_usd": 0.080,
        "pricing_per_m_tokens": {
            "prompt_usd": 0.050,
            "completion_usd": 0.080,
        },
        "context_length": 32768,
    },
]

VALID_MODEL_IDS = {m["id"] for m in TENANT_MODELS_CATALOG}


def get_models_catalog() -> List[Dict[str, Any]]:
    """Retourne la copie du catalogue officiel des modèles sélectionnables (KAN-122 CA1)."""
    return [dict(m) for m in TENANT_MODELS_CATALOG]


get_model_catalog = get_models_catalog


def is_valid_tenant_model(model_id: str) -> bool:
    """Vérifie qu'un identifiant de modèle appartient au catalogue autorisé (KAN-122 CA1)."""
    return bool(model_id and model_id.strip() in VALID_MODEL_IDS)


def get_model_info(model_id: Optional[str]) -> Dict[str, Any]:
    """Retourne les métadonnées du modèle ou celles du modèle par défaut."""
    clean_id = (model_id or DEFAULT_TENANT_MODEL_ID).strip()
    for m in TENANT_MODELS_CATALOG:
        if m["id"] == clean_id:
            return dict(m)
    return dict(TENANT_MODELS_CATALOG[0])


get_model_catalog_entry = get_model_info


def mask_secret_key(raw_key: Optional[str]) -> str:
    """Masque irréversiblement un token OpenRouter pour affichage sécurisé (CA3)."""
    if not raw_key or not isinstance(raw_key, str):
        return ""
    clean = raw_key.strip()
    if len(clean) <= 12:
        return "sk-or-v1-••••"
    return f"{clean[:10]}••••{clean[-4:]}"


def _derive_encryption_key(master_secret: Optional[str] = None) -> bytes:
    """Dérive une clé de chiffrement 32 octets à partir du secret maître hors dépôt."""
    secret = (
        master_secret
        or os.environ.get("ORSO_OPENROUTER_VAULT_SECRET")
        or os.environ.get("ORSO_PERSONA_HMAC_KEY")
        or "orso-default-local-vault-key"
    ).strip()
    return hashlib.sha256(secret.encode("utf-8")).digest()


def encrypt_token(plaintext: str, master_secret: Optional[str] = None) -> str:
    """Chiffre un token en flux XOR-HMAC déterministe authentifié (sans dépendance externe) (CA3)."""
    if not plaintext:
        return ""
    key = _derive_encryption_key(master_secret)
    nonce = os.urandom(16)
    pt_bytes = plaintext.encode("utf-8")
    # Génération du keystream par blocs SHA-256(key || nonce || counter)
    cipher_bytes = bytearray(len(pt_bytes))
    block_idx = 0
    offset = 0
    while offset < len(pt_bytes):
        ks_block = hashlib.sha256(key + nonce + block_idx.to_bytes(4, "big")).digest()
        chunk_len = min(32, len(pt_bytes) - offset)
        for i in range(chunk_len):
            cipher_bytes[offset + i] = pt_bytes[offset + i] ^ ks_block[i]
        offset += chunk_len
        block_idx += 1

    mac = hmac.new(key, nonce + bytes(cipher_bytes), hashlib.sha256).digest()
    payload = nonce + mac + bytes(cipher_bytes)
    return "enc:v1:" + base64.urlsafe_b64encode(payload).decode("ascii")


def decrypt_token(ciphertext: str, master_secret: Optional[str] = None) -> Optional[str]:
    """Déchiffre et vérifie l'authenticité HMAC d'un token chiffré par encrypt_token."""
    if not ciphertext or not isinstance(ciphertext, str):
        return None
    if not ciphertext.startswith("enc:v1:"):
        return None
    try:
        raw = base64.urlsafe_b64decode(ciphertext[len("enc:v1:"):].encode("ascii"))
        if len(raw) < 48:
            return None
        nonce = raw[:16]
        mac = raw[16:48]
        cipher_bytes = raw[48:]
        key = _derive_encryption_key(master_secret)
        expected_mac = hmac.new(key, nonce + cipher_bytes, hashlib.sha256).digest()
        if not hmac.compare_digest(mac, expected_mac):
            _log.error("[SECURITY] Échec de vérification d'intégrité HMAC lors du déchiffrement du token OpenRouter.")
            return None

        pt_bytes = bytearray(len(cipher_bytes))
        block_idx = 0
        offset = 0
        while offset < len(cipher_bytes):
            ks_block = hashlib.sha256(key + nonce + block_idx.to_bytes(4, "big")).digest()
            chunk_len = min(32, len(cipher_bytes) - offset)
            for i in range(chunk_len):
                pt_bytes[offset + i] = cipher_bytes[offset + i] ^ ks_block[i]
            offset += chunk_len
            block_idx += 1
        return pt_bytes.decode("utf-8")
    except Exception as e:
        _log.error("Erreur déchiffrement token OpenRouter : %s", e)
        return None


class OpenRouterProvisioningManager:
    """Gestionnaire du cycle de vie des tokens OpenRouter par client (KAN-116)."""

    def __init__(
        self,
        provisioning_key: Optional[str] = None,
        vault_dir: Optional[Path] = None,
        master_secret: Optional[str] = None,
    ):
        self._explicit_provisioning_key = provisioning_key
        self._master_secret = master_secret
        if vault_dir:
            self.vault_dir = Path(vault_dir).resolve()
        elif os.environ.get("ORSO_OPENROUTER_VAULT_DIR"):
            self.vault_dir = Path(os.environ["ORSO_OPENROUTER_VAULT_DIR"]).resolve()
        else:
            self.vault_dir = Path("./data/openrouter_vault").resolve()
        self._ensure_vault_dir()

    def _ensure_vault_dir(self) -> None:
        """Crée le répertoire coffre-fort avec permissions restreintes 0700 (CA3)."""
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.vault_dir, 0o700)
        except Exception:
            pass

    @property
    def provisioning_key(self) -> str:
        """Récupère la clé de provisioning OpenRouter hors dépôt (CA4)."""
        if self._explicit_provisioning_key is not None:
            return self._explicit_provisioning_key.strip()
        return (
            os.environ.get("OPENROUTER_PROVISIONING_API_KEY")
            or os.environ.get("OPENROUTER_MANAGEMENT_API_KEY")
            or ""
        ).strip()

    def _get_vault_file(self, tenant_slug: str) -> Path:
        clean_slug = "".join(c for c in tenant_slug.strip().lower() if c.isalnum() or c in ("-", "_"))
        if not clean_slug:
            clean_slug = "unknown"
        return self.vault_dir / f"{clean_slug}.key.json"

    def _record_path(self, tenant_slug: str) -> Path:
        return self._get_vault_file(tenant_slug)

    def _write_vault_record(self, vault_file: Path, record: Dict[str, Any]) -> Path:
        self._ensure_vault_dir()
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        fd = os.open(str(vault_file), flags, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(record, f, indent=2, ensure_ascii=False)
            os.chmod(vault_file, 0o600)
        except Exception:
            try:
                os.close(fd)
            except Exception:
                pass
            raise
        return vault_file

    def store_tenant_secret(
        self,
        tenant_id: str,
        tenant_slug: Any = None,
        raw_api_key: Optional[str] = None,
        key_hash: str = "",
        key_label: str = "",
        limit_usd: float = DEFAULT_CONSUMPTION_LIMIT_USD,
        limit_reset: Optional[str] = DEFAULT_LIMIT_RESET,
        alert_threshold_pct: float = DEFAULT_CONSUMPTION_ALERT_THRESHOLD_PCT,
    ) -> Path:
        """Enregistre le token chiffré dans un fichier local à permissions restreintes 0600 (CA3)."""
        # Support de l'appel raccourci store_tenant_secret(tenant_slug, record_dict)
        if isinstance(tenant_slug, dict) and raw_api_key is None:
            slug_str = str(tenant_id)
            rec_dict = dict(tenant_slug)
            rec_dict["updated_at"] = datetime.now(timezone.utc).isoformat()
            return self._write_vault_record(self._get_vault_file(slug_str), rec_dict)

        slug_str = str(tenant_slug or tenant_id)
        vault_file = self._get_vault_file(slug_str)
        encrypted = encrypt_token(raw_api_key or "", master_secret=self._master_secret)
        record = {
            "tenant_id": tenant_id,
            "tenant_slug": slug_str,
            "key_hash": key_hash,
            "key_label": key_label or f"orso-tenant-{slug_str}",
            "key_masked": mask_secret_key(raw_api_key),
            "encrypted_key": encrypted,
            "key_encrypted": encrypted,
            "limit_usd": float(limit_usd),
            "limit_reset": limit_reset,
            "alert_threshold_pct": float(alert_threshold_pct),
            "status": "active",
            "disabled": False,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        return self._write_vault_record(vault_file, record)

    def load_tenant_secret_record(self, tenant_slug: str) -> Optional[Dict[str, Any]]:
        """Charge les métadonnées du coffre-fort local pour un tenant."""
        vault_file = self._get_vault_file(tenant_slug)
        if not vault_file.is_file():
            return None
        try:
            with open(vault_file, "r", encoding="utf-8") as f:
                data = json.loads(f.read())
                if isinstance(data, dict) and "encrypted_key" in data and "key_encrypted" not in data:
                    data["key_encrypted"] = data["encrypted_key"]
                return data
        except Exception as e:
            _log.warning("Impossible de lire le coffre-fort OpenRouter pour %s : %s", tenant_slug, e)
            return None

    def get_tenant_secret_record(self, tenant_slug: str) -> Optional[Dict[str, Any]]:
        """Alias de load_tenant_secret_record."""
        return self.load_tenant_secret_record(tenant_slug)

    def record_local_usage(
        self,
        tenant_slug: str,
        cost_usd: float,
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Enregistre ou incrémente une consommation locale/sandbox attribuée au tenant (CA2, CA6)."""
        rec = self.load_tenant_secret_record(tenant_slug)
        if not rec:
            self.create_tenant_key(
                tenant_id=tenant_id or tenant_slug,
                tenant_slug=tenant_slug,
                allow_simulated=True,
            )
            rec = self.load_tenant_secret_record(tenant_slug) or {}
        cur_usage = float(rec.get("usage_usd", 0.0)) + float(cost_usd)
        cur_monthly = float(rec.get("usage_monthly_usd", 0.0)) + float(cost_usd)
        rec["usage_usd"] = round(cur_usage, 4)
        rec["usage_monthly_usd"] = round(cur_monthly, 4)
        rec["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_vault_record(self._get_vault_file(tenant_slug), rec)
        return self.get_tenant_usage(tenant_slug, tenant_id=tenant_id)

    def get_decrypted_tenant_key(self, tenant_slug: str) -> Optional[str]:
        """Déchiffre et retourne la clé API OpenRouter dédiée au tenant uniquement pour l'injection stdin conteneur."""
        rec = self.load_tenant_secret_record(tenant_slug)
        if not rec or rec.get("status") == "revoked" or rec.get("disabled"):
            return None
        enc = rec.get("encrypted_key") or rec.get("key_encrypted")
        if not enc:
            return None
        return decrypt_token(enc, master_secret=self._master_secret)

    def _api_request(
        self,
        path: str,
        method: str = "GET",
        payload: Optional[Dict[str, Any]] = None,
        bearer_key: Optional[str] = None,
        timeout: float = 8.0,
    ) -> Tuple[int, Dict[str, Any]]:
        """Exécute un appel HTTP vers l'API OpenRouter sans jamais logger les en-têtes ni la clé (CA3)."""
        token = (bearer_key or self.provisioning_key).strip()
        if not token:
            return 401, {"error": {"message": "Clé de provisioning OpenRouter absente (OPENROUTER_PROVISIONING_API_KEY).", "code": 401}}

        url = f"{OPENROUTER_API_BASE}/{path.lstrip('/')}"
        data_bytes = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "OrsoOlympe/1.0",
        }
        req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw_body = resp.read().decode("utf-8")
                return resp.status, json.loads(raw_body) if raw_body else {}
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8")
                err_json = json.loads(err_body)
            except Exception:
                err_json = {"error": {"message": err_body or f"HTTP {e.code}", "code": e.code}}
            return e.code, err_json
        except Exception as e:
            return 503, {"error": {"message": f"Erreur réseau OpenRouter : {type(e).__name__}", "code": 503}}

    def create_tenant_key(
        self,
        tenant_id: str,
        tenant_slug: str,
        limit_usd: float = DEFAULT_CONSUMPTION_LIMIT_USD,
        limit_reset: Optional[str] = DEFAULT_LIMIT_RESET,
        alert_threshold_pct: float = DEFAULT_CONSUMPTION_ALERT_THRESHOLD_PCT,
        allow_simulated_fallback: bool = False,
        allow_simulated: bool = False,
    ) -> Dict[str, Any]:
        """Crée à la volée un token OpenRouter dédié au tenant (CA1, CA3, CA4, CA6).

        Retourne les métadonnées publiques de la clé (hash, label, limit_usd, key_masked)
        et stocke la clé secrète chiffrée dans le coffre-fort local 0600.
        La clé en clair n'est JAMAIS retournée dans le dictionnaire de résultat public.
        """
        key_name = f"orso-tenant-{tenant_slug}"
        prov_key = self.provisioning_key
        can_simulate = bool(allow_simulated_fallback or allow_simulated)

        if not prov_key:
            if not can_simulate:
                return {
                    "success": False,
                    "error": "ERR_PROVISIONING_KEY_MISSING",
                    "message": (
                        "Création du token OpenRouter refusée : la clé de provisioning "
                        "OPENROUTER_PROVISIONING_API_KEY est absente de l'environnement de gestion."
                    ),
                }
            # Mode test/sandbox hermétique explicitement autorisé hors production
            raw_hash = hashlib.sha256(f"{tenant_id}:{tenant_slug}:{datetime.now(timezone.utc).isoformat()}".encode()).hexdigest()
            simulated_raw_key = f"sk-or-v1-{raw_hash}"
            vault_path = self.store_tenant_secret(
                tenant_id=tenant_id,
                tenant_slug=tenant_slug,
                raw_api_key=simulated_raw_key,
                key_hash=raw_hash,
                key_label=key_name,
                limit_usd=limit_usd,
                limit_reset=limit_reset,
                alert_threshold_pct=alert_threshold_pct,
            )
            return {
                "success": True,
                "simulated": True,
                "has_dedicated_token": True,
                "tenant_id": tenant_id,
                "tenant_slug": tenant_slug,
                "key_hash": raw_hash,
                "key_label": key_name,
                "key_masked": mask_secret_key(simulated_raw_key),
                "limit_usd": float(limit_usd),
                "limit_reset": limit_reset,
                "alert_threshold_pct": float(alert_threshold_pct),
                "status": "active",
                "disabled": False,
                "vault_file": str(vault_path),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

        payload: Dict[str, Any] = {
            "name": key_name,
            "limit": float(limit_usd),
        }
        if limit_reset:
            payload["limit_reset"] = limit_reset

        status_code, resp_data = self._api_request("keys", method="POST", payload=payload)
        if status_code not in (200, 201):
            err_msg = (
                resp_data.get("error", {}).get("message")
                if isinstance(resp_data.get("error"), dict)
                else str(resp_data.get("error") or f"HTTP {status_code}")
            )
            _log.error("Échec création clé OpenRouter pour tenant %s (HTTP %s) : %s", tenant_slug, status_code, err_msg)
            return {
                "success": False,
                "error": "ERR_OPENROUTER_API_REJECTED",
                "http_status": status_code,
                "message": f"Échec de création du token OpenRouter dédié : {err_msg}",
            }

        key_obj = resp_data.get("data") if isinstance(resp_data.get("data"), dict) else resp_data
        raw_secret = key_obj.get("key") or resp_data.get("key")
        key_hash = key_obj.get("hash") or hashlib.sha256((raw_secret or key_name).encode("utf-8")).hexdigest()
        key_label = key_obj.get("name") or key_obj.get("label") or key_name

        if not raw_secret:
            return {
                "success": False,
                "error": "ERR_OPENROUTER_NO_SECRET_RETURNED",
                "message": "L'API OpenRouter n'a pas retourné la valeur du token lors de la création.",
            }

        vault_path = self.store_tenant_secret(
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            raw_api_key=raw_secret,
            key_hash=key_hash,
            key_label=key_label,
            limit_usd=float(key_obj.get("limit") if key_obj.get("limit") is not None else limit_usd),
            limit_reset=key_obj.get("limit_reset") or limit_reset,
            alert_threshold_pct=alert_threshold_pct,
        )

        _log.info(
            "Token OpenRouter dédié créé et scellé pour le tenant %s (hash=%s, plafond=%.2f USD)",
            tenant_slug,
            key_hash[:12],
            float(limit_usd),
        )
        return {
            "success": True,
            "simulated": False,
            "tenant_id": tenant_id,
            "tenant_slug": tenant_slug,
            "key_hash": key_hash,
            "key_label": key_label,
            "key_masked": mask_secret_key(raw_secret),
            "limit_usd": float(key_obj.get("limit") if key_obj.get("limit") is not None else limit_usd),
            "limit_reset": key_obj.get("limit_reset") or limit_reset,
            "alert_threshold_pct": float(alert_threshold_pct),
            "status": "active",
            "vault_file": str(vault_path),
            "created_at": key_obj.get("created_at") or datetime.now(timezone.utc).isoformat(),
        }

    def revoke_tenant_key(
        self,
        tenant_slug: str,
        key_hash: Optional[str] = None,
        hard_delete: bool = False,
    ) -> Dict[str, Any]:
        """Révoque ou désactive immédiatement le token OpenRouter d'un client désactivé (CA5)."""
        rec = self.load_tenant_secret_record(tenant_slug)
        effective_hash = key_hash or (rec.get("key_hash") if rec else None)

        api_revoked = False
        if effective_hash and self.provisioning_key:
            if hard_delete:
                code, _ = self._api_request(f"keys/{effective_hash}", method="DELETE")
                api_revoked = code in (200, 204, 404)
            else:
                # Désactivation réversible + révocation immédiate du droit d'appel sur OpenRouter
                code, _ = self._api_request(
                    f"keys/{effective_hash}",
                    method="PATCH",
                    payload={"disabled": True},
                )
                if code in (200, 204):
                    api_revoked = True
                else:
                    # Fallback DELETE si PATCH non supporté
                    code_del, _ = self._api_request(f"keys/{effective_hash}", method="DELETE")
                    api_revoked = code_del in (200, 204, 404)

        vault_file = self._get_vault_file(tenant_slug)
        if rec and vault_file.is_file():
            rec["status"] = "revoked"
            rec["disabled"] = True
            rec["revoked_at"] = datetime.now(timezone.utc).isoformat()
            if hard_delete:
                rec["encrypted_key"] = ""
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            fd = os.open(str(vault_file), flags, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(rec, f, indent=2, ensure_ascii=False)
            os.chmod(vault_file, 0o600)

        _log.info("Token OpenRouter révoqué pour le tenant %s (hash=%s, api_revoked=%s)", tenant_slug, (effective_hash or "")[:12], api_revoked)
        return {
            "success": True,
            "tenant_slug": tenant_slug,
            "key_hash": effective_hash,
            "status": "revoked",
            "disabled": True,
            "api_revoked": api_revoked,
            "revoked_at": datetime.now(timezone.utc).isoformat(),
        }

    def update_tenant_limit(
        self,
        tenant_slug: str,
        limit_usd: float,
        key_hash: Optional[str] = None,
        limit_reset: Optional[str] = DEFAULT_LIMIT_RESET,
        alert_threshold_pct: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Met à jour le plafond de consommation et le seuil d'alerte d'un client (KAN-116 CA6 / KAN-123 CA4)."""
        if limit_usd < 0:
            raise ValueError("Le plafond de consommation doit être positif ou nul.")

        rec = self.load_tenant_secret_record(tenant_slug)
        effective_hash = key_hash or (rec.get("key_hash") if rec else None)

        api_updated = False
        if effective_hash and self.provisioning_key:
            patch_payload: Dict[str, Any] = {"limit": float(limit_usd)}
            if limit_reset is not None:
                patch_payload["limit_reset"] = limit_reset
            code, _ = self._api_request(f"keys/{effective_hash}", method="PATCH", payload=patch_payload)
            api_updated = code in (200, 204)

        if rec:
            rec["limit_usd"] = float(limit_usd)
            if limit_reset is not None:
                rec["limit_reset"] = limit_reset
            if alert_threshold_pct is not None:
                rec["alert_threshold_pct"] = float(alert_threshold_pct)
            rec["updated_at"] = datetime.now(timezone.utc).isoformat()
            vault_file = self._get_vault_file(tenant_slug)
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            fd = os.open(str(vault_file), flags, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(rec, f, indent=2, ensure_ascii=False)
            os.chmod(vault_file, 0o600)

        return {
            "success": True,
            "tenant_slug": tenant_slug,
            "key_hash": effective_hash,
            "limit_usd": float(limit_usd),
            "limit_reset": limit_reset,
            "alert_threshold_pct": float(
                alert_threshold_pct
                if alert_threshold_pct is not None
                else (rec.get("alert_threshold_pct", DEFAULT_CONSUMPTION_ALERT_THRESHOLD_PCT) if rec else DEFAULT_CONSUMPTION_ALERT_THRESHOLD_PCT)
            ),
            "api_updated": api_updated,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_tenant_usage(
        self,
        tenant_slug: str,
        key_hash: Optional[str] = None,
        extra_credits_usd: float = 0.0,
        override_limit_usd: Optional[float] = None,
        override_alert_pct: Optional[float] = None,
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Interroge la consommation réelle attribuée au tenant (KAN-116 CA2, CA6 / KAN-123 CA3)."""
        rec = self.load_tenant_secret_record(tenant_slug) or {}
        effective_hash = key_hash or rec.get("key_hash")
        base_limit = float(
            override_limit_usd
            if override_limit_usd is not None
            else rec.get("limit_usd", DEFAULT_CONSUMPTION_LIMIT_USD)
        )
        effective_limit = round(base_limit + float(extra_credits_usd or 0.0), 4)
        alert_pct = float(
            override_alert_pct
            if override_alert_pct is not None
            else rec.get("alert_threshold_pct", DEFAULT_CONSUMPTION_ALERT_THRESHOLD_PCT)
        )
        status = rec.get("status", "active" if effective_hash else "unprovisioned")

        usage_total = float(rec.get("usage_usd", 0.0))
        usage_daily = float(rec.get("usage_daily_usd", 0.0))
        usage_weekly = float(rec.get("usage_weekly_usd", 0.0))
        usage_monthly = float(rec.get("usage_monthly_usd", usage_total))
        limit_remaining = max(0.0, effective_limit - usage_monthly)
        live_fetched = False

        # 1. Interrogation via Management API si key_hash et provisioning_key sont disponibles
        if effective_hash and self.provisioning_key:
            code, data = self._api_request(f"keys/{effective_hash}", method="GET")
            if code == 200 and isinstance(data.get("data"), dict):
                kd = data["data"]
                usage_total = float(kd.get("usage") or 0.0)
                usage_daily = float(kd.get("usage_daily") or 0.0)
                usage_weekly = float(kd.get("usage_weekly") or 0.0)
                usage_monthly = float(kd.get("usage_monthly") or usage_total)
                if kd.get("limit") is not None and override_limit_usd is None:
                    effective_limit = float(kd["limit"])
                if kd.get("limit_remaining") is not None:
                    limit_remaining = float(kd["limit_remaining"])
                else:
                    limit_remaining = max(0.0, effective_limit - usage_monthly)
                if kd.get("disabled"):
                    status = "revoked"
                live_fetched = True

        # 2. Sinon interrogation directe via la clé dédiée du tenant (`GET /api/v1/key`)
        if not live_fetched:
            tenant_raw_key = self.get_decrypted_tenant_key(tenant_slug)
            if tenant_raw_key and not rec.get("simulated"):
                code, data = self._api_request("key", method="GET", bearer_key=tenant_raw_key)
                if code == 200 and isinstance(data.get("data"), dict):
                    kd = data["data"]
                    usage_total = float(kd.get("usage") or 0.0)
                    usage_daily = float(kd.get("usage_daily") or 0.0)
                    usage_weekly = float(kd.get("usage_weekly") or 0.0)
                    usage_monthly = float(kd.get("usage_monthly") or usage_total)
                    if kd.get("limit") is not None and override_limit_usd is None:
                        effective_limit = float(kd["limit"])
                    if kd.get("limit_remaining") is not None:
                        limit_remaining = float(kd["limit_remaining"])
                    else:
                        limit_remaining = max(0.0, effective_limit - usage_monthly)
                    live_fetched = True

        usage_pct = round((usage_monthly / effective_limit) * 100.0, 2) if effective_limit > 0 else 0.0
        threshold_usd = round(effective_limit * (alert_pct / 100.0), 4)
        threshold_reached = usage_monthly >= threshold_usd if effective_limit > 0 else False
        limit_exceeded = usage_monthly >= effective_limit if effective_limit > 0 else False
        is_disabled = bool(rec.get("disabled") or status == "revoked")

        return {
            "tenant_id": tenant_id or rec.get("tenant_id"),
            "tenant_slug": tenant_slug,
            "key_hash": effective_hash,
            "key_label": rec.get("key_label", f"orso-tenant-{tenant_slug}"),
            "key_masked": rec.get("key_masked") or (f"hash:{effective_hash[:10]}..." if effective_hash else "Non provisionné"),
            "has_dedicated_token": bool(effective_hash and status == "active"),
            "status": status,
            "disabled": is_disabled,
            "usage_usd": round(usage_monthly, 4),
            "usage_total_usd": round(usage_total, 4),
            "usage_daily_usd": round(usage_daily, 4),
            "usage_weekly_usd": round(usage_weekly, 4),
            "usage_monthly_usd": round(usage_monthly, 4),
            "base_limit_usd": round(base_limit, 2),
            "extra_credits_usd": round(float(extra_credits_usd or 0.0), 2),
            "limit_usd": round(effective_limit, 2),
            "limit_remaining_usd": round(max(0.0, effective_limit - usage_monthly), 4),
            "remaining_usd": round(max(0.0, effective_limit - usage_monthly), 4),
            "limit_reset": rec.get("limit_reset", DEFAULT_LIMIT_RESET),
            "alert_threshold_pct": round(alert_pct, 1),
            "alert_threshold_usd": round(threshold_usd, 2),
            "usage_pct": usage_pct,
            "threshold_reached": threshold_reached,
            "limit_exceeded": limit_exceeded,
            "live_fetched": live_fetched,
            "period_label": "Mois en cours (UTC)",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }


# Instance singleton partagée
openrouter_manager = OpenRouterProvisioningManager()
