#!/usr/bin/env python3
"""
Orso Agents - Build & Publish Engine to GHCR (KAN-64 / CA1)
------------------------------------------------------------
Automatise la construction de l'image Docker du moteur Orso,
l'étiquetage humain, la publication vers le registre privé GHCR,
et l'extraction irréfutable du digest SHA-256 OCI immuable.
"""

import os
import sys
import json
import shlex
import argparse
import subprocess
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def get_git_commit_sha() -> str:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--short=7", "HEAD"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return "unknown"


def docker_login_ghcr(username: str, token: str) -> bool:
    """Authentifie le démon Docker local auprès de GHCR."""
    proc = subprocess.Popen(
        ["docker", "login", "ghcr.io", "-u", username, "--password-stdin"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout, stderr = proc.communicate(token)
    if proc.returncode == 0:
        print("[✓] Connexion réussie à GitHub Container Registry (ghcr.io)")
        return True
    else:
        print(f"[!] Échec de connexion GHCR : {stderr.strip() or stdout.strip()}")
        return False


def build_and_publish_engine(
    registry_repo: str = "ghcr.io/tquinzain59/orso-engine",
    version_tag: str = "v1.0.0",
    push: bool = True,
    platform: str = "linux/amd64",
) -> dict:
    git_sha = get_git_commit_sha()
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")

    full_version_tag = f"{version_tag}-{git_sha}"
    calendar_tag = f"release-{today_str}"

    tag_version = f"{registry_repo}:{full_version_tag}"
    tag_calendar = f"{registry_repo}:{calendar_tag}"
    tag_latest = f"{registry_repo}:latest"

    dockerfile_path = PROJECT_ROOT / "Dockerfile.orso"
    if not dockerfile_path.exists():
        raise FileNotFoundError(f"Dockerfile introuvable : {dockerfile_path}")

    print(f"\n=== Construction de l'Image Moteur Orso ===")
    print(f"Plateforme cible : {platform}")
    print(f"Étiquettes       : {full_version_tag}, {calendar_tag}")
    print(f"Répertoire build : {PROJECT_ROOT}\n")

    build_cmd = [
        "docker", "buildx", "build",
        "--platform", platform,
        "-f", str(dockerfile_path),
        "-t", tag_version,
        "-t", tag_calendar,
        "-t", tag_latest,
    ]
    if push:
        build_cmd.append("--push")
    else:
        build_cmd.append("--load")

    build_cmd.append(str(PROJECT_ROOT))

    print(f"[>] Exécution : {' '.join(build_cmd)}")
    build_proc = subprocess.run(build_cmd, capture_output=True, text=True)

    if build_proc.returncode != 0:
        print(f"[!] Erreur de build/push :")
        print(build_proc.stderr)
        return {
            "success": False,
            "returncode": build_proc.returncode,
            "error": build_proc.stderr,
        }

    print("[✓] Build et publication terminés avec succès.")

    # Extraction du digest immuable
    digest = ""
    manifest_cmd = ["docker", "buildx", "imagetools", "inspect", tag_version]
    manifest_proc = subprocess.run(manifest_cmd, capture_output=True, text=True)
    if manifest_proc.returncode == 0:
        for line in manifest_proc.stdout.splitlines():
            if "digest:" in line.lower() or "sha256:" in line.lower():
                for word in line.split():
                    if word.startswith("sha256:"):
                        digest = word.strip()
                        break
            if digest:
                break

    if not digest:
        # Fallback inspection docker inspect
        inspect_proc = subprocess.run(["docker", "inspect", "--format='{{index .RepoDigests 0}}'", tag_version], capture_output=True, text=True)
        if inspect_proc.returncode == 0 and "@sha256:" in inspect_proc.stdout:
            digest = "sha256:" + inspect_proc.stdout.split("@sha256:")[1].strip().strip("'\"")

    result = {
        "success": True,
        "registry_repo": registry_repo,
        "version_tag": full_version_tag,
        "calendar_tag": calendar_tag,
        "target_image": f"{registry_repo}@{digest}" if digest else tag_version,
        "digest": digest,
        "git_commit": git_sha,
        "build_date": datetime.now(timezone.utc).isoformat(),
        "build_output": build_proc.stdout[:500],
    }

    print(f"\n[✓] RÉSULTAT FORMEL PUBLICATION :")
    print(f"Image épinglée : {result['target_image']}")
    print(f"Digest SHA-256 : {result['digest']}")

    return result


def main():
    parser = argparse.ArgumentParser(description="Build and Publish Orso Engine to GHCR")
    parser.add_argument("--repo", default="ghcr.io/tquinzain59/orso-engine")
    parser.add_argument("--version", default="v1.0.0")
    parser.add_argument("--platform", default="linux/amd64")
    parser.add_argument("--no-push", action="store_true", help="Ne pas pousser vers GHCR (build local uniquement)")
    parser.add_argument("--gh-user", default=os.environ.get("GITHUB_ACTOR", "tquinzain59"))
    parser.add_argument("--gh-token", default=os.environ.get("GHCR_PAT") or os.environ.get("GITHUB_PACKAGES_TOKEN"))

    args = parser.parse_args()

    if not args.no_push:
        token = args.gh_token
        if not token and os.path.exists(".env"):
            with open(".env") as f:
                for line in f:
                    if "GHCR_PAT=" in line or "GITHUB_PACKAGES_TOKEN=" in line:
                        token = line.split("=", 1)[1].strip().strip("\"'")
        if token:
            docker_login_ghcr(args.gh_user, token)
        else:
            print("[!] Attention : aucun token GHCR_PAT fourni. Le push échouera si docker login n'a pas été exécuté préalablement.")

    res = build_and_publish_engine(
        registry_repo=args.repo,
        version_tag=args.version,
        push=not args.no_push,
        platform=args.platform,
    )
    print(json.dumps(res, indent=2))
    sys.exit(0 if res.get("success") else 1)


if __name__ == "__main__":
    main()
