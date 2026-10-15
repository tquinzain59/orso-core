"""KAN-73 : la télémétrie ne fabrique aucune valeur.

Contrat : collecte coupée => état inconnu explicite, jamais un état sain ni une mesure à zéro.
"""

import re
from pathlib import Path
from unittest.mock import patch

import pytest

from olympe import telemetry_client as tc_module
from olympe.telemetry_client import TelemetryClient

CLIENT_SOURCE = Path(tc_module.__file__).read_text(encoding="utf-8")

# Marqueurs de valeurs de repli retirés par KAN-73 (aucun ne doit réapparaître dans le client).
FORBIDDEN_MARKERS = [
    r"simulat",
    r"PROD-FR-002",
    r"Up \d+ (hours?|minutes?|days?)",
    r"\(healthy\)",
    r"Agent #",
    r'"server_ip":\s*"127\.0\.0\.1"',
    r"Fallback simulation",
]

_DOCKER_WITH_MANAGED_CONTAINER = {
    "orso_client_financia": {
        "container_id": "abc123",
        "state": "running",
        "status_str": "Up 2 hours",
        "cpu_percent": 1.0,
        "memory_usage_mb": 10.0,
        "memory_limit_mb": 100.0,
        "memory_percent": 10.0,
        "labels": {},
        "is_managed": True,
        "tenant_slug": None,
        "role": None,
    }
}


@pytest.fixture
def cut_client():
    """Client dont la source de collecte est coupée, avec des conteneurs Docker gérés présents."""
    client = TelemetryClient(base_url="http://collecte.invalide:9120")
    with patch.object(client, "_fetch_api", return_value=None), \
         patch.object(client, "_get_docker_live_vitals", return_value=dict(_DOCKER_WITH_MANAGED_CONTAINER)):
        yield client


@pytest.mark.parametrize("pattern", FORBIDDEN_MARKERS)
def test_no_fabricated_marker_in_client_source(pattern):
    assert re.search(pattern, CLIENT_SOURCE, re.IGNORECASE) is None


def test_summary_when_source_cut_is_unknown_without_metrics(cut_client):
    summary = cut_client.get_summary()
    assert summary["connected"] is False
    assert summary["status"] == "unknown"
    assert summary["error"] == "telemetry_unavailable"
    assert summary["message"]
    for metric in ("total_tokens", "total_cost_usd", "agents_count", "alerts_active", "total_api_calls"):
        assert metric not in summary


def test_environments_when_source_cut_are_unknown_not_empty_not_docker_derived(cut_client):
    result = cut_client.get_environments([])
    assert result["connected"] is False
    assert result["status"] == "unknown"
    assert result["environments"] is None
    assert result["count"] is None


def test_alerts_when_source_cut_are_unknown_not_an_empty_list(cut_client):
    result = cut_client.get_alerts()
    assert result["connected"] is False
    assert result["status"] == "unknown"
    assert result["alerts"] is None


def test_history_when_source_cut_has_no_invented_agent_name(cut_client):
    result = cut_client.get_history(7)
    assert result["connected"] is False
    assert result["status"] == "unknown"
    assert result["agent_name"] is None
    assert result["snapshots"] is None


def test_unreadable_alerts_payload_is_not_read_as_no_alert():
    client = TelemetryClient()
    with patch.object(client, "_fetch_api", return_value={"unexpected": True}):
        assert client.get_alerts()["alerts"] is None


def test_agent_missing_fields_stay_unknown_never_defaulted():
    client = TelemetryClient()
    latest = {"agents": [{"agent_id": 9}]}
    with patch.object(client, "_fetch_api", return_value=latest), \
         patch.object(client, "_get_docker_live_vitals", return_value={}):
        result = client.get_environments([])
    assert result["connected"] is True
    env = result["environments"][0]
    assert env["status"] == "unknown"
    assert env["display_name"] is None
    assert env["server_ip"] is None
    for field in ("total_tokens", "api_calls", "cost_usd", "error_count"):
        assert env[field] is None
    assert env["vitals"]["docker_status"] == "unknown"
    for field in ("cpu_percent", "memory_usage_mb", "memory_percent"):
        assert env["vitals"][field] is None


def test_connected_empty_alerts_is_a_real_empty_list():
    client = TelemetryClient()
    with patch.object(client, "_fetch_api", return_value={"alerts": []}):
        result = client.get_alerts()
    assert result["connected"] is True
    assert result["alerts"] == []
    assert result["count"] == 0


def test_last_valid_timestamp_is_reported_after_a_valid_read_then_cut():
    client = TelemetryClient()
    client.last_valid_at = "2026-10-01T10:00:00+00:00"
    with patch.object(client, "_fetch_api", return_value=None):
        summary = client.get_summary()
    assert summary["last_valid_at"] == "2026-10-01T10:00:00+00:00"
    assert summary["status"] == "unknown"
