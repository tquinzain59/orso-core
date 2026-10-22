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

Contrat : `connectors.Connector.fetch()` renvoie des `RemoteDocument(ref, name, data)`. Le nom du
connecteur est inscrit sur chaque version (`origin_connector`, `origin_ref`) ; la clé du document est
`<connecteur>:<ref>`, donc un ré-import met à jour la même entrée. Livré : `DirectoryConnector`, qui
lit le dossier d'export d'un service (Drive synchronisé, export comptable). Les accès réseau directs
à Drive ou à la comptabilité ne sont **pas** livrés : leurs identifiants restent désignés par leur
emplacement (`GOOGLE_WORKSPACE_CREDENTIALS`, `PENNYLANE_API_KEY` dans l'environnement du conteneur),
jamais dans l'index, un commit ou une page.

## Citation (CA4)

Chaque passage porte `[Source: <document>, v<N>, §<k>]`. Quand un tour a appelé `knowledge_search`,
le hook `transform_llm_output` signale par un avertissement ajouté une réponse qui ne recopie aucune
de ces citations ou qui en invente une. Limite : un tour qui n'appelle pas l'outil n'est pas contrôlé.

## Index

Lexical (SQLite FTS5, local, aucun tiers). Le fournisseur de vectorisation reste à choisir par
l'architecte (hébergement UE, accord de traitement, réversibilité) : voir `handoff_KAN-130.md`.
