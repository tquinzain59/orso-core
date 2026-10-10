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
from datetime import datetime, timezone
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
    except Exception as e:
        violations.append({
            "file": "git",
            "type": "CLIENT_DATA_CHECK_ERROR",
            "label": f"Impossible d'exécuter git ls-files : {e}",
        })

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
    KAN-66 (CA2, CA3, CA4, CA5) : Inspecte une image Docker construite de façon falsifiable :
    1. Contrôle strict de la référence d'image fournie (non vide).
    2. Inspection Docker (Configuration, Variables d'environnement et Labels).
    3. Extraction réelle et scan de l'arborescence des fichiers via conteneur éphémère (docker create + docker export).
    4. Échec strict (code 1 / FAILED) sans repli silencieux si Docker est inaccessible ou si l'image ne peut être ouverte.
    5. Retourne la liste exhaustive des chemins applicatifs parcourus dans l'image et leur décompte calculé.
    """
    result: Dict[str, Any] = {
        "secrets": [],
        "client_data": [],
        "errors": [],
        "scanned_files_count": 0,
        "scanned_paths": [],
        "applicative_paths": [],
    }

    if not image_ref or not isinstance(image_ref, str) or not image_ref.strip():
        result["errors"].append({
            "type": "EMPTY_IMAGE_REF",
            "file": "cli_or_env",
            "label": "Référence d'image Docker vide ou non renseignée.",
        })
        return result

    clean_ref = image_ref.strip()

    # 1. Inspection Docker (Environnement et Labels)
    try:
        inspect_proc = subprocess.run(
            ["docker", "inspect", clean_ref],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as e:
        result["errors"].append({
            "type": "DOCKER_INSPECT_EXECUTION_ERROR",
            "file": f"docker://{clean_ref}",
            "label": f"Échec d'exécution de docker inspect : {type(e).__name__}: {e}",
        })
        return result

    if inspect_proc.returncode != 0:
        err_msg = inspect_proc.stderr.strip() or "Image introuvable ou démon Docker inaccessible"
        result["errors"].append({
            "type": "IMAGE_INSPECT_FAILED",
            "file": f"docker://{clean_ref}",
            "label": f"Échec docker inspect ({inspect_proc.returncode}) : {err_msg}",
        })
        return result

    try:
        data = json.loads(inspect_proc.stdout)
        if not data:
            result["errors"].append({
                "type": "IMAGE_INSPECT_EMPTY",
                "file": f"docker://{clean_ref}",
                "label": "Sortie docker inspect vide (aucun objet inspecté).",
            })
            return result
        img_data = data[0]
    except Exception as e:
        result["errors"].append({
            "type": "IMAGE_INSPECT_PARSE_ERROR",
            "file": f"docker://{clean_ref}",
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
                    "file": f"docker://{clean_ref}/env:{k}",
                    "type": "IMAGE_ENV_SECRET",
                    "label": label,
                })
        if k in ("ORSO_CLIENT_ID", "ORSO_CLIENT_SLUG") and v:
            result["client_data"].append({
                "file": f"docker://{clean_ref}/env:{k}",
                "type": "IMAGE_CLIENT_DATA",
                "label": f"Variable spécifique client figée dans l'image : {k}={v}",
            })

    for lk, lv in labels.items():
        if lk in ("com.orso.tenant_id", "com.orso.tenant_slug") and lv:
            result["client_data"].append({
                "file": f"docker://{clean_ref}/label:{lk}",
                "type": "IMAGE_CLIENT_LABEL",
                "label": f"Label spécifique client dans l'image : {lk}={lv}",
            })

    # 2. Scan physique de l'arborescence de l'image (docker create + docker export)
    try:
        create_proc = subprocess.run(
            ["docker", "create", clean_ref],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as e:
        result["errors"].append({
            "type": "CONTAINER_CREATE_EXECUTION_ERROR",
            "file": f"docker://{clean_ref}",
            "label": f"Échec d'exécution de docker create : {type(e).__name__}: {e}",
        })
        return result

    if create_proc.returncode != 0:
        result["errors"].append({
            "type": "CONTAINER_CREATE_FAILED",
            "file": f"docker://{clean_ref}",
            "label": f"Impossible de créer le conteneur éphémère pour inspection ({create_proc.returncode}) : {create_proc.stderr.strip()}",
        })
        return result

    cid = create_proc.stdout.strip()
    try:
        try:
            export_proc = subprocess.Popen(
                ["docker", "export", cid],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception as e:
            result["errors"].append({
                "type": "IMAGE_EXPORT_EXECUTION_ERROR",
                "file": f"docker://{clean_ref}",
                "label": f"Échec d'exécution de docker export : {type(e).__name__}: {e}",
            })
            return result

        if export_proc.stdout:
            try:
                with tarfile.open(mode="r|*", fileobj=export_proc.stdout) as tar:
                    files_scanned = 0
                    for member in tar:
                        files_scanned += 1
                        name = member.name.lstrip("./")
                        result["scanned_paths"].append(name)

                        # Classification des chemins applicatifs (CA2)
                        # Dans Dockerfile.orso, WORKDIR est /app (ex: app/run_agent.py, app/Dockerfile.orso)
                        is_system = (
                            name in ("bin", "sbin", "lib", "usr", "etc", "dev", "proc", "sys", "var", "run", "tmp", "media", "mnt", "srv", "root", "home", "dockerenv")
                            or name.startswith(("bin/", "sbin/", "lib/", "usr/", "etc/", "dev/", "proc/", "sys/", "var/", "run/", "tmp/", "media/", "mnt/", "srv/"))
                        )
                        is_app_path = (name == "app" or name.startswith("app/") or name.startswith("opt/orso/")) or not is_system

                        if is_app_path and not member.isdir():
                            result["applicative_paths"].append(name)

                        # Contrôle : Fichiers sensibles interdits (en excluant les certificats CA publics de l'OS ou de certifi)
                        is_system_ca = (
                            name.startswith(("etc/ssl", "usr/share/ca-certificates/", "etc/pki/", "usr/lib/ssl/"))
                            or name.endswith("cacert.pem")
                            or name.endswith("cert.pem")
                        )
                        for rule in MANDATORY_DOCKERIGNORE_RULES:
                            clean_rule = rule.replace("*", "")
                            if (name == clean_rule or name.endswith(clean_rule)) and not member.isdir():
                                if is_system_ca and clean_rule == ".pem":
                                    continue
                                result["secrets"].append({
                                    "file": f"docker://{clean_ref}/{name}",
                                    "type": "IMAGE_FORBIDDEN_FILE",
                                    "label": f"Fichier sensible interdit trouvé dans l'arborescence : {name}",
                                })

                        # Contrôle : Données clients et DBs
                        if any(b in name for b in ["consignes_olympe.jsonl", "tenant_secrets.json"]):
                            result["client_data"].append({
                                "file": f"docker://{clean_ref}/{name}",
                                "type": "IMAGE_CLIENT_DATA_FILE",
                                "label": f"Fichier de données client interdit dans l'image : {name}",
                            })

                        if name.endswith((".db", ".sqlite", ".sqlite3")) and ("data/" in name or "profiles/" in name or "tenants/" in name):
                            result["client_data"].append({
                                "file": f"docker://{clean_ref}/{name}",
                                "type": "IMAGE_CLIENT_DATABASE",
                                "label": f"Base de données client détectée dans l'image : {name}",
                            })

                        # Contrôle : Scan de secrets dans les fichiers texte applicatifs
                        if member.isfile() and member.size < 500_000:
                            if name.endswith((".py", ".json", ".yaml", ".yml", ".sh", ".toml", ".env", ".md", ".txt", ".cfg", ".ini")):
                                try:
                                    f_obj = tar.extractfile(member)
                                    if f_obj:
                                        raw_bytes = f_obj.read()
                                        content = raw_bytes.decode("utf-8", errors="replace")
                                        for pattern, label in SECRET_PATTERNS:
                                            if pattern.search(content):
                                                result["secrets"].append({
                                                    "file": f"docker://{clean_ref}/{name}",
                                                    "type": "IMAGE_FILE_SECRET_LEAK",
                                                    "label": f"{label} trouvé dans {name}",
                                                })
                                except Exception as read_err:
                                    # CA4 : Aucun rattrapage silencieux, erreur explicitement nommée
                                    result["errors"].append({
                                        "type": "IMAGE_FILE_READ_ERROR",
                                        "file": f"docker://{clean_ref}/{name}",
                                        "label": f"Erreur lors de la lecture du fichier applicatif {name} : {type(read_err).__name__}: {read_err}",
                                    })
                    result["scanned_files_count"] = files_scanned
            except Exception as tar_err:
                # CA4 : Erreur tar explicitement nommée
                result["errors"].append({
                    "type": "IMAGE_TAR_SCAN_ERROR",
                    "file": f"docker://{clean_ref}",
                    "label": f"Erreur lors du scan du flux tar de l'image : {type(tar_err).__name__}: {tar_err}",
                })

        export_proc.wait()
        if export_proc.returncode != 0:
            err_msg = export_proc.stderr.read().decode("utf-8", errors="ignore") if export_proc.stderr else ""
            result["errors"].append({
                "type": "IMAGE_EXPORT_FAILED",
                "file": f"docker://{clean_ref}",
                "label": f"Échec de l'export du conteneur ({export_proc.returncode}) : {err_msg.strip()}",
            })
    finally:
        subprocess.run(["docker", "rm", "-f", cid], capture_output=True, check=False)

    return result


def run_full_ca5_audit(
    image_ref: Optional[str] = None,
    require_image: bool = True,
) -> Dict[str, Any]:
    """
    Exécute l'audit complet du critère CA5 de KAN-63 / KAN-66 :
    - Scan de secrets dans le dépôt (audit_repository_for_secrets)
    - Conformité .dockerignore (audit_dockerignore)
    - Conformité Dockerfile.orso (audit_dockerfile_for_client_data)
    - Recherche de données client dans le dépôt (audit_client_data_in_repository)
    - Inspection falsifiable de l'image Docker (audit_docker_image_for_secrets_and_client_data)
    """
    repo_violations = audit_repository_for_secrets(PROJECT_ROOT)
    dockerignore_violations = audit_dockerignore(PROJECT_ROOT / ".dockerignore")
    dockerfile_violations = audit_dockerfile_for_client_data(PROJECT_ROOT / "Dockerfile.orso")
    client_data_violations = audit_client_data_in_repository(PROJECT_ROOT)
    image_scan_errors = []
    scanned_image_files = 0
    scanned_paths: List[str] = []
    applicative_paths: List[str] = []

    target_image = image_ref.strip() if (image_ref and isinstance(image_ref, str)) else None

    # CA1 : Si require_image est activé et qu'aucune image n'est passée, erreur bloquante
    if require_image and not target_image:
        image_scan_errors.append({
            "type": "MISSING_REQUIRED_IMAGE",
            "file": "cli_or_env",
            "label": "Référence d'image Docker obligatoire pour l'audit : aucune référence fournie.",
        })

    if target_image:
        img_results = audit_docker_image_for_secrets_and_client_data(target_image)
        repo_violations.extend(img_results.get("secrets", []))
        client_data_violations.extend(img_results.get("client_data", []))
        image_scan_errors.extend(img_results.get("errors", []))
        scanned_image_files = img_results.get("scanned_files_count", 0)
        scanned_paths = img_results.get("scanned_paths", [])
        applicative_paths = img_results.get("applicative_paths", [])

    # Compteurs calculés dynamiquement (CA5)
    secrets_count = len(repo_violations)
    dockerignore_count = len(dockerignore_violations)
    dockerfile_count = len(dockerfile_violations)
    client_data_count = len(client_data_violations)
    errors_count = len(image_scan_errors)
    total_violations = secrets_count + dockerignore_count + dockerfile_count + client_data_count + errors_count

    report = {
        "status": "PASSED" if total_violations == 0 else "FAILED",
        "timestamp": os.environ.get("AUDIT_TIMESTAMP", datetime.now(timezone.utc).isoformat()),
        "metrics": {
            "secrets_found_count": secrets_count,
            "dockerignore_violations_count": dockerignore_count,
            "dockerfile_violations_count": dockerfile_count,
            "client_data_in_engine_count": client_data_count,
            "client_data_calculation_source": "len(client_data_violations) via audit_client_data_in_repository + audit_docker_image_for_secrets_and_client_data",
            "image_scan_errors_count": errors_count,
            "image_scanned_files_count": scanned_image_files,
            "image_scanned_paths_count": len(scanned_paths),
            "image_applicative_paths_count": len(applicative_paths),
            "total_violations": total_violations,
        },
        "violations": {
            "repository": repo_violations,
            "dockerignore": dockerignore_violations,
            "dockerfile": dockerfile_violations,
            "client_data": client_data_violations,
            "image_scan_errors": image_scan_errors,
        },
        "image_inspection": {
            "image_ref": target_image,
            "scanned_paths_count": len(scanned_paths),
            "applicative_paths_count": len(applicative_paths),
            "applicative_paths": applicative_paths,
            "scanned_paths_sample": scanned_paths[:100],
        },
    }
    return report


if __name__ == "__main__":
    # CA1 : La preuve exige une référence d'image explicite sur la ligne de commande.
    # Une exécution sans référence sort en erreur explicite avec code retour non nul.
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        sys.stderr.write("✗ Erreur CA1 : Référence d'image Docker obligatoire. Aucune référence fournie sur la ligne de commande.\n")
        sys.stderr.write("Usage: python3 scripts/security/audit_zero_secrets_and_client_data.py <image_ref>\n")
        sys.stderr.write("Exemple: python3 scripts/security/audit_zero_secrets_and_client_data.py ghcr.io/tquinzain59/orso-engine@sha256:4506ccd6f51e68d3bf799c2a5b17d82916dc5cc285080f2fcf9c07046e2b904f\n")
        sys.exit(1)

    target_img = sys.argv[1].strip()
    report = run_full_ca5_audit(image_ref=target_img, require_image=True)
    print(json.dumps(report, indent=2))

    metrics = report["metrics"]
    print(f"\n--- SYNTHÈSE AUDIT CONFORMITÉ IMAGE (KAN-66) ---")
    print(f"Image inspectée                 : {target_img}")
    print(f"Total chemins parcourus         : {metrics['image_scanned_paths_count']}")
    print(f"Chemins applicatifs inspectés   : {metrics['image_applicative_paths_count']}")
    print(f"Secrets trouvés dans le dépôt   : {metrics['secrets_found_count']}")
    print(f"Violations .dockerignore        : {metrics['dockerignore_violations_count']}")
    print(f"Violations Dockerfile           : {metrics['dockerfile_violations_count']}")
    print(f"Données clients dans moteur     : {metrics['client_data_in_engine_count']} (calculé par audit_client_data_in_repository + audit_docker_image_for_secrets_and_client_data)")
    print(f"Erreurs d'ouverture d'image     : {metrics['image_scan_errors_count']}")
    print(f"TOTAL VIOLATIONS                : {metrics['total_violations']}")

    # CA4 : Affichage explicite des erreurs d'ouverture avec motif nommé
    if report["violations"]["image_scan_errors"]:
        print("\n--- DÉTAIL DES ERREURS D'OUVERTURE D'ARTEFACT (CA3 / CA4) ---")
        for i, err in enumerate(report["violations"]["image_scan_errors"], 1):
            print(f"[{i}] Type  : {err.get('type')}")
            print(f"    Cible : {err.get('file')}")
            print(f"    Motif : {err.get('label')}")

    # CA2 : Preuve par la liste des chemins parcourus dans l'image
    app_paths = report.get("image_inspection", {}).get("applicative_paths", [])
    if app_paths:
        print(f"\n--- ARBORESCENCE APPLICATIVE INSPECTÉE DANS L'IMAGE (CA2 : {len(app_paths)} chemins) ---")
        for p in app_paths:
            print(f"  ✓ {p}")

    if report["status"] == "PASSED":
        print("\n✓ Critère CA5 VALIDÉ : Compteurs nuls, arborescence inspectée et conformité stricte.")
        sys.exit(0)
    else:
        print("\n✗ Audit EN ÉCHEC : Des violations ou erreurs d'ouverture ont été détectées.")
        sys.exit(1)

