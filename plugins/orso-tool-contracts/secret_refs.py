"""Désignation des secrets par EMPLACEMENT et authentification des outils externes (KAN-131 CA2/CA5).

Un secret n'est jamais une valeur dans le catalogue ni dans une config : c'est une référence
`env:NOM` (variable d'environnement, résolue via `agent.secret_scope`) ou `file:chemin` (relatif
à `HERMES_HOME`, ex. `mcp-tokens/notion.json` écrit par le flux OAuth de Hermès). Ce module ne
lit jamais une valeur pour la renvoyer ni la journaliser : il répond seulement « provisionné ou non ».
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, List, Optional, Tuple

_ENV_REF = re.compile(r"^env:[A-Za-z_][A-Za-z0-9_]*$")
_FILE_REF = re.compile(r"^file:[A-Za-z0-9._/-]+$")
# Interpolation `${VAR}` / `${env:VAR}` déjà utilisée par la config MCP de Hermès : une référence, pas une valeur.
_INTERPOLATION = re.compile(r"^\$\{(env:)?[A-Za-z_][A-Za-z0-9_.-]*\}$")

_SECRET_KEY = re.compile(r"(token|secret|password|passwd|api[_-]?key|authorization|bearer|credential)", re.I)
# Formes de valeurs qui ressemblent à un secret même sous une clé anodine.
_SECRET_VALUE = re.compile(
    r"(^sk-[A-Za-z0-9_-]{16,}|^gh[pousr]_[A-Za-z0-9]{20,}|^xox[abp]-[A-Za-z0-9-]{10,}"
    r"|^eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.|^Bearer\s+[A-Za-z0-9._~+/=-]{12,})"
)

AUTH_TYPES_ACCEPTED = frozenset({"oauth", "bearer", "api_key", "header"})


class SecretRefError(ValueError):
    """La valeur n'est pas une référence d'emplacement valide (probable secret en clair)."""


@dataclass(frozen=True)
class AuthDecision:
    allowed: bool
    code: str  # OK | AUTH_REFUSED
    reason: str
    secret_ref: Optional[str] = None  # emplacement désigné, jamais la valeur


def _hermes_home() -> Path:
    from hermes_constants import get_hermes_home

    return Path(get_hermes_home())


def parse_secret_ref(ref: Any) -> Tuple[str, str]:
    """`("env", NOM)` ou `("file", chemin)` ; `SecretRefError` pour toute autre forme (message sans la valeur)."""
    if not isinstance(ref, str):
        raise SecretRefError("secret_ref absent : un emplacement `env:NOM` ou `file:chemin` est requis")
    if _ENV_REF.match(ref):
        return "env", ref[4:]
    if _FILE_REF.match(ref):
        rel = ref[5:]
        if rel.startswith("/") or ".." in Path(rel).parts:
            raise SecretRefError("emplacement `file:` hors de HERMES_HOME refusé")
        return "file", rel
    raise SecretRefError("valeur refusée : ce n'est pas un emplacement `env:NOM` ni `file:chemin` (secret en clair ?)")


def is_secret_provisioned(ref: str) -> bool:
    """Vrai si l'emplacement désigné contient une valeur non vide (la valeur n'est pas exposée)."""
    kind, target = parse_secret_ref(ref)
    if kind == "env":
        from agent.secret_scope import get_secret

        try:
            return bool((get_secret(target) or "").strip())
        except Exception:  # portée multi-profil active sans profil résolu : fail closed
            return False
    path = _hermes_home() / target
    return path.is_file() and path.stat().st_size > 0


def find_plaintext_secrets(node: Any, path: str = "") -> List[str]:
    """Chemins (jamais les valeurs) des champs qui portent un secret en clair.

    Un champ au nom sensible (token, secret, password, api_key, authorization…) est conforme
    s'il est vide ou s'il contient une référence (`env:`/`file:`/`${VAR}`) ; toute valeur de forme
    secrète (clé `sk-…`, jeton `ghp_…`, JWT, `Bearer …`) est signalée quelle que soit la clé.
    """
    found: List[str] = []
    for sub_path, key, value in _walk_strings(node, path):
        if not value.strip():
            continue
        is_reference = bool(_ENV_REF.match(value) or _FILE_REF.match(value) or _INTERPOLATION.match(value))
        if is_reference:
            continue
        if _SECRET_VALUE.search(value) or (_SECRET_KEY.search(key) and not _is_descriptive_key(key)):
            found.append(sub_path)
    return found


def _is_descriptive_key(key: str) -> bool:
    # `secret_ref`, `auth.type`… décrivent l'emplacement ou le mode, pas la valeur (la valeur de
    # `secret_ref` est validée par parse_secret_ref, pas ici).
    return key.lower() in {"secret_ref", "token_type", "token_url", "type"}


def _walk_strings(node: Any, path: str) -> Iterator[Tuple[str, str, str]]:
    if isinstance(node, dict):
        for k, v in node.items():
            sub = f"{path}.{k}" if path else str(k)
            if isinstance(v, str):
                yield sub, str(k), v
            else:
                yield from _walk_strings(v, sub)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            sub = f"{path}[{i}]"
            if isinstance(v, str):
                yield sub, path.rsplit(".", 1)[-1], v
            else:
                yield from _walk_strings(v, sub)


def check_external_auth(server: str, auth: Any) -> AuthDecision:
    """Décide si un outil externe (serveur MCP) peut être appelé : il doit s'authentifier ET son secret
    doit être désigné par emplacement et provisionné. `none`/absent = refusé (jamais d'outil anonyme)."""
    if not isinstance(auth, dict) or str(auth.get("type", "none")).lower() not in AUTH_TYPES_ACCEPTED:
        return AuthDecision(False, "AUTH_REFUSED", f"serveur externe '{server}' sans authentification : refusé")
    try:
        parse_secret_ref(auth.get("secret_ref"))
    except SecretRefError as exc:
        return AuthDecision(False, "AUTH_REFUSED", f"serveur externe '{server}' : {exc}")
    ref = str(auth["secret_ref"])
    if not is_secret_provisioned(ref):
        return AuthDecision(False, "AUTH_REFUSED", f"serveur externe '{server}' non authentifié : secret absent à l'emplacement {ref}", ref)
    return AuthDecision(True, "OK", f"serveur externe '{server}' authentifié (secret désigné par {ref})", ref)


def manifest_auth(manifest: dict, server: str) -> dict:
    """Déduit le bloc d'authentification d'un `optional-mcps/<serveur>/manifest.yaml` : le secret OAuth
    de Hermès vit dans `mcp-tokens/<serveur>.json` ; `none` reste `none`."""
    auth = manifest.get("auth") if isinstance(manifest, dict) else None
    kind = str((auth or {}).get("type", "none")).lower()
    if kind == "oauth":
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", server)
        return {"type": "oauth", "secret_ref": f"file:mcp-tokens/{safe}.json"}
    return {"type": kind}
