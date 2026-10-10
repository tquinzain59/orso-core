#!/usr/bin/env python3
"""
Orso Agents - Module d'Intégrité et de Surveillance des Personas SOUL.md (KAN-33).

Ce module garantit l'immutabilité et l'intégrité cryptographique des personnalités d'agents :
1. Calcul et vérification de l'empreinte SHA-256 ET signature HMAC-SHA256 au démarrage (R3, R4).
2. Refus de démarrage immédiat (Fail-Closed) en cas d'écart avec code d'événement PER-INTEGRITY-001 (CA4).
3. Surveillance continue périodique à l'exécution avec alerte PER-INTEGRITY-002 et arrêt forcé du conteneur (R6, CA6).
4. Détection et purge de tout fichier SOUL.md illégitime dans les répertoires inscriptibles (repli ambient).
5. Journalisation probante de chaque démarrage dans la télémétrie (R7, CA8).
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("orso.persona_integrity")

DEFAULT_LOCK_FILENAME = "personas.lock.json"
EVENT_OK = "PER-INTEGRITY-000"
EVENT_STARTUP_MISMATCH = "PER-INTEGRITY-001"
EVENT_RUNTIME_ALTERATION = "PER-INTEGRITY-002"
EVENT_CONFIG_ERROR = "PER-INTEGRITY-003"
EVENT_ROGUE_PERSONA_DETECTED = "PER-INTEGRITY-004"


def compute_file_sha256(file_path: Path | str) -> str:
    """Calcule l'empreinte SHA-256 d'un fichier."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Fichier introuvable : {path}")
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def compute_persona_hmac(key: str, agent_name: str, sha256_hash: str) -> str:
    """Calcule la signature HMAC-SHA256 pour un persona (R3)."""
    message = f"{agent_name}:{sha256_hash}".encode("utf-8")
    return hmac.new(key.encode("utf-8"), message, hashlib.sha256).hexdigest()


def resolve_profiles_dir(custom_path: Optional[Path | str] = None) -> Path:
    """Résout le dossier racine des profils selon l'environnement."""
    if custom_path:
        p = Path(custom_path)
        if p.exists():
            return p.resolve()

    env_dir = os.environ.get("ORSO_PROFILES_DIR")
    if env_dir and Path(env_dir).exists():
        return Path(env_dir).resolve()

    candidates = [
        Path("/app/profiles"),
        Path("./profiles"),
        Path(os.path.expanduser("~/.hermes/profiles")),
        Path("/app/data/hermes_home/profiles"),
    ]
    for c in candidates:
        if c.is_dir() and (c / DEFAULT_LOCK_FILENAME).exists():
            return c.resolve()
    for c in candidates:
        if c.is_dir() and any((c / name / "SOUL.md").exists() for name in ["jerome", "clara", "lucas", "victor"]):
            return c.resolve()

    return Path("./profiles").resolve()


def resolve_lock_file(profiles_dir: Path, custom_path: Optional[Path | str] = None) -> Path:
    """Localise le fichier personas.lock.json."""
    if custom_path:
        return Path(custom_path).resolve()
    return (profiles_dir / DEFAULT_LOCK_FILENAME).resolve()


