"""orso-knowledge — ingestion documentaire par client, versionnée, avec citation obligatoire.

Outil ``knowledge_search`` (lecture seule, client = ``ORSO_CLIENT_ID``, jamais un argument du modèle),
hooks de citation (``post_tool_call`` / ``transform_llm_output``) et CLI ``hermes knowledge``
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

from .citations import flag_answer
from .connectors import DirectoryConnector, import_from
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

# Citations retrouvées pendant le tour courant, par session. Verrou : les hooks tournent en parallèle.
_retrieved: Dict[str, List[str]] = {}
_lock = threading.Lock()


def _check_available() -> bool:
    try:
        return KnowledgeStore().has_active_documents()
    except (TenantRequiredError, TenantIsolationError, ValueError):
        return False


def _handle_search(args: Dict[str, Any], **_: Any) -> str:
    try:
        passages = KnowledgeStore().search(args.get("query", ""), int(args.get("limit") or 5))
    except (TenantRequiredError, TenantIsolationError, ValueError) as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    if not passages:
        return json.dumps(
            {"passages": [], "note": "Aucun passage trouvé : ne rien affirmer à partir d'un document."},
            ensure_ascii=False,
        )
    return json.dumps(
        {"passages": [
            {"citation": p.citation, "text": p.text, "document": p.title, "version": p.version,
             "origin_connector": p.origin_connector, "origin_ref": p.origin_ref}
            for p in passages
        ]},
        ensure_ascii=False,
    )


def _on_pre_llm_call(session_id: str = "", **_: Any) -> None:
    with _lock:
        _retrieved.pop(session_id, None)


def _on_post_tool_call(tool_name: str = "", result: Any = None, session_id: str = "", **_: Any) -> None:
    if tool_name != _TOOL_NAME or not isinstance(result, str):
        return
    try:
        passages = json.loads(result).get("passages", [])
    except (ValueError, AttributeError):
        return
    with _lock:
        _retrieved.setdefault(session_id, []).extend(p["citation"] for p in passages if "citation" in p)


def _on_transform_llm_output(response_text: str = "", session_id: str = "", **_: Any) -> str | None:
    """Signale (sans la supprimer) une réponse qui s'appuie sur des passages sans citer de source."""
    with _lock:
        citations = _retrieved.pop(session_id, [])
    if not citations or not isinstance(response_text, str):
        return None
    return flag_answer(response_text, citations)


def _setup_cli(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tenant", help="client (défaut : ORSO_CLIENT_ID)")
    parser.add_argument("--root", help="racine de stockage (défaut : <HERMES_HOME>/knowledge)")
    sub = parser.add_subparsers(dest="knowledge_cmd", required=True)
    p = sub.add_parser("ingest", help="ingérer un fichier déposé")
    p.add_argument("file")
    p = sub.add_parser("import", help="importer le dossier d'export d'un service connecté")
    p.add_argument("--connector", required=True, help="nom du connecteur d'origine (google-drive, pennylane...)")
    p.add_argument("--from-dir", required=True)
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
    except (TenantRequiredError, TenantIsolationError, UnknownDocumentError, ValueError, OSError) as exc:
        print(f"erreur : {exc}", file=sys.stderr)
        return 1


def _dispatch_cli(args: argparse.Namespace) -> int:
    store = KnowledgeStore(args.root, args.tenant)
    cmd = args.knowledge_cmd
    if cmd == "ingest":
        path = Path(args.file)
        out: Any = store.ingest(path.name, path.read_bytes(), origin_ref=str(path))
    elif cmd == "import":
        out = import_from(store, DirectoryConnector(args.connector, args.from_dir))
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
    ctx.register_hook("post_tool_call", _on_post_tool_call)
    ctx.register_hook("transform_llm_output", _on_transform_llm_output)
    ctx.register_cli_command(
        name="knowledge", help="Documents du client : ingestion, import, versions, retrait",
        setup_fn=_setup_cli, handler_fn=_run_cli,
    )
