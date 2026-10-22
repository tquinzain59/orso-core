"""Connecteurs API réels (CA5) : Google Drive et comptabilité (Pennylane), stdlib uniquement.

Identifiants : lus dans l'environnement du conteneur, désignés par leur nom
(``GOOGLE_WORKSPACE_CREDENTIALS``, ``PENNYLANE_API_KEY``), jamais en argument, jamais journalisés,
jamais écrits dans l'index. Le jeton n'est envoyé qu'en HTTPS (HTTP toléré en boucle locale pour les
tests) et jamais suivi vers un autre hôte lors d'une redirection.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Iterator, Mapping

from .chunking import is_supported
from .connectors import Connector, ConnectorError, RemoteDocument, RemoteFailure

GOOGLE_CREDENTIALS_ENV = "GOOGLE_WORKSPACE_CREDENTIALS"
PENNYLANE_KEY_ENV = "PENNYLANE_API_KEY"

DRIVE_API = "https://www.googleapis.com/drive/v3"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
PENNYLANE_API = "https://app.pennylane.com/api/external/v2"

MAX_DOCUMENT_BYTES = 25 * 1024 * 1024
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

_FOLDER = "application/vnd.google-apps.folder"
# Documents Google natifs : pas de contenu binaire, export texte (Sheets : première feuille seulement).
_GOOGLE_EXPORTS = {
    "application/vnd.google-apps.document": ("text/plain", ".txt"),
    "application/vnd.google-apps.presentation": ("text/plain", ".txt"),
    "application/vnd.google-apps.spreadsheet": ("text/csv", ".csv"),
}


def _check_base_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in _LOOPBACK):
        return url.rstrip("/")
    raise ValueError(f"URL de service refusée (HTTPS requis) : {parts.scheme}://{parts.hostname}")


class _SameHostRedirect(urllib.request.HTTPRedirectHandler):
    """urllib rejoue l'en-tête Authorization sur une redirection : on la refuse hors de l'hôte d'origine."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).netloc != urllib.parse.urlsplit(req.full_url).netloc:
            raise ConnectorError(f"redirection vers un autre hôte refusée ({code})")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HttpClient:
    """Transport HTTP minimal. Les messages d'erreur ne contiennent ni en-têtes ni corps (jetons)."""

    def __init__(self, timeout: float = 30.0, max_bytes: int = MAX_DOCUMENT_BYTES) -> None:
        self.timeout = timeout
        self.max_bytes = max_bytes
        self._opener = urllib.request.build_opener(_SameHostRedirect)

    def request(self, url: str, headers: Mapping[str, str] | None = None, data: bytes | None = None) -> bytes:
        host = urllib.parse.urlsplit(url).netloc
        req = urllib.request.Request(url, data=data, headers=dict(headers or {}))
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                body = resp.read(self.max_bytes + 1)
        except urllib.error.HTTPError as exc:
            raise ConnectorError(f"{host} a répondu HTTP {exc.code}") from None
        except urllib.error.URLError as exc:
            raise ConnectorError(f"{host} injoignable : {exc.reason}") from None
        if len(body) > self.max_bytes:
            raise ConnectorError(f"réponse de {host} au-delà de {self.max_bytes} octets")
        return body

    def get_json(self, url: str, headers: Mapping[str, str]) -> Any:
        try:
            return json.loads(self.request(url, headers))
        except ValueError:
            raise ConnectorError(f"réponse non JSON de {urllib.parse.urlsplit(url).netloc}") from None


def _query(**params: Any) -> str:
    return urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})