def find_rogue_personas(
    profiles_dir: Optional[Path | str] = None,
    scan_roots: Optional[List[Path | str]] = None,
) -> List[Path]:
    """Recherche tous les fichiers SOUL.md illégitimes situés hors du dossier profiles officiel.

    Couvre la classe de défaut du repli ambient (KAN-54) :
    - <HERMES_HOME>/SOUL.md (si HERMES_HOME n'est pas le dossier profiles)
    - /app/data/**/SOUL.md et ./data/**/SOUL.md
    - <profiles_parent>/data/**/SOUL.md
    """
    p_dir = resolve_profiles_dir(profiles_dir).resolve()
    rogue_found: List[Path] = []
    checked_paths: set[Path] = set()

    # 1. Chemins précis prioritaires dans les volumes inscriptibles
    specific_candidates: List[Path] = [
        Path("/app/data/hermes_home/SOUL.md"),
        Path("/app/data/SOUL.md"),
        Path("./data/hermes_home/SOUL.md"),
        Path("./data/SOUL.md"),
    ]

    # HERMES_HOME explicite dans l'environnement
    env_hermes_home = os.environ.get("HERMES_HOME")
    if env_hermes_home:
        specific_candidates.append(Path(env_hermes_home) / "SOUL.md")

    # Répertoire data frère de profiles_dir si applicable (environnements de test)
    if p_dir.parent.is_dir():
        specific_candidates.append(p_dir.parent / "data" / "hermes_home" / "SOUL.md")
        specific_candidates.append(p_dir.parent / "data" / "SOUL.md")
        specific_candidates.append(p_dir.parent / "hermes_home" / "SOUL.md")

    for cand in specific_candidates:
        try:
            if not cand.exists() or cand.is_symlink():
                continue
            resolved = cand.resolve()
            if resolved in checked_paths:
                continue
            checked_paths.add(resolved)
            try:
                resolved.relative_to(p_dir)
            except ValueError:
                rogue_found.append(cand)
        except Exception:
            pass

    # 2. Scan récursif des racines inscriptibles
    default_roots: List[Path] = []
    if Path("/app/data").is_dir():
        default_roots.append(Path("/app/data"))
    if env_hermes_home and Path(env_hermes_home).is_dir():
        default_roots.append(Path(env_hermes_home))
    if p_dir.parent.is_dir() and (p_dir.parent / "data").is_dir():
        default_roots.append(p_dir.parent / "data")

    # Si profiles_dir pointe vers le dépôt local, scanner le ./data local
    try:
        if p_dir.resolve() == Path("./profiles").resolve() and Path("./data").is_dir():
            default_roots.append(Path("./data"))
    except Exception:
        pass

    roots_to_scan = [Path(r) for r in scan_roots] if scan_roots is not None else default_roots
    for root_path in roots_to_scan:
        if not root_path.is_dir():
            continue
        try:
            for item in root_path.rglob("*"):
                if item.is_file() and item.name.lower() == "soul.md" and not item.is_symlink():
                    norm_path = str(item).replace("\\", "/")
                    # Ignorer les profils de sous-espaces clients structurés (data/spaces/<slug>/profiles/...)
                    if "/spaces/" in norm_path and "/profiles/" in norm_path:
                        continue
                    try:
                        resolved = item.resolve()
                        if resolved in checked_paths:
                            continue
                        checked_paths.add(resolved)
                        try:
                            resolved.relative_to(p_dir)
                        except ValueError:
                            rogue_found.append(item)
                    except Exception:
                        pass
        except Exception as e:
            logger.debug("Erreur lors du scan rogue persona dans %s: %s", root_path, e)

    return rogue_found


