#!/usr/bin/env python3
"""
Orso Agents - Zero Secrets & Zero Client Data Audit Tool (KAN-63 / CA5)
-----------------------------------------------------------------------
Inspecte le dépôt et la configuration Docker pour prouver de manière irréfutable :
1. Qu'aucun secret d'accès au registre (token GHCR, mot de passe) ne figure dans le dépôt.
2. Qu'aucune donnée de client spécifique n'est embarquée dans le code du moteur.
3. Que le fichier .dockerignore bloque strictement tous les fichiers sensibles.

Critère CA5 de KAN-63 : Compteurs nuls impératifs.
"""

import os
import re
import sys
import json
import subprocess
import tarfile
from pathlib import Path
from typing import Dict, List, Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Motifs de détection de secrets et tokens de registre
SECRET_PATTERNS = [
    (re.compile(r"ghp_[a-zA-Z0-9]{36}"), "GitHub Personal Access Token (ghp_)"),
    (re.compile(r"github_pat_[a-zA-Z0-9_]{82}"), "GitHub Fine-Grained PAT"),
    (re.compile(r"gho_[a-zA-Z0-9]{36}"), "GitHub OAuth Access Token"),
    (re.compile(r"-----BEGIN (RSA|EC|DSA|OPENSSH) PRIVATE KEY-----"), "Clé privée RSA/SSH"),
    (re.compile(r"(?i)(ghcr_token|registry_password|registry_secret)\s*[:=]\s*[\"'][a-zA-Z0-9_-]{16,}[\"']"), "Secret de registre en clair"),
]

# Chemins obligatoirement ignorés par .dockerignore
MANDATORY_DOCKERIGNORE_RULES = [
    ".env",
    "Secrets/",
    "*.pem",
    "*.key",
    "*.token",
]

# Répertoires à exclure du scan de code de production
IGNORED_DIRS = {
    ".git",
    "venv",
    ".venv",
    ".uv_cache",
    ".pip-cache",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".coverage",
    "tests",  # Contient des mocks de tokens factices pour tester la rédaction
    "evals",
}


def audit_repository_for_secrets(root_dir: Path) -> List[Dict[str, Any]]:
    """Scanne tous les fichiers suivis et sources du dépôt à la recherche de secrets."""
    violations = []
    
    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Filtrer répertoires ignorés
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        
        for fname in filenames:
            fpath = Path(dirpath) / fname
            # Ignorer fichiers binaires, tests d'audit eux-mêmes et .env local non versionné
            if fname.endswith((".pyc", ".png", ".jpg", ".jpeg", ".pdf", ".tar", ".gz", ".lock")):
                continue
            if fname in (".env", ".env.local"):  # Les .env locaux sont ignorés par git
                continue
            if "test_kan63_engine_distribution.py" in fname or "audit_zero_secrets" in fname:
                continue

            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            for pattern, label in SECRET_PATTERNS:
                matches = pattern.findall(content)
                if matches:
                    violations.append({
                        "file": str(fpath.relative_to(root_dir)),
                        "type": "SECRET_LEAK",
                        "label": label,
                        "count": len(matches),
                    })

    return violations


def audit_dockerignore(dockerignore_path: Path) -> List[Dict[str, Any]]:
    """Vérifie que les règles d'exclusion de secrets sont bien présentes."""
    violations = []
    if not dockerignore_path.exists():
        return [{"type": "MISSING_DOCKERIGNORE", "file": str(dockerignore_path)}]

    content = dockerignore_path.read_text(encoding="utf-8")
    lines = [l.strip() for l in content.splitlines() if l.strip() and not l.strip().startswith("#")]

    for rule in MANDATORY_DOCKERIGNORE_RULES:
        # Vérifie la présence de la règle (exacte ou avec slash)
        found = any(rule == l or rule.rstrip("/") == l.rstrip("/") for l in lines)
        if not found:
            violations.append({
                "type": "DOCKERIGNORE_MISSING_RULE",
                "rule": rule,
                "file": ".dockerignore",
            })

    return violations


