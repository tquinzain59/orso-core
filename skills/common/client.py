"""
Client HTTP unifié pour les compétences et intégrations d'Hermès.
Utilise httpx par défaut avec fallback élégant sur urllib si exécuté hors conteneur.
"""

import json
from typing import Any, Dict, Optional
from urllib.parse import urlencode

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError


class HermesHttpClient:
    """Client HTTP avec gestion uniforme des erreurs, timeouts et headers."""

    DEFAULT_USER_AGENT = "Hermes-Core/1.0 (CreditManager; +https://github.com/tquinzain59/hermes-core)"

    def __init__(self, timeout: float = 30.0, default_headers: Optional[Dict[str, str]] = None):
        self.timeout = timeout
        self.default_headers = {
            "User-Agent": self.DEFAULT_USER_AGENT,
            "Accept": "application/json",
        }
        if default_headers:
            self.default_headers.update(default_headers)

    def get(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Optional[Any]:
        """Effectue une requête GET et retourne la réponse JSON parsée."""
        merged_headers = dict(self.default_headers)
        if headers:
            merged_headers.update(headers)

        if HAS_HTTPX:
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.get(url, params=params, headers=merged_headers)
                    if resp.status_code >= 400:
                        print(f"❌ Erreur HTTP {resp.status_code} sur {url}: {resp.text[:300]}")
                        return None
                    return resp.json()
            except httpx.HTTPError as e:
                print(f"❌ Erreur réseau HTTPX sur {url}: {e}")
                return None
            except json.JSONDecodeError as e:
                print(f"❌ Erreur décodage JSON sur {url}: {e}")
                return None
        else:
            # Fallback urllib
            full_url = url
            if params:
                query_str = urlencode({k: v for k, v in params.items() if v is not None})
                full_url = f"{url}?{query_str}" if "?" not in url else f"{url}&{query_str}"

            req = Request(full_url, headers=merged_headers)
            try:
                with urlopen(req, timeout=self.timeout) as resp:
                    raw_data = resp.read().decode("utf-8")
                    return json.loads(raw_data)
            except HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")
                print(f"❌ Erreur HTTP {e.code} sur {url}: {body[:300]}")
                return None
            except URLError as e:
                print(f"❌ Erreur réseau URLLib sur {url}: {e.reason}")
                return None
            except json.JSONDecodeError as e:
                print(f"❌ Erreur décodage JSON sur {url}: {e}")
                return None

    def post(
        self,
        url: str,
        json_data: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Optional[Any]:
        """Effectue une requête POST et retourne la réponse JSON parsée."""
        merged_headers = dict(self.default_headers)
        if headers:
            merged_headers.update(headers)

        if HAS_HTTPX:
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(url, json=json_data, data=data, headers=merged_headers)
                    if resp.status_code >= 400:
                        print(f"❌ Erreur HTTP {resp.status_code} sur {url}: {resp.text[:300]}")
                        return None
                    return resp.json()
            except httpx.HTTPError as e:
                print(f"❌ Erreur réseau HTTPX sur {url}: {e}")
                return None
            except json.JSONDecodeError as e:
                print(f"❌ Erreur décodage JSON sur {url}: {e}")
                return None
        else:
            # Fallback urllib
            payload = None
            if json_data is not None:
                payload = json.dumps(json_data).encode("utf-8")
                merged_headers["Content-Type"] = "application/json"
            elif data is not None:
                payload = urlencode(data).encode("utf-8")
                merged_headers["Content-Type"] = "application/x-www-form-urlencoded"

            req = Request(url, data=payload, headers=merged_headers, method="POST")
            try:
                with urlopen(req, timeout=self.timeout) as resp:
                    raw_data = resp.read().decode("utf-8")
                    return json.loads(raw_data)
            except HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")
                print(f"❌ Erreur HTTP {e.code} sur {url}: {body[:300]}")
                return None
            except URLError as e:
                print(f"❌ Erreur réseau URLLib sur {url}: {e.reason}")
                return None
            except json.JSONDecodeError as e:
                print(f"❌ Erreur décodage JSON sur {url}: {e}")
                return None
