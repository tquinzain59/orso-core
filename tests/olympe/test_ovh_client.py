"""Tests unitaires pour le Client OVH et l'estimation de dimensionnement (olympe/ovh_client.py)."""

import pytest
from olympe.ovh_client import OVHClient, OVH_FLAVORS


def test_ovh_client_not_configured_by_default():
    client = OVHClient(application_key="", application_secret="", consumer_key="")
    assert not client.is_configured()
    assert client.request("GET", "/cloud/project") is None


def test_ovh_client_signature():
    client = OVHClient(
        application_key="test_ak",
        application_secret="test_as",
        consumer_key="test_ck",
    )
    sig = client._sign("GET", "https://eu.api.ovh.com/1.0/auth/time", "", 1700000000)
    assert sig.startswith("$1$")
    assert len(sig) == 43  # "$1$" + 40 hex chars


def test_estimate_sizing():
    client = OVHClient()
    # 1 client avec 2 agents
    sizing = client.estimate_sizing(pending_tenants_count=1, pending_agents_count=2)
    assert sizing["pending_tenants"] == 1
    assert sizing["pending_agents"] == 2
    assert sizing["ram_mb_estimated"] == (2 * 1024) + 512  # 2560 Mo
    assert sizing["can_fit_on_current_pool"] is True
    assert "docker_deploy_snippet" in sizing
    assert "cloud_init_snippet" in sizing

    # Gros déploiement : 5 clients et 15 agents
    sizing_heavy = client.estimate_sizing(pending_tenants_count=5, pending_agents_count=15)
    assert sizing_heavy["pending_agents"] == 15
    assert sizing_heavy["can_fit_on_current_pool"] is False
    assert sizing_heavy["recommended_flavor"] in ("b2-15", "b2-30")
