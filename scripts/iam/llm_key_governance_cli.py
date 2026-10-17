#!/usr/bin/env python3
"""CLI de gouvernance des clés d'API LLM (KAN-53).

Les valeurs de clés ne passent jamais en argument : elles sont lues dans une variable
d'environnement nommée (``--key-env`` / ``--new-key-env``) ou sur l'entrée standard
(``--key-stdin`` / ``--new-key-stdin``), afin de ne laisser aucune trace dans l'historique
du shell ni dans la liste des processus. Toutes les sorties sont du JSON sans secret.

Exemples (base par défaut : ORSO_LLM_GOVERNANCE_DB ou ./data/llm_governance.db) :

    llm_key_governance_cli.py register --key-id openrouter-acme --provider openrouter \\
        --tenant acme --location "env:OPENROUTER_API_KEY@orso-client-acme" --owner svc-orso-ops
    llm_key_governance_cli.py set-policy --tenant acme --cap-usd 50 --mode refuse
    llm_key_governance_cli.py authorize --tenant acme --provider openrouter --model m --estimate 1.5
    NEW_KEY=... llm_key_governance_cli.py rotate --key-id openrouter-acme \\
        --actor svc-orso-rotation --new-key-env NEW_KEY --grace-seconds 900
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from olympe.llm_key_governance import (  # noqa: E402
    DEFAULT_GRACE_SECONDS,
    GovernanceError,
    LLMGovernance,
)


def _read_secret(env_name: Optional[str], use_stdin: bool, label: str) -> Optional[str]:
    if env_name:
        value = os.environ.get(env_name, "")
        if not value:
            raise GovernanceError(f"Variable d'environnement vide ou absente : {env_name}")
        return value
    if use_stdin:
        value = sys.stdin.readline().rstrip("\n")
        if not value:
            raise GovernanceError(f"Aucune valeur reçue sur l'entrée standard pour {label}.")
        return value
    return None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=None, help="Chemin de la base de gouvernance.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("register", help="Inscrire une clé à l'inventaire (sans valeur).")
    p.add_argument("--key-id", required=True)
    p.add_argument("--provider", required=True)
    p.add_argument("--tenant", required=True, help="Slug du tenant, ou '*' pour une clé mutualisée.")
    p.add_argument("--location", required=True, help="Emplacement (ex. env:NOM@conteneur), jamais la valeur.")
    p.add_argument("--owner", required=True)
    p.add_argument("--last-rotation", default=None)
    p.add_argument("--key-env", default=None, help="Variable portant la valeur (empreinte seule conservée).")
    p.add_argument("--key-stdin", action="store_true")

    p = sub.add_parser("inventory", help="Afficher l'inventaire (JSON ou tableau Markdown).")
    p.add_argument("--markdown", action="store_true")

    p = sub.add_parser("set-policy", help="Fixer plafond, mode et seuils d'un tenant ('*' = défaut).")
    p.add_argument("--tenant", required=True)
    p.add_argument("--cap-usd", type=float, default=None, help="Plafond mensuel USD ; omis = aucun plafond.")
    p.add_argument("--mode", choices=["refuse", "alert_only"], default="refuse")
    p.add_argument("--thresholds", type=float, nargs="+", default=None, help="Ratios d'alerte, ex. 0.5 0.8 1.0")
    p.add_argument("--drift-factor", type=float, default=3.0)

    p = sub.add_parser("authorize", help="Contrôle de plafond avant appel (code retour 3 si refusé).")
    p.add_argument("--tenant", required=True)
    p.add_argument("--provider", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--estimate", type=float, default=0.0)

    p = sub.add_parser("record", help="Enregistrer un appel (coût lu à la source de vérité).")
    p.add_argument("--tenant", required=True)
    p.add_argument("--provider", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--cost-usd", type=float, required=True)
    p.add_argument("--input-tokens", type=int, default=0)
    p.add_argument("--output-tokens", type=int, default=0)
    p.add_argument("--key-id", default=None)
    p.add_argument("--session-id", default=None)

    p = sub.add_parser("audit", help="Extrait du journal d'audit des appels.")
    p.add_argument("--tenant", default=None)
    p.add_argument("--since", default=None)
    p.add_argument("--until", default=None)
    p.add_argument("--csv", action="store_true")

    p = sub.add_parser("alerts", help="Lister les alertes émises.")
    p.add_argument("--tenant", default=None)
    p.add_argument("--kind", default=None)

    p = sub.add_parser("rotate", help="Rotation à chaud avec fenêtre de grâce.")
    p.add_argument("--key-id", required=True)
    p.add_argument("--actor", required=True, help="Compte de service (jamais un identifiant humain).")
    p.add_argument("--new-key-env", default=None)
    p.add_argument("--new-key-stdin", action="store_true")
    p.add_argument("--grace-seconds", type=int, default=DEFAULT_GRACE_SECONDS)

    p = sub.add_parser("verify", help="Vérifier une valeur présentée (code retour 4 si refusée).")
    p.add_argument("--key-id", required=True)
    p.add_argument("--key-env", default=None)
    p.add_argument("--key-stdin", action="store_true")

    p = sub.add_parser("rotation-log", help="Journal de rotation.")
    p.add_argument("--key-id", default=None)

    sub.add_parser("finalize", help="Révoquer les anciennes valeurs dont la grâce est échue.")
    return parser


def _emit(payload) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))


def main(argv: Optional[list] = None) -> int:
    args = _build_parser().parse_args(argv)
    gov = LLMGovernance(db_path=args.db)
    try:
        cmd = args.command
        if cmd == "register":
            value = _read_secret(args.key_env, args.key_stdin, "la clé")
            _emit(gov.register_key(args.key_id, args.provider, args.tenant, args.location,
                                   args.owner, key_value=value, last_rotation=args.last_rotation))
        elif cmd == "inventory":
            if args.markdown:
                print(gov.inventory_markdown(), end="")
            else:
                _emit(gov.inventory())
        elif cmd == "set-policy":
            _emit(gov.set_policy(args.tenant, args.cap_usd, args.mode, args.thresholds, args.drift_factor))
        elif cmd == "authorize":
            decision = gov.authorize(args.tenant, args.provider, args.model, args.estimate)
            _emit(decision)
            return 0 if decision["allowed"] else 3
        elif cmd == "record":
            _emit(gov.record_call(args.tenant, args.provider, args.model, args.cost_usd,
                                  args.input_tokens, args.output_tokens, args.key_id, args.session_id))
        elif cmd == "audit":
            if args.csv:
                print(gov.audit_csv(tenant_slug=args.tenant, since=args.since, until=args.until), end="")
            else:
                _emit(gov.audit(tenant_slug=args.tenant, since=args.since, until=args.until))
        elif cmd == "alerts":
            _emit(gov.alerts(tenant_slug=args.tenant, kind=args.kind))
        elif cmd == "rotate":
            value = _read_secret(args.new_key_env, args.new_key_stdin, "la nouvelle clé")
            if value is None:
                raise GovernanceError("Fournir --new-key-env ou --new-key-stdin.")
            _emit(gov.rotate_key(args.key_id, value, args.actor, args.grace_seconds))
        elif cmd == "verify":
            value = _read_secret(args.key_env, args.key_stdin, "la clé à vérifier")
            if value is None:
                raise GovernanceError("Fournir --key-env ou --key-stdin.")
            result = gov.verify_key(args.key_id, value)
            _emit(result)
            return 0 if result["accepted"] else 4
        elif cmd == "rotation-log":
            _emit(gov.rotation_log(args.key_id))
        elif cmd == "finalize":
            _emit({"revoked": gov.finalize_rotations()})
    except GovernanceError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
