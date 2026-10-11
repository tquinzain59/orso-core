#!/usr/bin/env python3
"""KAN-88 CA4 — écritures PostgREST du dépôt vers des tables non servies par la production.

Recense les chemins ``rest/v1/<table>`` / ``_query_supabase("<table>...")`` suivis d'un verbe
d'écriture (POST/PATCH/PUT/DELETE) et les compare à la liste des tables servies par l'API de
production (relevé PO du 2026-10-03, ticket KAN-88). Heuristique par fenêtre de texte : elle
sert à ne rien oublier, pas à prouver l'absence de faux positifs ; chaque ligne rendue se relit.

Usage : python scripts/iam/audit_supabase_write_targets.py   (code retour 1 si écart)
"""

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SERVED_BY_PRODUCTION = {
    "audit_logs", "agent_instances", "organization_members", "organizations",
    "profiles", "subscriptions", "support_alerts", "tenant_instances", "tenants",
}
TARGET = re.compile(
    r"""(?:_query_supabase\(\s*f?["']|rest/v1/|supabase_request_strict\(\s*self\.supabase_url,\s*self\.supabase_key,\s*f?["'])([a-z_]+)"""
)
WRITE_VERB = re.compile(r"""method\s*=\s*["'](POST|PATCH|PUT|DELETE)["']""")
WINDOW = 700
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "tests", "website"}


def scan() -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    for path in REPO.rglob("*.py"):
        if SKIP_DIRS & set(path.relative_to(REPO).parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in TARGET.finditer(text):
            if WRITE_VERB.search(text[m.end(): m.end() + WINDOW]):
                line = text.count("\n", 0, m.start()) + 1
                hits.setdefault(m.group(1), []).append(f"{path.relative_to(REPO)}:{line}")
    return hits


def main() -> int:
    hits = scan()
    missing = {t: w for t, w in hits.items() if t not in SERVED_BY_PRODUCTION}
    print("Tables servies par la production :", ", ".join(sorted(SERVED_BY_PRODUCTION)))
    print("\nTables visées en écriture dans le dépôt :")
    for table in sorted(hits):
        status = "SERVIE" if table in SERVED_BY_PRODUCTION else "ABSENTE"
        print(f"  [{status}] {table}")
        for where in hits[table]:
            print(f"      {where}")
    print(f"\n{len(missing)} table(s) visée(s) en écriture mais absente(s) de la production : {sorted(missing)}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
