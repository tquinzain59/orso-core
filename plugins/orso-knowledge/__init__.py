"""orso-knowledge — ingestion documentaire par client, versionnée, avec citation obligatoire.

Outil ``knowledge_search`` (lecture seule, client = ``ORSO_CLIENT_ID``, jamais un argument du modèle),
hooks de citation bloquante (``pre_llm_call`` / ``transform_llm_output``) et CLI ``hermes knowledge``
(ingestion, import connecteur, historique, retrait). Le moteur n'est pas modifié.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List

from .citations import block_answer
from .connectors import Connector, ConnectorError, DirectoryConnector, import_from
from .connectors_api import build_api_connector
from .store import (
    KnowledgeStore, TenantIsolationError, TenantRequiredError, UnknownDocumentError)

logger = logging.getLogger(__name__)

_TOOL_NAME = "knowledge_search"

SEARCH_SCHEMA = {
    "name": _TOOL_NAME,
    "description": (
        "Recherche dans les documents du client (versions à jour uniquement). Toute réponse qui "
        "s'appuie sur un passage DOIT recopier sa citation exacte, champ `citation` (ex. "
        "[Source: contrat.md, v2, §3]). Sans passage trouvé, ne rien affirmer à partir d'un document."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Mots-clés ou question."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
        },
        "required": ["query"],
    },
}

# Citations retrouvées pendant le tour courant (obligation de citer) et depuis le début de la session
# (une citation d'un tour précédent reste valide, une citation inventée non), par session. Verrou :
# les outils tournent en parallèle. Enregistrées par le handler lui-même, pas par un hook observateur.
_retrieved: Dict[str, List[str]] = {}
_known: Dict[str, set] = {}
_MAX_SESSIONS = 256
_lock = threading.Lock()


def _check_available() -> bool:
    try:
        return KnowledgeStore().has_active_documents()
    except (TenantRequiredError, TenantIsolationError, ValueError):
        return False


def _handle_search(args: Dict[str, Any], session_id: str | None = None, **_: Any) -> str:
    try:
        passages = KnowledgeStore().search(args.get("query", ""), int(args.get("limit") or 5))
    except (TenantRequiredError, TenantIsolationError, ValueError) as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    if not passages:
        return json.dumps(
            {"passages": [], "note": "Aucun passage trouvé : ne rien affirmer à partir d'un document."},
            ensure_ascii=False,
        )
    _remember(session_id or "", [p.citation for p in passages])
    return json.dumps(
        {"passages": [
            {"citation": p.citation, "text": p.text, "document": p.title, "version": p.version,
             "origin_connector": p.origin_connector, "origin_ref": p.origin_ref}
            for p in passages
        ]},
        ensure_ascii=False,
    )


def _remember(session_id: str, citations: List[str]) -> None:
    with _lock:
        _retrieved.setdefault(session_id, []).extend(citations)
        known = _known.setdefault(session_id, set())
        known.update(citations)
        while len(_known) > _MAX_SESSIONS:
            oldest = next(iter(_known))
            _known.pop(oldest)
            _retrieved.pop(oldest, None)


def _on_pre_llm_call(session_id: str = "", **_: Any) -> None:
    with _lock:
        _retrieved.pop(session_id or "", None)


def _on_transform_llm_output(response_text: str = "", session_id: str = "", **_: Any) -> str | None:
    """Remplace par un refus toute réponse qui s'appuie sur des passages retrouvés sans citer de
    source valide, ou qui cite une source inventée. Réponse conforme ou sans document : ``None``."""
    with _lock:
        turn = _retrieved.pop(session_id or "", [])
        known = set(_known.get(session_id or "", ()))
    if not isinstance(response_text, str):
        return None
    return block_answer(response_text, turn, known)


def _setup_cli(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tenant", help="client (défaut : ORSO_CLIENT_ID)")
    parser.add_argument("--root", help="racine de stockage (défaut : <HERMES_HOME>/knowledge)")
    sub = parser.add_subparsers(dest="knowledge_cmd", required=True)
    p = sub.add_parser("ingest", help="ingérer un fichier déposé")
    p.add_argument("file")
    p = sub.add_parser("import", help="importer depuis un service connecté (API) ou un dossier d'export")
    p.add_argument("--connector", required=True, help="google-drive, pennylane (API), ou nom d'origine d'un dossier")
    p.add_argument("--from-dir", help="dossier d'export local (sans accès API)")
    p.add_argument("--folder-id", help="google-drive : identifiant du dossier Drive à importer")
    p.add_argument("--resource", action="append", help="pennylane : customer_invoices, supplier_invoices (répétable)")
    p = sub.add_parser("search", help="rechercher des passages")
    p.add_argument("query")
    sub.add_parser("list", help="lister les documents")
    p = sub.add_parser("history", help="historique des versions")
    p.add_argument("doc_key")
    p = sub.add_parser("retire", help="retirer un document de l'index")
    p.add_argument("doc_key")


def _run_cli(args: argparse.Namespace) -> int:
    try:
        return _dispatch_cli(args)
    except (TenantRequiredError, TenantIsolationError, UnknownDocumentError, ConnectorError, ValueError, OSError) as exc:
        print(f"erreur : {exc}", file=sys.stderr)
        return 1


def _build_connector(args: argparse.Namespace) -> Connector:
    """``--from-dir`` : dossier d'export local. Sinon : connecteur API, identifiants lus dans
    l'environnement du conteneur (jamais en argument)."""
    if args.from_dir:
        return DirectoryConnector(args.connector, args.from_dir)
    return build_api_connector(args.connector, folder_id=args.folder_id, resources=args.resource)


def _dispatch_cli(args: argparse.Namespace) -> int:
    store = KnowledgeStore(args.root, args.tenant)
    cmd = args.knowledge_cmd
    if cmd == "ingest":
        path = Path(args.file)
        out: Any = store.ingest(path.name, path.read_bytes(), origin_ref=str(path))
    elif cmd == "import":
        out = import_from(store, _build_connector(args))
    elif cmd == "search":
        out = [{"citation": p.citation, "text": p.text, "origin_connector": p.origin_connector}
               for p in store.search(args.query)]
    elif cmd == "list":
        out = store.documents()
    elif cmd == "history":
        out = store.history(args.doc_key)
    else:
        store.retire(args.doc_key)
        out = {"retired": args.doc_key}
    print(json.dumps(out, default=lambda o: o.__dict__, ensure_ascii=False, indent=2))
    return 0


def register(ctx) -> None:
    ctx.register_tool(
        name=_TOOL_NAME, toolset="knowledge", schema=SEARCH_SCHEMA, handler=_handle_search,
        check_fn=_check_available, emoji="📚",
    )
    ctx.register_hook("pre_llm_call", _on_pre_llm_call)
    ctx.register_hook("transform_llm_output", _on_transform_llm_output)
    ctx.register_cli_command(
        name="knowledge", help="Documents du client : ingestion, import, versions, retrait",
        setup_fn=_setup_cli, handler_fn=_run_cli,
    )
