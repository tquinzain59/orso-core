"""
Tests d'acceptation et de non-régression : Sanctuarisation du chemin de repli ambient de SOUL.md (KAN-54).

Couvre rigoureusement :
- CA3 : Détection en cours d'exécution par le moniteur périodique avec code d'événement stable PER-INTEGRITY-004,
  horodatage de création vs détection, et consignation dans les journaux d'intégrité.
- CA3 : Détection au démarrage (Fail-Closed) de tout SOUL.md illégitime hors profiles/.
- CA4 : Suite de tests de non-régression dédiée KAN-54.
- CA5 : Maintien et durcissement des garde-fous d'écriture KAN-33 (_check_sensitive_path bloquant universellement tout SOUL.md).
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
import pytest

from scripts.security.persona_integrity import (
    DEFAULT_LOCK_FILENAME,
    EVENT_OK,
    EVENT_ROGUE_PERSONA_DETECTED,
    EVENT_RUNTIME_ALTERATION,
    find_rogue_personas,
    generate_lock_manifest,
    monitor_loop,
    verify_all_personas,
)
from tools.file_tools_write_guards import _check_sensitive_path


TEST_HMAC_KEY = "test_persona_hmac_secret_key_kan54"


@pytest.fixture
def isolated_kan54_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Crée un environnement isolé temporaire avec profils légitimes et répertoires de données."""
    monkeypatch.setenv("ORSO_PERSONA_HMAC_KEY", TEST_HMAC_KEY)
    
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    hermes_home = data_dir / "hermes_home"
    hermes_home.mkdir()
    telemetry_dir = data_dir / "telemetry"
    telemetry_dir.mkdir()

    monkeypatch.setenv("TELEMETRY_DIR", str(telemetry_dir))
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    # Initialisation des 4 profils officiels
    agents = {
        "jerome": "# Jérôme - Crédit Manager\nDirectives officielles.\n",
        "clara": "# Clara - Support Client\nDirectives officielles.\n",
        "lucas": "# Lucas - Commercial\nDirectives officielles.\n",
        "victor": "# Victor - Marchés Publics\nDirectives officielles.\n",
    }
    for name, content in agents.items():
        agent_dir = profiles_dir / name
        agent_dir.mkdir()
        (agent_dir / "SOUL.md").write_text(content, encoding="utf-8")

    lock_file = profiles_dir / DEFAULT_LOCK_FILENAME
    manifest = generate_lock_manifest(
        profiles_dir=profiles_dir,
        output_file=lock_file,
        hmac_key=TEST_HMAC_KEY,
        version="1.0.0",
    )

    return {
        "root": tmp_path,
        "profiles_dir": profiles_dir,
        "data_dir": data_dir,
        "hermes_home": hermes_home,
        "telemetry_dir": telemetry_dir,
        "lock_file": lock_file,
        "manifest": manifest,
    }


