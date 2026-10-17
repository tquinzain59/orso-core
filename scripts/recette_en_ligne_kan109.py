#!/usr/bin/env python3
"""Mesures en direct KAN-109 : tenant de banc et compte client de test sur le service OPS.

Rejoue, en lecture seule (un GET, un POST de connexion), les mesures de CA1 et CA2.
Aucun secret n'est affiché : seuls les codes HTTP, le champ ``detail`` des refus et
l'emplacement du fichier d'identifiants sont écrits.

Usage : python3 scripts/recette_en_ligne_kan109.py [chemin_fichier_env]
Le fichier par défaut est ``~/.hermes/secrets/orso_drone.env`` (voir spec KAN-35).
Code retour : 0 si CA1 et CA2 sont verts, 1 sinon, 2 si le fichier est inutilisable.
"""

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_ENV = Path("~/.hermes/secrets/orso_drone.env").expanduser()
REQUIRED = (
    "ORSO_OPS_BASE_URL",
    "ORSO_DRONE_API_TOKEN",
    "ORSO_TEST_TENANT_SLUG",
    "ORSO_TEST_CLIENT_EMAIL",
    "ORSO_TEST_CLIENT_PASSWORD",
)


def load_env(path: Path) -> dict:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.removeprefix("export ").strip()
        values[key] = value.strip().strip("'\"")
    return values


def call(
    method: str, url: str, headers: dict, body: dict | None = None
) -> tuple[int, str]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def detail_of(raw: str) -> str:
    try:
        return str(json.loads(raw).get("detail", ""))
    except (ValueError, AttributeError):
        return ""


def main() -> int:
    path = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else DEFAULT_ENV
    try:
        env = load_env(path)
    except OSError as exc:
        print(
            f"[ERREUR] fichier d'identifiants illisible : {path} ({exc.__class__.__name__})"
        )
        return 2
    missing = [k for k in REQUIRED if not env.get(k)]
    if missing:
        print(f"[ERREUR] variables absentes de {path} : {', '.join(missing)}")
        return 2

    base = env["ORSO_OPS_BASE_URL"].rstrip("/")
    slug = env["ORSO_TEST_TENANT_SLUG"]
    print(
        f"Mesure du {datetime.now(timezone.utc).isoformat(timespec='seconds')} sur {base}"
    )
    print(f"Identifiants lus dans : {path} (valeurs non affichées)")

    url = f"{base}/api/olympe/ops/tenants/{slug}"
    code, raw = call(
        "GET", url, {"Authorization": f"Bearer {env['ORSO_DRONE_API_TOKEN']}"}
    )
    ca1 = code == 200
    print(
        f"\nCA1  GET /api/olympe/ops/tenants/{slug} (jeton drone) -> HTTP {code} {detail_of(raw)}"
    )
    print(f"     {'[OK]' if ca1 else '[KO]'} attendu 200 avec le détail du tenant")

    code, raw = call(
        "POST",
        f"{base}/api/olympe/ops/auth/login",
        {"Content-Type": "application/json"},
        {
            "email": env["ORSO_TEST_CLIENT_EMAIL"],
            "password": env["ORSO_TEST_CLIENT_PASSWORD"],
        },
    )
    # 401 = identifiants invalides (le refus ne prouve rien) ; 403 = identifiants valides,
    # rôle refusé (preuve de séparation) ; 200 = le client obtient le cockpit (défaut grave).
    ca2 = code == 403
    meaning = {
        401: "identifiants invalides : refus non probant",
        403: "identifiants valides, accès cockpit refusé : séparation prouvée",
        200: "ANOMALIE : un compte client obtient une session cockpit",
    }.get(code, "réponse inattendue")
    print(
        f"\nCA2  POST /api/olympe/ops/auth/login (compte client de test) -> HTTP {code} {detail_of(raw)}"
    )
    print(f"     {'[OK]' if ca2 else '[KO]'} attendu 403 ; {meaning}")

    print(f"\nVerdict : CA1 {'OK' if ca1 else 'KO'} / CA2 {'OK' if ca2 else 'KO'}")
    return 0 if ca1 and ca2 else 1


if __name__ == "__main__":
    sys.exit(main())
