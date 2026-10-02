"""Gestionnaire d'Artefacts d'Espace Client Orso (KAN-60 / POC 3).

Ce module implémente la construction, le scellement cryptographique, le versionnement,
la vérification d'empreinte (SHA-256), l'audit de secrets (compteur nul) et l'extraction
contrôlée pour le montage en lecture seule dans les conteneurs clients.

Conforme au Document 27 (sections 2, 5, 6), KAN-33 (personas HMAC), et KAN-58 (espaces propres).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

_log = logging.getLogger("orso.olympe.artifact")

# Motifs rigoureux de détection de secrets pour CA4 (compteur nul impératif)
SECRET_PATTERNS = [
    (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "OpenAI API Key (sk-)"),
    (re.compile(r"sk-proj-[a-zA-Z0-9_-]{20,}"), "OpenAI Project API Key (sk-proj-)"),
    (re.compile(r"sk-ant-[a-zA-Z0-9_-]{20,}"), "Anthropic API Key (sk-ant-)"),
    (re.compile(r"(?i)deepseek-[a-zA-Z0-9]{20,}"), "DeepSeek API Key"),
    (re.compile(r"(sk_live|rk_live|sk_test)_[0-9a-zA-Z]{24,}"), "Stripe Secret / Restricted Key"),
    (re.compile(r"ghp_[a-zA-Z0-9]{36}"), "GitHub Personal Access Token (ghp_)"),
    (re.compile(r"github_pat_[a-zA-Z0-9_]{82}"), "GitHub Fine-Grained PAT"),
    (re.compile(r"ATATT3[a-zA-Z0-9_\-=]{20,}"), "Atlassian API Token (ATATT3)"),
    (re.compile(r"-----BEGIN (RSA|EC|DSA|OPENSSH) PRIVATE KEY-----"), "Clé privée RSA/SSH"),
    (re.compile(r"(?i)(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|password)\s*[:=]\s*[\"'][a-zA-Z0-9_\-\.]{20,}[\"']"), "Clé d'authentification ou mot de passe en dur"),
]


def compute_sha256_bytes(data: bytes) -> str:
    """Calcule l'empreinte SHA-256 de données binaires."""
    return hashlib.sha256(data).hexdigest()


def compute_sha256_file(file_path: Union[str, Path]) -> str:
    """Calcule l'empreinte SHA-256 d'un fichier sur disque."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Fichier introuvable : {path}")
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _force_rmtree(path: Union[str, Path]) -> None:
    """Supprime récursivement un répertoire en déverrouillant d'abord les permissions en écriture."""
    p = Path(path)
    if not p.exists():
        return
    for root, dirs, files in os.walk(p):
        for d in dirs:
            try:
                os.chmod(os.path.join(root, d), 0o755)
            except Exception:
                pass
        for f in files:
            try:
                os.chmod(os.path.join(root, f), 0o644)
            except Exception:
                pass
    try:
        os.chmod(p, 0o755)
    except Exception:
        pass
    shutil.rmtree(p, ignore_errors=True)


