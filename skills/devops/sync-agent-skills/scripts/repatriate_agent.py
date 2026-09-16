#!/usr/bin/env python3
"""
repatriate_agent.py: Rapatrie et assainit les compétences, mémoires et personnalités
d'un agent Orso depuis un environnement distant (VPS, conteneur) vers le socle orso-core.

Exemple d'utilisation :
    python -m skills.devops.sync-agent-skills.scripts.repatriate_agent \
        --source /chemin/vers/profiles/jerome \
        --agent jerome \
        --sanitize
"""

import os
import re
import sys
import json
import shutil
import argparse
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple


# Modèles d'exclusion stricte pour la sécurité (Fichiers contenant des secrets)
EXCLUDED_FILE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "auth.json",
    "auth.lock",
    "gateway.pid",
    "gateway.lock",
}

EXCLUDED_EXTENSIONS = {
    ".db-wal",
    ".db-shm",
    ".log",
    ".pyc",
}

# Regex pour détecter les clés API ou tokens sensibles dans les textes
SENSITIVE_PATTERNS = [
    (re.compile(r"sk-or-v1-[a-f0-9]{64}", re.IGNORECASE), "sk-or-v1-REDACTED"),
    (re.compile(r"pat[A-Za-z0-9_]{10,}\.[A-Za-z0-9_]{10,}", re.IGNORECASE), "pat_REDACTED"),
    (re.compile(r"(password\s*[:=]\s*['\"])[^'\"]+(['\"])", re.IGNORECASE), r"\1REDACTED\2"),
    (re.compile(r"(ODOO_PASSWORD\s*=\s*['\"]?)[^\s'\"]+", re.IGNORECASE), r"\1YOUR_ODOO_PASSWORD"),
]

ENV_VAR_PATTERN = re.compile(
    r"(?:export\s+|os\.environ\.get\(['\"]|os\.getenv\(['\"])([A-Z0-9_]{3,})(?:['\"]|\s*=)"
)


class AgentRepatriator:
    """Orchestrateur de rapatriement et de désensibilisation d'un agent."""

    def __init__(
        self,
        source_dir: Path,
        target_root: Path,
        agent_id: str = "jerome",
        sanitize: bool = True,
        dry_run: bool = False,
        export_shared: bool = False,
    ):
        self.source_dir = Path(source_dir).resolve()
        self.target_root = Path(target_root).resolve()
        self.agent_id = agent_id.lower().strip()
        self.sanitize = sanitize
        self.dry_run = dry_run
        self.export_shared = export_shared

        self.skills_source = self._locate_skills_dir()
        self.target_profile_dir = self.target_root / "profiles" / self.agent_id
        self.target_shared_skills = self.target_root / "skills"

    def _locate_skills_dir(self) -> Path:
        """Détermine où se trouvent les compétences dans la source."""
        candidates = [
            self.source_dir / "skills",
            self.source_dir / "profiles" / self.agent_id / "skills",
            self.source_dir,
        ]
        for c in candidates:
            if c.is_dir() and any(c.glob("**/SKILL.md")):
                return c
        return self.source_dir / "skills"

    def is_secret_file(self, file_path: Path) -> bool:
        """Vérifie si un fichier contient des secrets et doit être exclu."""
        name = file_path.name.lower()
        if name in EXCLUDED_FILE_NAMES:
            return True
        if name.startswith(".env"):
            return True
        for ext in EXCLUDED_EXTENSIONS:
            if name.endswith(ext):
                return True
        return False

    def sanitize_text(self, content: str) -> Tuple[str, bool]:
        """Expurge les secrets d'un contenu texte."""
        modified = False
        res = content
        for pattern, replacement in SENSITIVE_PATTERNS:
            new_res, count = pattern.subn(replacement, res)
            if count > 0:
                modified = True
                res = new_res
        return res, modified

    def extract_env_vars(self, content: str) -> Set[str]:
        """Extrait les noms de variables d'environnement requises."""
        found = set()
        for m in ENV_VAR_PATTERN.finditer(content):
            var = m.group(1).strip()
            if var not in ("PATH", "USER", "HOME", "PWD"):
                found.add(var)
        return found

    def copy_file_safely(self, src: Path, dst: Path) -> bool:
        """Copie un fichier en appliquant la désensibilisation si nécessaire."""
        if self.is_secret_file(src):
            return False

        if dst.exists() and dst.samefile(src):
            return True

        if self.dry_run:
            return True

        dst.parent.mkdir(parents=True, exist_ok=True)

        try:
            content = src.read_text(encoding="utf-8")
            if self.sanitize:
                content, _ = self.sanitize_text(content)
            dst.write_text(content, encoding="utf-8")
            return True
        except (UnicodeDecodeError, PermissionError):
            # Fichier binaire ou non décodable UTF-8
            if not self.is_secret_file(src):
                shutil.copy2(src, dst)
                return True
        return False

    def repatriate(self) -> Dict[str, Any]:
        """Exécute l'ensemble du processus de rapatriement."""
        results: Dict[str, Any] = {
            "agent_id": self.agent_id,
            "source": str(self.source_dir),
            "target": str(self.target_root),
            "dry_run": self.dry_run,
            "sanitized": self.sanitize,
            "skills_copied": [],
            "memories_copied": [],
            "secrets_filtered": [],
            "env_vars_detected": [],
        }

        if not self.source_dir.exists():
            raise FileNotFoundError(f"Dossier source introuvable : {self.source_dir}")

        all_env_vars: Set[str] = set()

        # 1. Rapatriement des compétences (skills)
        if self.skills_source.is_dir():
            skill_files = list(self.skills_source.glob("**/SKILL.md"))
            for skill_file in skill_files:
                skill_dir = skill_file.parent
                rel_skill = skill_dir.relative_to(self.skills_source)
                target_skill_dir = self.target_profile_dir / "skills" / rel_skill

                # Copie récursive du skill
                for f in skill_dir.glob("**/*"):
                    if f.is_file():
                        if self.is_secret_file(f):
                            results["secrets_filtered"].append(str(f))
                            continue

                        rel_file = f.relative_to(skill_dir)
                        dst_file = target_skill_dir / rel_file
                        if self.copy_file_safely(f, dst_file):
                            try:
                                text = f.read_text(encoding="utf-8", errors="ignore")
                                all_env_vars.update(self.extract_env_vars(text))
                            except Exception:
                                pass

                results["skills_copied"].append(str(rel_skill))

                # Export optionnel dans skills/ global
                if self.export_shared:
                    shared_dst = self.target_shared_skills / rel_skill
                    for f in skill_dir.glob("**/*"):
                        if f.is_file() and not self.is_secret_file(f):
                            rel_file = f.relative_to(skill_dir)
                            self.copy_file_safely(f, shared_dst / rel_file)

        # 2. Rapatriement des mémoires et de l'âme (SOUL.md / USER.md)
        memories_source = self.source_dir / "memories"
        if not memories_source.is_dir() and (self.source_dir / "profiles" / self.agent_id / "memories").is_dir():
            memories_source = self.source_dir / "profiles" / self.agent_id / "memories"

        if memories_source.is_dir():
            for mem_file in memories_source.glob("*.md"):
                dst_mem = self.target_profile_dir / "memories" / mem_file.name
                if self.copy_file_safely(mem_file, dst_mem):
                    results["memories_copied"].append(str(mem_file.name))

        # Fichier SOUL.md et profile.yaml s'ils existent
        for meta_name in ("SOUL.md", "profile.yaml"):
            meta_src = self.source_dir / meta_name
            if not meta_src.is_file():
                meta_src = self.source_dir / "profiles" / self.agent_id / meta_name
            if meta_src.is_file():
                dst_meta = self.target_profile_dir / meta_name
                if self.copy_file_safely(meta_src, dst_meta):
                    results["memories_copied"].append(meta_name)

        # 3. Génération du gabarit .env.example avec les variables détectées
        if all_env_vars and not self.dry_run:
            env_example_path = self.target_profile_dir / ".env.example"
            existing_vars = set()
            if env_example_path.is_file():
                existing_lines = env_example_path.read_text(encoding="utf-8").splitlines()
                for line in existing_lines:
                    if "=" in line and not line.strip().startswith("#"):
                        existing_vars.add(line.split("=")[0].strip())

            new_vars = sorted(list(all_env_vars - existing_vars))
            if new_vars:
                with open(env_example_path, "a", encoding="utf-8") as fe:
                    fe.write("\n# Variables requises par les compétences rapatriées\n")
                    for nv in new_vars:
                        fe.write(f"{nv}=\n")

        results["env_vars_detected"] = sorted(list(all_env_vars))
        return results


