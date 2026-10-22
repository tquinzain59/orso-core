# Handoff KAN-130 — Knowledge : ingestion, indexation, versionnement, citation par client

> **Reprise du 22/10/2026** (CA4 et CA5, après recette de la PR 56) : voir la section « Reprise » en bas.
> Les sections ci-dessous décrivent la première passe ; là où elles disent « avertissement » (CA4) ou
> « dossier d'export seulement » (CA5), la section « Reprise » fait foi.

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

---

## Reprise (CA4 et CA5) — 22/10/2026

### Étape 0 — prémisse revérifiée
Sur la branche (HEAD `90bd750454`) : `citations.flag_answer` renvoyait *la réponse suivie d'un
avertissement* (`NOTICE`) et `__init__._on_transform_llm_output` la livrait telle quelle ; le seul
connecteur était `DirectoryConnector` (lecture d'un dossier local). **Prémisse vraie** : CA4 et CA5 non tenus.

### Ce qui a changé (zone d'évolution uniquement, sanctuaire non touché)

| Fichier | Changement |
|---|---|
| `plugins/orso-knowledge/citations.py` | `flag_answer` → `block_answer` : renvoie un **refus de remplacement** (le contenu non sourcé n'est pas transmis) ; citation inventée refusée même sans recherche ce tour |
| `plugins/orso-knowledge/__init__.py` | le handler `knowledge_search` enregistre lui-même les citations (hook `post_tool_call` supprimé : observateur, contournable) ; `transform_llm_output` substitue le refus ; CLI `import` : `--folder-id`, `--resource`, `--from-dir` devient optionnel |
| `plugins/orso-knowledge/connectors_api.py` (nouveau) | `GoogleDriveConnector` (API Drive v3) et `PennylaneConnector` (API v2), transport HTTP stdlib |
| `plugins/orso-knowledge/connectors.py` | `ConnectorError`, `RemoteFailure` (échec par document consigné) |
| `plugins/orso-knowledge/chunking.py` | `is_supported(name)` (ne pas télécharger un PDF pour le refuser) |
| `plugins/orso-knowledge/plugin.yaml`, `README.md` | hooks, usage, limites |
| `tests/plugins/test_orso_knowledge.py` | 14 tests (9 d'origine, CA4 réécrits, 5 CA5/CLI ajoutés) |

Aucun secret ajouté ; aucune dépendance ajoutée (stdlib), donc ni `pyproject.toml` ni `uv.lock`.

### Preuves

- **CA4** : `test_ca4_*` (3 tests) : réponse citée acceptée (hook rend rien), réponse sans source
  remplacée par `⛔ Réponse refusée…` sans le texte original, source inventée refusée. E2E par le
  vrai gestionnaire de plugins (`discover_plugins`, `registry.dispatch`, `invoke_hook`) :
  sans source → `["⛔ Réponse refusée : … Format de citation attendu : [Source: cond.md, v1, §1]"]` ;
  avec source → `[]`. Contrôle rouge : avec l'ancien comportement (réponse + avertissement), les 3 tests échouent.
- **CA5** : `test_ca5_google_drive_*`, `test_ca5_pennylane_*`, `test_ca5_connector_errors_*`,
  `test_cli_import_from_api_connector_*`. Le transport tourne pour de vrai (sockets) contre un faux
  service sur la boucle locale : échange de jeton OAuth, pagination Drive/Pennylane, export des Docs,
  document indexé, `origin_connector`/`origin_ref` tracés (`google-drive`/id Drive, `pennylane`/`customer_invoices/8`),
  ré-import `unchanged`, PDF consigné sans téléchargement, erreurs sans fuite du jeton, HTTP clair refusé.
- `scripts/run_tests.sh tests/plugins/test_orso_knowledge.py` : `1 files, 14 tests passed, 0 failed`, code 0.
- `ruff check plugins/orso-knowledge tests/plugins/test_orso_knowledge.py` : `All checks passed!`, code 0 (ruff 0.15.10).

### Ce que je n'ai PAS pu vérifier
1. **Aucun appel à un vrai Drive ni à un vrai compte Pennylane** : pas d'identifiants, pas de réseau de recette. Les contrats d'API (chemins, paramètres `q`/`fields`/`pageToken`, export `text/plain|text/csv`, `items`/`has_more`/`next_cursor` de Pennylane, jeton Bearer) sont écrits d'après la documentation publique connue, **sans la relire** (la recherche web a échoué dans cet environnement). **CA5 reste à recetter sur un compte réel avant d'être déclaré tenu.**
2. Le choix du « service comptabilité » : Pennylane est retenu car c'est le seul désigné dans les specs du dépôt (`PENNYLANE_API_KEY`, KAN-31). Sellsy/Odoo ne sont pas couverts.
3. Citation (CA4) : tour qui s'appuie sur un document sans appeler l'outil et sans citer : non détecté ; hook borné en temps par le moteur → sur délai ou exception la réponse passe (fail-open, imposé par le moteur, le sanctuaire n'a pas été touché) ; après redémarrage une citation d'un tour antérieur est refusée.
4. Le binaire `hermes` complet ne démarre pas dans cet environnement (`httpx`, `rich`… absents du `.venv`) : l'E2E passe par le gestionnaire de plugins et les fonctions CLI du plugin, pas par `hermes knowledge`.
5. Le refus remplace la réponse livrée ; je n'ai pas vérifié ce que voit l'historique de session côté interface (le finalizer écrit la réponse transformée dans la transcription).
6. Toujours ouverts depuis la première passe : fournisseur de vectorisation (index FTS5 lexical), dépôt par l'interface web, PDF/Office.

### À vérifier à la recette (PO)
- Avec un vrai dossier Drive : `GOOGLE_WORKSPACE_CREDENTIALS` posé dans le conteneur, `hermes knowledge import --connector google-drive --folder-id <id>`, puis `hermes knowledge list` / `history` : `origin_connector=google-drive`, `origin_ref` = id du fichier.
- Avec une vraie clé : `PENNYLANE_API_KEY` posé, `hermes knowledge import --connector pennylane` : factures indexées, citables.
- Dans l'agent : une question documentaire sans citation produit le refus, avec citation la réponse passe. Valider que le texte du refus convient (et s'il faut une relance automatique : hors périmètre plugin).
- Conséquence UX à arbitrer : le refus remplace la réponse ; l'utilisateur doit redemander.