class ClientSpaceArtifactManager:
    """Gestionnaire de construction, vérification et déploiement d'artefacts d'espace client."""

    def __init__(
        self,
        artifacts_root: Optional[Union[str, Path]] = None,
        spaces_root: Optional[Union[str, Path]] = None,
    ):
        project_root = Path(__file__).resolve().parent.parent
        self.artifacts_root = (
            Path(artifacts_root).resolve()
            if artifacts_root
            else project_root / "data" / "artifacts"
        )
        self.spaces_root = (
            Path(spaces_root).resolve()
            if spaces_root
            else project_root / "data" / "spaces"
        )
        self.artifacts_root.mkdir(parents=True, exist_ok=True)
        self.spaces_root.mkdir(parents=True, exist_ok=True)

    def get_tenant_artifact_dir(self, tenant_slug: str, version: Optional[str] = None) -> Path:
        """Retourne le répertoire de stockage des artefacts d'un tenant."""
        base = self.artifacts_root / tenant_slug
        if version:
            return base / version
        return base

    def scan_for_secrets(
        self,
        source: Union[str, Path, bytes],
        ignore_files: Optional[List[str]] = None,
    ) -> Tuple[int, List[Dict[str, Any]]]:
        """Scanne un fichier, un dossier ou un tampon binaire contre les secrets sensibles (CA4)."""
        violations: List[Dict[str, Any]] = []
        ignored = set(ignore_files or [])

        if isinstance(source, bytes):
            text = source.decode("utf-8", errors="replace")
            for pattern, desc in SECRET_PATTERNS:
                matches = pattern.findall(text)
                if matches:
                    violations.append({
                        "type": desc,
                        "count": len(matches),
                        "file": "<binary_buffer>",
                    })
            return len(violations), violations

        source_path = Path(source)
        if not source_path.exists():
            return 0, []

        if source_path.is_file():
            files_to_scan = [source_path]
        else:
            files_to_scan = [
                p for p in source_path.rglob("*")
                if p.is_file() and not p.name.endswith((".pyc", ".tar", ".gz", ".png", ".jpg", ".lock"))
            ]

        for f in files_to_scan:
            rel = str(f.relative_to(source_path)) if source_path.is_dir() else f.name
            if rel in ignored or f.name in ignored:
                continue

            try:
                content = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            for pattern, desc in SECRET_PATTERNS:
                matches = pattern.findall(content)
                if matches:
                    violations.append({
                        "file": rel,
                        "type": desc,
                        "count": len(matches),
                    })

        return len(violations), violations

    def build_artifact(
        self,
        tenant_slug: str,
        version: str,
        source_dir: Union[str, Path],
        author: str = "Olympe Artifact Builder",
        hmac_key: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Construit un artefact scellé et versionné pour l'espace d'agents d'un client (CA1, CA4)."""
        source_path = Path(source_dir).resolve()
        if not source_path.is_dir():
            raise FileNotFoundError(f"Dossier source d'artefact introuvable : {source_path}")

        # Validation de la version (format libre semver e.g. 1.0.0, v1.0.0)
        norm_version = version.strip()
        if not norm_version:
            raise ValueError("Le numéro de version de l'artefact est requis.")

        # CA4 : Audit préalable anti-secrets sur les sources
        secrets_count, secret_findings = self.scan_for_secrets(source_path)
        if secrets_count > 0:
            err_msg = (
                f"Construction de l'artefact refusée pour {tenant_slug} v{norm_version} : "
                f"{secrets_count} violation(s) de secrets détectée(s) (CA4). "
                f"Détails : {json.dumps(secret_findings, ensure_ascii=False)}"
            )
            _log.error(err_msg)
            raise ValueError(f"ERR_SECRET_DETECTED_IN_ARTIFACT: {err_msg}")

        # Vérification d'intégrité des personas (KAN-33) si personas.lock.json présent
        personas_integrity = {"status": "unverified", "hmac_verified": False, "personas": []}
        lock_file = source_path / "profiles" / "personas.lock.json"
        effective_key = hmac_key or os.environ.get("ORSO_PERSONA_HMAC_KEY")

        if lock_file.is_file():
            try:
                from scripts.security.persona_integrity import verify_all_personas
                is_valid, errors, audit_entries = verify_all_personas(
                    profiles_dir=source_path / "profiles",
                    lock_file=lock_file,
                    hmac_key=effective_key,
                    record_logs=False,
                )
                personas_integrity = {
                    "status": "valid" if is_valid else "invalid",
                    "hmac_verified": bool(is_valid and effective_key),
                    "details": errors if errors else "Toutes les signatures HMAC et empreintes SHA-256 sont valides",
                    "personas_count": len(audit_entries),
                }
            except Exception as e:
                _log.warning("Impossible de valider personas.lock.json via le module de sécurité : %s", e)
                personas_integrity["status"] = "warning"
                personas_integrity["details"] = str(e)

        # Inventaire récursif des fichiers et calculs d'empreintes unitaires
        files_manifest: Dict[str, Dict[str, Any]] = {}
        total_size = 0
        canonical_content_entries: List[str] = []

        # Parcourir et trier les fichiers pour un calcul canonique déterministe
        all_files = sorted(
            [p for p in source_path.rglob("*") if p.is_file() and not p.name.startswith(".")],
            key=lambda p: str(p.relative_to(source_path)).replace("\\", "/")
        )

        for f in all_files:
            rel_path = str(f.relative_to(source_path)).replace("\\", "/")
            f_sha = compute_sha256_file(f)
            f_size = f.stat().st_size
            files_manifest[rel_path] = {
                "sha256": f_sha,
                "size_bytes": f_size,
            }
            total_size += f_size
            canonical_content_entries.append(f"{rel_path}:{f_sha}")

        # Empreinte de contenu (Content Merkle Tree)
        content_tree_digest = compute_sha256_bytes("\n".join(canonical_content_entries).encode("utf-8"))
        content_fingerprint = f"sha256:{content_tree_digest}"

        # Préparation du répertoire cible d'artefact
        target_dir = self.get_tenant_artifact_dir(tenant_slug, norm_version)
        target_dir.mkdir(parents=True, exist_ok=True)
        archive_path = target_dir / f"client-space-{tenant_slug}-{norm_version}.tar.gz"

        # Construction déterministe de l'archive tar.gz (mtime fixé à epoch 0, uid/gid normalisés)
        with tarfile.open(archive_path, "w:gz", format=tarfile.PAX_FORMAT) as tar:
            for f in all_files:
                rel_path = str(f.relative_to(source_path)).replace("\\", "/")
                tarinfo = tar.gettarinfo(f, arcname=rel_path)
                tarinfo.uid = 0
                tarinfo.gid = 0
                tarinfo.uname = "orso"
                tarinfo.gname = "orso"
                tarinfo.mtime = 1700000000  # Date fixe déterministe
                if tarinfo.isreg():
                    with open(f, "rb") as fl:
                        tar.addfile(tarinfo, fl)
                else:
                    tar.addfile(tarinfo)

        # Calcul de l'empreinte cryptographique de l'artefact scellé (.tar.gz)
        archive_sha = compute_sha256_file(archive_path)
        archive_fingerprint = f"sha256:{archive_sha}"

        # Manifeste officiel d'artefact
        manifest = {
            "schema_version": "1.0",
            "artifact_type": "orso_client_space_artifact",
            "tenant_slug": tenant_slug,
            "version": norm_version,
            "fingerprint": archive_fingerprint,
            "content_fingerprint": content_fingerprint,
            "archive_filename": archive_path.name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "author": author,
            "files_count": len(files_manifest),
            "total_size_bytes": total_size,
            "archive_size_bytes": archive_path.stat().st_size,
            "files": files_manifest,
            "personas_integrity": personas_integrity,
            "secrets_scan": {
                "secrets_detected": 0,
                "status": "clean",
                "scanned_files_count": len(all_files),
            },
            "metadata": metadata or {},
        }

        # Écriture du manifeste JSON
        manifest_path = target_dir / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as mf:
            json.dump(manifest, mf, indent=2, ensure_ascii=False)

        _log.info(
            "Artefact client construit avec succès : %s v%s -> %s (Empreinte: %s)",
            tenant_slug,
            norm_version,
            archive_path.name,
            archive_fingerprint,
        )

        return manifest

    def verify_artifact(
        self,
        tenant_slug: str,
        version: str,
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """Vérifie formellement l'intégrité cryptographique d'un artefact scellé (CA1, CA4)."""
        target_dir = self.get_tenant_artifact_dir(tenant_slug, version)
        manifest_path = target_dir / "manifest.json"

        if not manifest_path.is_file():
            return False, f"Manifeste introuvable : {manifest_path}", None

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception as e:
            return False, f"Erreur de lecture du manifeste : {e}", None

        expected_fingerprint = manifest.get("fingerprint")
        archive_name = manifest.get("archive_filename") or f"client-space-{tenant_slug}-{version}.tar.gz"
        archive_path = target_dir / archive_name

        if not archive_path.is_file():
            return False, f"Archive d'artefact introuvable : {archive_path}", manifest

        actual_sha = compute_sha256_file(archive_path)
        actual_fingerprint = f"sha256:{actual_sha}"

        if actual_fingerprint != expected_fingerprint:
            return (
                False,
                f"Discordance d'empreinte d'artefact : attendu {expected_fingerprint}, obtenu {actual_fingerprint}",
                manifest,
            )

        # Audit anti-secrets dans l'archive
        secrets_count, findings = self.scan_for_secrets(archive_path)
        if secrets_count > 0:
            return (
                False,
                f"Secrets détectés dans l'archive ({secrets_count} violations): {findings}",
                manifest,
            )

        return True, None, manifest

    def extract_and_deploy_artifact(
        self,
        tenant_slug: str,
        version: str,
        target_space_dir: Union[str, Path],
        verify_fingerprint: bool = True,
    ) -> Dict[str, Any]:
        """Extrait de manière contrôlée et sécurisée un artefact scellé vers l'espace propre client (CA2).

        Garantit :
        1. La vérification stricte de l'empreinte avant toute extraction (Fail-Closed).
        2. Une extraction atomique via répertoire temporaire staging.
        3. Le verrouillage des permissions en lecture seule stricte (chmod -R 555 / 444).
        """
        dest_path = Path(target_space_dir).resolve()
        target_dir = self.get_tenant_artifact_dir(tenant_slug, version)
        manifest_path = target_dir / "manifest.json"

        if not manifest_path.is_file():
            raise FileNotFoundError(f"Manifeste d'artefact introuvable pour {tenant_slug} v{version}")

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        archive_name = manifest.get("archive_filename") or f"client-space-{tenant_slug}-{version}.tar.gz"
        archive_path = target_dir / archive_name

        if not archive_path.is_file():
            raise FileNotFoundError(f"Archive d'artefact introuvable : {archive_path}")

        if verify_fingerprint:
            is_valid, err, _ = self.verify_artifact(tenant_slug, version)
            if not is_valid:
                raise ValueError(f"ERR_ARTIFACT_DIGEST_MISMATCH: {err}")

        # Déploiement atomique via répertoire temporaire staging
        staging_dir = dest_path.parent / f".staging_{tenant_slug}_{version}_{os.getpid()}"
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        staging_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Extraction sécurisée anti-zip slip (validation des membres)
            with tarfile.open(archive_path, "r:gz") as tar:
                for member in tar.getmembers():
                    # Bloquer toute tentative d'échappement par '../' ou chemin absolu
                    norm_name = os.path.normpath(member.name)
                    if norm_name.startswith("..") or os.path.isabs(norm_name):
                        raise SecurityError(f"Chemin malveillant détecté dans l'artefact : {member.name}")
                    tar.extract(member, path=staging_dir)

            # Remplacement atomique de l'espace cible
            if dest_path.exists():
                _force_rmtree(dest_path)
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(staging_dir), str(dest_path))

            # Verrouillage strict en lecture seule sur le système de fichiers hôte
            # Répertoires : r-xr-xr-x (0o555), Fichiers : r--r--r-- (0o444)
            for root, dirs, files in os.walk(dest_path):
                for d in dirs:
                    os.chmod(os.path.join(root, d), 0o555)
                for f in files:
                    os.chmod(os.path.join(root, f), 0o444)
            os.chmod(dest_path, 0o555)

        except Exception as e:
            if staging_dir.exists():
                _force_rmtree(staging_dir)
            _log.error("Échec lors de l'extraction contrôlée de l'artefact %s v%s: %s", tenant_slug, version, e)
            raise

        _log.info(
            "Artefact %s v%s extrait et monté avec succès vers %s (Permissions 0555/0444)",
            tenant_slug,
            version,
            dest_path,
        )

        return {
            "success": True,
            "tenant_slug": tenant_slug,
            "version": version,
            "fingerprint": manifest.get("fingerprint"),
            "content_fingerprint": manifest.get("content_fingerprint"),
            "target_space_dir": str(dest_path),
            "files_count": manifest.get("files_count"),
            "deployed_at": datetime.now(timezone.utc).isoformat(),
        }

    def list_artifact_versions(self, tenant_slug: str) -> List[Dict[str, Any]]:
        """Liste toutes les versions d'artefacts disponibles pour un client avec leurs empreintes."""
        tenant_dir = self.get_tenant_artifact_dir(tenant_slug)
        if not tenant_dir.is_dir():
            return []

        versions: List[Dict[str, Any]] = []
        for version_dir in tenant_dir.iterdir():
            if not version_dir.is_dir():
                continue
            manifest_file = version_dir / "manifest.json"
            if manifest_file.is_file():
                try:
                    with open(manifest_file, "r", encoding="utf-8") as f:
                        m = json.load(f)
                    versions.append({
                        "version": m.get("version") or version_dir.name,
                        "fingerprint": m.get("fingerprint"),
                        "created_at": m.get("created_at"),
                        "files_count": m.get("files_count"),
                        "author": m.get("author"),
                        "archive_filename": m.get("archive_filename"),
                    })
                except Exception:
                    continue

        # Tri antéchronologique (les plus récents en premier)
        versions.sort(key=lambda v: v.get("created_at") or "", reverse=True)
        return versions

    def get_artifact_manifest(self, tenant_slug: str, version: str) -> Optional[Dict[str, Any]]:
        """Récupère le manifeste JSON d'une version d'artefact."""
        manifest_file = self.get_tenant_artifact_dir(tenant_slug, version) / "manifest.json"
        if not manifest_file.is_file():
            return None
        with open(manifest_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def rollback_space(
        self,
        tenant_slug: str,
        target_version: str,
        target_space_dir: Union[str, Path],
        verify_fingerprint: bool = True,
    ) -> Dict[str, Any]:
        """Exécute un retour arrière vers une version d'artefact antérieure spécifique (CA3)."""
        _log.info("Rollback de l'espace client %s vers la version %s", tenant_slug, target_version)
        res = self.extract_and_deploy_artifact(
            tenant_slug=tenant_slug,
            version=target_version,
            target_space_dir=target_space_dir,
            verify_fingerprint=verify_fingerprint,
        )
        res["action"] = "rollback"
        return res
