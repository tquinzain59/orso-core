"""KAN-129 / CA7 — la politique réseau sortant est déclarée validée et datée (preuve documentaire)."""

from __future__ import annotations

import re
from pathlib import Path

SPEC = Path(__file__).resolve().parents[2] / "docs" / "3_Technique" / "spec_kan129_sandbox_produit.md"


def _network_section() -> str:
    text = SPEC.read_text(encoding="utf-8")
    m = re.search(r"## 6\. Politique réseau.*?(?=\n## 7\.)", text, re.S)
    assert m, "section politique réseau absente"
    return m.group(0)


def test_network_policy_is_dated_declared_validated_and_not_pending():
    section = _network_section()
    assert re.search(r"20\d\d-\d\d-\d\d", section.splitlines()[0]), "titre non daté"
    assert "validée" in section.lower()
    assert "allowlist stricte" in section.lower()
    assert "en attente" not in section.lower()
