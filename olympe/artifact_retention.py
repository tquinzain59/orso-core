"""Conservation et purge automatique des artefacts d'espace client (KAN-129 / CA5).

Durée de conservation arbitrée le 21/10/2026 : 30 jours. L'âge se lit dans ``created_at`` du
manifeste scellé par ``ClientSpaceArtifactManager`` (jamais dans la date de modification du fichier).
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from olympe.artifact_manager import ClientSpaceArtifactManager
from olympe.sandbox_policy import resolve_within

_log = logging.getLogger("olympe.artifact_retention")

ARTIFACT_RETENTION_DAYS = 30


def _parse_created_at(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def purge_expired_artifacts(
    manager: ClientSpaceArtifactManager,
    tenant_slug: Optional[str] = None,
    retention_days: int = ARTIFACT_RETENTION_DAYS,
    now: Optional[datetime] = None,
    dry_run: bool = False,
    keep_latest: bool = True,
) -> Dict[str, Any]:
    """Supprime les versions d'artefacts plus anciennes que ``retention_days``.

    ``keep_latest`` protège la version la plus récente de chaque client (base de reprise/rollback,
    KAN-60) même expirée ; un manifeste illisible ou sans date est conservé et signalé, jamais purgé.
    Chaque client est traité dans son propre répertoire : aucune purge ne franchit la racine d'un tenant.
    """
    if retention_days <= 0:
        raise ValueError("retention_days doit être strictement positif.")
    current = now or datetime.now(timezone.utc)
    cutoff = current - timedelta(days=retention_days)

    if tenant_slug is not None:
        tenants: List[str] = [tenant_slug]
    else:
        tenants = sorted(p.name for p in manager.artifacts_root.iterdir() if p.is_dir())

    purged: List[Dict[str, Any]] = []
    kept_protected: List[Dict[str, Any]] = []
    skipped_unreadable: List[Dict[str, Any]] = []

    for slug in tenants:
        tenant_dir = resolve_within(manager.artifacts_root, slug)
        if not tenant_dir.is_dir():
            continue
        dated: List[Dict[str, Any]] = []
        for vdir in sorted(p for p in tenant_dir.iterdir() if p.is_dir()):
            manifest = vdir / "manifest.json"
            created: Optional[datetime] = None
            if manifest.is_file():
                try:
                    created = _parse_created_at(json.loads(manifest.read_text(encoding="utf-8")).get("created_at"))
                except (OSError, ValueError):
                    created = None
            entry = {"tenant_slug": slug, "version": vdir.name, "path": vdir}
            if created is None:
                skipped_unreadable.append({"tenant_slug": slug, "version": vdir.name, "reason": "manifest_unreadable_or_undated"})
                continue
            entry["created_at"] = created
            dated.append(entry)

        newest = max(dated, key=lambda e: e["created_at"], default=None) if keep_latest else None
        for entry in dated:
            if entry["created_at"] >= cutoff:  # exactement 30 jours : conservé, la purge vise « au-delà »
                continue
            record = {
                "tenant_slug": slug,
                "version": entry["version"],
                "created_at": entry["created_at"].isoformat(),
                "age_days": (current - entry["created_at"]).days,
            }
            if newest is not None and entry is newest:
                kept_protected.append({**record, "reason": "latest_version_protected"})
                continue
            if not dry_run:
                shutil.rmtree(entry["path"])
                _log.info("Artefact expiré purgé : %s v%s (âge %s j)", slug, entry["version"], record["age_days"])
            purged.append(record)

    return {
        "retention_days": retention_days,
        "cutoff": cutoff.isoformat(),
        "dry_run": dry_run,
        "purged": purged,
        "protected": kept_protected,
        "skipped": skipped_unreadable,
    }
