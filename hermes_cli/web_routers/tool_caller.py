"""Identité d'appelant (rôle + client) par session, pour la couche contrat d'outils (KAN-131).

Le routeur client (`client_ui`) lie le rôle Orso (superadmin/admin/user, cf.
`_resolve_user_system_role_and_job_title`) et le client à la session avant de lancer l'agent ;
le plugin `orso-tool-contracts` relit cette liaison dans son hook `pre_tool_call` via le
`session_id`. Ce module est volontairement hors du plugin : le plugin est chargé sous un nom de
paquet dynamique, alors que le routeur a besoin d'un point d'import stable. Aucun I/O, aucun
secret : uniquement un rôle et un identifiant de client.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

# Rangs alignés sur les rôles existants : admin = tout, utilisateur simple = sous-ensemble.
ROLE_RANK = {"user": 1, "admin": 2, "superadmin": 3}
DEFAULT_ROLE = "user"  # moindre privilège quand le rôle est absent ou inconnu

_MAX_BOUND_SESSIONS = 4096


@dataclass(frozen=True)
class ToolCaller:
    role: str
    client_id: str


_callers: "OrderedDict[str, ToolCaller]" = OrderedDict()
_lock = threading.Lock()


def normalize_role(role: object) -> str:
    """Rôle connu en minuscules, sinon `DEFAULT_ROLE` (jamais un rôle plus élevé par défaut)."""
    value = str(role or "").strip().lower()
    return value if value in ROLE_RANK else DEFAULT_ROLE


def bind_tool_caller(session_id: str, role: object, client_id: object) -> ToolCaller:
    """Lie (ou relie) une session à son appelant ; la plus ancienne liaison est évincée au-delà de la borne."""
    caller = ToolCaller(role=normalize_role(role), client_id=str(client_id or "").strip() or "default")
    with _lock:
        _callers[session_id] = caller
        _callers.move_to_end(session_id)
        while len(_callers) > _MAX_BOUND_SESSIONS:
            _callers.popitem(last=False)
    return caller


def get_tool_caller(session_id: str) -> Optional[ToolCaller]:
    """Appelant lié à la session, ou `None` (session non cliente : la couche contrat s'abstient)."""
    with _lock:
        return _callers.get(session_id)


def unbind_tool_caller(session_id: str) -> None:
    with _lock:
        _callers.pop(session_id, None)
