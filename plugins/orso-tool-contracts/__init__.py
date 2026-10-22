"""orso-tool-contracts — garde de contrat d'outils à la marge (KAN-131).

Hook `pre_tool_call` uniquement : aucun fichier du moteur n'est modifié. Il n'agit que sur les
sessions CLIENTES liées par `hermes_cli.web_routers.tool_caller.bind_tool_caller` (routeur client) ;
CLI, gateway et cron, non liés, ne sont pas affectés. Pour une session liée, la garde est
fail-closed : une erreur interne de la garde bloque l'appel au lieu de le laisser passer
(un échec de hook est sinon ignoré par le moteur). Activation : `plugins.enabled: [orso-tool-contracts]`.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from hermes_cli.web_routers.tool_caller import get_tool_caller

from . import guard
from .contracts import load_catalog

logger = logging.getLogger(__name__)


def _on_pre_tool_call(tool_name: str = "", args: Any = None, session_id: str = "", **_: Any) -> Optional[Dict[str, str]]:
    caller = get_tool_caller(session_id) if session_id else None
    if caller is None:
        return None
    try:
        decision = guard.decide(load_catalog(), tool_name, caller.role, caller.client_id, session_id)
    except Exception as exc:
        logger.exception("orso-tool-contracts: erreur de garde, appel bloqué (fail-closed)")
        return {"action": "block", "message": f"GUARD_ERROR : contrôle de contrat impossible ({type(exc).__name__}), appel bloqué."}
    if decision.allowed:
        return None
    return {"action": "block", "message": f"{decision.code} : {decision.message}"}


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
