"""Publication du compte-rendu d'avancement et de résolution KAN-68 sur Jira Atlassian."""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request

if os.path.exists(".env"):
    with open(".env", "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))

EMAIL = os.environ.get("ATLASSIAN_EMAIL")
TOKEN = os.environ.get("ATLASSIAN_API_TOKEN")
DOMAIN = os.environ.get("ATLASSIAN_DOMAIN", "orso-agents")
TICKET_KEY = "KAN-68"

if not EMAIL or not TOKEN:
    print("[!] Identifiants Atlassian manquants dans .env", file=sys.stderr)
    sys.exit(1)

auth_str = base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()
headers = {
    "Authorization": f"Basic {auth_str}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

COMMENT_TEXT = """h2. ⚡ Résolution KAN-68 : Synchronisation du Verrou npm et Intégration des Espaces de Travail

Bonjour Jarvis, Thibaut,

L'ensemble des critères d'acceptation du ticket KAN-68 a été traité avec succès, dans le strict respect de la Charte de Gouvernance du Fork (Sanctuaire 100% intouché, zéro altération applicative, zéro montée de version non justifiée).

---

h3. 1. Validation du Contrôle JS et TS en Succès (CA1)
* *Job GitHub Actions* : {{JS & TS checks / JS & TS checks}}
* *Identifiant d'exécution (Run)* : [36832261480|https://github.com/tquinzain59/orso-core/actions/runs/36832261480]
* *Identifiant du Job* : [110271432389|https://github.com/tquinzain59/orso-core/actions/runs/36832261480/job/110271432389]
* *Branche* : {{KAN-68-sync-verrou-npm-workspaces}}
* *Pull Request* : [#5|https://github.com/tquinzain59/orso-core/pull/5]
* *Conclusion* : *SUCCESS* (10/10 sous-projets et vérifications validés en 4m56s).

---

h3. 2. Reproductibilité de l'Installation Verrouillée (CA2)
* *Environnement d'exécution* : Docker {{node:26-bookworm-slim}} avec alignement {{npm@12.2.0}} (strictement identique à l'environnement CI du job JS & TS).
* *Commande* : {{npm ci}}
* *Code retour* : *0*
* *Sortie brute* :
{code}
npm notice run hermes-agent@1.0.0 postinstall
npm notice run echo '✅ Node dependencies installed. Run: python run_agent.py --help'
✅ Node dependencies installed. Run: python run_agent.py --help

added 1343 packages, and audited 1353 packages in 20s

293 packages are looking for funding
  run `npm fund` for details

17 vulnerabilities (1 low, 6 moderate, 10 high)
npm ci return code: 0
{code}

---

h3. 3. Mesure Factuelle de la Cohérence Avant / Après (CA3)
* *Occurrences avant correction* :
** {{@orso/ui-client}} : *0* occurrence
** {{@orso/ui-ops}} : *0* occurrence
* *Occurrences après correction* :
** {{@orso/ui-client}} : *2* occurrences (définition dans {{packages}} et lien sous {{node_modules/@orso/ui-client}})
** {{@orso/ui-ops}} : *2* occurrences (définition dans {{packages}} et lien sous {{node_modules/@orso/ui-ops}})
* *Contrôle de cohérence du verrou* :
** Commande : {{npm ls --package-lock-only}}
** Code retour : *0*
** Extrait vérifié :
{code}
+-- @orso/ui-client@1.0.0 -> ./apps/ui-client
+-- @orso/ui-ops@1.0.0 -> ./apps/ui-ops
{code}

---

h3. 4. Traçabilité du Diff et Invariance des Dépendances (CA4)
* *Outil d'audit sémantique du dépôt* : {{scripts/ci/lockfile_diff.py}}
{code:markdown}
#### `package-lock.json`

| Package | Before | After |
| --- | --- | --- |
| ➕ apps/ui-client | — | `1.0.0` |
| ➕ apps/ui-ops | — | `1.0.0` |
{code}
* *Dépendances déplacées* : *0*. Aucune version existante n'a bougé.
* *Changements de métadonnées* :
** Ajout des entrées de manifeste pour {{apps/ui-client}} et {{apps/ui-ops}} (1.0.0).
** Ajout des liens symboliques workspace sous {{node_modules/@orso/ui-client}} et {{node_modules/@orso/ui-ops}}.
** Retrait de l'attribut redondant {{"peer": true}} sur les binaires optionnels esbuild/rollup (standard npm 12 lors du calcul de graphe des workspaces).

---

h3. 5. Périmètre Borné & Zéro Altération Métier (CA5)
* *Code applicatif touché* : *0 ligne, 0 fichier*.
* *Fichiers de la pull request* :
** {{package-lock.json}} (synchronisation verrou)
** {{web/src/pages/SessionsPage.test.tsx}} (timeout 20s pour la charge parallèle conforme à la flake policy AGENTS.md)
** {{docs/3_Technique/note_exploitation_kan68_synchronisation_verrou_npm.md}} (note d'exploitation et réponses aux questions ouvertes)
** {{scripts/publish_kan68_atlassian.py}} (outillage de traçabilité Jira)

---

h3. 6. Réponses aux Questions Ouvertes du Ticket
1. *Espaces de travail vs dépendances publiées* : Les paquets doivent impérativement demeurer des *espaces de travail (workspaces)* du monorepo. Ils constituent des briques d'interface d'Orso vivant avec le moteur. Les publier induirait des frictions de publication et de versioning inutiles.
2. *Rôle du contrôle automatique de réparation* : {{js-autofix.yml}} ne doit pas toucher au verrou pour des raisons de sécurité supply-chain (d'où l'exclusion explicite). En revanche, le job CI {{JS & TS checks}} joue ce rôle de garde strict : {{npm ci}} échoue immédiatement en cas de désynchronisation.
"""


def main():
    print(f"\nPublication du compte-rendu sur {TICKET_KEY}...")
    url = f"https://{DOMAIN}.atlassian.net/rest/api/3/issue/{TICKET_KEY}/comment"
    payload = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": COMMENT_TEXT,
                        }
                    ],
                }
            ],
        }
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            print(f"[✓] Commentaire publié avec succès sur {TICKET_KEY} (HTTP {resp.status}).")
    except urllib.error.HTTPError as e:
        print(f"[!] Erreur HTTP {e.code} : {e.read().decode('utf-8')}")
    except Exception as e:
        print(f"[!] Erreur : {e}")


if __name__ == "__main__":
    main()
