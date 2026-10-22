"""orso-model-policy — politique de modèle opposable par client (KAN-127).

Vit à la marge du moteur, par les surfaces génériques de plugin uniquement :

* ``llm_execution`` (middleware) : plafond atteint => la requête n'est PAS envoyée au fournisseur,
  le client reçoit une réponse portant le code ``MODEL_POLICY_CAP_BLOCKED`` (blocage).
* ``post_api_request`` : coût de chaque appel cumulé dans le registre du mois ; passage du seuil
  d'alerte puis du plafond tracé (``MODEL_POLICY_CAP_ALERT`` / ``MODEL_POLICY_CAP_BLOCKED``).
* ``pre_api_request`` / ``api_request_error`` : indisponibilité du primaire et bascule sur le frugal de
  secours (``MODEL_POLICY_FALLBACK_ACTIVATED``) tracées ; écarts de route tracés.
* ``transform_llm_output`` : le client est informé (alerte de consommation, bascule de modèle).

La bascule elle-même reste portée par ``fallback_model`` (config Hermes) ; ce plugin l'observe et
l'annonce, il ne la réimplémente pas.
"""

from __future__ import annotations

import logging
import time
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional

from hermes_constants import get_hermes_home

from . import policy as pol
from .ledger import Ledger

logger = logging.getLogger(__name__)

_PLUGIN_DIR = Path(__file__).resolve().parent
_USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "reasoning_tokens")


def _call_cost_usd(model: str, provider: str, base_url: str, usage: Optional[Dict[str, Any]]) -> Optional[float]:
    """Coût estimé d'un appel via le barème du moteur ; None si le barème est inconnu."""
    if not usage:
        return 0.0
    from agent.usage_pricing import CanonicalUsage, estimate_usage_cost

    allowed = {f.name for f in fields(CanonicalUsage)} & set(_USAGE_FIELDS)
    canonical = CanonicalUsage(**{k: int(usage.get(k) or 0) for k in allowed})
    result = estimate_usage_cost(model, canonical, provider=provider, base_url=base_url)
    return None if result.amount_usd is None else float(result.amount_usd)


def _blocked_response(model: str, text: str) -> SimpleNamespace:
    """Réponse de type chat-completions sans appel réseau (forme lue par ChatCompletionsTransport)."""
    message = SimpleNamespace(
        role="assistant", content=text, tool_calls=None, reasoning=None, reasoning_content=None,
        reasoning_details=None, refusal=None,
    )
    return SimpleNamespace(
        id="orso-model-policy-block", model=model, created=int(time.time()), usage=None,
        choices=[SimpleNamespace(index=0, finish_reason="stop", message=message)],
    )


