# orso-knowledge

Ingestion documentaire **par client** (KAN-130) : ingestion, découpage, index, versions, retrait,
citation obligatoire des sources. Le moteur n'est pas modifié : tout passe par l'API de plugin.

Activation (les plugins sont opt-in) : `plugins.enabled: [orso-knowledge]` dans `config.yaml`.

## Cloisonnement

Un fichier SQLite par client : `<HERMES_HOME>/knowledge/<client>/knowledge.db`. Le client est
`ORSO_CLIENT_ID` (posé par le cycle de vie Olympe, un conteneur et un volume par client) ; le modèle
ne choisit jamais le client. Le garde-fou de code refuse d'ouvrir un autre client que celui lié au
conteneur ; l'isolation réelle est celle du sandbox/volume. Hors conteneur, `--tenant` est requis
(aucun client par défaut).

## Utilisation

| Besoin | Commande |
|---|---|
| Fichier déposé | `hermes knowledge ingest <fichier>` |
| Import d'un service connecté | `hermes knowledge import --connector google-drive --from-dir <export>` |
| Requête | `hermes knowledge search "<mots>"` ou l'outil `knowledge_search` (agent) |
| Versions | `hermes knowledge history <doc_key>` / `list` |
| Retrait | `hermes knowledge retire <doc_key>` |

Formats : texte, Markdown, CSV, JSON, YAML, XML, HTML (UTF-8). Les autres (PDF, Office) sont
refusés explicitement et consignés dans le rapport d'import.

## Versions et fraîcheur

Même `doc_key` et même contenu : aucune nouvelle version. Contenu modifié : nouvelle version,
l'ancienne sort de l'index et passe `superseded` (trace conservée dans `versions`). Retrait : plus
aucune réponse, version `retired`. Une ré-ingestion après retrait repart à la version suivante.

## Connecteurs (CA5)

Contrat : `connectors.Connector.fetch()` renvoie des `RemoteDocument(ref, name, data)` (ou des
`RemoteFailure` consignées dans le rapport sans interrompre les autres). Le nom du connecteur est
inscrit sur chaque version (`origin_connector`, `origin_ref`) ; la clé du document est
`<connecteur>:<ref>`, donc un ré-import met à jour la même entrée.

| Connecteur | Commande | Identifiants (environnement du conteneur, par leur nom) |
|---|---|---|
| `google-drive` (API Drive v3, dossier récursif, Docs/Slides en texte, Sheets en CSV) | `hermes knowledge import --connector google-drive --folder-id <id>` | `GOOGLE_WORKSPACE_CREDENTIALS` (JSON : `client_id`, `client_secret`, `refresh_token`, ou `access_token`) |
| `pennylane` (API v2 : `customer_invoices`, `supplier_invoices`, une pièce JSON par facture) | `hermes knowledge import --connector pennylane [--resource customer_invoices]` | `PENNYLANE_API_KEY` |
| dossier d'export local (sans accès API) | `hermes knowledge import --connector <nom> --from-dir <dossier>` | aucun |

Les identifiants ne passent jamais en argument, ne sont jamais journalisés (les erreurs ne portent
ni en-tête ni corps de réponse) ni écrits dans l'index, un commit ou une page. Le jeton n'est envoyé
qu'en HTTPS et n'est jamais suivi vers un autre hôte lors d'une redirection. Les liens signés
(`*_url`) sont retirés des factures : ils changent à chaque appel et fabriqueraient de fausses versions.
Limites : un fichier Drive de plus de 25 Mo ou d'un format sans extracteur (PDF, Office) est consigné
en échec ; pas de reprise automatique sur HTTP 429 ; le retrait d'un document côté source n'est pas
répercuté automatiquement (`hermes knowledge retire`).

## Citation (CA4)

Chaque passage porte `[Source: <document>, v<N>, §<k>]`. La citation est **bloquante** : le hook
`transform_llm_output` remplace par un refus (qui ne reprend pas le contenu non sourcé) toute
réponse qui, après un `knowledge_search` retrouvant des passages, n'en cite aucun, ou qui cite une
`[Source: ...]` absente des passages retrouvés dans la session (y compris sans recherche ce tour).
Les citations sont enregistrées par le handler de l'outil (pas par un hook observateur).
Limites : un tour qui s'appuie sur un document sans appeler l'outil et sans citation n'est pas
détecté ; le hook est borné en temps par le moteur (`_HOOK_TIMEOUT_BOUNDED_HOOKS`) : sur délai
dépassé ou exception, la réponse passe (le moteur n'offre pas de hook de sortie fail-closed) ; après
redémarrage, une citation d'un tour antérieur n'est plus connue et est refusée.

## Index

Lexical (SQLite FTS5, local, aucun tiers). Le fournisseur de vectorisation reste à choisir par
l'architecte (hébergement UE, accord de traitement, réversibilité) : voir `handoff_KAN-130.md`.
