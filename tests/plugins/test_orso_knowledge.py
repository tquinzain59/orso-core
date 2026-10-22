"""Contrats de la capacité Knowledge (KAN-130) : plugins/orso-knowledge/.

Un test par critère d'acceptation (CA1 à CA5) ; le magasin tourne pour de vrai sur un répertoire
temporaire, sans mock.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_PKG = Path(__file__).resolve().parents[2] / "plugins" / "orso-knowledge"


def _load():
    name = "orso_knowledge_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, _PKG / "__init__.py", submodule_search_locations=[str(_PKG)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def k(tmp_path, monkeypatch):
    monkeypatch.delenv("ORSO_CLIENT_ID", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    return _load()


def _store(k, tenant, tmp_path):
    return sys.modules[k.__name__ + ".store"].KnowledgeStore(tmp_path / "root", tenant)


def test_ca1_ingested_document_is_found_with_its_source(k, tmp_path):
    store = _store(k, "acme", tmp_path)
    store.ingest("conditions.md", b"# Paiement\n\nLe delai de reglement des factures est de 30 jours.")
    hits = store.search("delai de reglement")
    assert hits and "30 jours" in hits[0].text
    assert hits[0].citation == "[Source: conditions.md, v1, §1]"
    assert store.search("zebre") == []


def test_ca2_document_is_invisible_to_other_tenant(k, tmp_path, monkeypatch):
    _store(k, "acme", tmp_path).ingest("secret.txt", b"Le code interne du projet est Orion.")
    other = _store(k, "globex", tmp_path)
    assert other.search("Orion") == []
    # Un conteneur lié à un client refuse d'ouvrir le magasin d'un autre.
    monkeypatch.setenv("ORSO_CLIENT_ID", "globex")
    with pytest.raises(PermissionError):
        _store(k, "acme", tmp_path)


def test_tenant_is_required_and_cannot_escape_the_root(k, tmp_path):
    store_mod = sys.modules[k.__name__ + ".store"]
    with pytest.raises(store_mod.TenantRequiredError):
        store_mod.KnowledgeStore(tmp_path / "root", None)
    with pytest.raises(ValueError):
        store_mod.KnowledgeStore(tmp_path / "root", "../acme")


def test_ca3_latest_version_prevails_and_retired_stops_answering(k, tmp_path):
    store = _store(k, "acme", tmp_path)
    assert store.ingest("tarif.txt", b"Le tarif est de 100 euros.").status == "created"
    assert store.ingest("tarif.txt", b"Le tarif est de 100 euros.").status == "unchanged"
    assert store.ingest("tarif.txt", b"Le tarif est de 120 euros.").status == "updated"
    hits = store.search("tarif")
    assert [h.version for h in hits] == [2] and "120" in hits[0].text
    assert [v["status"] for v in store.history("tarif.txt")] == ["superseded", "current"]
    store.retire("tarif.txt")
    assert store.search("tarif") == []
    assert store.history("tarif.txt")[-1]["status"] == "retired"
    assert store.ingest("tarif.txt", b"Le tarif est de 130 euros.").version == 3
    assert store.search("tarif")[0].version == 3


def test_ca4_answer_without_citation_is_flagged_and_cited_one_passes(k, tmp_path):
    citations = ["[Source: conditions.md, v1, §1]"]
    flagged = k.flag_answer("Le delai est de 30 jours.", citations)
    assert flagged and "Réponse signalée" in flagged and citations[0] in flagged
    assert k.flag_answer(f"Le delai est de 30 jours {citations[0]}.", citations) is None
    invented = k.flag_answer(f"30 jours {citations[0]} [Source: faux.md, v9, §1]", citations)
    assert invented and "non reconnue" in invented


def test_ca4_hooks_flag_only_turns_that_used_retrieved_passages(k, tmp_path, monkeypatch):
    monkeypatch.setenv("ORSO_CLIENT_ID", "acme")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    store_mod = sys.modules[k.__name__ + ".store"]
    store_mod.KnowledgeStore(tmp_path / "home" / "knowledge").ingest(
        "conditions.md", b"Le delai de reglement est de 30 jours."
    )
    assert k._check_available() is True
    result = k._handle_search({"query": "delai reglement"})
    k._on_pre_llm_call(session_id="s1")
    k._on_post_tool_call(tool_name="knowledge_search", result=result, session_id="s1")
    out = k._on_transform_llm_output(response_text="C'est 30 jours.", session_id="s1")
    assert out and "Réponse signalée" in out
    # Tour sans recherche documentaire : aucune obligation, réponse inchangée.
    k._on_pre_llm_call(session_id="s2")
    assert k._on_transform_llm_output(response_text="Bonjour", session_id="s2") is None


def test_ca5_connector_import_indexes_and_traces_origin(k, tmp_path):
    export = tmp_path / "drive_export"
    (export / "compta").mkdir(parents=True)
    (export / "compta" / "bilan.csv").write_bytes(b"poste;montant\nloyer;1200")
    (export / "scan.pdf").write_bytes(b"%PDF-1.4")
    conn = sys.modules[k.__name__ + ".connectors"]
    store = _store(k, "acme", tmp_path)
    report = conn.import_from(store, conn.DirectoryConnector("google-drive", export))
    assert report.created == ["google-drive:compta/bilan.csv"]
    assert list(report.failed) == ["scan.pdf"]  # format non géré : refusé et consigné, pas silencieux
    hit = store.search("loyer")[0]
    assert (hit.origin_connector, hit.origin_ref) == ("google-drive", "compta/bilan.csv")
    again = conn.import_from(store, conn.DirectoryConnector("google-drive", export))
    assert again.unchanged == ["google-drive:compta/bilan.csv"]


def test_registration_exposes_tool_hooks_and_cli(k):
    seen = {"tools": [], "hooks": [], "cli": []}

    class Ctx:
        def register_tool(self, **kw):
            seen["tools"].append(kw["name"])

        def register_hook(self, name, fn):
            seen["hooks"].append(name)

        def register_cli_command(self, **kw):
            seen["cli"].append(kw["name"])

    k.register(Ctx())
    assert seen["tools"] == ["knowledge_search"]
    assert set(seen["hooks"]) == {"pre_llm_call", "post_tool_call", "transform_llm_output"}
    assert seen["cli"] == ["knowledge"]
    assert json.loads(k._handle_search({"query": "x"}))  # sans client : erreur JSON, pas d'exception


def test_cli_refuses_foreign_tenant_with_exit_code_1(k, tmp_path, monkeypatch, capsys):
    import argparse

    monkeypatch.setenv("ORSO_CLIENT_ID", "acme")
    parser = argparse.ArgumentParser()
    k._setup_cli(parser)
    args = parser.parse_args(["--tenant", "globex", "--root", str(tmp_path / "root"), "list"])
    assert k._run_cli(args) == 1
    assert "accès refusé" in capsys.readouterr().err
