#!/usr/bin/env python3
"""
Orso Agents - Engine Image Distribution & Versioning Manager (KAN-63)
---------------------------------------------------------------------
Fournit les primitives de gestion, de validation cryptographique (SHA-256),
de détection de dérive multi-hôtes et de procédure de mise à jour / rollback.

Respecte les critères d'acceptation KAN-63 :
- CA2 : Épinglage et vérification par empreinte (Digest SHA-256)
- CA3 : Détection d'écart de version entre hôtes
- CA4 : Procédure de mise à jour et retour arrière rejouable
- CA5 : Moindre privilège et zéro secret
"""

import os
import re
import json
import hashlib
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
_logger = logging.getLogger("engine_image_manager")

DIGEST_REGEX = re.compile(r"^sha256:[a-f0-9]{64}$")
IMAGE_WITH_DIGEST_REGEX = re.compile(r"^(?P<repo>[^@:]+)(?::(?P<tag>[^@]+))?@(?P<digest>sha256:[a-f0-9]{64})$")


@dataclass
class HostEngineState:
    host_id: str
    host_name: str
    active_digest: str
    pinned_image: str
    running_containers: List[str]
    last_checked: str
    status: str  # "IN_SYNC", "DRIFT_DETECTED", "UNREACHABLE", "ERROR"
    previous_digest: Optional[str] = None
    drift_details: Optional[str] = None


@dataclass
class DriftAuditReport:
    target_digest: str
    timestamp: str
    total_hosts: int
    in_sync_count: int
    drifted_count: int
    unreachable_count: int
    is_drift_detected: bool
    hosts: List[HostEngineState]


def validate_digest(digest: str) -> bool:
    """Vérifie qu'une chaîne est un digest OCI/Docker SHA-256 valide."""
    if not digest or not isinstance(digest, str):
        return False
    return bool(DIGEST_REGEX.match(digest.strip()))


def format_pinned_image(image_repo: str, digest: str, tag: Optional[str] = None) -> str:
    """Formate une référence d'image Docker immuable épinglée par digest."""
    clean_digest = digest.strip()
    if not validate_digest(clean_digest):
        raise ValueError(f"Digest SHA-256 invalide : {digest}. Format attendu : sha256:<64_hex_digits>")
    
    clean_repo = image_repo.split("@")[0].split(":")[0].strip()
    if tag:
        return f"{clean_repo}:{tag.strip()}@{clean_digest}"
    return f"{clean_repo}@{clean_digest}"


