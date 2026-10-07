"""Tests d'acceptation et invariants pour le filtrage des flux sortants KAN-52 (CA1 à CA6)."""

from __future__ import annotations

from pathlib import Path

from scripts.security.configure_docker_egress_filter import (
    OFFICIAL_EGRESS_ALLOWLIST,
    audit_current_rules,
    build_iptables_rules,
    build_rollback_rules,
)


def test_kan52_ca1_allowlist_structure_and_categories():
    """CA1 : Vérifie que l'allowlist minimale est formalisée avec catégories, ports et demandeurs."""
    expected_categories = {"dns", "ntp", "llm_providers", "payments", "client_erps"}
    assert set(OFFICIAL_EGRESS_ALLOWLIST.keys()) == expected_categories

    # LLM providers
    llms = OFFICIAL_EGRESS_ALLOWLIST["llm_providers"]
    assert "443/tcp" in llms["ports"]
    assert "openrouter.ai" in llms["domains"]
    assert "api.openai.com" in llms["domains"]
    assert "api.anthropic.com" in llms["domains"]
    assert len(llms["requester"]) > 0

    # Payments
    payments = OFFICIAL_EGRESS_ALLOWLIST["payments"]
    assert "api.stripe.com" in payments["domains"]

    # ERPs
    erps = OFFICIAL_EGRESS_ALLOWLIST["client_erps"]
    assert "app.pennylane.com" in erps["domains"]
    assert "apiv2.sellsy.com" in erps["domains"]


def test_kan52_ca2_ca3_iptables_rules_generation():
    """CA2 & CA3 : Vérifie la génération exacte des règles DOCKER-USER avec filtrage et journalisation."""
    rules = build_iptables_rules(interface="docker0")
    rules_text = "\n".join(rules)

    # Invariants de filtrage
    assert "-m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT" in rules_text
    assert "--dport 53 -j ACCEPT" in rules_text
    assert "--dport 123 -j ACCEPT" in rules_text
    assert "--dport 443 -j ACCEPT" in rules_text

    # Journalisation des rejets avec préfixe conforme (CA3)
    assert "-j LOG --log-prefix '[ORSO-EGRESS-DROP]: '" in rules_text

    # Rejet par défaut de tout autre flux (CA2)
    assert rules[-1] == "iptables -A DOCKER-USER -i docker0 -j DROP"


def test_kan52_ca5_rollback_rules_generation():
    """CA5 : Vérifie la génération des règles de rollback remettant la chaîne à l'état neutre."""
    rb = build_rollback_rules()
    assert rb == [
        "iptables -F DOCKER-USER",
        "iptables -A DOCKER-USER -j RETURN",
    ]


def test_kan52_audit_current_rules_parser():
    """Vérifie la détection de conformité sur un dump iptables."""
    compliant_dump = """
    -P DOCKER-USER ACCEPT
    -A DOCKER-USER -i docker0 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
    -A DOCKER-USER -i docker0 -p udp -m udp --dport 53 -j ACCEPT
    -A DOCKER-USER -i docker0 -p tcp -m tcp --dport 443 -j ACCEPT
    -A DOCKER-USER -i docker0 -m limit --limit 5/min -j LOG --log-prefix "[ORSO-EGRESS-DROP]: "
    -A DOCKER-USER -i docker0 -j DROP
    """
    ok, details = audit_current_rules(iptables_output=compliant_dump)
    assert ok is True
    assert details["compliant"] is True
    assert details["has_drop_logging"] is True

    insecure_dump = "-P DOCKER-USER ACCEPT\n-A DOCKER-USER -j RETURN"
    ok_bad, details_bad = audit_current_rules(iptables_output=insecure_dump)
    assert ok_bad is False
    assert details_bad["compliant"] is False


def test_kan52_ca6_operational_doc_exists():
    """CA1 & CA5 : Vérifie l'existence et la substance de la documentation d'exploitation."""
    doc_file = Path(__file__).resolve().parent.parent.parent / "docs/3_Technique/procedure_filtrage_flux_sortants_kan52.md"
    assert doc_file.is_file(), "La documentation docs/3_Technique/procedure_filtrage_flux_sortants_kan52.md doit exister"
    content = doc_file.read_text(encoding="utf-8")
    assert "[ORSO-EGRESS-DROP]" in content
    assert "DOCKER-USER" in content
    assert "Rollback" in content or "Retour Arrière" in content