class PolicyRuntime:
    def __init__(self, policy: pol.ModelPolicy, ledger: Ledger):
        self.policy = policy
        self.ledger = ledger
        self._fallback_sessions: Dict[str, str] = {}
        self._fallback_notified: set = set()

    def verdict(self) -> pol.CapVerdict:
        return pol.evaluate_cap(self.policy, self.ledger.client_id, self.ledger.spent_eur())

    # -- observateurs -------------------------------------------------------------------------
    def pre_api_request(self, *, model: str = "", provider: str = "", base_url: str = "",
                        session_id: str = "", api_mode: str = "", **_: Any) -> None:
        p = self.policy
        if model == p.primary_model:
            self._fallback_sessions.pop(session_id, None)
            self._fallback_notified.discard(session_id)
        elif model == p.fallback_model and self._fallback_sessions.get(session_id) != model:
            self._fallback_sessions[session_id] = model
            self.ledger.record_event(
                pol.CODE_FALLBACK, session_id=session_id, primary=p.primary_model, fallback=model,
            )
            logger.warning("%s primary=%s fallback=%s", pol.CODE_FALLBACK, p.primary_model, model)
        route_ok = (
            (provider or "").lower() == p.required_provider
            and pol.model_allowed(p, model)
            and not (p.forbid_local and pol.is_local_route(provider, base_url))
        )
        if not route_ok and self.ledger.first_time(f"route_violation:{provider}:{model}"):
            self.ledger.record_event(pol.CODE_ROUTE_VIOLATION, provider=provider, model=model, api_mode=api_mode)
            logger.warning("%s provider=%s model=%s", pol.CODE_ROUTE_VIOLATION, provider, model)

    def api_request_error(self, *, model: str = "", status_code: Any = None, reason: Any = None,
                          session_id: str = "", **_: Any) -> None:
        if model == self.policy.primary_model:
            self.ledger.record_event(
                pol.CODE_PRIMARY_ERROR, session_id=session_id, model=model, status_code=status_code, reason=str(reason),
            )

    def post_api_request(self, *, model: str = "", provider: str = "", base_url: str = "",
                         usage: Optional[Dict[str, Any]] = None, **_: Any) -> None:
        cost = _call_cost_usd(model, provider, base_url, usage)
        if cost is None:
            if self.ledger.first_time(f"cost_unknown:{model}"):
                self.ledger.record_event(pol.CODE_COST_UNKNOWN, model=model, provider=provider)
            cost = 0.0
        spent = self.ledger.record_usage(
            provider=provider, model=model, cost_usd=cost, usd_to_eur=self.policy.usd_to_eur,
            tokens=int((usage or {}).get("total_tokens") or 0),
        )
        verdict = pol.evaluate_cap(self.policy, self.ledger.client_id, spent)
        if verdict.code and self.ledger.first_time(f"event:{verdict.code}"):
            self.ledger.record_event(
                verdict.code, spent_eur=round(verdict.spent_eur, 4), cap_eur=verdict.cap_eur, ratio=round(verdict.ratio, 4),
            )
            logger.warning("%s spent=%.4f cap=%.2f", verdict.code, verdict.spent_eur, verdict.cap_eur)

    # -- effets -------------------------------------------------------------------------------
    def llm_execution(self, *, request: Any = None, next_call: Any = None, api_mode: str = "",
                      model: str = "", session_id: str = "", **_: Any) -> Any:
        verdict = self.verdict()
        if verdict.status != pol.CAP_BLOCKED:
            return next_call(request)
        self.ledger.record_event(
            pol.CODE_CAP_BLOCKED, surface="llm_execution", session_id=session_id, model=model,
            spent_eur=round(verdict.spent_eur, 4), cap_eur=verdict.cap_eur, request_sent=False,
        )
        if api_mode != "chat_completions":
            # Tout cloud via OpenRouter => chat_completions ; autre mode = écart de route déjà tracé.
            logger.error("%s non bloquable en api_mode=%s : requête laissée passer", pol.CODE_CAP_BLOCKED, api_mode)
            return next_call(request)
        return _blocked_response(model, pol.blocked_message(verdict))

    def transform_llm_output(self, *, response_text: str = "", session_id: str = "", **_: Any) -> Optional[str]:
        notices = []
        if session_id in self._fallback_sessions and session_id not in self._fallback_notified:
            self._fallback_notified.add(session_id)
            notices.append(pol.fallback_message(self.policy.primary_model, self._fallback_sessions[session_id]))
            self.ledger.record_event(pol.CODE_CLIENT_INFORMED, about=pol.CODE_FALLBACK, session_id=session_id)
        verdict = self.verdict()
        if verdict.status == pol.CAP_ALERT and self.ledger.first_time("alert_notified"):
            notices.append(pol.alert_message(verdict))
            self.ledger.record_event(pol.CODE_CLIENT_INFORMED, about=pol.CODE_CAP_ALERT, session_id=session_id)
        if not notices:
            return None
        return (response_text or "").rstrip() + "\n\n" + "\n".join(notices)


def build_runtime() -> Optional[PolicyRuntime]:
    import os

    home = get_hermes_home()
    path = pol.resolve_policy_path(home, _PLUGIN_DIR)
    if path is None:
        logger.error("MODEL_POLICY_NOT_LOADED: aucune %s (profil, /app/config, dépôt)", pol.DEFAULT_POLICY_FILENAME)
        return None
    policy = pol.load_policy(path)
    return PolicyRuntime(policy, Ledger(home / "orso_model_policy", pol.client_id_from_env(os.environ)))


def register(ctx) -> None:
    try:
        runtime = build_runtime()
    except pol.PolicyError as exc:
        logger.error("MODEL_POLICY_NOT_LOADED: %s", exc)
        return
    if runtime is None:
        return
    ctx.register_hook("pre_api_request", runtime.pre_api_request)
    ctx.register_hook("api_request_error", runtime.api_request_error)
    ctx.register_hook("post_api_request", runtime.post_api_request)
    ctx.register_hook("transform_llm_output", runtime.transform_llm_output)
    ctx.register_middleware("llm_execution", runtime.llm_execution)