class GoogleDriveConnector(Connector):
    """Importe un dossier Google Drive (récursif). ``origin_ref`` = identifiant du fichier Drive :
    stable, donc un fichier modifié donne une nouvelle version du même document."""

    name = "google-drive"

    def __init__(
        self,
        folder_id: str,
        *,
        environ: Mapping[str, str] | None = None,
        api_base: str = DRIVE_API,
        http: HttpClient | None = None,
        max_files: int = 2000,
        max_depth: int = 10,
    ) -> None:
        if not _ID_RE.match(folder_id or ""):
            raise ValueError("identifiant de dossier Drive invalide ou absent (--folder-id)")
        self.folder_id = folder_id
        self.api_base = _check_base_url(api_base)
        self.http = http or HttpClient()
        self.max_files = max_files
        self.max_depth = max_depth
        self._environ = os.environ if environ is None else environ

    def _access_token(self) -> str:
        raw = self._environ.get(GOOGLE_CREDENTIALS_ENV, "")
        if not raw:
            raise ConnectorError(f"identifiants Google absents : variable {GOOGLE_CREDENTIALS_ENV}")
        try:
            creds = json.loads(raw)
            if not isinstance(creds, dict):
                raise ValueError
        except ValueError:
            raise ConnectorError(f"{GOOGLE_CREDENTIALS_ENV} n'est pas un objet JSON valide") from None
        if creds.get("access_token"):
            return str(creds["access_token"])
        missing = [k for k in ("client_id", "client_secret", "refresh_token") if not creds.get(k)]
        if missing:
            raise ConnectorError(f"{GOOGLE_CREDENTIALS_ENV} incomplet : {', '.join(missing)} manquant(s)")
        token_uri = _check_base_url(str(creds.get("token_uri") or GOOGLE_TOKEN_URI))
        form = _query(
            grant_type="refresh_token", client_id=creds["client_id"],
            client_secret=creds["client_secret"], refresh_token=creds["refresh_token"],
        ).encode()
        try:
            payload = json.loads(self.http.request(
                token_uri, {"Content-Type": "application/x-www-form-urlencoded"}, form))
            return str(payload["access_token"])
        except (ValueError, KeyError, TypeError):
            raise ConnectorError("échange du jeton Google : réponse sans access_token") from None

    def fetch(self) -> Iterator[RemoteDocument | RemoteFailure]:
        auth = {"Authorization": f"Bearer {self._access_token()}"}
        queue: list[tuple[str, str, int]] = [(self.folder_id, "", 0)]
        delivered = 0
        while queue:
            folder, prefix, depth = queue.pop(0)
            for item in self._list(folder, auth):
                if item.get("mimeType") == _FOLDER:
                    if depth + 1 > self.max_depth:
                        yield RemoteFailure(item["id"], "profondeur de dossiers maximale atteinte")
                    else:
                        queue.append((item["id"], f"{prefix}{item['name']}/", depth + 1))
                    continue
                if delivered >= self.max_files:
                    yield RemoteFailure(item["id"], f"limite de {self.max_files} fichiers atteinte")
                    continue
                delivered += 1
                yield self._download(item, prefix, auth)

    def _list(self, folder: str, auth: Mapping[str, str]) -> Iterator[dict]:
        token = None
        while True:
            url = f"{self.api_base}/files?" + _query(
                q=f"'{folder}' in parents and trashed = false",
                fields="nextPageToken,files(id,name,mimeType,size)",
                pageSize=100, pageToken=token, supportsAllDrives="true", includeItemsFromAllDrives="true",
            )
            page = self.http.get_json(url, auth)
            yield from page.get("files", [])
            token = page.get("nextPageToken")
            if not token:
                return

    def _download(self, item: dict, prefix: str, auth: Mapping[str, str]) -> RemoteDocument | RemoteFailure:
        file_id, name, mime = item["id"], item["name"], item.get("mimeType", "")
        if mime in _GOOGLE_EXPORTS:
            export_mime, suffix = _GOOGLE_EXPORTS[mime]
            name += suffix
            url = f"{self.api_base}/files/{file_id}/export?" + _query(mimeType=export_mime)
        elif mime.startswith("application/vnd.google-apps."):
            return RemoteFailure(file_id, f"type Google non exportable en texte : {mime}")
        else:
            url = f"{self.api_base}/files/{file_id}?" + _query(alt="media", supportsAllDrives="true")
        if not is_supported(name):
            return RemoteFailure(file_id, f"format non pris en charge : {name!r}")
        try:
            return RemoteDocument(ref=file_id, name=f"{prefix}{name}", data=self.http.request(url, auth))
        except ConnectorError as exc:
            return RemoteFailure(file_id, str(exc))


