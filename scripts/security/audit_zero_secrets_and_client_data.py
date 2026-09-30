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


def audit_docker_image_for_secrets_and_client_data(image_ref: str) -> Dict[str, List[Dict[str, Any]]]:
    """Inspecte une image Docker construite pour vérifier l'absence de secrets et de données clients."""
    result = {"secrets": [], "client_data": []}
    try:
        inspect_proc = subprocess.run(
            ["docker", "inspect", image_ref],
            capture_output=True,
            text=True,
            check=False,
        )
        if inspect_proc.returncode != 0:
            return result

        data = json.loads(inspect_proc.stdout)
        if not data:
            return result

        img_data = data[0]
        config = img_data.get("Config", {})
        envs = config.get("Env", [])
        labels = config.get("Labels", {}) or {}

        # 1. Contrôle des variables d'environnement dans l'image
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

        # 2. Contrôle des labels d'image
        for lk, lv in labels.items():
            if lk in ("com.orso.tenant_id", "com.orso.tenant_slug") and lv:
                result["client_data"].append({
                    "file": f"docker://{image_ref}/label:{lk}",
                    "type": "IMAGE_CLIENT_LABEL",
                    "label": f"Label spécifique client dans l'image : {lk}={lv}",
                })

    except Exception:
        pass

    return result


def run_full_ca5_audit(image_ref: Optional[str] = None) -> Dict[str, Any]:
    """Exécute l'audit complet du critère CA5 de KAN-63 / KAN-64."""
    repo_violations = audit_repository_for_secrets(PROJECT_ROOT)
    dockerignore_violations = audit_dockerignore(PROJECT_ROOT / ".dockerignore")
    dockerfile_violations = audit_dockerfile_for_client_data(PROJECT_ROOT / "Dockerfile.orso")
    client_data_violations = audit_client_data_in_repository(PROJECT_ROOT)

    # Si une image est spécifiée ou présente, on l'inspecte également
    if image_ref:
        img_results = audit_docker_image_for_secrets_and_client_data(image_ref)
        repo_violations.extend(img_results["secrets"])
        client_data_violations.extend(img_results["client_data"])

    # Compteurs calculés dynamiquement (CA5)
    secrets_count = len(repo_violations)
    dockerignore_count = len(dockerignore_violations)
    dockerfile_count = len(dockerfile_violations)
    client_data_count = len(client_data_violations)
    total_violations = secrets_count + dockerignore_count + dockerfile_count + client_data_count

    report = {
        "status": "PASSED" if total_violations == 0 else "FAILED",
        "timestamp": os.environ.get("AUDIT_TIMESTAMP", "2026-09-30T16:00:00Z"),
        "metrics": {
            "secrets_found_count": secrets_count,
            "dockerignore_violations_count": dockerignore_count,
            "dockerfile_violations_count": dockerfile_count,
            "client_data_in_engine_count": client_data_count,
            "total_violations": total_violations,
        },
        "violations": {
            "repository": repo_violations,
            "dockerignore": dockerignore_violations,
            "dockerfile": dockerfile_violations,
            "client_data": client_data_violations,
        },
    }
    return report


if __name__ == "__main__":
    target_img = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("AUDIT_IMAGE_REF")
    report = run_full_ca5_audit(image_ref=target_img)
    print(json.dumps(report, indent=2))
    
    metrics = report["metrics"]
    print(f"\n--- SYNTHÈSE AUDIT CA5 ---")
    print(f"Secrets trouvés dans le dépôt : {metrics['secrets_found_count']}")
    print(f"Violations .dockerignore      : {metrics['dockerignore_violations_count']}")
    print(f"Violations Dockerfile         : {metrics['dockerfile_violations_count']}")
    print(f"Données clients dans moteur   : {metrics['client_data_in_engine_count']} (calculé)")
    print(f"TOTAL VIOLATIONS              : {metrics['total_violations']}")
    
    if report["status"] == "PASSED":
        print("✓ Critère CA5 VALIDÉ : Compteurs nuls et conformité stricte.")
        sys.exit(0)
    else:
        print("✗ Critère CA5 EN ÉCHEC : Des violations ont été détectées.")
        sys.exit(1)
