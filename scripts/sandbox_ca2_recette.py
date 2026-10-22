#!/usr/bin/env python3
"""Recette CA2 de KAN-129 : deux exécutions simultanées d'un même client sont-elles isolées ?

Usage :
    python scripts/sandbox_ca2_recette.py --backend docker --image repo@sha256:<64 hex> [--config config/hermes.yaml]
    python scripts/sandbox_ca2_recette.py --backend local     # mesure l'état sans isolation (attendu : INTERFERENCE)

Code retour : 0 ISOLATED, 1 INTERFERENCE, 2 NOT_VERIFIED (backend indisponible, image non épinglée, échec
d'exécution). Une recette qui n'a pas pu s'exécuter ne retourne jamais 0.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from olympe.execution_isolation import (  # noqa: E402
    NOT_VERIFIED,
    EnvFactory,
    IsolationReport,
    execution_isolation_gaps,
    is_digest_pinned,
    run_isolation_probe,
)
from olympe.sandbox_policy import PRODUCT_DEFAULT_QUOTAS  # noqa: E402


def _docker_factory(image: str) -> EnvFactory:
    from tools.environments.docker import DockerEnvironment

    run = uuid.uuid4().hex[:8]
    memory_mb = int(PRODUCT_DEFAULT_QUOTAS["memory"].rstrip("m"))

    def make(idx: int):
        return DockerEnvironment(
            image=image,
            cwd="/workspace",
            timeout=60,
            cpu=float(PRODUCT_DEFAULT_QUOTAS["cpus"]),
            memory=memory_mb,
            persistent_filesystem=False,
            persist_across_processes=False,
            task_id=f"ca2-{run}-{idx}",
        )

    return make


def _local_factory() -> EnvFactory:
    from tools.environments.local import LocalEnvironment

    shared_cwd = tempfile.mkdtemp(prefix="orso_ca2_local_")
    return lambda idx: LocalEnvironment(cwd=shared_cwd, timeout=60)


def _config_gaps(config_path: str | None) -> list[str] | None:
    if not config_path:
        return None
    import yaml

    data = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    return execution_isolation_gaps(data.get("terminal"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--backend", choices=("docker", "local"), required=True)
    ap.add_argument("--image", default=None, help="docker : image épinglée par empreinte (repo@sha256:...)")
    ap.add_argument("--parallel", type=int, default=2)
    ap.add_argument("--config", default=None, help="config client dont la section terminal est contrôlée")
    args = ap.parse_args(argv)

    if args.backend == "docker" and not is_digest_pinned(args.image or ""):
        report = IsolationReport(NOT_VERIFIED, detail="--image doit être épinglée par empreinte (repo@sha256:<64 hex>)")
    else:
        try:
            factory = _docker_factory(args.image) if args.backend == "docker" else _local_factory()
            report = run_isolation_probe(factory, parallel=args.parallel)
        except Exception as exc:  # noqa: BLE001 — backend indisponible => NOT_VERIFIED
            report = IsolationReport(NOT_VERIFIED, detail=f"{type(exc).__name__}: {exc}")

    out = report.as_dict()
    out["backend"] = args.backend
    out["config_gaps"] = _config_gaps(args.config)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