def _without_urls(value: Any) -> Any:
    """Retire les champs ``*_url`` (liens signés qui changent à chaque appel : fausses versions)."""
    if isinstance(value, dict):
        return {k: _without_urls(v) for k, v in value.items() if not str(k).endswith("_url")}
    if isinstance(value, list):
        return [_without_urls(v) for v in value]
    return value


class PennylaneConnector(Connector):
    """Importe les factures de la comptabilité Pennylane (une pièce JSON par facture). ``origin_ref``
    = ``<ressource>/<id>`` : une facture modifiée côté Pennylane donne une nouvelle version."""

    name = "pennylane"
    RESOURCES = ("customer_invoices", "supplier_invoices")

    def __init__(
        self,
        resources: list[str] | None = None,
        *,
        environ: Mapping[str, str] | None = None,
        api_base: str = PENNYLANE_API,
        http: HttpClient | None = None,
        page_limit: int = 100,
        max_pages: int = 500,
    ) -> None:
        self.resources = list(resources or self.RESOURCES)
        unknown = [r for r in self.resources if r not in self.RESOURCES]
        if unknown:
            raise ValueError(f"ressource Pennylane inconnue : {', '.join(unknown)} (acceptées : {', '.join(self.RESOURCES)})")
        self.api_base = _check_base_url(api_base)
        self.http = http or HttpClient()
        self.page_limit = page_limit
        self.max_pages = max_pages
        self._environ = os.environ if environ is None else environ

    def fetch(self) -> Iterator[RemoteDocument | RemoteFailure]:
        key = self._environ.get(PENNYLANE_KEY_ENV, "")
        if not key:
            raise ConnectorError(f"clé API absente : variable {PENNYLANE_KEY_ENV}")
        auth = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
        for resource in self.resources:
            cursor = None
            for _ in range(self.max_pages):
                page = self.http.get_json(
                    f"{self.api_base}/{resource}?" + _query(limit=self.page_limit, cursor=cursor), auth)
                for item in page.get("items", []):
                    yield self._document(resource, item)
                nxt = page.get("next_cursor")
                if not page.get("has_more") or not nxt or nxt == cursor:
                    break
                cursor = nxt
            else:
                yield RemoteFailure(resource, f"pagination interrompue après {self.max_pages} pages")

    @staticmethod
    def _document(resource: str, item: dict) -> RemoteDocument | RemoteFailure:
        if "id" not in item:
            return RemoteFailure(resource, "élément sans identifiant")
        label = re.sub(r"[^\w.-]", "_", str(item.get("invoice_number") or item["id"]))
        body = json.dumps(_without_urls(item), ensure_ascii=False, sort_keys=True, indent=2)
        return RemoteDocument(
            ref=f"{resource}/{item['id']}", name=f"{resource}/{label}.json", data=body.encode("utf-8"))


_FACTORIES: dict[str, Callable[..., Connector]] = {
    GoogleDriveConnector.name: lambda folder_id, resources: GoogleDriveConnector(folder_id or ""),
    PennylaneConnector.name: lambda folder_id, resources: PennylaneConnector(resources),
}


def build_api_connector(
    name: str, *, folder_id: str | None = None, resources: list[str] | None = None
) -> Connector:
    """Connecteur API désigné par son nom (CLI). Nom inconnu : ValueError listant les valides."""
    try:
        factory = _FACTORIES[name]
    except KeyError:
        raise ValueError(
            f"connecteur API inconnu : {name!r} (disponibles : {', '.join(_FACTORIES)} ; "
            "ou --from-dir pour un dossier d'export)"
        ) from None
    return factory(folder_id, resources)
