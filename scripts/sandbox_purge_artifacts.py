#!/usr/bin/env python3
"""Purge des artefacts d'espace client au-delà de la rétention (KAN-129 / CA5).

Usage (planifié quotidiennement, voir docs/3_Technique/spec_kan129_sandbox_produit.md) :
    python scripts/sandbox_purge_artifacts.py [--dry-run] [--tenant SLUG] [--days 30] [--no-keep-latest]

La racine des artefacts est celle du gestionnaire (ORSO_ARTIFACTS_ROOT sinon <data>/artifacts).
Code retour : 0 si la passe s'est terminée, 2 si les paramètres sont invalides.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from olympe.artifact_manager import ClientSpaceArtifactManager  # noqa: E402
from olympe.artifact_retention import ARTIFACT_RETENTION_DAYS, purge_expired_artifacts  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=ARTIFACT_RETENTION_DAYS)
    ap.add_argument("--tenant", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-keep-latest", action="store_true")
    args = ap.parse_args(argv)
    manager = ClientSpaceArtifactManager(artifacts_root=os.environ.get("ORSO_ARTIFACTS_ROOT") or None)
    try:
        report = purge_expired_artifacts(
            manager,
            tenant_slug=args.tenant,
            retention_days=args.days,
            dry_run=args.dry_run,
            keep_latest=not args.no_keep_latest,
        )
    except ValueError as exc:
        print(f"ERREUR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
