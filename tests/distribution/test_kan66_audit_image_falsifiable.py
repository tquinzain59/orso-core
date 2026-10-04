"""
Tests d'acceptation automatisés pour la livraison KAN-66 :
POC - Rendre falsifiable l'audit de conformité de l'image construite.

Vérifie l'intégralité des 5 critères d'acceptation :
- CA1 : La preuve exige une référence d'image explicite, sortie en erreur explicite sans référence (code retour non nul).
- CA2 : L'inspection ouvre l'arborescence applicative de l'image et consigne la liste des chemins parcourus et leur nombre calculé.
- CA3 : La preuve échoue quand l'artefact n'a pas pu être ouvert (preuve négative obligatoire, statut FAILED, code retour non nul).
- CA4 : Aucun rattrapage silencieux, toute erreur d'ouverture est explicitement nommée avec son motif.
- CA5 : Le compteur de données client reste calculé (jamais déclaré) et les fonctions qui l'alimentent sont nommées.
"""

import os
import sys
import io
import json
import tarfile
import tempfile
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from scripts.security.audit_zero_secrets_and_client_data import (
    run_full_ca5_audit,
    audit_docker_image_for_secrets_and_client_data,
    audit_client_data_in_repository,
    PROJECT_ROOT,
)


class TestKAN66AuditImageFalsifiable:
    """Suite d'acceptation formelle KAN-66."""

    def test_ca1_missing_image_ref_exits_with_error(self):
        """
        CA1 : La preuve exige une référence d'image explicite.
        Une exécution sans référence sort en erreur explicite au lieu de rendre un succès (code retour non nul).
        """
        script_path = PROJECT_ROOT / "scripts" / "security" / "audit_zero_secrets_and_client_data.py"

        # 1. Exécution CLI réelle sans argument
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode != 0, "L'exécution CLI sans référence d'image DOIT échouer (code retour non nul)"
        assert "Erreur CA1" in proc.stderr or "Erreur CA1" in proc.stdout
        assert "Référence d'image Docker obligatoire" in (proc.stderr + proc.stdout)

        # 2. Exécution via l'API run_full_ca5_audit sans référence
        report = run_full_ca5_audit(image_ref=None, require_image=True)
        assert report["status"] == "FAILED"
        assert report["metrics"]["image_scan_errors_count"] >= 1
        assert any(err["type"] == "MISSING_REQUIRED_IMAGE" for err in report["violations"]["image_scan_errors"])

        report_empty_str = run_full_ca5_audit(image_ref="   ", require_image=True)
        assert report_empty_str["status"] == "FAILED"
        assert any(err["type"] == "MISSING_REQUIRED_IMAGE" for err in report_empty_str["violations"]["image_scan_errors"])

    def test_ca2_inspects_applicative_file_tree_with_paths_list(self):
        """
        CA2 : L'inspection ouvre l'arborescence applicative de l'image et pas seulement sa configuration et ses étiquettes.
        Preuve : liste des chemins parcourus dans l'image, avec leur nombre, et non un total annoncé.
        """
        # Construction d'une archive tar simulée représentant une image Docker
        tar_bytes_io = io.BytesIO()
        with tarfile.open(fileobj=tar_bytes_io, mode="w") as tar:
            # Fichiers applicatifs
            f1_data = b"# Orso Agent Engine\nprint('hello')\n"
            ti1 = tarfile.TarInfo(name="app/run_agent.py")
            ti1.size = len(f1_data)
            tar.addfile(ti1, io.BytesIO(f1_data))

            f2_data = b"FROM python:3.11-slim\nWORKDIR /app\n"
            ti2 = tarfile.TarInfo(name="app/Dockerfile.orso")
            ti2.size = len(f2_data)
            tar.addfile(ti2, io.BytesIO(f2_data))

            f3_data = b"{\"name\": \"orso-core\"}\n"
            ti3 = tarfile.TarInfo(name="app/config/settings.json")
            ti3.size = len(f3_data)
            tar.addfile(ti3, io.BytesIO(f3_data))

            # Fichier système exclu des chemins applicatifs
            f_sys = b"Linux system file\n"
            ti_sys = tarfile.TarInfo(name="etc/hosts")
            ti_sys.size = len(f_sys)
            tar.addfile(ti_sys, io.BytesIO(f_sys))

        tar_bytes = tar_bytes_io.getvalue()

        # Mock de docker inspect, docker create et docker export
        mock_inspect_proc = subprocess.CompletedProcess(
            args=["docker", "inspect"],
            returncode=0,
            stdout=json.dumps([{"Config": {"Env": ["PORT=9119"], "Labels": {}}}]),
            stderr="",
        )
        mock_create_proc = subprocess.CompletedProcess(
            args=["docker", "create"],
            returncode=0,
            stdout="fake-cid-ca2",
            stderr="",
        )

        mock_export_popen = MagicMock()
        mock_export_popen.stdout = io.BytesIO(tar_bytes)
        mock_export_popen.stderr = io.BytesIO(b"")
        mock_export_popen.wait.return_value = 0
        mock_export_popen.returncode = 0

        with patch("subprocess.run") as mock_run, patch("subprocess.Popen", return_value=mock_export_popen):
            mock_run.side_effect = [mock_inspect_proc, mock_create_proc, MagicMock()]
            result = audit_docker_image_for_secrets_and_client_data("test-engine:v1.0.0")

        # Vérification CA2 : arborescence ouverte, liste réelle des chemins fournie, décompte calculé
        assert len(result["errors"]) == 0
        assert result["scanned_files_count"] == 4
        assert "app/run_agent.py" in result["scanned_paths"]
        assert "app/Dockerfile.orso" in result["scanned_paths"]
        assert "app/config/settings.json" in result["scanned_paths"]
        assert "etc/hosts" in result["scanned_paths"]

        # Liste des chemins applicatifs isolée
        applicative = result["applicative_paths"]
        assert len(applicative) == 3
        assert "app/run_agent.py" in applicative
        assert "app/Dockerfile.orso" in applicative
        assert "app/config/settings.json" in applicative
        assert "etc/hosts" not in applicative

    def test_ca3_failure_when_artifact_cannot_be_opened(self):
        """
        CA3 : La preuve échoue quand l'artefact n'a pas pu être ouvert.
        Preuve négative obligatoire : la même commande, avec une référence, dans un état où l'ouverture est impossible,
        doit rendre un statut en échec et un code retour non nul.
        """
        script_path = PROJECT_ROOT / "scripts" / "security" / "audit_zero_secrets_and_client_data.py"

        # 1. Preuve négative CLI : image inexistante
        proc = subprocess.run(
            [sys.executable, str(script_path), "nonexistent-image-kan66:invalid"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode != 0, "L'audit d'une image introuvable DOIT échouer avec code retour non nul"
        assert "FAILED" in proc.stdout or "FAILED" in proc.stderr
        assert "IMAGE_INSPECT_FAILED" in proc.stdout or "IMAGE_INSPECT_FAILED" in proc.stderr

        # 2. Preuve négative API : docker inaccessible (code retour != 0 de inspect)
        mock_fail_inspect = subprocess.CompletedProcess(
            args=["docker", "inspect"],
            returncode=1,
            stdout="",
            stderr="Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?",
        )
        with patch("subprocess.run", return_value=mock_fail_inspect):
            res_daemon_down = audit_docker_image_for_secrets_and_client_data("ghcr.io/tquinzain59/orso-engine:latest")
            assert len(res_daemon_down["errors"]) >= 1
            err = res_daemon_down["errors"][0]
            assert err["type"] == "IMAGE_INSPECT_FAILED"
            assert "Cannot connect to the Docker daemon" in err["label"]

        # 3. Preuve négative API : échec docker create (impossible d'ouvrir le conteneur)
        mock_inspect_ok = subprocess.CompletedProcess(
            args=["docker", "inspect"],
            returncode=0,
            stdout=json.dumps([{"Config": {"Env": [], "Labels": {}}}]),
            stderr="",
        )
        mock_create_fail = subprocess.CompletedProcess(
            args=["docker", "create"],
            returncode=125,
            stdout="",
            stderr="Error response from daemon: filesystem corruption",
        )
        with patch("subprocess.run", side_effect=[mock_inspect_ok, mock_create_fail]):
            res_create_fail = audit_docker_image_for_secrets_and_client_data("test-engine:corrupt")
            assert len(res_create_fail["errors"]) >= 1
            err = res_create_fail["errors"][0]
            assert err["type"] == "CONTAINER_CREATE_FAILED"
            assert "filesystem corruption" in err["label"]

    def test_ca4_no_silent_fallback_error_named_in_output(self):
        """
        CA4 : Aucun rattrapage silencieux : une erreur d'ouverture est nommée dans la sortie.
        Preuve : lecture de la fonction qui inspecte l'image, et sortie de CA3 qui porte le motif d'échec.
        """
        # Vérification par inspection du code source : absence de "except Exception: pass" muet dans l'inspection
        audit_source = (PROJECT_ROOT / "scripts" / "security" / "audit_zero_secrets_and_client_data.py").read_text(encoding="utf-8")
        assert "IMAGE_FILE_READ_ERROR" in audit_source
        assert "IMAGE_TAR_SCAN_ERROR" in audit_source
        assert "IMAGE_EXPORT_FAILED" in audit_source
        assert "CONTAINER_CREATE_FAILED" in audit_source
        assert "IMAGE_INSPECT_FAILED" in audit_source

        # Vérification dynamique : injection d'une erreur de lecture de fichier dans le tar
        tar_bytes_io = io.BytesIO()
        with tarfile.open(fileobj=tar_bytes_io, mode="w") as tar:
            f_corrupt = b"\xff\xfe\x00\x00INVALID_UTF8"
            ti = tarfile.TarInfo(name="app/broken_file.py")
            ti.size = len(f_corrupt)
            tar.addfile(ti, io.BytesIO(f_corrupt))

        mock_inspect_ok = subprocess.CompletedProcess(
            args=["docker", "inspect"],
            returncode=0,
            stdout=json.dumps([{"Config": {"Env": [], "Labels": {}}}]),
            stderr="",
        )
        mock_create_ok = subprocess.CompletedProcess(
            args=["docker", "create"],
            returncode=0,
            stdout="cid-broken",
            stderr="",
        )
        mock_export_popen = MagicMock()
        mock_export_popen.stdout = io.BytesIO(tar_bytes_io.getvalue())
        mock_export_popen.stderr = io.BytesIO(b"")
        mock_export_popen.wait.return_value = 0
        mock_export_popen.returncode = 0

        # On simule une erreur de lecture I/O lors de tar.extractfile
        with patch("subprocess.run", side_effect=[mock_inspect_ok, mock_create_ok, MagicMock()]), \
             patch("subprocess.Popen", return_value=mock_export_popen):
            with patch("tarfile.TarFile.extractfile", side_effect=OSError("Disk read error inside archive")):
                res = audit_docker_image_for_secrets_and_client_data("test-engine:io-error")
                assert len(res["errors"]) >= 1
                assert res["errors"][0]["type"] == "IMAGE_FILE_READ_ERROR"
                assert "Disk read error inside archive" in res["errors"][0]["label"]

    def test_ca5_client_data_counter_calculated_and_source_named(self):
        """
        CA5 : Le compteur de données client reste calculé, jamais déclaré, et la fonction qui l'alimente est nommée au ticket.
        Preuve : lecture du code et sortie de la commande.
        """
        # 1. Vérification dans le rapport que la source de calcul est nommée
        report = run_full_ca5_audit(image_ref="alpine:latest", require_image=True)
        metrics = report["metrics"]
        assert "client_data_calculation_source" in metrics
        assert "audit_client_data_in_repository" in metrics["client_data_calculation_source"]
        assert "audit_docker_image_for_secrets_and_client_data" in metrics["client_data_calculation_source"]

        # 2. Vérification que le compteur est dynamiquement calculé : injection de données client dans l'image
        fake_inspect_with_client_data = subprocess.CompletedProcess(
            args=["docker", "inspect"],
            returncode=0,
            stdout=json.dumps([{
                "Config": {
                    "Env": ["ORSO_CLIENT_ID=client-12345", "ORSO_CLIENT_SLUG=financia"],
                    "Labels": {"com.orso.tenant_id": "tenant-xyz"},
                }
            }]),
            stderr="",
        )
        mock_create = subprocess.CompletedProcess(args=["docker", "create"], returncode=0, stdout="c1", stderr="")
        mock_export = MagicMock()
        mock_export.stdout = io.BytesIO(b"")
        mock_export.wait.return_value = 0
        mock_export.returncode = 0

        with patch("subprocess.run", side_effect=[fake_inspect_with_client_data, mock_create, MagicMock()]), \
             patch("subprocess.Popen", return_value=mock_export):
            res_client_data = audit_docker_image_for_secrets_and_client_data("test-engine:client-leak")
            # 2 variables d'environnement + 1 label = 3 violations
            assert len(res_client_data["client_data"]) == 3
            assert any("ORSO_CLIENT_ID" in d["file"] for d in res_client_data["client_data"])
            assert any("ORSO_CLIENT_SLUG" in d["file"] for d in res_client_data["client_data"])
            assert any("com.orso.tenant_id" in d["file"] for d in res_client_data["client_data"])
