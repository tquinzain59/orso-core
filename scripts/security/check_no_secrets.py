#!/usr/bin/env python3
"""Contrôle de fuite de secrets (KAN-55, suite de KAN-46 / KAN-49).

Trois audits, tous bloquants (code de sortie 1 dès qu'un contrôle trouve) :

1. **Fichiers interdits** : pages publiques d'administration / supervision et
   documents d'identifiants (``Secrets/``, ``docs/04_Secrets``,
   ``admin.html``, ``monitoring.html``...).
2. **Contenu de l'arbre de travail** : motifs de secrets, quel que soit le nom
   de variable, la présence de guillemets ou l'extension du fichier.
3. **Historique git** : actif par défaut (``--no-history`` pour le couper
   explicitement). Un dépôt superficiel (shallow) est refusé : un audit
   partiel passerait pour un audit complet.

Aucune valeur secrète n'est écrite ici : les motifs décrivent la *forme*
d'un secret (préfixe + longueur), jamais une valeur réelle. Les motifs sont
écrits en ERE POSIX pour être partagés entre ``re`` et ``git log -G``.

Codes de sortie : 0 = propre, 1 = fuite détectée, 2 = audit impossible.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Chemins interdits (relatifs à la racine). Les dossiers le sont en entier.
FORBIDDEN_PATHS: tuple[str, ...] = (
    "Secrets",
    "Secrets/secrets_poc.md",
    "docs/04_Secrets",
)
# Noms de fichiers interdits à n'importe quelle profondeur (artefacts vitrine).
FORBIDDEN_BASENAMES: tuple[str, ...] = (
    "secrets_poc.md",
    "admin.html",
    "monitoring.html",
)


@dataclass(frozen=True)
class SecretPattern:
    name: str
    ere: str  # ERE POSIX : compatible `re` et `git log -G`

    @property
    def regex(self) -> re.Pattern[str]:
        return re.compile(self.ere)


# Un cas de test par motif : tests/security/test_check_no_secrets.py
PATTERNS: tuple[SecretPattern, ...] = (
    SecretPattern("jeton_github", r"gh[pousr]_[A-Za-z0-9]{36,}"),
    SecretPattern("cle_stripe_live", r"[sr]k_live_[A-Za-z0-9]{16,}"),
    SecretPattern("cle_privee", r"-----BEGIN ([A-Z]+ )?PRIVATE KEY-----"),
    # Assemblé pour que le script ne se détecte pas lui-même.
    SecretPattern("identifiants_par_defaut", r"(^|[^A-Za-z0-9_])" + "admin" + ":" + "admin" + r"($|[^A-Za-z0-9_])"),
    # Mot de passe temporaire de démonstration : « Temp<Mot>20NN ».
    SecretPattern("mot_de_passe_temporaire", r"(^|[^A-Za-z0-9])Temp[A-Za-z]{3,}20[0-9]{2}($|[^A-Za-z0-9])"),
)

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache", ".ruff_cache"}
DEFAULT_MAX_FILE_BYTES = 5 * 1024 * 1024
DEFAULT_ALLOWLIST = Path(__file__).with_name("leak_check_allowlist.txt")


@dataclass(frozen=True)
class Finding:
    kind: str  # forbidden | content | history
    where: str
    detail: str

    def render(self) -> str:
        return f"::error:: [{self.kind}] {self.where} : {self.detail}"


class AuditError(RuntimeError):
    """L'audit n'a pas pu s'exécuter (code de sortie 2)."""


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        raise AuditError(f"git {' '.join(args)} a échoué : {proc.stderr.strip()}")
    return proc.stdout


def load_allowlist(path: Path | None) -> tuple[set[str], list[str]]:
    """Retourne (préfixes de commits tolérés, globs de chemins tolérés).

    Format : ``history <sha> # raison`` / ``path <glob> # raison``.
    """
    commits: set[str] = set()
    globs: list[str] = []
    if path is None or not path.is_file():
        return commits, globs
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        kind, _, value = line.partition(" ")
        value = value.strip()
        if kind == "history" and value:
            commits.add(value.lower())
        elif kind == "path" and value:
            globs.append(value)
        else:
            raise AuditError(f"Ligne d'allowlist invalide : {raw!r}")
    return commits, globs


