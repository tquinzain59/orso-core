#!/usr/bin/env python3
"""Sonde de vérification en direct du service déployé pour le ticket KAN-45.

Effectue des vérifications HTTP en LECTURE SEULE (GET) :
1. Neutralisation des 4 anciennes routes d'onboarding autonome -> attendu HTTP 404 (Condition 1).
2. Porte de conformité sécurité vitrine KAN-46 -> redirection admin.html vers https://ops.orso-agents.fr (Condition 4).
3. Accessibilité des routes vitrine principales (Vercel) : /contact, /tarifs, /onboarding -> HTTP 200.
4. Health check superviseur Olympe (ops.orso-agents.fr) -> HTTP 200.
5. Inspection SQL de la base de production (absence de traces de banc, intégrité du schéma) (Condition 5).
"""

import subprocess
import urllib.error
import urllib.request

print("=" * 70)
print("1. VERIFICATION ROUTES ONBOARDING AUTONOME NEUTRALISEES (CONDITION 1)")
print("   Règle : Tout GET sur ces anciennes routes doit renvoyer HTTP 404.")
print("=" * 70)

neutralized_routes = [
    "https://ops.orso-agents.fr/api/olympe/onboarding/init-setup",
    "https://ops.orso-agents.fr/api/olympe/onboarding/create-subscription",
    "https://ops.orso-agents.fr/api/olympe/onboarding/create-admin-user",
    "https://ops.orso-agents.fr/api/olympe/onboarding/rewrite-mission-letter",
]

for url in neutralized_routes:
    req = urllib.request.Request(url, headers={"User-Agent": "OrsoLiveCheck/1.0"})
    try:
        with urllib.request.urlopen(req) as resp:
            print(f"[FAIL] GET {url} -> HTTP {resp.status} (devrait renvoyer 404)")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"[OK]   GET {url} -> HTTP 404 Not Found (neutralisé avec succès)")
        else:
            print(f"[WARN] GET {url} -> HTTP {e.code} (attendu 404)")

print("\n" + "=" * 70)
print("2. VERIFICATION PORTE DE SECURITE KAN-46 (CONDITION 4)")
print("   Règle : Redirection 1-hop directe admin.html vers https://ops.orso-agents.fr")
print("=" * 70)

class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

opener = urllib.request.build_opener(NoRedirectHandler)
admin_url = "https://www.orso-agents.fr/admin.html"
req_admin = urllib.request.Request(admin_url, headers={"User-Agent": "OrsoLiveCheck/1.0"})
try:
    with opener.open(req_admin) as resp:
        print(f"[FAIL] GET {admin_url} -> HTTP {resp.status} (pas de redirection)")
except urllib.error.HTTPError as e:
    loc = e.headers.get("Location", "")
    if e.code in (301, 308) and "ops.orso-agents.fr" in loc:
        print(f"[OK]   GET {admin_url} -> HTTP {e.code} vers {loc}")
    else:
        print(f"[WARN] GET {admin_url} -> HTTP {e.code} vers {loc}")

print("\n" + "=" * 70)
print("3. VERIFICATION ROUTES VITRINE VERCEL (www.orso-agents.fr)")
print("=" * 70)

vitrine_routes = [
    "https://www.orso-agents.fr/contact",
    "https://www.orso-agents.fr/tarifs",
    "https://www.orso-agents.fr/onboarding",
]

for url in vitrine_routes:
    req = urllib.request.Request(url, headers={"User-Agent": "OrsoLiveCheck/1.0"})
    try:
        with urllib.request.urlopen(req) as resp:
            print(f"[OK]   GET {url} -> HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        print(f"[WARN] GET {url} -> HTTP {e.code}")

print("\n" + "=" * 70)
print("4. VERIFICATION HEALTH SUPERVISEUR OLYMPE (ops.orso-agents.fr)")
print("=" * 70)

health_url = "https://ops.orso-agents.fr/api/olympe/health"
req_health = urllib.request.Request(health_url, headers={"User-Agent": "OrsoLiveCheck/1.0"})
try:
    with urllib.request.urlopen(req_health) as resp:
        body = resp.read().decode("utf-8")
        print(f"[OK]   GET {health_url} -> HTTP {resp.status} | Body: {body.strip()}")
except Exception as e:
    print(f"[WARN] GET {health_url} -> Erreur: {e}")

print("\n" + "=" * 70)
print("5. VERIFICATION INSPECTION SQL PRODUCTION (CONDITION 5 & CONDITION 2)")
print("=" * 70)

ssh_cmd = [
    "/usr/bin/ssh",
    "-o", "BatchMode=yes",
    "ubuntu@92.222.68.80",
    "docker exec olympe_core python3 -c \""
    "import sqlite3\n"
    "from olympe.server import ops_manager\n"
    "conn = sqlite3.connect(str(ops_manager.db_path))\n"
    "cursor = conn.cursor()\n"
    "# Vérification purge traces banc (a.dupont@logistique-france.fr)\n"
    "cursor.execute('SELECT COUNT(*) FROM contact_leads WHERE id = \\\"lead_1791218130_7859\\\" OR email = \\\"a.dupont@logistique-france.fr\\\"')\n"
    "dupont_lead_count = cursor.fetchone()[0]\n"
    "cursor.execute('SELECT COUNT(*) FROM tenants WHERE slug = \\\"lead-logistique-france-sa-130\\\" OR id = \\\"tenant-lead-logistique-france-sa-130\\\"')\n"
    "dupont_tenant_count = cursor.fetchone()[0]\n"
    "cursor.execute('SELECT COUNT(*) FROM audit_events WHERE id = 3')\n"
    "audit_3_count = cursor.fetchone()[0]\n"
    "print('[PURGE CHECK] Leads Dupont résiduels :', dupont_lead_count)\n"
    "print('[PURGE CHECK] Tenants Dupont résiduels :', dupont_tenant_count)\n"
    "print('[PURGE CHECK] Audit Event 3 résiduel   :', audit_3_count)\n"
    "# Vérification lecture consolidation cockpit (get_tenants_overview)\n"
    "overview = ops_manager.get_tenants_overview()\n"
    "print('[COCKPIT CHECK] Total tenants retournés par get_tenants_overview() :', len(overview))\n"
    "\""
]

res = subprocess.run(ssh_cmd, capture_output=True, text=True)
print(res.stdout)
if res.stderr:
    print("Stderr:", res.stderr)