def resolve_telemetry_dir() -> Path:
    """Détermine l'emplacement du dossier de télémétrie."""
    env_dir = os.environ.get("TELEMETRY_DIR")
    if env_dir:
        p = Path(env_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p.resolve()

    if Path("/app/data").is_dir():
        p = Path("/app/data/telemetry")
        p.mkdir(parents=True, exist_ok=True)
        return p.resolve()

    p = Path("./data/telemetry")
    p.mkdir(parents=True, exist_ok=True)
    return p.resolve()


def log_integrity_event(
    agent: str,
    version: str,
    sha256_hash: str,
    status: str,
    event_code: str,
    details: str = "",
    telemetry_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Enregistre un événement dans le journal d'intégrité probant (R7, CA8).
    Génère une entrée dans personas_integrity.log et personas_integrity.jsonl.
    Met également à jour le fichier telemetry_export.json si présent.
    """
    t_dir = telemetry_dir or resolve_telemetry_dir()
    now_iso = datetime.now(timezone.utc).isoformat()
    now_ts = time.time()

    entry = {
        "timestamp": now_iso,
        "timestamp_unix": now_ts,
        "agent": agent,
        "version": version,
        "sha256": sha256_hash,
        "status": status,
        "event_code": event_code,
        "details": details,
    }

    # 1. personas_integrity.log (format lisible ligne par ligne)
    log_file = t_dir / "personas_integrity.log"
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{now_iso}] [{event_code}] [{status.upper()}] agent={agent} version={version} sha256={sha256_hash} {details}\n")
    except Exception as e:
        logger.warning("Échec écriture personas_integrity.log: %s", e)

    # 2. personas_integrity.jsonl (format structuré pour analyse)
    jsonl_file = t_dir / "personas_integrity.jsonl"
    try:
        with open(jsonl_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("Échec écriture personas_integrity.jsonl: %s", e)

    # 3. Synchronisation avec telemetry_export.json
    export_candidates = [
        t_dir.parent / "telemetry_export.json",
        Path("/app/data/telemetry_export.json"),
        Path("./data/telemetry_export.json"),
    ]
    for export_file in export_candidates:
        if export_file.exists():
            try:
                with open(export_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    data = {}
                integrity_sec = data.setdefault("persona_integrity", {
                    "last_check": now_iso,
                    "status": "healthy",
                    "events": [],
                })
                integrity_sec["last_check"] = now_iso
                if status != "verified":
                    integrity_sec["status"] = "compromised"
                events_list = integrity_sec.setdefault("events", [])
                events_list.append(entry)
                integrity_sec["events"] = events_list[-20:]  # Garde les 20 derniers
                with open(export_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
            except Exception as e:
                logger.warning("Échec maj telemetry_export.json: %s", e)

    return entry


def verify_all_personas(
    profiles_dir: Optional[Path | str] = None,
    lock_file: Optional[Path | str] = None,
    hmac_key: Optional[str] = None,
    record_logs: bool = True,
    event_type: str = EVENT_OK,
) -> Tuple[bool, List[str], List[Dict[str, Any]]]:
    """
    Vérifie l'intégrité de tous les personas déclarés dans personas.lock.json.
    Exige la concordance stricte SHA-256 ET signature HMAC-SHA256 (R3).
    Détecte également tout fichier SOUL.md illégitime dans les répertoires de données inscriptibles.
    Retourne (success, errors, audit_entries).
    """
    p_dir = resolve_profiles_dir(profiles_dir)
    l_file = resolve_lock_file(p_dir, lock_file)
    effective_hmac_key = hmac_key or os.environ.get("ORSO_PERSONA_HMAC_KEY")

    if not effective_hmac_key:
        err = "Clé secrète HMAC absente : variable ORSO_PERSONA_HMAC_KEY requise pour la vérification (R3 - Zero Fallback)."
        if record_logs:
            log_integrity_event("system", "unknown", "none", "error", EVENT_CONFIG_ERROR, err)
        return False, [err], []

    if not l_file.is_file():
        err = f"Manifeste d'intégrité introuvable : {l_file}"
        if record_logs:
            log_integrity_event("system", "unknown", "none", "error", EVENT_CONFIG_ERROR, err)
        return False, [err], []

    try:
        with open(l_file, "r", encoding="utf-8") as f:
            lock_data = json.load(f)
    except Exception as exc:
        err = f"Impossible de parser {l_file}: {exc}"
        if record_logs:
            log_integrity_event("system", "unknown", "none", "error", EVENT_CONFIG_ERROR, err)
        return False, [err], []

    personas = lock_data.get("personas", {})
    if not personas:
        err = f"Aucun persona déclaré dans {l_file}"
        return False, [err], []

    all_valid = True
    errors: List[str] = []
    audit_entries: List[Dict[str, Any]] = []

    # Contrôle de défense en profondeur & sanctuarisation du repli ambient (KAN-33 / KAN-54)
    # Détection exhaustive de tout SOUL.md hors du dossier officiel profiles/
    rogue_souls = find_rogue_personas(profiles_dir=p_dir)
    for r_path in rogue_souls:
        err_d = f"Fichier persona illégitime détecté dans un volume inscriptible : {r_path}"
        errors.append(err_d)
        all_valid = False
        if record_logs:
            entry = log_integrity_event("rogue_persona", "unknown", "dangerous", "compromised", EVENT_ROGUE_PERSONA_DETECTED, err_d)
            audit_entries.append(entry)

    for agent_name, meta in sorted(personas.items()):
        version = meta.get("version", "1.0.0")
        expected_sha = meta.get("sha256", "").strip().lower()
        expected_hmac = meta.get("hmac_signature", "").strip().lower()

        soul_path = p_dir / agent_name / "SOUL.md"
        if not soul_path.exists():
            msg = f"Persona manquant pour {agent_name} : {soul_path} introuvable"
            errors.append(msg)
            all_valid = False
            if record_logs:
                entry = log_integrity_event(agent_name, version, "missing", "failed", event_type, msg)
                audit_entries.append(entry)
            continue

        try:
            actual_sha = compute_file_sha256(soul_path).lower()
        except Exception as read_err:
            msg = f"Erreur de lecture {soul_path} : {read_err}"
            errors.append(msg)
            all_valid = False
            if record_logs:
                entry = log_integrity_event(agent_name, version, "read_error", "failed", event_type, msg)
                audit_entries.append(entry)
            continue

        # 1. Vérification SHA-256
        if actual_sha != expected_sha:
            msg = (
                f"Écart d'intégrité SHA-256 détecté sur {agent_name}/SOUL.md ! "
                f"Attendu: {expected_sha}, Obtenu: {actual_sha}"
            )
            errors.append(msg)
            all_valid = False
            if record_logs:
                entry = log_integrity_event(agent_name, version, actual_sha, "compromised", event_type, msg)
                audit_entries.append(entry)
            continue

        # 2. Vérification HMAC-SHA256 obligatoire (R3)
        if not expected_hmac:
            msg = f"Signature HMAC absente du manifeste pour {agent_name} (exigence R3 non respectée) !"
            errors.append(msg)
            all_valid = False
            if record_logs:
                entry = log_integrity_event(agent_name, version, actual_sha, "hmac_missing", event_type, msg)
                audit_entries.append(entry)
            continue

        calculated_hmac = compute_persona_hmac(effective_hmac_key, agent_name, actual_sha)
        if calculated_hmac != expected_hmac:
            msg = (
                f"Signature HMAC invalide pour {agent_name} ! "
                f"Attendu: {expected_hmac}, Obtenu: {calculated_hmac}"
            )
            errors.append(msg)
            all_valid = False
            if record_logs:
                entry = log_integrity_event(agent_name, version, actual_sha, "hmac_failed", event_type, msg)
                audit_entries.append(entry)
            continue

        # Succès
        if record_logs:
            entry = log_integrity_event(agent_name, version, actual_sha, "verified", EVENT_OK, "Intégrité SHA-256 & HMAC validée")
            audit_entries.append(entry)

    return all_valid, errors, audit_entries


def generate_lock_manifest(
    profiles_dir: Optional[Path | str] = None,
    output_file: Optional[Path | str] = None,
    hmac_key: Optional[str] = None,
    version: str = "1.0.0",
) -> Dict[str, Any]:
    """Génère le manifeste personas.lock.json avec signatures HMAC obligatoires (R3)."""
    p_dir = resolve_profiles_dir(profiles_dir)
    out_file = resolve_lock_file(p_dir, output_file)
    effective_hmac_key = hmac_key or os.environ.get("ORSO_PERSONA_HMAC_KEY")

    if not effective_hmac_key:
        raise ValueError("Clé secrète HMAC absente : variable ORSO_PERSONA_HMAC_KEY requise pour générer les signatures du manifeste (R3 - Zero Fallback).")

    roles = {
        "jerome": "Crédit Manager & Recouvrement",
        "lucas": "Commercial & Prospection",
        "clara": "Support Client & Relation Usagers",
        "victor": "Assistant Appels d'Offres & Marchés Publics",
    }

    personas_meta: Dict[str, Any] = {}
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for agent_dir in sorted(p_dir.iterdir()):
        if not agent_dir.is_dir() or agent_dir.name.startswith("."):
            continue
        soul = agent_dir / "SOUL.md"
        if not soul.is_file():
            continue

        agent_name = agent_dir.name
        sha = compute_file_sha256(soul)
        hmac_sig = compute_persona_hmac(effective_hmac_key, agent_name, sha)
        personas_meta[agent_name] = {
            "name": agent_name,
            "role": roles.get(agent_name, f"Agent {agent_name.capitalize()}"),
            "version": version,
            "date": today_iso,
            "sha256": sha,
            "hmac_signature": hmac_sig,
        }

    manifest = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "version": version,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "hash_algorithm": "sha256",
        "hmac_algorithm": "hmac-sha256",
        "personas": personas_meta,
    }

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return manifest


def monitor_loop(
    interval_seconds: int = 300,
    profiles_dir: Optional[Path | str] = None,
    lock_file: Optional[Path | str] = None,
    hmac_key: Optional[str] = None,
    on_violation: Optional[Callable[[List[str]], None]] = None,
    max_iterations: Optional[int] = None,
) -> None:
    """
    Boucle de surveillance périodique de l'intégrité (R6, CA6).
    En cas d'altération en cours de route :
    1. Écrit l'alerte critique PER-INTEGRITY-002 dans la télémétrie.
    2. Exécute le callback on_violation ou force l'arrêt d'urgence du conteneur.
    """
    logger.info("Démarrage du moniteur d'intégrité des personas (intervalle=%ds)...", interval_seconds)
    iterations = 0

    while True:
        iterations += 1
        valid, errors, _ = verify_all_personas(
            profiles_dir=profiles_dir,
            lock_file=lock_file,
            hmac_key=hmac_key,
            record_logs=True,
            event_type=EVENT_RUNTIME_ALTERATION,
        )

        if not valid:
            msg = f"[ALERTE CRITIQUE {EVENT_RUNTIME_ALTERATION}] Altération de persona détectée en cours d'exécution !"
            print(f"\n🚨 {msg}", file=sys.stderr)
            for err in errors:
                print(f"   ❌ {err}", file=sys.stderr)

            if on_violation:
                on_violation(errors)
                return

            # Arrêt d'urgence garanti du conteneur (R6, CA6)
            print("🚨 [PER-INTEGRITY-002] Arrêt d'urgence immédiat du conteneur de l'agent compromis.", file=sys.stderr)
            try:
                # Écriture d'un drapeau d'urgence sur disque
                flag_path = Path("/app/data/EMERGENCY_STOP_PER_INTEGRITY")
                if not flag_path.parent.is_dir():
                    flag_path = Path(resolve_telemetry_dir()).parent / "EMERGENCY_STOP_PER_INTEGRITY"
                flag_path.touch(exist_ok=True)
            except Exception:
                pass

            try:
                os.kill(1, getattr(signal, "SIGKILL", signal.SIGTERM))
            except Exception:
                pass
            try:
                os.system("kill -9 1 2>/dev/null || pkill -9 -f hermes 2>/dev/null || pkill -9 -f python 2>/dev/null")
            except Exception:
                pass
            sys.exit(1)

        if max_iterations and iterations >= max_iterations:
            break

        time.sleep(interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Vérification et surveillance de l'intégrité des Personas SOUL.md")
    subparsers = parser.add_subparsers(dest="command")

    # verify
    v_parser = subparsers.add_parser("verify", help="Vérifie l'intégrité au démarrage (Fail-Closed)")
    v_parser.add_argument("--profiles-dir", help="Chemin vers le dossier profiles")
    v_parser.add_argument("--lock-file", help="Chemin vers personas.lock.json")
    v_parser.add_argument("--hmac-key", help="Clé HMAC (défaut: variable ORSO_PERSONA_HMAC_KEY)")
    v_parser.add_argument("--fail-fast", action="store_true", help="Quitte avec code 1 dès la première erreur")
    v_parser.add_argument("--quiet", action="store_true", help="N'affiche que les erreurs")

    # monitor
    m_parser = subparsers.add_parser("monitor", help="Surveillance périodique à l'exécution (R6, CA6)")
    m_parser.add_argument("--interval", type=int, default=300, help="Intervalle de vérification en secondes (défaut: 300)")
    m_parser.add_argument("--profiles-dir", help="Chemin vers le dossier profiles")
    m_parser.add_argument("--lock-file", help="Chemin vers personas.lock.json")
    m_parser.add_argument("--hmac-key", help="Clé HMAC")
    m_parser.add_argument("--once", action="store_true", help="Exécute une seule vérification de surveillance")

    # generate-lock
    g_parser = subparsers.add_parser("generate-lock", help="Génère ou met à jour personas.lock.json")
    g_parser.add_argument("--profiles-dir", help="Chemin vers le dossier profiles")
    g_parser.add_argument("--output", help="Chemin de sortie du lockfile")
    g_parser.add_argument("--hmac-key", help="Clé HMAC à utiliser pour la signature")
    g_parser.add_argument("--version", default="1.0.0", help="Version applicative")

    args = parser.parse_args()

    if args.command == "verify" or not args.command:
        profiles_dir = getattr(args, "profiles_dir", None)
        lock_file = getattr(args, "lock_file", None)
        hmac_key = getattr(args, "hmac_key", None)
        quiet = getattr(args, "quiet", False)

        valid, errors, audits = verify_all_personas(
            profiles_dir=profiles_dir,
            lock_file=lock_file,
            hmac_key=hmac_key,
            record_logs=True,
            event_type=EVENT_STARTUP_MISMATCH,
        )

        if not valid:
            print(f"[{EVENT_STARTUP_MISMATCH}] Échec de vérification d'intégrité des personas :", file=sys.stderr)
            for e in errors:
                print(f"  - {e}", file=sys.stderr)
            sys.exit(1)

        if not quiet:
            print(f"[{EVENT_OK}] Intégrité des {len(audits)} personas vérifiée avec succès (SHA-256 + HMAC-SHA256).")
            for a in audits:
                print(f"  ✓ {a['agent']} (v{a['version']}) : {a['sha256']}")
        sys.exit(0)

    elif args.command == "monitor":
        monitor_loop(
            interval_seconds=args.interval,
            profiles_dir=args.profiles_dir,
            lock_file=args.lock_file,
            hmac_key=args.hmac_key,
            max_iterations=1 if args.once else None,
        )

    elif args.command == "generate-lock":
        manifest = generate_lock_manifest(
            profiles_dir=args.profiles_dir,
            output_file=args.output,
            hmac_key=args.hmac_key,
            version=args.version,
        )
        print(f"Manifeste personas.lock.json généré avec succès ({len(manifest['personas'])} personas avec signatures HMAC).")


if __name__ == "__main__":
    main()
