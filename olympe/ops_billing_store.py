"""Accès Supabase strict pour la facturation et l'idempotence du webhook Stripe (KAN-88).

``OpsManager._query_supabase`` absorbe toute erreur et rend ``None`` : un refus
PostgREST ``PGRST205`` (table absente du schéma) y est indiscernable d'une table vide.
Pour ``public.invoices`` et ``public.processed_webhook_events`` ce silence est le défaut
à fermer : ici l'échec LÈVE, et la route le rend au lecteur (HTTP 503).
"""

import json
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

# Codes ``error`` rendus par ``OpsManager.handle_stripe_webhook`` lorsque le support
# de facturation/idempotence est indisponible. La route les traduit en HTTP 503
# (Stripe rejoue alors la livraison) ; TENANT_NOT_FOUND garde son contrat historique.
ERR_IDEMPOTENCE_STORE = "IDEMPOTENCE_STORE_UNAVAILABLE"
ERR_BILLING_WRITE = "BILLING_WRITE_FAILED"
ERR_EVENT_RECORD_WRITE = "EVENT_RECORD_WRITE_FAILED"
STORAGE_FAILURE_CODES = frozenset({ERR_IDEMPOTENCE_STORE, ERR_BILLING_WRITE, ERR_EVENT_RECORD_WRITE})


class SupabaseStoreError(RuntimeError):
    """Lecture ou écriture Supabase refusée ; le message garde le statut HTTP et le corps PostgREST."""


def supabase_request_strict(
    base_url: str,
    api_key: str,
    path: str,
    method: str = "GET",
    payload: Optional[Dict[str, Any]] = None,
    extra_headers: Optional[Dict[str, str]] = None,
    timeout: float = 5.0,
) -> Any:
    """Appel PostgREST authentifié qui lève ``SupabaseStoreError`` sur tout échec.

    La clé d'API n'apparaît jamais dans l'exception ; le chemin y est tronqué avant ``?``
    pour ne pas journaliser les filtres.
    """
    table_path = path.split("?")[0]
    if not base_url or not api_key:
        raise SupabaseStoreError(f"{method} {table_path}: Supabase non configuré")

    headers = {
        "apikey": api_key,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "OrsoOlympeOps/1.0",
        "Prefer": "return=representation",
    }
    if extra_headers:
        headers.update(extra_headers)
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"{base_url}/rest/v1/{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            body = ""
        raise SupabaseStoreError(f"{method} {table_path} -> HTTP {e.code}: {body}") from e
    except Exception as e:
        raise SupabaseStoreError(f"{method} {table_path} -> {type(e).__name__}: {e}") from e
