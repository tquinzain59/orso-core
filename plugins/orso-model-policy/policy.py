"""Politique de modèle Orso (KAN-127) : chargement, validation et évaluation du plafond.

Module pur (aucune dépendance au moteur) : le plugin et le script de contrôle s'y appuient.
Les codes ci-dessous sont les codes opposables observés dans les traces et les sorties.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Mapping, Optional
from urllib.parse import urlparse

import yaml

CODE_CAP_ALERT = "MODEL_POLICY_CAP_ALERT"
CODE_CAP_BLOCKED = "MODEL_POLICY_CAP_BLOCKED"
CODE_FALLBACK = "MODEL_POLICY_FALLBACK_ACTIVATED"
CODE_PRIMARY_ERROR = "MODEL_POLICY_PRIMARY_UNAVAILABLE"
CODE_ROUTE_VIOLATION = "MODEL_POLICY_ROUTE_VIOLATION"
CODE_COST_UNKNOWN = "MODEL_POLICY_COST_UNKNOWN"
CODE_CLIENT_INFORMED = "MODEL_POLICY_CLIENT_INFORMED"

CAP_OK, CAP_ALERT, CAP_BLOCKED = "ok", "alert", "blocked"

_LOCAL_PROVIDERS = frozenset({"ollama", "lmstudio", "lm-studio", "llamacpp", "llama.cpp", "vllm", "local", "custom"})
_LOCAL_HOSTS = ("localhost", "127.", "0.0.0.0", "::1", "host.docker.internal")  # détection de route, pas un bind

DEFAULT_POLICY_FILENAME = "orso_model_policy.yaml"


class PolicyError(ValueError):
    """Politique absente ou invalide : le plugin échoue fermé sur la validation, jamais en silence."""


@dataclass(frozen=True)
class ModelPolicy:
    required_provider: str
    forbid_local: bool
    allowed_prefixes: tuple
    primary_provider: str
    primary_model: str
    fallback_provider: str
    fallback_model: str
    default_monthly_eur: float
    alert_ratio: float
    client_caps: Mapping[str, float] = field(default_factory=dict)
    usd_to_eur: float = 1.0
    decided_on: str = ""
    evaluation_candidates: tuple = ()

    def monthly_cap_eur(self, client_id: str) -> float:
        return float(self.client_caps.get(client_id, self.default_monthly_eur))


@dataclass(frozen=True)
class CapVerdict:
    status: str
    code: Optional[str]
    spent_eur: float
    cap_eur: float
    ratio: float


def month_key(now: Optional[datetime] = None) -> str:
    """Mois civil UTC `YYYY-MM` : la fenêtre du plafond."""
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m")


def is_local_route(provider: str, base_url: str = "") -> bool:
    if (provider or "").strip().lower() in _LOCAL_PROVIDERS:
        return True
    host = (urlparse(base_url).hostname or "") if base_url else ""
    return any(host.startswith(h) for h in _LOCAL_HOSTS) if host else False


def parse_policy(raw: Mapping[str, Any]) -> ModelPolicy:
    try:
        routing, cap = raw["routing"], raw["cost_cap"]
        policy = ModelPolicy(
            required_provider=str(routing["required_provider"]).lower(),
            forbid_local=bool(routing.get("forbid_local", True)),
            allowed_prefixes=tuple(routing["allowed_model_prefixes"]),
            primary_provider=str(routing["primary"]["provider"]).lower(),
            primary_model=str(routing["primary"]["model"]),
            fallback_provider=str(routing["fallback"]["provider"]).lower(),
            fallback_model=str(routing["fallback"]["model"]),
            default_monthly_eur=float(cap["default_monthly_eur"]),
            alert_ratio=float(cap["alert_ratio"]),
            client_caps={str(k): float(v["monthly_eur"]) for k, v in (cap.get("clients") or {}).items()},
            usd_to_eur=float(cap.get("usd_to_eur", 1.0)),
            decided_on=str(raw.get("decided_on", "")),
            evaluation_candidates=tuple((raw.get("evaluation") or {}).get("candidates") or ()),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PolicyError(f"politique de modèle illisible : {exc!r}") from exc
    problems = validate_policy(policy)
    if problems:
        raise PolicyError("politique de modèle invalide : " + " ; ".join(problems))
    return policy


def load_policy(path: Path) -> ModelPolicy:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PolicyError(f"politique de modèle illisible ({path}) : {exc}") from exc
    if not isinstance(raw, dict):
        raise PolicyError(f"politique de modèle vide ou mal formée : {path}")
    return parse_policy(raw)


def model_allowed(policy: ModelPolicy, model: str) -> bool:
    return str(model or "").startswith(policy.allowed_prefixes)


def validate_policy(policy: ModelPolicy) -> List[str]:
    """Cohérence interne : primaire et secours conformes, secours distinct, plafonds sensés."""
    problems: List[str] = []
    for role, provider, model in (
        ("primaire", policy.primary_provider, policy.primary_model),
        ("secours", policy.fallback_provider, policy.fallback_model),
    ):
        if provider != policy.required_provider:
            problems.append(f"{role}: fournisseur {provider!r} != {policy.required_provider!r}")
        if policy.forbid_local and is_local_route(provider):
            problems.append(f"{role}: route locale interdite ({provider!r})")
        if not model_allowed(policy, model):
            problems.append(f"{role}: modèle {model!r} hors préfixes autorisés {list(policy.allowed_prefixes)}")
    if policy.primary_model == policy.fallback_model:
        problems.append("le modèle de secours doit différer du primaire")
    if policy.default_monthly_eur <= 0 or any(v <= 0 for v in policy.client_caps.values()):
        problems.append("les plafonds mensuels doivent être strictement positifs")
    if not 0 < policy.alert_ratio < 1:
        problems.append("alert_ratio doit être dans ]0, 1[")
    if policy.usd_to_eur <= 0:
        problems.append("usd_to_eur doit être > 0")
    return problems


def validate_hermes_config(policy: ModelPolicy, cfg: Mapping[str, Any]) -> List[str]:
    """Conformité d'une config Hermes (`model` + `fallback_model`) à la politique."""
    problems: List[str] = []
    model_cfg = cfg.get("model")
    if isinstance(model_cfg, dict):
        provider, model = str(model_cfg.get("provider", "")).lower(), str(model_cfg.get("default", ""))
        base_url = str(model_cfg.get("base_url", "") or "")
    else:
        provider, model, base_url = "", str(model_cfg or ""), ""
    fb = cfg.get("fallback_model") if isinstance(cfg.get("fallback_model"), dict) else {}
    for role, prov, mod, url in (
        ("model", provider, model, base_url),
        ("fallback_model", str(fb.get("provider", "")).lower(), str(fb.get("model", "")), str(fb.get("base_url", "") or "")),
    ):
        if not mod:
            problems.append(f"{role}: absent")
            continue
        if prov != policy.required_provider:
            problems.append(f"{role}: fournisseur {prov!r} != {policy.required_provider!r}")
        if policy.forbid_local and is_local_route(prov, url):
            problems.append(f"{role}: route locale interdite")
        if not model_allowed(policy, mod):
            problems.append(f"{role}: modèle {mod!r} hors politique (frugaux deepseek/ et mistralai/ uniquement)")
    if fb.get("model") and str(fb.get("model")) == model:
        problems.append("fallback_model identique au modèle primaire")
    return problems


