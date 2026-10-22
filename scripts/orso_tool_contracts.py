#!/usr/bin/env python3
"""Outil de contrôle KAN-131 : catalogue, contrat, permissions, authentification, secrets, dérive.

    python scripts/orso_tool_contracts.py catalog
    python scripts/orso_tool_contracts.py contract feishu_doc_read
    python scripts/orso_tool_contracts.py check --tool messages_send --role user [--client acme]
    python scripts/orso_tool_contracts.py auth --server notion
    python scripts/orso_tool_contracts.py auth --manifest optional-mcps/wolfram/manifest.yaml
    python scripts/orso_tool_contracts.py secrets
    python scripts/orso_tool_contracts.py verify

Codes retour : 0 conforme/autorisé, 3 refusé ou non conforme, 2 usage. Aucune valeur secrète n'est lue pour
affichage : seuls les emplacements et l'état « provisionné / absent » sont rapportés.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import types
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = REPO_ROOT / "plugins" / "orso-tool-contracts"


def _load_plugin() -> types.ModuleType:
    """Charge le plugin comme le fait PluginManager (paquet dynamique), sans l'activer."""
    sys.path.insert(0, str(REPO_ROOT))
    if "hermes_plugins" not in sys.modules:
        ns = types.ModuleType("hermes_plugins")
        ns.__path__ = []
        sys.modules["hermes_plugins"] = ns
    name = "hermes_plugins.orso_tool_contracts"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PLUGIN_DIR / "__init__.py", submodule_search_locations=[str(PLUGIN_DIR)])
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = name
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _sub(name: str):
    _load_plugin()
    return importlib.import_module(f"hermes_plugins.orso_tool_contracts.{name}")


def cmd_catalog(_: argparse.Namespace) -> int:
    contracts = _sub("contracts")
    cat = contracts.load_catalog()
    print(f"catalogue exposé v{cat.version} daté {cat.dated} — catégories : {', '.join(cat.categories)}")
    for name in cat.tool_names():
        e = cat.resolve(name)
        print(f"  {e.category:<10} {e.name:<28} v{e.version} min_role={e.min_role:<5} origine={e.origin}")
    for server, cfg in cat.external_servers.items():
        print(f"  {cfg['category']:<10} mcp__{server}__*{'':<17} v{cfg.get('version', cat.version)} min_role={cfg['min_role']:<5} origine=mcp_external (auth {cfg['auth']['type']})")
    for cat_name in cat.categories:
        has = any(cat.resolve(n).category == cat_name for n in cat.tool_names()) or any(c["category"] == cat_name for c in cat.external_servers.values())
        if not has:
            print(f"  [LACUNE] aucune entrée exposée pour la catégorie '{cat_name}'")
    return 0


def cmd_contract(args: argparse.Namespace) -> int:
    cat = _sub("contracts").load_catalog()
    contract = cat.contract(args.tool)
    if contract is None:
        print(f"TOOL_NOT_EXPOSED : '{args.tool}' n'est pas dans le catalogue exposé v{cat.version}")
        return 3
    print(yaml.safe_dump(contract, allow_unicode=True, sort_keys=False).rstrip())
    print("erreurs communes :", ", ".join(e["code"] for e in cat.raw.get("common_errors", [])))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    guard, contracts = _sub("guard"), _sub("contracts")
    from hermes_cli.web_routers.tool_caller import normalize_role
    from tools.registry import discover_builtin_tools

    discover_builtin_tools()  # comme au runtime : l'état du registre alimente la décision de disponibilité
    role = normalize_role(args.role)
    decision = guard.decide(contracts.load_catalog(), args.tool, role, args.client, session_id="cli-check")
    print(f"{'AUTORISÉ' if decision.allowed else 'REFUSÉ'} {decision.code} tool={args.tool} role={role} client={args.client}")
    if decision.message:
        print(decision.message)
    return 0 if decision.allowed else 3


def cmd_auth(args: argparse.Namespace) -> int:
    secret_refs, contracts = _sub("secret_refs"), _sub("contracts")
    if args.manifest:
        manifest_path = Path(args.manifest)
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        server = str(manifest.get("name", manifest_path.parent.name))
        auth = secret_refs.manifest_auth(manifest, server)
    else:
        server = args.server
        cfg = contracts.load_catalog().external_servers.get(server)
        if cfg is None:
            print(f"AUTH_REFUSED : serveur '{server}' absent du catalogue exposé")
            return 3
        auth = cfg.get("auth")
    decision = secret_refs.check_external_auth(server, auth)
    print(f"{'ACCEPTÉ' if decision.allowed else 'REFUSÉ'} {decision.code} : {decision.reason}")
    return 0 if decision.allowed else 3


def cmd_secrets(_: argparse.Namespace) -> int:
    secret_refs = _sub("secret_refs")
    raw = yaml.safe_load((PLUGIN_DIR / "catalog.yaml").read_text(encoding="utf-8"))
    refs = {s: cfg["auth"]["secret_ref"] for s, cfg in (raw.get("external_servers") or {}).items()}
    found = secret_refs.find_plaintext_secrets(raw)
    for server, ref in refs.items():
        print(f"secret de '{server}' désigné par emplacement : {ref}")
    print(f"secrets en clair dans le catalogue : {len(found)}" + "".join(f"\n  - {p}" for p in found))
    return 0 if not found else 3


def cmd_verify(_: argparse.Namespace) -> int:
    contracts = _sub("contracts")
    cat = contracts.load_catalog()
    problems = contracts.validate_catalog(cat.raw)
    findings = contracts.registry_findings(cat)
    for line in [*(f"ERREUR {p}" for p in problems), *findings]:
        print(line)
    errors = len(problems) + sum(1 for f in findings if f.startswith("ERREUR"))
    leaked = sorted(set(cat.tool_names()) & contracts.SYSTEM_TOOLS)
    print(f"outils système dans le catalogue exposé : {json.dumps(leaked)}")
    print(f"verify : {errors} erreur(s)")
    return 0 if errors == 0 else 3


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("catalog").set_defaults(fn=cmd_catalog)
    p = sub.add_parser("contract")
    p.add_argument("tool")
    p.set_defaults(fn=cmd_contract)
    p = sub.add_parser("check")
    p.add_argument("--tool", required=True)
    p.add_argument("--role", required=True)
    p.add_argument("--client", default="default")
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("auth")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--server")
    g.add_argument("--manifest")
    p.set_defaults(fn=cmd_auth)
    sub.add_parser("secrets").set_defaults(fn=cmd_secrets)
    sub.add_parser("verify").set_defaults(fn=cmd_verify)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
