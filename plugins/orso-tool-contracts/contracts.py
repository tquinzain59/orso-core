"""Catalogue exposé et contrats d'outils (KAN-131 CA1) : chargement, validation, résolution, dérive.

Le catalogue (`catalog.yaml`) est le sous-ensemble MÉTIER exposé au client. Un outil absent n'est
pas exposé ; un outil système n'y est jamais admis (`validate_catalog` le refuse).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from hermes_cli.web_routers.tool_caller import ROLE_RANK

from .secret_refs import SecretRefError, find_plaintext_secrets, parse_secret_ref

CATALOG_PATH = Path(__file__).with_name("catalog.yaml")
MCP_TOOL_PREFIX = "mcp__"  # tools/mcp_tool_schema.py::MCP_TOOL_NAME_PREFIX
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")

# Outils système : jamais exposables, même si quelqu'un les ajoutait au catalogue.
SYSTEM_TOOLS = frozenset({
    "terminal", "process_manage", "execute_code", "read_file", "write_file", "patch", "search_files",
    "cronjob_manage", "delegate_task", "computer_use", "browser_cdp", "browser_exec", "skill_manage",
    "memory", "setup_mcp", "manage_connections",
})
SYSTEM_TOOLSETS = frozenset({
    "terminal", "file", "code_execution", "cronjob", "delegation", "computer_use", "browser-cdp",
    "browser-use", "browser", "skills", "memory", "kanban", "homeassistant",
})


@dataclass(frozen=True)
class Entry:
    """Contrat résolu d'un outil exposé (natif, mcp_serve ou outil d'un serveur externe)."""

    name: str
    version: str
    category: str
    origin: str  # registry | mcp_serve | mcp_external
    min_role: str
    clients: tuple
    fallback: Dict[str, Any]
    server: Optional[str] = None  # serveur MCP pour origin == mcp_external
    auth: Optional[Dict[str, Any]] = None


@lru_cache(maxsize=4)
def _read(path: str, mtime_ns: int) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_catalog(path: Optional[Path] = None) -> "Catalog":
    p = Path(path or CATALOG_PATH)
    return Catalog(_read(str(p), p.stat().st_mtime_ns))


class Catalog:
    def __init__(self, raw: Dict[str, Any]):
        self.raw = raw
        self.version = str(raw.get("catalog_version", ""))
        self.dated = str(raw.get("dated", ""))
        self.categories = tuple(raw.get("categories") or ())
        self._tools: Dict[str, Dict[str, Any]] = {t["name"]: t for t in raw.get("tools") or [] if "name" in t}
        self.external_servers: Dict[str, Dict[str, Any]] = dict(raw.get("external_servers") or {})

    def tool_names(self) -> List[str]:
        return sorted(self._tools)

    def contract(self, name: str) -> Optional[Dict[str, Any]]:
        return self._tools.get(name)

    def resolve(self, tool_name: str) -> Optional[Entry]:
        """Entrée exposée pour ce nom d'outil, ou `None` (= non exposé)."""
        if tool_name in self._tools:
            t = self._tools[tool_name]
            return Entry(
                name=tool_name, version=str(t["version"]), category=t["category"], origin=t.get("origin", "registry"),
                min_role=t.get("min_role", "admin"), clients=tuple(t.get("clients") or ()), fallback=dict(t.get("fallback") or {}),
            )
        if tool_name.startswith(MCP_TOOL_PREFIX):
            server_key = tool_name[len(MCP_TOOL_PREFIX):].split("__", 1)[0]
            for server, cfg in self.external_servers.items():
                if re.sub(r"[^A-Za-z0-9_-]", "_", server) == server_key:
                    return Entry(
                        name=tool_name, version=str(cfg.get("version", self.version)), category=cfg["category"],
                        origin="mcp_external", min_role=cfg.get("min_role", "admin"), clients=tuple(cfg.get("clients") or ()),
                        fallback=dict(cfg.get("fallback") or {}), server=server, auth=cfg.get("auth"),
                    )
        return None


def validate_catalog(raw: Dict[str, Any]) -> List[str]:
    """Problèmes de forme du catalogue (liste vide = conforme). Ne lit aucune valeur secrète."""
    problems: List[str] = []
    categories = set(raw.get("categories") or ())
    if not _SEMVER.match(str(raw.get("catalog_version", ""))):
        problems.append("catalog_version doit être un semver X.Y.Z")
    if not raw.get("dated"):
        problems.append("catalogue non daté (`dated`)")
    seen = set()
    for tool in raw.get("tools") or []:
        name = str(tool.get("name", ""))
        where = f"outil '{name}'"
        if not name or name in seen:
            problems.append(f"{where} : nom absent ou en double")
        seen.add(name)
        if name in SYSTEM_TOOLS:
            problems.append(f"{where} : outil système, non exposable")
        if not _SEMVER.match(str(tool.get("version", ""))):
            problems.append(f"{where} : version semver absente")
        if tool.get("category") not in categories:
            problems.append(f"{where} : catégorie hors {sorted(categories)}")
        if tool.get("min_role") not in ROLE_RANK:
            problems.append(f"{where} : min_role hors {sorted(ROLE_RANK)}")
        for key in ("inputs", "outputs", "errors", "fallback"):
            if key not in tool:
                problems.append(f"{where} : contrat incomplet, `{key}` manquant")
    for server, cfg in (raw.get("external_servers") or {}).items():
        where = f"serveur externe '{server}'"
        if cfg.get("category") not in categories:
            problems.append(f"{where} : catégorie hors {sorted(categories)}")
        if cfg.get("min_role") not in ROLE_RANK:
            problems.append(f"{where} : min_role hors {sorted(ROLE_RANK)}")
        auth = cfg.get("auth") or {}
        if str(auth.get("type", "none")).lower() == "none":
            problems.append(f"{where} : sans authentification, refusé")
        try:
            parse_secret_ref(auth.get("secret_ref"))
        except SecretRefError as exc:
            problems.append(f"{where} : {exc}")
    problems += [f"secret en clair à {p}" for p in find_plaintext_secrets(raw)]
    return problems


def registry_findings(catalog: Catalog) -> List[str]:
    """Écarts entre le catalogue et le registre Hermès vivant : outil système, dérive de schéma.

    Un outil `registry` non enregistré dans cet environnement n'est pas une erreur (il sera
    « indisponible » à l'appel) ; un schéma natif qui a changé impose de relever la version du contrat.
    """
    from tools.registry import discover_builtin_tools, registry

    discover_builtin_tools()
    findings: List[str] = []
    for name in catalog.tool_names():
        contract = catalog.contract(name) or {}
        if contract.get("origin", "registry") != "registry":
            continue
        entry = registry.get_entry(name)
        if entry is None:
            findings.append(f"INFO {name} : non enregistré dans ce registre (indisponible à l'appel)")
            continue
        if entry.toolset in SYSTEM_TOOLSETS:
            findings.append(f"ERREUR {name} : toolset système '{entry.toolset}' dans le catalogue exposé")
        params = (entry.schema or {}).get("parameters", {})
        declared = contract.get("inputs", {})
        if set(params.get("properties", {})) != set(declared.get("properties", {})) or set(params.get("required", [])) != set(declared.get("required", [])):
            findings.append(f"ERREUR {name} : dérive d'entrées avec le schéma natif, relever la version du contrat")
    return findings
