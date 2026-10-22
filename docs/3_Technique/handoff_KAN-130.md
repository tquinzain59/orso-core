# Handoff KAN-130 — Knowledge : ingestion, indexation, versionnement, citation par client

Branche : `KAN-130-knowledge-ingestion`. Rien n'a été poussé, `main` n'est pas touchée.

## Étape 0 — prémisse vérifiée (avant toute modification)

Le ticket affirme qu'aucune ingestion documentaire par client n'existe. Constat sur cette branche
(base `3de0625e2c`) : aucun module, plugin, outil ni ticket Knowledge. `plugins/memory/` ne contient que
des backends de mémoire d'agent. Seuls voisins : `optional-skills/research/pinecone-research/scripts/rag_pipeline.py`
(script facultatif, clé API en variable d'environnement, pas de client ni de versions) et le skill
`llm-wiki`. Aucun ne couvre le périmètre. **Prémisse vraie, travail justifié.**

## Ce qui a été fait (zone d'évolution uniquement)

| Fichier | Rôle |
|---|---|
| `plugins/orso-knowledge/chunking.py` | extraction de texte (texte, Markdown, CSV, JSON, YAML, XML, HTML) et découpage par paragraphes avec recouvrement |
| `plugins/orso-knowledge/store.py` | magasin SQLite/FTS5 par client : ingestion, versions, retrait, recherche, historique |
| `plugins/orso-knowledge/citations.py` | vérification et signalement des réponses sans source |
| `plugins/orso-knowledge/connectors.py` | contrat de connecteur, `DirectoryConnector`, `import_from` (origine tracée) |
| `plugins/orso-knowledge/__init__.py`, `plugin.yaml` | outil `knowledge_search`, 3 hooks, CLI `hermes knowledge` |
| `plugins/orso-knowledge/README.md` | usage, cloisonnement, connecteurs, limites |
| `tests/plugins/test_orso_knowledge.py` | 9 tests de contrat (CA1 à CA5) |

Sanctuaire non touché (aucun fichier de `agent/turn_*`, `run_agent.py`, `conversation_loop.py`,
`hermes_state*`, `providers/`, `tools/registry.py`). Le plugin est opt-in : `plugins.enabled: [orso-knowledge]`.

## Critères d'acceptation

| CA | Preuve | Statut |
|---|---|---|
| CA1 | `test_ca1_*` ; E2E : `ingest` puis `search` rend `[Source: conditions.md, v1, §1]` | prouvé |
| CA2 | `test_ca2_*` : autre client ne voit rien ; un conteneur lié à un client refuse un autre identifiant (CLI : code 1). Un fichier SQLite par client | prouvé en code ; **isolation réelle du sandbox non vérifiée** |
| CA3 | `test_ca3_*` : v1 puis v2 (v2 seule répond), version remplacée tracée, retrait, ré-ingestion en v3. Contrôle rouge : sans retrait de l'index, le test échoue | prouvé |
| CA4 | `test_ca4_*` : réponse citée acceptée ; sans source ou source inventée **signalée** (avertissement ajouté, pas de refus) | prouvé sur le périmètre ci-dessous |
| CA5 | `test_ca5_*` + E2E : import `google-drive`, `origin_connector`/`origin_ref` tracés, ré-import `unchanged`, PDF refusé et consigné | **partiel** : dossier d'export seulement |
| CA6 | aucun secret ; les identifiants sources sont désignés par leur nom (`GOOGLE_WORKSPACE_CREDENTIALS`, `PENNYLANE_API_KEY`) | tenu |

## Vérifications

- `scripts/run_tests.sh tests/plugins/test_orso_knowledge.py` : `1 files, 9 tests passed, 0 failed`, code 0.
- `ruff check plugins/orso-knowledge tests/plugins/test_orso_knowledge.py` : `All checks passed!`, code 0 (ruff 0.16.9 et 0.15.10).
- E2E par la vraie découverte de plugins (HERMES_HOME temporaire, `ORSO_CLIENT_ID=acme`) : outil `knowledge_search` enregistré, commande `knowledge` enregistrée, `ingest`/`search`/`import`/`history` exécutés, `registry.dispatch("knowledge_search", ...)` rend la citation.

## Ce qui reste / limites connues

1. **Fournisseur de vectorisation : non choisi** (arbitrage laissé à l'architecte : hébergement UE, accord de traitement, réversibilité). L'index est lexical (FTS5, local, sans tiers) : pas de recherche sémantique. Un index vectoriel s'ajoutera derrière `KnowledgeStore.search` une fois le fournisseur arbitré.
2. **Connecteurs Drive et comptabilité en accès direct : non livrés.** Seul le dossier d'export est lu. Un adaptateur API demande les identifiants réels et une recette sur le compte du client.
3. **Dépôt par le client dans l'interface** : il n'existe que la CLI. Un point d'entrée d'envoi dans `hermes_cli/web_routers/` reste à faire (même magasin).
4. **Citation (CA4) : contrôle limité aux tours qui appellent `knowledge_search`.** Une réponse qui s'appuierait sur un document sans appeler l'outil n'est pas détectée. Le signalement est un avertissement ajouté, pas un refus : choix à confirmer par le PO.
5. **Formats** : PDF et Office refusés explicitement (pas d'extracteur livré, dépendances à arbitrer).
6. La CLI complète `hermes` n'a pas pu démarrer dans cet environnement (`rich`, `httpx`, `requests` absents du `.venv`) : l'E2E a appelé les fonctions d'enregistrement de la CLI via le gestionnaire de plugins, pas le binaire `hermes`.
7. `ruff format` n'est pas appliqué (hors porte CI, qui ne bloque que `ruff check`).

## À vérifier à la recette (PO)

- Sur un conteneur client réel (`ORSO_CLIENT_ID` posé, volume dédié) : déposer un document, interroger depuis l'agent, constater la citation dans la réponse.
- Avec deux conteneurs clients : le document de l'un est introuvable depuis l'autre.
- Mettre à jour puis retirer un document : la réponse suit la dernière version, puis ne répond plus.
- Trancher : avertissement ou refus pour une réponse sans source ; fournisseur de vectorisation ; priorité des connecteurs API Drive/compta.