def evaluate_cap(policy: ModelPolicy, client_id: str, spent_eur: float) -> CapVerdict:
    cap = policy.monthly_cap_eur(client_id)
    ratio = spent_eur / cap if cap else 1.0
    if ratio >= 1.0:
        return CapVerdict(CAP_BLOCKED, CODE_CAP_BLOCKED, spent_eur, cap, ratio)
    if ratio >= policy.alert_ratio:
        return CapVerdict(CAP_ALERT, CODE_CAP_ALERT, spent_eur, cap, ratio)
    return CapVerdict(CAP_OK, None, spent_eur, cap, ratio)


def default_policy_paths(hermes_home: Path, plugin_dir: Path) -> List[Path]:
    """Ordre de recherche : profil actif, volume de config monté en prod, copie du dépôt."""
    return [
        hermes_home / DEFAULT_POLICY_FILENAME,
        Path("/app/config") / DEFAULT_POLICY_FILENAME,
        plugin_dir.parent.parent / "config" / DEFAULT_POLICY_FILENAME,
    ]


def resolve_policy_path(hermes_home: Path, plugin_dir: Path) -> Optional[Path]:
    return next((p for p in default_policy_paths(hermes_home, plugin_dir) if p.is_file()), None)


def client_id_from_env(env: Mapping[str, str]) -> str:
    return (env.get("ORSO_CLIENT_ID") or env.get("ORSO_CLIENT_SLUG") or "default").strip() or "default"


def blocked_message(verdict: CapVerdict) -> str:
    return (
        f"[{CODE_CAP_BLOCKED}] Le plafond mensuel de consommation de modèle est atteint "
        f"({verdict.spent_eur:.2f} € sur {verdict.cap_eur:.2f} €). Les requêtes sont suspendues "
        f"jusqu'au prochain mois civil (UTC) ou à un relèvement du plafond par votre administrateur."
    )


def alert_message(verdict: CapVerdict) -> str:
    return (
        f"[{CODE_CAP_ALERT}] Alerte consommation : {verdict.spent_eur:.2f} € consommés sur un plafond "
        f"mensuel de {verdict.cap_eur:.2f} € ({verdict.ratio:.0%}). Au-delà, les requêtes seront bloquées."
    )


def fallback_message(primary: str, fallback: str) -> str:
    return (
        f"[{CODE_FALLBACK}] Information : le modèle principal ({primary}) est momentanément indisponible ; "
        f"cette réponse a été produite par le modèle de secours ({fallback})."
    )

