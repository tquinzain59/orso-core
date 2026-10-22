"""Contrats de la capacité Knowledge (KAN-130) : plugins/orso-knowledge/.

Un test par critère d'acceptation (CA1 à CA5) ; le magasin tourne pour de vrai sur un répertoire
temporaire, sans mock. Les connecteurs API parlent HTTP à un faux service sur la boucle locale
(vraies sockets, vrai transport) : aucun réseau externe, aucun identifiant réel.
"""

import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
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


def test_ca4_answer_without_source_is_refused_and_cited_one_accepted(k):
    citations = ["[Source: conditions.md, v1, §1]"]
    secret_claim = "Le delai est de 30 jours."
    refused = k.block_answer(secret_claim, citations)
    assert refused and "Réponse refusée" in refused and citations[0] in refused
    assert secret_claim not in refused  # bloquée : le contenu non sourcé n'est pas transmis
    assert k.block_answer(f"{secret_claim} {citations[0]}", citations) is None
    invented = k.block_answer(f"30 jours {citations[0]} [Source: faux.md, v9, §1]", citations)
    assert invented and "faux.md" in invented and "30 jours" not in invented


def _seed_and_search(k, tmp_path, monkeypatch, session):
    monkeypatch.setenv("ORSO_CLIENT_ID", "acme")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    store_mod = sys.modules[k.__name__ + ".store"]
    store_mod.KnowledgeStore(tmp_path / "home" / "knowledge").ingest(
        "conditions.md", b"Le delai de reglement est de 30 jours."
    )
    k._on_pre_llm_call(session_id=session)
    result = json.loads(k._handle_search({"query": "delai reglement"}, session_id=session))
    return result["passages"][0]["citation"]


def test_ca4_hooks_block_unsourced_turn_and_let_sourced_or_documentless_turns_through(
    k, tmp_path, monkeypatch
):
    citation = _seed_and_search(k, tmp_path, monkeypatch, "s1")
    out = k._on_transform_llm_output(response_text="C'est 30 jours.", session_id="s1")
    assert out and "Réponse refusée" in out and "30 jours" not in out
    # Réponse avec source : acceptée (le hook ne remplace rien).
    _seed_and_search(k, tmp_path, monkeypatch, "s2")
    assert k._on_transform_llm_output(response_text=f"30 jours {citation}", session_id="s2") is None
    # Tour sans recherche documentaire : aucune obligation, réponse inchangée.
    k._on_pre_llm_call(session_id="s3")
    assert k._on_transform_llm_output(response_text="Bonjour", session_id="s3") is None


def test_ca4_invented_source_is_refused_even_without_search_this_turn(k, tmp_path, monkeypatch):
    citation = _seed_and_search(k, tmp_path, monkeypatch, "s1")
    assert k._on_transform_llm_output(response_text=f"ok {citation}", session_id="s1") is None
    # Tour suivant, sans recherche : la citation d'un passage déjà retrouvé reste valide...
    k._on_pre_llm_call(session_id="s1")
    assert k._on_transform_llm_output(response_text=f"rappel {citation}", session_id="s1") is None
    # ... une source inventée est refusée, y compris dans une session sans aucune recherche.
    fake = "[Source: fiction.md, v1, §1]"
    for session in ("s1", "jamais-cherche"):
        k._on_pre_llm_call(session_id=session)
        out = k._on_transform_llm_output(response_text=f"selon {fake}", session_id=session)
        assert out and "Réponse refusée" in out


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


