# Handoff KAN-73 — Télémétrie : replis retirés, spec KAN-43 alignée

**Date** : 15/10/2026 — **Branche** : `KAN-73-auto` — **Base** : `c13b03698c` (`main`)
**Statut** : code, tests et spec livrés localement ; **non poussé, non fusionné, non déployé.**

## Étape 0 — Prémisse (partiellement vraie)

Les lignes citées par le ticket ne correspondent plus au code : `"simulated": True`, `display_name: "PROD-FR-002"` et `"Up 6 hours (healthy)"` ont déjà été retirés par `679f529c44` (KAN-43, présent dans `main`). Le constat de fond reste vrai : d'autres valeurs fabriquées subsistaient (agents « actifs » synthétisés depuis Docker, compteurs et signes vitaux à 0, `Agent #<id>`, alertes `[]` collecte coupée, statut `"active"` par défaut). Sortie brute :

```console
$ grep -n -i -E "simulat|PROD-FR-002|Up 6 hours|fallback|default" olympe/telemetry_client.py   # avant modification
149: # Télémétrie indisponible / hors ligne : métriques réelles à zéro
163: "simulated": False,
193-208: raw_agents.append({... "status": "active" if running ..., "server_ip": "127.0.0.1"})   # agents synthétisés
331: "agent_name": f"Agent #{agent_id}",
349: # Fallback simulation propre : aucune alerte anormale par défaut      -> return []
```

La correction a donc été menée (la requalification n'était pas applicable).

## Fichiers changés

| Fichier | Changement |
|---|---|
| `olympe/telemetry_client.py` | Plus aucune valeur fabriquée. Collecte coupée : `{connected: false, status: "unknown", error: "telemetry_unavailable", message, last_valid_at}`. Mesure absente = `None`. Agents Docker non synthétisés. `get_environments` et `get_alerts` retournent une enveloppe (dict). |
| `olympe/server.py` | Les routes `environments` et `alerts` renvoient l'enveloppe du client telle quelle. |
| `apps/ui-ops/src/{api,types}.ts`, `components/EnvironmentsView.tsx` | Bannière « État inconnu » + dernière mesure valide, KPI masqués, `n/a` pour toute mesure absente, badge « Inconnu ». |
| `tests/olympe/test_kan73_telemetry_no_fabrication.py` (nouveau) | 15 tests : marqueurs interdits dans la source + contrat « collecte coupée = inconnu ». |
| `tests/olympe/test_ops_manager.py` | Le test hors ligne n'exige plus des zéros mais l'état inconnu. |
| `docs/3_Technique/spec_kan43_source_de_verite_cockpit_ops.md` | Phrase de la Règle 1 corrigée + §5 (retiré / restant, date, SHA). |

Sanctuaire non touché (aucun fichier `agent/`, `run_agent.py`, `hermes_state*`, `providers/`, `tools/registry.py`).

## Rejeu

```bash
source .venv/bin/activate
ruff check olympe/telemetry_client.py olympe/server.py tests/olympe/test_kan73_telemetry_no_fabrication.py tests/olympe/test_ops_manager.py
scripts/run_tests.sh tests/olympe/
grep -n -i -E "simulat|PROD-FR-002|Up [0-9]+ hours|healthy|Agent #|127\.0\.0\.1" olympe/telemetry_client.py   # attendu : aucune ligne, code 1
```

## Critères

| CA | Sonde | Résultat |
|---|---|---|
| CA1 | commande `grep` ci-dessus | aucune ligne, code retour 1 |
| CA2 | client réel, deux URL injoignables (voir sortie ci-dessous) | `connected: false`, `status: "unknown"`, `environments`/`alerts`/`snapshots`: `null` |
| CA3 | phrase Règle 1 + §5 de la spec ; même `grep` | la spec n'affirme plus « zéro fallback » pour la télémétrie |
| CA4 | repli volontaire (alertes `[]` + `"simulated": True` réinjectés temporairement) | `5 failed, 10 passed` ; fichier restauré : `15 passed` |

Extrait CA2 : `summary {"connected": false, "status": "unknown", "error": "telemetry_unavailable", "message": "Collecte de télémétrie indisponible : état inconnu.", "last_valid_at": null}`

## Résultats de contrôle

* `ruff check` (4 fichiers Python) : `All checks passed!`, code 0.
* `scripts/run_tests.sh tests/olympe/` : tout passe sauf `test_kan58_acceptance.py::test_kan58_dashboard_auth_strictly_required_no_fallback`, **déjà rouge sur la base sans mes changements** (`FileNotFoundError: 'docker'` : binaire absent de cet environnement). Sans lien avec KAN-73.

## Limites / non vérifié

* **Build UI non exécuté** : `apps/ui-ops` n'a pas de `node_modules`. `tsc` lancé sans dépendances : aucune nouvelle erreur de type (seule la quantité d'éléments JSX non typés augmente, du fait de la bannière). Le rendu de la bannière est **à voir à la recette** (`npm run build --workspace=@orso/ui-ops`).
* **Pas de vérification en ligne** : la route publique de production n'a pas été interrogée, rien n'est déployé. Le SHA déployé et la date restent à écrire dans le ticket.
* Pas testé contre une vraie collecte ni un vrai socket Docker.
* Changement de contrat : `/telemetry/environments` et `/telemetry/alerts` renvoient désormais `connected`, `last_valid_at`, et `null` (au lieu de `[]`) collecte coupée ; `/telemetry/history` renvoie `snapshots: null`. Tout autre consommateur que le cockpit est à vérifier (aucun autre trouvé dans le dépôt).
* Retrait du rattachement par nom `prod-fr-002` : un agent de ce nom dont le module ne contient pas « recouvrement » n'est plus rattaché à Financia Solutions.
* `last_valid_at` est en mémoire du processus : `null` après redémarrage.
* Hors périmètre, inchangés : purge de la base (KAN-71), route sandbox, flotte vide en `200` sur lecture de base en échec, filtre de l'agent « Recouvrement ».

## À vérifier à la recette (PO)

1. Couper la collecte (arrêter `olympe_supervision_agent`) : l'écran Environnements affiche « État inconnu — … Dernière mesure valide : … », aucun KPI, aucun conteneur « Actif ».
2. Collecte rétablie : agents, jetons et coûts réapparaissent ; une mesure Docker absente s'affiche `n/a`.
3. Route publique, sans authentification puis avec : plus aucune valeur fabriquée.
4. Décision de Thibaut : « inconnu + horodatage » (implémenté) ou « dernier état connu ».

## Retour arrière

`git revert <SHA du commit KAN-73>` ; aucun changement de schéma, de donnée ni de configuration.
