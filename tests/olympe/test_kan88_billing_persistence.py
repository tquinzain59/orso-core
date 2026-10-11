"""KAN-88 — facturation et idempotence du webhook Stripe : support réel, échec rendu.

Le support est un serveur PostgREST de test (HTTP réel, sans mock de ``urllib``) : le chemin
``handle_stripe_webhook`` -> ``supabase_request_strict`` -> socket est exercé de bout en bout.
Les identifiants de test sont préfixés ``evt_kan88_test_`` / ``in_kan88_test_`` (purgeables).

- CA1/CA2 : facture écrite, trace d'idempotence écrite, rejeu = already_processed + compteur persisté
  (y compris après perte de la mémoire du processus).
- CA3 : table indisponible (PGRST205) -> HTTP 503, erreur nommée, livraison « failed », événement
  non mémorisé comme traité.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from olympe.server import app, ops_manager

TENANT_ID = "11111111-1111-4111-8111-111111111111"
SLUG = "kan88-test-tenant"
CUS = "cus_kan88_test"


class _PostgrestStub(BaseHTTPRequestHandler):
    tables: dict = {}
    absent: set = set()
    requests: list = []

    def log_message(self, *args):  # silence
        pass

    def _reply(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _handle(self, method):
        url = urlparse(self.path)
        table = url.path.rsplit("/", 1)[-1]
        query = parse_qs(url.query)
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length)) if length else None
        type(self).requests.append((method, table, query, payload))
        if table in self.absent:
            return self._reply(404, {
                "code": "PGRST205",
                "message": f"Could not find the table 'public.{table}' in the schema cache",
            })
        rows = self.tables.setdefault(table, [])
        filters = {k: v[0][3:] for k, v in query.items() if v and v[0].startswith("eq.")}
        match = [r for r in rows if all(str(r.get(k)) == v for k, v in filters.items())]
        if method == "GET":
            return self._reply(200, match)
        if method == "PATCH":
            for r in match:
                r.update(payload)
            return self._reply(200, match)
        if method == "POST":
            conflict = query.get("on_conflict", [None])[0]
            if conflict and any(r.get(conflict) == payload.get(conflict) for r in rows):
                for r in rows:
                    if r.get(conflict) == payload.get(conflict):
                        r.update(payload)
                return self._reply(201, [payload])
            rows.append(dict(payload))
            return self._reply(201, [payload])
        return self._reply(405, {})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PATCH(self):
        self._handle("PATCH")


@pytest.fixture
def stub(monkeypatch, tmp_path):
    monkeypatch.setenv("OLYMPE_DB_PATH", str(tmp_path / "ops.db"))
    _PostgrestStub.tables = {
        "tenants": [{"id": TENANT_ID, "slug": SLUG, "name": "KAN-88 test", "status": "active"}],
        "subscriptions": [],
        "invoices": [],
        "processed_webhook_events": [],
    }
    _PostgrestStub.absent = set()
    _PostgrestStub.requests = []
    server = HTTPServer(("127.0.0.1", 0), _PostgrestStub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(ops_manager, "supabase_url", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setattr(ops_manager, "supabase_key", "test-key-not-a-secret")
    monkeypatch.setattr(ops_manager, "stripe_secret_key", "")
    for store in (ops_manager._processed_events, ops_manager._webhook_deliveries, ops_manager._audit_log):
        store.clear()
    yield _PostgrestStub
    server.shutdown()
    server.server_close()
    for store in (ops_manager._processed_events, ops_manager._webhook_deliveries, ops_manager._audit_log):
        store.clear()


def _payment_event(suffix: str) -> dict:
    return {
        "id": f"evt_kan88_test_{suffix}",
        "type": "invoice.payment_succeeded",
        "data": {"object": {
            "id": f"in_kan88_test_{suffix}",
            "customer": CUS,
            "amount_paid": 12000,
            "currency": "eur",
            "number": f"KAN88-TEST-{suffix}",
            "metadata": {"tenant_slug": SLUG},
        }},
    }


def test_ca1_ca2_invoice_and_idempotence_are_persisted_and_survive_restart(stub):
    client = TestClient(app)
    event = _payment_event("a1")

    first = client.post("/api/olympe/ops/webhooks/stripe", json=event)
    assert first.status_code == 200 and first.json()["status"] == "processed"

    invoice = stub.tables["invoices"][0]
    assert invoice["stripe_invoice_id"] == "in_kan88_test_a1"
    assert invoice["tenant_id"] == TENANT_ID and invoice["amount_ttc"] == 120.0
    recorded = stub.tables["processed_webhook_events"][0]
    assert recorded["event_id"] == "evt_kan88_test_a1" and recorded["replay_count"] == 0

    ops_manager._processed_events.clear()  # redémarrage : seule la base fait foi
    second = client.post("/api/olympe/ops/webhooks/stripe", json=event)
    assert second.status_code == 200
    assert second.json()["status"] == "already_processed" and second.json()["replay_count"] == 1
    assert stub.tables["processed_webhook_events"][0]["replay_count"] == 1
    assert len(stub.tables["invoices"]) == 1  # aucun retraitement


def test_same_invoice_under_new_event_id_updates_instead_of_failing(stub):
    client = TestClient(app)
    first = _payment_event("b1")
    again = {**_payment_event("b1"), "id": "evt_kan88_test_b2"}
    assert client.post("/api/olympe/ops/webhooks/stripe", json=first).status_code == 200
    assert client.post("/api/olympe/ops/webhooks/stripe", json=again).status_code == 200
    assert len(stub.tables["invoices"]) == 1


@pytest.mark.parametrize(
    "absent, expected_error",
    [
        ({"processed_webhook_events"}, "IDEMPOTENCE_STORE_UNAVAILABLE"),
        ({"invoices"}, "BILLING_WRITE_FAILED"),
    ],
)
def test_ca3_unavailable_table_is_rendered_as_failure_not_success(stub, absent, expected_error):
    stub.absent = set(absent)
    client = TestClient(app)
    event = _payment_event("c1")

    resp = client.post("/api/olympe/ops/webhooks/stripe", json=event)

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "failed" and body["error"] == expected_error
    assert "PGRST205" in body["detail"]
    assert event["id"] not in ops_manager._processed_events
    assert stub.tables["processed_webhook_events"] == []  # jamais « traité » sans écriture réelle
    delivery = next(d for d in ops_manager._webhook_deliveries if d["id"] == event["id"])
    assert delivery["status"] == "failed" and expected_error in delivery["error_reason"]
    assert any(e["action"] == "webhook:failed" for e in ops_manager._audit_log)


def test_ca3_failed_event_is_processed_on_redelivery_once_table_is_back(stub):
    stub.absent = {"invoices"}
    client = TestClient(app)
    event = _payment_event("d1")
    assert client.post("/api/olympe/ops/webhooks/stripe", json=event).status_code == 503

    stub.absent = set()
    retry = client.post("/api/olympe/ops/webhooks/stripe", json=event)
    assert retry.status_code == 200 and retry.json()["status"] == "processed"
    assert [r["stripe_invoice_id"] for r in stub.tables["invoices"]] == ["in_kan88_test_d1"]