class _FakeService(BaseHTTPRequestHandler):
    """Faux Drive / Pennylane / jeton OAuth, sur la boucle locale. ``seen`` consigne les requêtes."""

    seen: list = []
    drive_files = {
        "root1": [
            {"id": "f1", "name": "conditions", "mimeType": "application/vnd.google-apps.document"},
            {"id": "f2", "name": "scan.pdf", "mimeType": "application/pdf"},
            {"id": "d1", "name": "compta", "mimeType": "application/vnd.google-apps.folder"},
        ],
        "d1": [{"id": "f3", "name": "bilan.csv", "mimeType": "text/csv"}],
    }
    bodies = {
        "/drive/v3/files/f1/export": b"Le delai de reglement des factures est de 45 jours.",
        "/drive/v3/files/f3": b"poste;montant\nloyer;1200",
    }

    def log_message(self, *args):
        pass

    def _send(self, status, body: bytes, ctype="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.seen.append(("POST", self.path, self.headers.get("Authorization"), self.rfile.read(length)))
        self._send(200, json.dumps({"access_token": "tok-from-refresh"}).encode())

    def do_GET(self):
        from urllib.parse import parse_qs, urlsplit

        url = urlsplit(self.path)
        query = parse_qs(url.query)
        auth = self.headers.get("Authorization")
        self.seen.append(("GET", self.path, auth, b""))
        if auth not in ("Bearer tok-from-refresh", "Bearer pl-key"):
            return self._send(401, b'{"error": "secret-echoed-by-server"}')
        if url.path == "/drive/v3/files":
            folder = query["q"][0].split("'")[1]
            return self._send(200, json.dumps({"files": self.drive_files[folder]}).encode())
        if url.path in self.bodies:
            return self._send(200, self.bodies[url.path], "text/plain")
        if url.path == "/pl/customer_invoices":
            first = "cursor" not in query
            items = [{"id": 7, "invoice_number": "F-2026-007", "label": "Loyer octobre",
                      "amount": "1200.00", "public_file_url": "https://x/f?sig=" + ("a" if first else "b")}]
            if not first:
                items = [{"id": 8, "invoice_number": "F-2026-008", "label": "Maintenance", "amount": "300.00"}]
            return self._send(200, json.dumps(
                {"items": items, "has_more": first, "next_cursor": "c2" if first else None}).encode())
        if url.path == "/pl/supplier_invoices":
            return self._send(200, json.dumps({"items": [], "has_more": False, "next_cursor": None}).encode())
        self._send(404, b"{}")


@pytest.fixture
def service():
    _FakeService.seen = []
    server = HTTPServer(("127.0.0.1", 0), _FakeService)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", _FakeService.seen
    server.shutdown()
    server.server_close()


_GOOGLE_ENV = {"GOOGLE_WORKSPACE_CREDENTIALS": json.dumps(
    {"client_id": "cid", "client_secret": "csecret", "refresh_token": "rtok"})}


def test_ca5_google_drive_api_import_indexes_and_traces_origin(k, tmp_path, service):
    base, seen = service
    api = sys.modules[k.__name__ + ".connectors_api"]
    conn = sys.modules[k.__name__ + ".connectors"]
    drive = api.GoogleDriveConnector(
        "root1", environ={**_GOOGLE_ENV, "GOOGLE_WORKSPACE_CREDENTIALS": json.dumps(
            {"client_id": "cid", "client_secret": "csecret", "refresh_token": "rtok",
             "token_uri": base + "/token"})},
        api_base=base + "/drive/v3",
    )
    store = _store(k, "acme", tmp_path)
    report = conn.import_from(store, drive)
    assert sorted(report.created) == ["google-drive:f1", "google-drive:f3"]
    assert list(report.failed) == ["f2"]  # PDF : refusé et consigné, pas téléchargé
    assert [r for r in seen if r[0] == "POST"][0][3].count(b"refresh_token=rtok") == 1
    hit = store.search("reglement")[0]
    assert (hit.origin_connector, hit.origin_ref) == ("google-drive", "f1")
    assert hit.title == "conditions.txt" and "45 jours" in hit.text
    assert store.search("loyer")[0].title == "compta/bilan.csv"
    assert conn.import_from(store, drive).unchanged == ["google-drive:f1", "google-drive:f3"]
    # Le document est indexé dans le magasin du client : l'autre client ne le voit pas.
    assert _store(k, "globex", tmp_path).search("reglement") == []


def test_ca5_pennylane_api_import_paginates_and_versions_changes(k, tmp_path, service):
    base, seen = service
    api = sys.modules[k.__name__ + ".connectors_api"]
    conn = sys.modules[k.__name__ + ".connectors"]
    pl = api.PennylaneConnector(["customer_invoices"], environ={"PENNYLANE_API_KEY": "pl-key"},
                                api_base=base + "/pl")
    store = _store(k, "acme", tmp_path)
    assert conn.import_from(store, pl).created == [
        "pennylane:customer_invoices/7", "pennylane:customer_invoices/8"]
    hit = store.search("Maintenance")[0]
    assert (hit.origin_connector, hit.origin_ref) == ("pennylane", "customer_invoices/8")
    assert hit.citation == "[Source: customer_invoices/F-2026-008.json, v1, §1]"
    # Le lien signé change à chaque appel : il ne doit pas fabriquer de version.
    assert conn.import_from(store, pl).unchanged == [
        "pennylane:customer_invoices/7", "pennylane:customer_invoices/8"]


def test_ca5_connector_errors_are_explicit_and_leak_no_secret(k, tmp_path, service):
    base, _ = service
    api = sys.modules[k.__name__ + ".connectors_api"]
    conn = sys.modules[k.__name__ + ".connectors"]
    store = _store(k, "acme", tmp_path)
    with pytest.raises(conn.ConnectorError, match="PENNYLANE_API_KEY"):
        conn.import_from(store, api.PennylaneConnector(environ={}, api_base=base + "/pl"))
    with pytest.raises(conn.ConnectorError) as exc:
        conn.import_from(store, api.PennylaneConnector(
            environ={"PENNYLANE_API_KEY": "mauvaise-cle"}, api_base=base + "/pl"))
    assert "401" in str(exc.value)
    assert "mauvaise-cle" not in str(exc.value) and "secret-echoed" not in str(exc.value)
    with pytest.raises(conn.ConnectorError, match="GOOGLE_WORKSPACE_CREDENTIALS"):
        conn.import_from(store, api.GoogleDriveConnector("root1", environ={}, api_base=base + "/drive/v3"))
    with pytest.raises(ValueError, match="HTTPS"):
        api.PennylaneConnector(api_base="http://app.example.com/api")
    with pytest.raises(ValueError, match="connecteur API inconnu"):
        api.build_api_connector("dropbox")
    with pytest.raises(ValueError, match="dossier Drive"):
        api.build_api_connector("google-drive")


def test_cli_import_from_api_connector_without_credentials_exits_1(k, tmp_path, monkeypatch, capsys):
    import argparse

    monkeypatch.delenv("PENNYLANE_API_KEY", raising=False)
    parser = argparse.ArgumentParser()
    k._setup_cli(parser)
    args = parser.parse_args(
        ["--tenant", "acme", "--root", str(tmp_path / "root"), "import", "--connector", "pennylane"])
    assert k._run_cli(args) == 1
    assert "PENNYLANE_API_KEY" in capsys.readouterr().err


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
    assert set(seen["hooks"]) == {"pre_llm_call", "transform_llm_output"}
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