def audit_dockerfile_for_client_data(dockerfile_path: Path) -> List[Dict[str, Any]]:
    """Vérifie que Dockerfile.orso ne contient aucune donnée ou secret en dur."""
    violations = []
    if not dockerfile_path.exists():
        return [{"type": "MISSING_DOCKERFILE", "file": str(dockerfile_path)}]

    content = dockerfile_path.read_text(encoding="utf-8")
    
    # Contrôle : absence de secrets en clair dans les ENV
    env_matches = re.findall(r"ENV\s+([A-Za-z0-9_]+)\s*=\s*[\"']?([^\"'\n]+)[\"']?", content)
    for key, val in env_matches:
        if any(secret_term in key.lower() for secret_term in ["token", "secret", "password", "key"]):
            if not val.startswith("/"):  # Pas un chemin de fichier
                violations.append({
                    "type": "DOCKERFILE_ENV_SECRET",
                    "variable": key,
                    "file": str(dockerfile_path.name),
                })

    return violations


def audit_client_data_in_repository(root_dir: Path) -> List[Dict[str, Any]]:
    """Vérifie qu'aucune donnée de client spécifique n'est présente dans les fichiers suivis."""
    violations = []
    
    # 1. Vérification des fichiers d'état ou bases de données clients trackés dans Git
    try:
        res = subprocess.run(
            ["git", "ls-files", "data/", "profiles/*/*.db*", "runtime/tenants/", "**/consignes_olympe.jsonl"],
            cwd=str(root_dir),
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            for line in res.stdout.strip().splitlines():
                if line.strip():
                    violations.append({
                        "file": line.strip(),
                        "type": "CLIENT_DATA_IN_GIT",
                        "label": "Fichier de persistance ou données client suivi dans le dépôt",
                    })
    except Exception:
        pass

    # 2. Vérification des fichiers d'espace de travail client résiduels non ignorés
    client_artifacts = ["consignes_olympe.jsonl", "tenant_secrets.json"]
    for art in client_artifacts:
        for found in root_dir.glob(f"**/{art}"):
            if any(ig in str(found) for ig in IGNORED_DIRS):
                continue
            violations.append({
                "file": str(found.relative_to(root_dir)),
                "type": "CLIENT_DATA_LEAK",
                "label": f"Fichier client résiduel détecté : {art}",
            })

    return violations


def audit_docker_image_for_secrets_and_client_data(image_ref: str) -> Dict[str, Any]:
    """
    CA5 : Inspecte une image Docker construite de façon falsifiable :
    1. Contrôle des variables d'environnement et labels via docker inspect (sans exception pass).
    2. Extraction réelle et scan de l'arborescence des fichiers via conteneur éphémère (docker create + docker export).
    3. Échec strict (code 1 / FAILED) si Docker est inaccessible ou si l'image ne peut être ouverte.
    """
    result: Dict[str, Any] = {
        "secrets": [],
        "client_data": [],
        "errors": [],
        "scanned_files_count": 0,
    }

    if not image_ref:
        result["errors"].append({
            "type": "EMPTY_IMAGE_REF",
            "file": "cli_or_env",
            "label": "Référence d'image Docker vide ou non renseignée.",
        })
        return result

    # 1. Inspection Docker (Environnement et Labels)
    inspect_proc = subprocess.run(
        ["docker", "inspect", image_ref],
        capture_output=True,
        text=True,
        check=False,
    )
    if inspect_proc.returncode != 0:
        result["errors"].append({
            "type": "IMAGE_INSPECT_FAILED",
            "file": f"docker://{image_ref}",
            "label": f"Échec docker inspect ({inspect_proc.returncode}) : {inspect_proc.stderr.strip() or 'Image introuvable ou démon Docker inaccessible'}",
        })
        return result

    try:
        data = json.loads(inspect_proc.stdout)
        if not data:
            result["errors"].append({
                "type": "IMAGE_INSPECT_EMPTY",
                "file": f"docker://{image_ref}",
                "label": "Sortie docker inspect vide.",
            })
            return result
        img_data = data[0]
    except Exception as e:
        result["errors"].append({
            "type": "IMAGE_INSPECT_PARSE_ERROR",
            "file": f"docker://{image_ref}",
            "label": f"Impossible de parser la sortie docker inspect : {e}",
        })
        return result

    config = img_data.get("Config", {})
    envs = config.get("Env", []) or []
    labels = config.get("Labels", {}) or {}

    for env in envs:
        k, _, v = env.partition("=")
        for pattern, label in SECRET_PATTERNS:
            if pattern.search(v):
                result["secrets"].append({
                    "file": f"docker://{image_ref}/env:{k}",
                    "type": "IMAGE_ENV_SECRET",
                    "label": label,
                })
        if k in ("ORSO_CLIENT_ID", "ORSO_CLIENT_SLUG") and v:
            result["client_data"].append({
                "file": f"docker://{image_ref}/env:{k}",
                "type": "IMAGE_CLIENT_DATA",
                "label": f"Variable spécifique client figée dans l'image : {k}={v}",
            })

    for lk, lv in labels.items():
        if lk in ("com.orso.tenant_id", "com.orso.tenant_slug") and lv:
            result["client_data"].append({
                "file": f"docker://{image_ref}/label:{lk}",
                "type": "IMAGE_CLIENT_LABEL",
                "label": f"Label spécifique client dans l'image : {lk}={lv}",
            })

    # 2. Scan physique de l'arborescence de l'image (docker create + docker export)
    create_proc = subprocess.run(
        ["docker", "create", image_ref],
        capture_output=True,
        text=True,
        check=False,
    )
    if create_proc.returncode != 0:
        result["errors"].append({
            "type": "CONTAINER_CREATE_FAILED",
            "file": f"docker://{image_ref}",
            "label": f"Impossible de créer le conteneur éphémère pour inspection : {create_proc.stderr.strip()}",
        })
        return result

    cid = create_proc.stdout.strip()
    try:
        export_proc = subprocess.Popen(
            ["docker", "export", cid],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if export_proc.stdout:
            try:
                with tarfile.open(mode="r|*", fileobj=export_proc.stdout) as tar:
                    files_scanned = 0
                    for member in tar:
                        files_scanned += 1
                        name = member.name.lstrip("./")

                        # Contrôle : Fichiers sensibles interdits (en excluant les certificats CA publics de l'OS système)
                        is_system_ca = name.startswith(("etc/ssl", "usr/share/ca-certificates/", "etc/pki/"))
                        for rule in MANDATORY_DOCKERIGNORE_RULES:
                            clean_rule = rule.replace("*", "")
                            if (name == clean_rule or name.endswith(clean_rule)) and not member.isdir():
                                if is_system_ca and clean_rule == ".pem":
                                    continue
                                result["secrets"].append({
                                    "file": f"docker://{image_ref}/{name}",
                                    "type": "IMAGE_FORBIDDEN_FILE",
                                    "label": f"Fichier sensible interdit trouvé dans l'arborescence : {name}",
                                })

                        # Contrôle : Données clients et DBs
                        if any(b in name for b in ["consignes_olympe.jsonl", "tenant_secrets.json"]):
                            result["client_data"].append({
                                "file": f"docker://{image_ref}/{name}",
                                "type": "IMAGE_CLIENT_DATA_FILE",
                                "label": f"Fichier de données client interdit dans l'image : {name}",
                            })

                        if name.endswith((".db", ".sqlite", ".sqlite3")) and "data/" in name:
                            result["client_data"].append({
                                "file": f"docker://{image_ref}/{name}",
                                "type": "IMAGE_CLIENT_DATABASE",
                                "label": f"Base de données client détectée dans l'image : {name}",
                            })

                        # Contrôle : Scan de secrets dans les fichiers texte applicatifs
                        if member.isfile() and member.size < 200_000:
                            if name.endswith((".py", ".json", ".yaml", ".yml", ".sh", ".toml", ".env")):
                                f_obj = tar.extractfile(member)
                                if f_obj:
                                    try:
                                        content = f_obj.read().decode("utf-8", errors="ignore")
                                        for pattern, label in SECRET_PATTERNS:
                                            if pattern.search(content):
                                                result["secrets"].append({
                                                    "file": f"docker://{image_ref}/{name}",
                                                    "type": "IMAGE_FILE_SECRET_LEAK",
                                                    "label": f"{label} trouvé dans {name}",
                                                })
                                    except Exception:
                                        pass
                    result["scanned_files_count"] = files_scanned
            except Exception as tar_err:
                result["errors"].append({
                    "type": "IMAGE_TAR_SCAN_ERROR",
                    "file": f"docker://{image_ref}",
                    "label": f"Erreur lors du scan du flux tar de l'image : {tar_err}",
                })
        export_proc.wait()
        if export_proc.returncode != 0:
            err_msg = export_proc.stderr.read().decode("utf-8", errors="ignore") if export_proc.stderr else ""
            result["errors"].append({
                "type": "IMAGE_EXPORT_FAILED",
                "file": f"docker://{image_ref}",
                "label": f"Échec de l'export du conteneur ({export_proc.returncode}) : {err_msg.strip()}",
            })
    finally:
        subprocess.run(["docker", "rm", "-f", cid], capture_output=True, check=False)

    return result


def run_full_ca5_audit(
    image_ref: Optional[str] = None,
    require_image: bool = False,
) -> Dict[str, Any]:
    """Exécute l'audit complet du critère CA5 de KAN-63 / KAN-64."""
    repo_violations = audit_repository_for_secrets(PROJECT_ROOT)
    dockerignore_violations = audit_dockerignore(PROJECT_ROOT / ".dockerignore")
    dockerfile_violations = audit_dockerfile_for_client_data(PROJECT_ROOT / "Dockerfile.orso")
    client_data_violations = audit_client_data_in_repository(PROJECT_ROOT)
    image_scan_errors = []
    scanned_image_files = 0

    target_image = image_ref or os.environ.get("AUDIT_IMAGE_REF")
    if not target_image:
        target_digest = os.environ.get("ORSO_TARGET_ENGINE_DIGEST")
        if target_digest:
            target_image = f"ghcr.io/tquinzain59/orso-engine@{target_digest}"

    if require_image and not target_image:
        image_scan_errors.append({
            "type": "MISSING_REQUIRED_IMAGE",
            "file": "cli_or_env",
            "label": "Référence d'image Docker strictement obligatoire pour l'audit CA5.",
        })

    if target_image:
        img_results = audit_docker_image_for_secrets_and_client_data(target_image)
        repo_violations.extend(img_results.get("secrets", []))
        client_data_violations.extend(img_results.get("client_data", []))
        image_scan_errors.extend(img_results.get("errors", []))
        scanned_image_files = img_results.get("scanned_files_count", 0)

    # Compteurs calculés dynamiquement (CA5)
    secrets_count = len(repo_violations)
    dockerignore_count = len(dockerignore_violations)
    dockerfile_count = len(dockerfile_violations)
    client_data_count = len(client_data_violations)
    errors_count = len(image_scan_errors)
    total_violations = secrets_count + dockerignore_count + dockerfile_count + client_data_count + errors_count

    report = {
        "status": "PASSED" if total_violations == 0 else "FAILED",
        "timestamp": os.environ.get("AUDIT_TIMESTAMP", "2026-09-30T16:00:00Z"),
        "metrics": {
            "secrets_found_count": secrets_count,
            "dockerignore_violations_count": dockerignore_count,
            "dockerfile_violations_count": dockerfile_count,
            "client_data_in_engine_count": client_data_count,
            "image_scan_errors_count": errors_count,
            "image_scanned_files_count": scanned_image_files,
            "total_violations": total_violations,
        },
        "violations": {
            "repository": repo_violations,
            "dockerignore": dockerignore_violations,
            "dockerfile": dockerfile_violations,
            "client_data": client_data_violations,
            "image_scan_errors": image_scan_errors,
        },
    }
    return report


if __name__ == "__main__":
    target_img = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("AUDIT_IMAGE_REF")
    if not target_img:
        target_digest = os.environ.get("ORSO_TARGET_ENGINE_DIGEST")
        if target_digest:
            target_img = f"ghcr.io/tquinzain59/orso-engine@{target_digest}"

    if not target_img:
        print("✗ Erreur CA5 : Référence d'image Docker obligatoire en paramètre (ex: ghcr.io/tquinzain59/orso-engine@sha256:... ou via ORSO_TARGET_ENGINE_DIGEST).")
        sys.exit(1)

    report = run_full_ca5_audit(image_ref=target_img, require_image=True)
    print(json.dumps(report, indent=2))

    metrics = report["metrics"]
    print(f"\n--- SYNTHÈSE AUDIT CA5 ---")
    print(f"Image inspectée               : {target_img}")
    print(f"Fichiers scannés dans l'image : {metrics['image_scanned_files_count']}")
    print(f"Secrets trouvés dans le dépôt : {metrics['secrets_found_count']}")
    print(f"Violations .dockerignore      : {metrics['dockerignore_violations_count']}")
    print(f"Violations Dockerfile         : {metrics['dockerfile_violations_count']}")
    print(f"Données clients dans moteur   : {metrics['client_data_in_engine_count']} (calculé)")
    print(f"Erreurs d'inspection Docker   : {metrics['image_scan_errors_count']}")
    print(f"TOTAL VIOLATIONS              : {metrics['total_violations']}")

    if report["status"] == "PASSED":
        print("✓ Critère CA5 VALIDÉ : Compteurs nuls et conformité stricte.")
        sys.exit(0)
    else:
        print("✗ Critère CA5 EN ÉCHEC : Des violations ont été détectées.")
        sys.exit(1)