def list_files(root: Path) -> list[Path]:
    """Fichiers de l'arbre (suivis + non ignorés si dépôt git, sinon parcours)."""
    if (root / ".git").exists():
        out = _git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
        return [root / p for p in out.split("\0") if p and (root / p).is_file()]
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        files.extend(Path(dirpath, f) for f in filenames)
    return files


def check_forbidden(root: Path) -> list[Finding]:
    findings = [
        Finding("forbidden", rel, "chemin interdit présent")
        for rel in FORBIDDEN_PATHS
        if (root / rel).exists()
    ]
    for path in list_files(root):
        if path.name in FORBIDDEN_BASENAMES:
            findings.append(Finding("forbidden", str(path.relative_to(root)), "fichier interdit présent"))
    return findings


def scan_text(text: str) -> list[str]:
    """Noms des motifs présents dans ``text`` (sans jamais renvoyer la valeur)."""
    return [p.name for p in PATTERNS if any(p.regex.search(line) for line in text.splitlines())]


def check_content(root: Path, max_bytes: int, path_globs: list[str]) -> tuple[list[Finding], int]:
    findings: list[Finding] = []
    skipped = 0
    for path in list_files(root):
        rel = path.relative_to(root).as_posix()
        if any(fnmatch.fnmatch(rel, g) for g in path_globs):
            continue
        try:
            if path.stat().st_size > max_bytes:
                skipped += 1
                continue
            data = path.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:8192]:  # binaire
            skipped += 1
            continue
        text = data.decode("utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            for pat in PATTERNS:
                if pat.regex.search(line):
                    findings.append(Finding("content", f"{rel}:{lineno}", f"motif {pat.name}"))
    return findings, skipped


def check_history(
    root: Path, allowed_commits: set[str], path_globs: list[str] | None = None
) -> tuple[list[Finding], int]:
    if not (root / ".git").exists():
        raise AuditError("Audit d'historique impossible : pas de dépôt git (utiliser --no-history).")
    if _git(root, "rev-parse", "--is-shallow-repository").strip() == "true":
        raise AuditError(
            "Dépôt superficiel : l'historique est incomplet. "
            "Utiliser `fetch-depth: 0` au checkout (ou --no-history, explicitement)."
        )
    total = int(_git(root, "rev-list", "--all", "--count").strip())
    print(f"[history] analyse de l'historique : {total} commits (toutes références)")

    pathspec = [".", *(f":(exclude,glob){g}" for g in path_globs or [])]
    combined = "|".join(f"({p.ere})" for p in PATTERNS)
    shas = _git(root, "log", "--all", "-G", combined, "--format=%H", "--", *pathspec).split()
    findings: list[Finding] = []
    for sha in shas:
        if any(sha.lower().startswith(a) for a in allowed_commits):
            continue
        diff = _git(root, "show", "--format=", "-U0", "--no-color", sha, "--", *pathspec)
        added = "\n".join(ln[1:] for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
        for name in scan_text(added):
            findings.append(Finding("history", sha[:12], f"motif {name}"))
    return findings, total


def run(
    root: Path,
    *,
    history: bool = True,
    max_bytes: int = DEFAULT_MAX_FILE_BYTES,
    allowlist: Path | None = DEFAULT_ALLOWLIST,
) -> int:
    allowed_commits, path_globs = load_allowlist(allowlist)
    findings = check_forbidden(root)
    content, skipped = check_content(root, max_bytes, path_globs)
    findings += content
    print(f"[content] arbre analysé ({skipped} fichiers binaires ou > {max_bytes} octets ignorés)")
    if history:
        hist, _ = check_history(root, allowed_commits, path_globs)
        findings += hist
    else:
        print("[history] audit d'historique désactivé explicitement (--no-history)")

    for f in findings:
        print(f.render())
    if findings:
        print(f"[✗] {len(findings)} fuite(s) détectée(s)")
        return 1
    print("[✓] Aucun secret ni fichier interdit détecté")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--no-history", action="store_true", help="coupe l'audit d'historique (actif par défaut)")
    parser.add_argument("--max-file-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES)
    parser.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST)
    args = parser.parse_args(argv)
    try:
        return run(
            args.root.resolve(),
            history=not args.no_history,
            max_bytes=args.max_file_bytes,
            allowlist=args.allowlist,
        )
    except AuditError as exc:
        print(f"::error:: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
