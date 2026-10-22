# Passation KAN-129 — Sandbox produit (isolation, droits, quotas, reproductibilité, artefacts)

Branche : `KAN-129-sandbox-isolation` — date : 2026-10-22. Spécification : `spec_kan129_sandbox_produit.md`.

## Étape 0 — prémisse vérifiée
Vrai pour l'essentiel : défauts du code = 0.5 vCPU / 512 Mo, aucun quota disque, aucune rétention/purge d'artefacts, aucun document de politique réseau.
Déjà en place (non refait) : refus sans digest (KAN-64), admission capacité hôte (KAN-59), espaces par client (KAN-58/60), garde admin facturation.

## Fait
| CA | Livré | Preuve |
|---|---|---|
| CA1 | Cloisonnement de chemin (`resolve_within`) sur espaces et artefacts : slug/version forgés refusés `ERR_PATH_ESCAPE` | `test_kan129_acceptance.py::test_ca1_*` |
| CA3 | Défauts 2 vCPU / 4096m / 40g ; quota disque contrôlé au provisioning (`ERR_DISK_QUOTA_EXCEEDED`, valeur illisible = refus) ; label `com.orso.quotas.disk` ; `no-new-privileges` | `test_ca3_*` |
| CA4 | Rien de nouveau (KAN-64) ; test de non-régression : `repo@sha256:…` et refus sans digest | `test_ca4_*`, `test_ca3_container_gets_all_quota_flags_and_labels` |
| CA5 | `olympe/artifact_retention.py` + `scripts/sandbox_purge_artifacts.py` (30 j, `--dry-run`) ; dernière version protégée ; manifeste illisible jamais purgé | `test_ca5_*` + passe CLI de bout en bout sur répertoire temporaire |
| CA6 | Modèle documenté (spec §2) ; refus simple / accès promu vérifiés sur 3 routes admin | `tests/hermes_cli/test_client_roles_kan129.py` |
| CA7 | Politique réseau **rédigée et datée** (spec §6), marquée « en attente de validation » | document |
| CA8 | Aucun secret ajouté ; scanner d'artefacts rejoué sur les fichiers ajoutés | `test_ca8_*` ; audit repo : `secrets_found_count: 0` |

Fichiers : `olympe/sandbox_policy.py`, `olympe/artifact_retention.py` (nouveaux) ; `olympe/lifecycle_manager.py`, `olympe/artifact_manager.py` (modifiés à la marge) ;
`scripts/sandbox_purge_artifacts.py` ; tests ; spec. Sanctuaire non touché.

## Changement de comportement à connaître
`get_quotas_for_tier(None)` retournait le palier `1_agent` (0.5 vCPU / 512 Mo) ; il retourne désormais le défaut produit (2 / 4 Go / 40 g), conformément à l'arbitrage.
Un provisioning **sans palier** sur un hôte < 4 Go de RAM libre sera donc refusé (`ERR_HOST_CAPACITY_EXCEEDED`) — c'est le comportement voulu, mais l'hôte POC (3,8 Go) n'accepte plus un client sans palier.
`tests/olympe/test_kan59_acceptance.py::test_kan59_ca1_no_container_without_quotas` a été adapté (il figeait 0.5/512m) pour lire `DEFAULT_CLIENT_QUOTAS`. Les paliers tarifaires sont inchangés.

## Reste à faire / NON vérifié
- **Aucune preuve sur espace client réel** (DoD) : pas de démon Docker dans l'environnement de dev. Tout est prouvé par tests avec Docker simulé.
- **CA2 (exécutions simultanées d'un même client)** : non traité ni prouvé. Le moteur sait isoler par `task_id` (`tools/environments/docker.py`, sanctuaire hors périmètre) ; il faut une recette réelle (deux exécutions parallèles, vérification d'absence d'interférence) et décider si la config produit force `container_persistent: false`.
- **Disque** : contrôle à l'admission seulement, pas de plafond noyau ni de surveillance continue (`--storage-opt` non garanti selon le FS hôte). À arbitrer : surveillance périodique ou volume dimensionné.
- **Purge automatique** : script livré, **cron non posé** (ligne proposée en spec §5). Ambiguïté : « artefacts » = artefacts d'espace KAN-60 (versions scellées). Si l'on vise aussi les sorties d'exécution, un second périmètre reste à définir.
- **Promotion par case à cocher** : le backend de ce dépôt ne montre que la création d'utilisateur avec `is_admin` (cockpit, `olympe/server.py`) ; je n'ai pas localisé de route de promotion d'un utilisateur existant. À vérifier côté UI/Supabase.
- **CA7** : politique à valider en commentaire du ticket ; le filtrage effectif est celui de KAN-52 (non audité ici). Liste des hôtes à confirmer par le PO (fournisseurs réellement utilisés par client).
- Test pré-existant rouge, sans lien : `tests/olympe/test_kan58_acceptance.py::test_kan58_dashboard_auth_strictly_required_no_fallback` (binaire `docker` absent) — idem avant mes changements.
- `scripts/security/audit_zero_secrets_and_client_data.py` : `status: FAILED` uniquement car aucune image à scanner (`image_scan_errors_count: 1`) ; `secrets_found_count: 0`.

## À vérifier à la recette (PO)
1. Sur un hôte avec Docker : `docker inspect` d'un client → `--cpus 2`, mémoire 4 Go = swap, labels `com.orso.quotas.*` dont `disk`, `no-new-privileges`, image en `@sha256`.
2. Client dont l'espace dépasse 40g → refus `ERR_DISK_QUOTA_EXCEEDED`.
3. Artefact daté > 30 j : `python scripts/sandbox_purge_artifacts.py --dry-run` puis réel.
4. Deux comptes de rôles différents sur les routes de facturation.
5. Valider (ou amender) la politique réseau § 6 et poser le cron.
