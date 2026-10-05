#!/usr/bin/env python3
"""Sonde de vérification en direct du service déployé pour le ticket KAN-45.

Effectue les requêtes HTTP réelles sur :
- www.orso-agents.fr (Vercel)
- ops.orso-agents.fr (VPS OVH / Olympe Core)
- Inspection de la base de données SQLite sur le serveur de production.
"""

import json
import subprocess
import urllib.error
import urllib.request

print("=" * 70)
print("1. VERIFICATION DIRECTE VITRINE VERCEL (www.orso-agents.fr)")
print("=" * 70)

routes = [
    "https://www.orso-agents.fr/contact",
    "https://www.orso-agents.fr/tarifs",
    "https://www.orso-agents.fr/onboarding",
    "https://www.orso-agents.fr/contact.html",
]

for url in routes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req) as resp:
            print(f"GET {url} -> HTTP {resp.status} (Final URL: {resp.url})")
    except urllib.error.HTTPError as e:
        print(f"GET {url} -> HTTP {e.code}")

print("\n" + "=" * 70)
print("2. VERIFICATION HEALTH SUPERVISEUR OLYMPE (ops.orso-agents.fr)")
print("=" * 70)

health_url = "https://ops.orso-agents.fr/api/olympe/health"
req_health = urllib.request.Request(health_url)
try:
    with urllib.request.urlopen(req_health) as resp:
        body = resp.read().decode("utf-8")
        print(f"GET {health_url} -> HTTP {resp.status}")
        print(f"Response: {body}")
except Exception as e:
    print(f"GET {health_url} -> Error: {e}")

print("\n" + "=" * 70)
print("3. VERIFICATION SECURITE ENDPOINT PUBLIC (CONSENTEMENT RGPD OBLIGATOIRE)")
print("=" * 70)

contact_url = "https://ops.orso-agents.fr/api/olympe/contact"
bad_payload = json.dumps({
    "name": "Audit Security",
    "email": "audit@orso-agents.fr",
    "message": "Test sans consentement",
    "consent": False,
}).encode("utf-8")

req_bad = urllib.request.Request(contact_url, data=bad_payload, headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req_bad) as resp:
        print(f"POST {contact_url} (consent=False) -> Inattendu: HTTP {resp.status}")
except urllib.error.HTTPError as e:
    print(f"POST {contact_url} (consent=False) -> Attendu: HTTP {e.code}")
    print(f"Detail: {e.read().decode('utf-8')}")

print("\n" + "=" * 70)
print("4. VERIFICATION LIVE SOUMISSION LEAD VITRINE -> OPS COCKPIT")
print("=" * 70)

live_lead = {
    "name": "Alexandre Dupont",
    "email": "a.dupont@logistique-france.fr",
    "company": "Logistique France SAS",
    "phone": "06 99 88 77 66",
    "interest": "recouvrement",
    "message": "Demande de qualification pour essai 30 jours KAN-45 verification live PO.",
    "consent": True,
}
req_live = urllib.request.Request(
    contact_url,
    data=json.dumps(live_lead).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)

try:
    with urllib.request.urlopen(req_live) as resp:
        body = resp.read().decode("utf-8")
        print(f"POST {contact_url} (consent=True) -> HTTP {resp.status}")
        print(f"Lead Response: {body}")
except Exception as e:
    print(f"POST {contact_url} -> Error: {e}")

print("\n" + "=" * 70)
print("5. VERIFICATION BASE DE DONNEES SQLITE VPS (PERSISTANCE EN DIRECT)")
print("=" * 70)

ssh_cmd = [
    "/usr/bin/ssh",
    "-o", "BatchMode=yes",
    "ubuntu@92.222.68.80",
    "docker exec olympe_core python3 -c \""
    "import sqlite3, json\n"
    "from olympe.server import ops_manager\n"
    "conn = sqlite3.connect(str(ops_manager.db_path))\n"
    "cursor = conn.cursor()\n"
    "cursor.execute('SELECT id, name, email, company, status, consent, created_at FROM contact_leads WHERE email = \\\"a.dupont@logistique-france.fr\\\"')\n"
    "lead = cursor.fetchone()\n"
    "print('[PROD SQL LEAD]      ', lead)\n"
    "cursor.execute('SELECT id, slug, name, status, contact_email FROM tenants WHERE contact_email = \\\"a.dupont@logistique-france.fr\\\"')\n"
    "tenant = cursor.fetchone()\n"
    "print('[PROD SQL TENANT]    ', tenant)\n"
    "cursor.execute('SELECT id, action, target, actor, timestamp FROM audit_events WHERE target = \\\"a.dupont@logistique-france.fr\\\"')\n"
    "audit = cursor.fetchone()\n"
    "print('[PROD SQL AUDIT]     ', audit)\n"
    "\""
]

res = subprocess.run(ssh_cmd, capture_output=True, text=True)
print(res.stdout)
if res.stderr:
    print("Stderr:", res.stderr)