def main():
    parser = argparse.ArgumentParser(description="Rapatriement et désensibilisation des compétences d'agent Orso")
    parser.add_argument("--source", required=True, help="Chemin du dossier source du profil ou conteneur")
    parser.add_argument("--target", default=".", help="Racine du dépôt de destination (défaut: .)")
    parser.add_argument("--agent", default="jerome", help="Identifiant de l'agent (défaut: jerome)")
    parser.add_argument("--no-sanitize", action="store_true", help="Désactiver l'assainissement des secrets")
    parser.add_argument("--dry-run", action="store_true", help="Simuler les opérations sans écrire de fichiers")
    parser.add_argument("--export-shared", action="store_true", help="Exporter également les skills dans skills/")
    parser.add_argument("--json", action="store_true", help="Sortie au format JSON")
    args = parser.parse_args()

    repatriator = AgentRepatriator(
        source_dir=Path(args.source),
        target_root=Path(args.target),
        agent_id=args.agent,
        sanitize=not args.no_sanitize,
        dry_run=args.dry_run,
        export_shared=args.export_shared,
    )

    try:
        res = repatriator.repatriate()
        if args.json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            print("\n" + "=" * 65)
            print(f"  RAPATRIEMENT DES COMPÉTENCES : Agent {args.agent.upper()}")
            print("=" * 65)
            print(f"Source   : {res['source']}")
            print(f"Cible    : {res['target']}")
            print(f"Mode     : {'SIMULATION (Dry-Run)' if res['dry_run'] else 'ÉCRITURE ACTIVE'}")
            print(f"Sécurité : {'Assainissement STRICT des secrets activé' if res['sanitized'] else 'ATTENTION : Non assaini'}")
            print("-" * 65)
            print(f"📦 Compétences rapatriées ({len(res['skills_copied'])}) :")
            for sk in res["skills_copied"]:
                print(f"   • {sk}")
            print(f"🧠 Mémoires & Profils ({len(res['memories_copied'])}) :")
            for mem in res["memories_copied"]:
                print(f"   • {mem}")
            if res["secrets_filtered"]:
                print(f"🛡️  Fichiers sensibles filtrés & exclus ({len(res['secrets_filtered'])}) :")
                for sec in res["secrets_filtered"]:
                    print(f"   ⊘ {sec}")
            if res["env_vars_detected"]:
                print(f"🔑 Variables d'environnement détectées ({len(res['env_vars_detected'])}) :")
                for ev in res["env_vars_detected"]:
                    print(f"   ⚙ {ev}")
            print("=" * 65 + "\n")
    except Exception as e:
        print(f"❌ Erreur lors du rapatriement : {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
