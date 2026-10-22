"""Décision d'appel (exposition, rôle, client, authentification externe, disponibilité) et trace (KAN-131 CA1-CA4).

`decide()` est pure vis-à-vis du moteur : elle lit le catalogue, le rôle/client liés à la session,
l'état du registre (lecture seule) et la config ; elle renvoie une `Decision` que le hook
`pre_tool_call` traduit en blocage. Toute décision négative est tracée (JSONL + log) : une
dégradation n'est jamais silencieuse. Les arguments d'outil ne sont jamais tracés (ils peuvent
contenir des données client ou des secrets).
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, FrozenSet, Optional

from hermes_cli.web_routers.tool_caller import ROLE_RANK

from .contracts import Catalog, Entry
from .secret_refs import check_external_auth

logger = logging.getLogger("orso.tool_contracts")
_trace_lock = threading.Lock()

TRACE_FILENAME = "tool_contracts.jsonl"


@dataclass(frozen=True)
class Decision:
    allowed: bool
    code: str  # OK | TOOL_NOT_EXPOSED | ROLE_FORBIDDEN | CLIENT_FORBIDDEN | AUTH_REFUSED | TOOL_UNAVAILABLE
    message: str = ""
    degraded: bool = False


def trace_path() -> Path:
    from hermes_constants import get_hermes_home

    return Path(get_hermes_home()) / "logs" / TRACE_FILENAME


def write_trace(event: str, **fields: Any) -> None:
    """Une ligne JSON par décision négative ; jamais d'arguments d'outil ni de valeur secrète."""
    record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": event, **fields}
    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    logger.warning("tool_contract %s", line)
    path = trace_path()
    with _trace_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def cut_tools() -> FrozenSet[str]:
    """Outils coupés par l'opérateur : `orso_tool_contracts.unavailable` dans config.yaml."""
    from hermes_cli.config import load_config

    section = (load_config() or {}).get("orso_tool_contracts") or {}
    return frozenset(str(n) for n in (section.get("unavailable") or ()))


def unavailable_reason(entry: Entry, cut: FrozenSet[str]) -> Optional[str]:
    """Raison d'indisponibilité, ou `None` si l'outil est utilisable."""
    if entry.name in cut or (entry.server and f"mcp__{entry.server}" in cut):
        return "outil coupé par l'opérateur"
    if entry.origin == "registry":
        from tools.registry import registry

        reg = registry.get_entry(entry.name)
        if reg is None:
            return "outil non enregistré dans ce déploiement"
        if reg.check_fn is not None:
            try:
                ok = bool(reg.check_fn())
            except Exception:
                ok = False
            if not ok:
                return "prérequis de l'outil non satisfaits (check_fn)"
    return None


def degradation_message(entry: Entry, reason: str, catalog: Catalog) -> str:
    fb = entry.fallback or {}
    parts = [f"Outil '{entry.name}' indisponible ({reason}) : mode dégradé, aucune action n'a été effectuée."]
    alt = fb.get("tool")
    if alt and catalog.resolve(alt) is not None:
        parts.append(f"Repli possible : utiliser '{alt}'.")
    if fb.get("text"):
        parts.append(str(fb["text"]))
    parts.append("Incident tracé (tool_contracts.jsonl).")
    return " ".join(parts)


def decide(catalog: Catalog, tool_name: str, role: str, client_id: str, session_id: str = "") -> Decision:
    ctx: Dict[str, Any] = {"tool": tool_name, "role": role, "client": client_id, "session": session_id}
    entry = catalog.resolve(tool_name)
    if entry is None:
        write_trace("TOOL_NOT_EXPOSED", **ctx)
        return Decision(False, "TOOL_NOT_EXPOSED", f"Outil '{tool_name}' non exposé : hors du catalogue métier (documents, messagerie, calcul).")
    if ROLE_RANK[role] < ROLE_RANK[entry.min_role]:
        write_trace("ROLE_FORBIDDEN", min_role=entry.min_role, **ctx)
        return Decision(False, "ROLE_FORBIDDEN", f"Outil '{tool_name}' réservé au rôle {entry.min_role} ou supérieur (rôle courant : {role}).")
    if entry.clients and "*" not in entry.clients and client_id not in entry.clients:
        write_trace("CLIENT_FORBIDDEN", **ctx)
        return Decision(False, "CLIENT_FORBIDDEN", f"Outil '{tool_name}' non autorisé pour ce client.")
    if entry.origin == "mcp_external":
        auth = check_external_auth(entry.server or "", entry.auth)
        if not auth.allowed:
            write_trace("AUTH_REFUSED", reason=auth.reason, **ctx)
            return Decision(False, "AUTH_REFUSED", f"Appel refusé : {auth.reason}.")
    reason = unavailable_reason(entry, cut_tools())
    if reason:
        write_trace("TOOL_UNAVAILABLE", reason=reason, version=entry.version, **ctx)
        return Decision(False, "TOOL_UNAVAILABLE", degradation_message(entry, reason, catalog), degraded=True)
    return Decision(True, "OK")