def parse_pinned_image(image_ref: str) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Extrait (repo, tag, digest) d'une référence d'image.
    Retourne (repo, tag, digest).
    """
    match = IMAGE_WITH_DIGEST_REGEX.match(image_ref)
    if match:
        return match.group("repo"), match.group("tag"), match.group("digest")
    
    # Sans digest
    if ":" in image_ref:
        repo, tag = image_ref.split(":", 1)
        return repo, tag, None
    return image_ref, None, None


class EngineDistributionManager:
    """Gestionnaire de versionnement et distribution du moteur Orso."""

    def __init__(self, target_digest: str, registry_base: str = "ghcr.io/tquinzain59/orso-engine"):
        if not validate_digest(target_digest):
            raise ValueError(f"Le digest cible est invalide : {target_digest}")
        self.target_digest = target_digest
        self.registry_base = registry_base
        self._host_history: Dict[str, List[Dict[str, Any]]] = {}

    def get_target_pinned_image(self, human_tag: Optional[str] = None) -> str:
        """Retourne la référence d'image complète épinglée pour la production."""
        return format_pinned_image(self.registry_base, self.target_digest, tag=human_tag)

    def audit_hosts_drift(self, hosts: List[Dict[str, Any]]) -> DriftAuditReport:
        """
        CA3 : Évalue l'état de version de chaque hôte et détecte toute dérive
        par rapport au digest de référence cible.
        """
        now = datetime.now(timezone.utc).isoformat()
        evaluated_hosts: List[HostEngineState] = []
        in_sync_count = 0
        drifted_count = 0
        unreachable_count = 0

        for h in hosts:
            host_id = h.get("host_id", "unknown")
            host_name = h.get("host_name", host_id)
            active_digest = h.get("active_digest", "").strip()
            pinned_image = h.get("pinned_image", "")
            containers = h.get("running_containers", [])
            is_reachable = h.get("is_reachable", True)
            prev_digest = h.get("previous_digest")

            if not is_reachable:
                status = "UNREACHABLE"
                drift_details = "Hôte inaccessible ou démon Docker muet"
                unreachable_count += 1
            elif not validate_digest(active_digest):
                status = "ERROR"
                drift_details = f"Digest invalide sur l'hôte : {active_digest}"
                drifted_count += 1
            elif active_digest == self.target_digest:
                status = "IN_SYNC"
                drift_details = None
                in_sync_count += 1
            else:
                status = "DRIFT_DETECTED"
                drift_details = (
                    f"Dérive détectée : actif={active_digest[:19]}... vs cible={self.target_digest[:19]}..."
                )
                drifted_count += 1

            host_state = HostEngineState(
                host_id=host_id,
                host_name=host_name,
                active_digest=active_digest,
                pinned_image=pinned_image or self.get_target_pinned_image(),
                running_containers=containers,
                last_checked=now,
                status=status,
                previous_digest=prev_digest,
                drift_details=drift_details,
            )
            evaluated_hosts.append(host_state)

        report = DriftAuditReport(
            target_digest=self.target_digest,
            timestamp=now,
            total_hosts=len(hosts),
            in_sync_count=in_sync_count,
            drifted_count=drifted_count,
            unreachable_count=unreachable_count,
            is_drift_detected=(drifted_count > 0),
            hosts=evaluated_hosts,
        )

        if report.is_drift_detected:
            _logger.warning("ALERTE CRITIQUE : Dérive de version détectée sur %d hôte(s) !", drifted_count)
        else:
            _logger.info("Audit d'intégrité OK : tous les hôtes (%d) exécutent le digest cible.", in_sync_count)

        return report

    def execute_host_update(
        self,
        host_state: HostEngineState,
        new_digest: str,
        human_tag: Optional[str] = None,
    ) -> Tuple[HostEngineState, Dict[str, Any]]:
        """
        CA4 : Exécute et enregistre la mise à jour d'un hôte vers un nouveau digest.
        """
        if not validate_digest(new_digest):
            raise ValueError(f"Nouveau digest invalide pour la mise à jour : {new_digest}")

        state_before = {
            "host_id": host_state.host_id,
            "digest": host_state.active_digest,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Enregistrement dans l'historique de l'hôte
        if host_state.host_id not in self._host_history:
            self._host_history[host_state.host_id] = []
        self._host_history[host_state.host_id].append(state_before)

        # Mise à jour de l'état
        updated_state = HostEngineState(
            host_id=host_state.host_id,
            host_name=host_state.host_name,
            active_digest=new_digest,
            pinned_image=format_pinned_image(self.registry_base, new_digest, tag=human_tag),
            running_containers=list(host_state.running_containers),
            last_checked=datetime.now(timezone.utc).isoformat(),
            status="IN_SYNC" if new_digest == self.target_digest else "DRIFT_DETECTED",
            previous_digest=host_state.active_digest,
            drift_details=None if new_digest == self.target_digest else "Digest mis à jour différent de la cible globale",
        )

        audit_log = {
            "action": "UPDATE",
            "host_id": host_state.host_id,
            "old_digest": host_state.active_digest,
            "new_digest": new_digest,
            "timestamp": updated_state.last_checked,
            "success": True,
        }
        return updated_state, audit_log

    def execute_host_rollback(self, host_state: HostEngineState) -> Tuple[HostEngineState, Dict[str, Any]]:
        """
        CA4 : Exécute le retour arrière immédiat d'un hôte vers son digest précédent.
        """
        if not host_state.previous_digest or not validate_digest(host_state.previous_digest):
            raise ValueError(
                f"Impossible d'effectuer le rollback pour l'hôte {host_state.host_id} : aucun digest précédent valide"
            )

        target_rollback_digest = host_state.previous_digest
        current_digest = host_state.active_digest

        rolled_back_state = HostEngineState(
            host_id=host_state.host_id,
            host_name=host_state.host_name,
            active_digest=target_rollback_digest,
            pinned_image=format_pinned_image(self.registry_base, target_rollback_digest),
            running_containers=list(host_state.running_containers),
            last_checked=datetime.now(timezone.utc).isoformat(),
            status="IN_SYNC" if target_rollback_digest == self.target_digest else "DRIFT_DETECTED",
            previous_digest=current_digest,  # Permet un redo si nécessaire
            drift_details=None if target_rollback_digest == self.target_digest else "Rollback sur digest historique",
        )

        audit_log = {
            "action": "ROLLBACK",
            "host_id": host_state.host_id,
            "from_digest": current_digest,
            "to_digest": target_rollback_digest,
            "timestamp": rolled_back_state.last_checked,
            "success": True,
        }
        return rolled_back_state, audit_log

    @staticmethod
    def calculate_file_sha256(filepath: str) -> str:
        """Calcule le hash SHA-256 d'un fichier (ex: archive Docker .tar.gz)."""
        sha = hashlib.sha256()
        with open(filepath, "rb") as f:
            while chunk := f.read(65536):
                sha.update(chunk)
        return sha.hexdigest()

    @staticmethod
    def verify_bundle_manifest(archive_path: str, expected_sha256: str) -> bool:
        """Vérifie qu'une archive de secours correspond exactement à l'empreinte signée."""
        actual_sha = EngineDistributionManager.calculate_file_sha256(archive_path)
        return actual_sha.lower() == expected_sha256.lower().replace("sha256:", "").strip()


if __name__ == "__main__":
    # Test d'auto-diagnostic CLI
    ref_digest = "sha256:d8a5f82c448bb95b28a9b49b43e8b0b8c6e07eb4838a1f2987a123456789abcd"
    mgr = EngineDistributionManager(target_digest=ref_digest)
    print("Moteur Orso épinglé :", mgr.get_target_pinned_image(human_tag="v1.0.0"))
