"""Politique produit du bac à sable client (KAN-129) : quotas par défaut, quota disque, cloisonnement des chemins.

Module de marge (plan de gestion) : aucun code du moteur n'est touché. Les valeurs par défaut sont
celles arbitrées le 21/10/2026 : 2 vCPU, 4 Go de RAM, 40 Go de disque par client.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple, Union

PRODUCT_DEFAULT_QUOTAS: Dict[str, str] = {
    "cpus": "2.0",
    "memory": "4096m",
    "pids_limit": "250",
    "disk": "40g",
}

# Slug de tenant ou version d'artefact : un seul segment de chemin, sans séparateur ni « .. ».
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def parse_disk_str_to_bytes(disk_val: Any) -> int:
    """Convertit un quota disque ('40g', '512m', '1t', entier d'octets) en octets.

    Refuse explicitement une valeur illisible plutôt que de retomber sur un défaut silencieux.
    """
    if isinstance(disk_val, bool):
        raise ValueError(f"Quota disque invalide : {disk_val!r}")
    if isinstance(disk_val, (int, float)):
        if disk_val <= 0:
            raise ValueError(f"Quota disque invalide : {disk_val!r}")
        return int(disk_val)
    if not isinstance(disk_val, str):
        raise ValueError(f"Quota disque invalide : {disk_val!r}")
    m = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*([a-z]*)$", disk_val.strip().lower())
    if not m:
        raise ValueError(f"Quota disque invalide : {disk_val!r}")
    num, unit = float(m.group(1)), m.group(2)
    factors = {
        "": 1, "b": 1,
        "k": 1024, "kb": 1024, "kib": 1024,
        "m": 1024**2, "mb": 1024**2, "mib": 1024**2,
        "g": 1024**3, "gb": 1024**3, "gib": 1024**3,
        "t": 1024**4, "tb": 1024**4, "tib": 1024**4,
    }
    if unit not in factors or num <= 0:
        raise ValueError(f"Quota disque invalide : {disk_val!r}")
    return int(num * factors[unit])


def measure_dir_bytes(path: Union[str, Path]) -> int:
    """Octets occupés sous ``path`` (liens symboliques non suivis, fichiers illisibles ignorés)."""
    root = Path(path)
    if not root.exists():
        return 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
        for name in filenames:
            fp = os.path.join(dirpath, name)
            try:
                if not os.path.islink(fp):
                    total += os.lstat(fp).st_size
            except OSError:
                continue
    return total


def check_disk_quota(
    paths: Iterable[Union[str, Path]],
    disk_quota: Any,
    additional_bytes: int = 0,
) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    """Refuse explicitement si l'occupation des ``paths`` (+ ``additional_bytes``) dépasse le quota disque."""
    quota_bytes = parse_disk_str_to_bytes(disk_quota)
    used = sum(measure_dir_bytes(p) for p in paths)
    projected = used + max(0, int(additional_bytes))
    details = {
        "disk_quota_bytes": quota_bytes,
        "disk_used_bytes": used,
        "disk_projected_bytes": projected,
    }
    if projected > quota_bytes:
        msg = (
            f"Quota disque dépassé : {projected} octets projetés pour un quota de "
            f"{quota_bytes} octets ({disk_quota})."
        )
        return False, msg, details
    return True, None, details


def resolve_within(root: Union[str, Path], *segments: str) -> Path:
    """Joint ``segments`` sous ``root`` ; lève ValueError si un segment tente de sortir de ``root``.

    Garantit qu'un slug de tenant ou une version forgés (``../autre-client``) ne permettent pas
    la lecture croisée de l'espace d'un autre client.
    """
    base = Path(root).resolve()
    for seg in segments:
        if not isinstance(seg, str) or not _SAFE_SEGMENT.match(seg) or seg.strip(".") == "":
            raise ValueError(f"ERR_PATH_ESCAPE: segment de chemin refusé : {seg!r}")
    target = base.joinpath(*segments).resolve()
    if target != base and base not in target.parents:
        raise ValueError(f"ERR_PATH_ESCAPE: chemin hors de la racine autorisée : {target}")
    return target
