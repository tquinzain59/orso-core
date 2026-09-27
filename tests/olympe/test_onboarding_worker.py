"""Tests unitaires pour le Worker souverain d'onboarding Orso Core (olympe/onboarding_worker.py)."""

import pytest
from olympe.onboarding_worker import OnboardingWorker, BASE_PROMPTS


def test_build_system_prompt_injection():
    worker = OnboardingWorker()
    mission = (
        "1. Contexte & Enjeux Stratégiques : Réduire le DSO à 35 jours.\n"
        "2. Objectifs Prioritaires : Recouvrer 85% sous 15j.\n"
        "3. Posture : Diplomatique.\n"
        "4. Escalade : Litige > 5000 €."
    )
    prompt = worker.build_system_prompt("jerome", mission)
    assert "Jérôme" in prompt
    assert "LETTRE DE MISSION OPÉRATIONNELLE DU CLIENT" in prompt
    assert "Réduire le DSO à 35 jours" in prompt
    assert "Litige > 5000 €" in prompt


def test_configure_connectors():
    worker = OnboardingWorker()
    cfg = worker.configure_connectors("Pennylane", {"cadence": [7, 15, 30]})
    assert cfg["primary_tool"] == "Pennylane"
    assert cfg["config"]["cadence"] == [7, 15, 30]
    assert cfg["status"] == "ready"

    cfg_none = worker.configure_connectors(None, {})
    assert cfg_none["status"] == "unconfigured"


def test_pending_instances_empty_when_no_supabase():
    worker = OnboardingWorker(supabase_url=None, supabase_key=None)
    pending = worker.get_pending_agent_instances()
    assert pending == []