def test_ca3_runtime_rogue_soul_detection_and_stable_event_code(isolated_kan54_env):
    """CA3 : Un SOUL.md créé hors profiles/ pendant l'exécution est détecté par le moniteur
    avec le code d'événement stable PER-INTEGRITY-004, horodatage probant et extrait de journal."""
    p_dir = isolated_kan54_env["profiles_dir"]
    l_file = isolated_kan54_env["lock_file"]
    hermes_home = isolated_kan54_env["hermes_home"]
    t_dir = isolated_kan54_env["telemetry_dir"]

    # 1. Vérification nominale initiale (environnement sain)
    valid, errors, _ = verify_all_personas(profiles_dir=p_dir, lock_file=l_file, record_logs=False)
    assert valid is True, f"L'état initial doit être valide: {errors}"

    # 2. Simulation de l'attaque CARBONATO : création d'un SOUL.md pirate dans HERMES_HOME
    t_creation_iso = datetime.now(timezone.utc).isoformat()
    t_creation_unix = time.time()
    rogue_soul = hermes_home / "SOUL.md"
    rogue_soul.write_text("# ROGUE PIRATE PERSONA (CARBONATO INJECTION)\n", encoding="utf-8")

    # 3. Exécution d'un tour de contrôle du moniteur d'intégrité
    violations_captured = []

    def mock_on_violation(errs):
        violations_captured.append(errs)

    monitor_loop(
        interval_seconds=1,
        profiles_dir=p_dir,
        lock_file=l_file,
        on_violation=mock_on_violation,
        max_iterations=1,
    )

    t_detection_iso = datetime.now(timezone.utc).isoformat()
    t_detection_unix = time.time()

    # 4. Vérification de la détection et des preuves temporelles
    assert len(violations_captured) == 1, "Le moniteur aurait dû capturer l'infraction."
    assert any("Fichier persona illégitime détecté" in e for e in violations_captured[0])
    assert t_detection_unix >= t_creation_unix

    # 5. Contrôle du journal d'intégrité et du code d'événement stable (PER-INTEGRITY-004)
    log_file = t_dir / "personas_integrity.log"
    assert log_file.is_file(), "Le fichier personas_integrity.log doit avoir été généré."
    log_content = log_file.read_text(encoding="utf-8")

    assert EVENT_ROGUE_PERSONA_DETECTED in log_content
    assert "PER-INTEGRITY-004" in log_content
    assert "rogue_persona" in log_content

    # Vérification du format JSONL structuré
    jsonl_file = t_dir / "personas_integrity.jsonl"
    assert jsonl_file.is_file()
    lines = [json.loads(line) for line in jsonl_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    rogue_entries = [e for e in lines if e.get("event_code") == EVENT_ROGUE_PERSONA_DETECTED]
    assert len(rogue_entries) >= 1
    entry = rogue_entries[-1]
    assert entry["status"] == "compromised"
    assert entry["agent"] == "rogue_persona"
    assert "Fichier persona illégitime détecté" in entry["details"]


def test_ca3_startup_verify_rejects_rogue_soul(isolated_kan54_env):
    """CA3 : La vérification au démarrage (verify) échoue immédiatement (Fail-Closed)
    si un SOUL.md illégitime existe dans les répertoires inscriptibles."""
    p_dir = isolated_kan54_env["profiles_dir"]
    l_file = isolated_kan54_env["lock_file"]
    data_dir = isolated_kan54_env["data_dir"]

    # Création d'un SOUL.md dans data/SOUL.md
    rogue_file = data_dir / "SOUL.md"
    rogue_file.write_text("# INJECTED SOUL\n", encoding="utf-8")

    valid, errors, audits = verify_all_personas(
        profiles_dir=p_dir,
        lock_file=l_file,
        record_logs=True,
    )

    assert valid is False, "Le démarrage doit échouer si un SOUL.md existe hors profiles/"
    assert any("Fichier persona illégitime détecté" in e for e in errors)
    assert any(a.get("event_code") == EVENT_ROGUE_PERSONA_DETECTED for a in audits)


def test_find_rogue_personas_exhaustiveness(isolated_kan54_env):
    """Vérifie l'exhaustivité de la détection de find_rogue_personas sans faux positif sur profiles/."""
    p_dir = isolated_kan54_env["profiles_dir"]
    data_dir = isolated_kan54_env["data_dir"]
    hermes_home = isolated_kan54_env["hermes_home"]

    # Aucun fichier rogue initialement
    assert find_rogue_personas(profiles_dir=p_dir) == []

    # Création de 2 fichiers pirates dans des sous-arborescences distinctes
    r1 = hermes_home / "SOUL.md"
    r1.write_text("rogue 1")
    sub_dir = data_dir / "nested" / "workspace"
    sub_dir.mkdir(parents=True)
    r2 = sub_dir / "SOUL.md"
    r2.write_text("rogue 2")

    found = find_rogue_personas(profiles_dir=p_dir, scan_roots=[data_dir])
    found_resolved = {f.resolve() for f in found}

    assert r1.resolve() in found_resolved
    assert r2.resolve() in found_resolved
    # Vérifie qu'aucun profil officiel n'est marqué comme rogue
    for name in ["jerome", "clara", "lucas", "victor"]:
        assert (p_dir / name / "SOUL.md").resolve() not in found_resolved


def test_ca5_file_tools_write_guard_blocks_all_soul_md_writes():
    """CA5 : Le garde-fou d'écriture file_tools_write_guards bloque universellement
    toute tentative d'écriture ou de création d'un fichier SOUL.md n'importe où sur le disque."""
    test_paths = [
        "SOUL.md",
        "./SOUL.md",
        "/app/data/hermes_home/SOUL.md",
        "/app/data/SOUL.md",
        "./data/hermes_home/SOUL.md",
        "/tmp/SOUL.md",
        "/tmp/arbitrary/path/SOUL.md",
        "profiles/jerome/SOUL.md",
        "/home/orso/.hermes/SOUL.md",
        "nested/sub/dir/soul.md",
    ]

    for target in test_paths:
        refusal = _check_sensitive_path(target)
        assert refusal is not None, f"L'écriture dans {target} aurait dû être bloquée !"
        assert "Refusing to write to protected agent profile path" in refusal
        assert "KAN-33/KAN-54" in refusal or "read-only and immutable" in refusal


def test_ca5_legitimate_files_not_blocked_by_guard():
    """Vérifie que les fichiers de travail ordinaires de l'agent ne sont pas bloqués à tort."""
    allowed_paths = [
        "notes.txt",
        "reports/balance_agee.csv",
        "/app/data/reports/synthese.pdf",
        "src/utils.py",
        "my_soul_analysis.md",  # Pas un SOUL.md exact
    ]

    for path in allowed_paths:
        refusal = _check_sensitive_path(path)
        assert refusal is None, f"Le chemin légitime {path} ne doit pas être bloqué : {refusal}"
