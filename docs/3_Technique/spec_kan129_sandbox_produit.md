# KAN-129 — Sandbox produit : isolation, droits, quotas, reproductibilité, conservation, réseau

Date de rédaction : 2026-10-22. Arbitrages sources : Thibaut, 2026-10-21 (rôles existants conservés,
allowlist stricte, 30 jours, 2 vCPU / 4 Go / 40 Go). Périmètre code : `olympe/` (plan de gestion) et scripts — aucune
modification du sanctuaire.

## 1. Isolation (CA1, CA2)

- **Entre clients** : un conteneur, un espace (`spaces/<slug>`), un répertoire de données (`tenants/<slug>`) et un répertoire
  d'artefacts par client (KAN-58/60). KAN-129 ajoute le **cloisonnement de chemin** : `olympe.sandbox_policy.resolve_within`
  refuse tout slug/version qui sort de la racine (`ERR_PATH_ESCAPE`), appliqué à `get_tenant_space_dir` et
  `ClientSpaceArtifactManager.get_tenant_artifact_dir`. Le conteneur client est lancé avec `--security-opt no-new-privileges`.
- **Entre exécutions d'un même client (CA2)** : la couche d'exécution d'outils du moteur (`tools/environments/docker.py`,
  `task_id`, `container_persistent: false`) sait isoler chaque exécution dans son propre conteneur. **Ce lot ne l'a pas
  recetté** (pas de démon Docker sur l'environnement de développement) : voir la note de passation.

## 2. Droits par rôle (CA6)

Modèle conservé : **utilisateur simple** (`user`) et **administrateur** (`admin`) ; le rôle `superadmin` est réservé au cockpit Ops
(`olympe/auth.py`). La promotion consiste à positionner `is_admin` dans le profil (case à cocher « administrateur » de l'espace admin).
Résolution unique : `_resolve_user_system_role_and_job_title` (`hermes_cli/web_routers/client_ui.py`).

| Action | Utilisateur simple | Administrateur |
|---|---|---|
| Consulter facturation / abonnement (`GET /api/client/billing`) | 403 | autorisé |
| Changer d'abonnement (`POST /api/client/billing/subscription`) | 403 | autorisé |
| Portail de paiement (`POST /api/client/billing/portal-session`) | 403 | autorisé |
| Chat, agents, profil personnel | autorisé | autorisé |

Contrôle vérifié par `tests/hermes_cli/test_client_roles_kan129.py` (même utilisateur : refusé simple, accepté promu).

## 3. Quotas par client (CA3)

Défauts produit (`olympe.sandbox_policy.PRODUCT_DEFAULT_QUOTAS`, repris par `DEFAULT_CLIENT_QUOTAS`) :

| Ressource | Défaut | Application |
|---|---|---|
| vCPU | 2.0 | `docker run --cpus` |
| RAM | 4096m (swap = RAM) | `--memory`, `--memory-swap` ; dépassement = OOM-kill Docker, jamais de swap silencieux |
| Disque | 40g | **contrôle côté plan de gestion** (`check_disk_quota`) au provisioning, label `com.orso.quotas.disk` |

Les paliers tarifaires (`TIER_RESOURCE_QUOTAS`) restent des plafonds inférieurs ; ils portent désormais aussi `disk: 40g`.
Refus explicites : `ERR_DISK_QUOTA_EXCEEDED` (disque, ou valeur de quota illisible — jamais de repli silencieux),
`ERR_HOST_CAPACITY_EXCEEDED` (capacité hôte, KAN-59). **Limite connue** : le disque n'est pas un plafond noyau
(`--storage-opt` exige overlay2 sur XFS `pquota`, non garanti) ; il est contrôlé à l'admission, pas en continu.

## 4. Reproductibilité (CA4)

Le provisioning refuse toute image sans empreinte `sha256:<64 hex>` (`ERR_DIGEST_REQUIRED`, `ERR_INVALID_DIGEST`, KAN-64) ;
l'image est lancée en `repo@sha256:…` et l'empreinte est portée par le label `com.orso.engine.digest`.

## 5. Conservation des artefacts (CA5)

30 jours (`ARTIFACT_RETENTION_DAYS`), mesurés sur `created_at` du manifeste scellé. Purge : `scripts/sandbox_purge_artifacts.py`
(`--dry-run`, `--tenant`, `--days`, `--no-keep-latest`). Garde-fous : la version la plus récente de chaque client est conservée même
expirée (base de rollback KAN-60) ; un manifeste illisible ou non daté n'est jamais purgé (signalé dans `skipped`).
**Planification** (à poser sur l'hôte de gestion, quotidienne) :

```
17 3 * * *  cd /chemin/orso-core && .venv/bin/python scripts/sandbox_purge_artifacts.py >> /var/log/orso/purge_artifacts.log 2>&1
```

## 6. Politique réseau — projet daté du 2026-10-22 (CA7) — **EN ATTENTE DE VALIDATION**

Principe : **refus par défaut**, seules les destinations nécessaires sortent. Le mécanisme de filtrage est celui de KAN-52 ;
KAN-129 en fixe le contenu.

Sortant autorisé (par conteneur client) :

| Destination | Raison | Désignation |
|---|---|---|
| Fournisseurs de modèles effectivement configurés pour le client (`openrouter.ai`, `api.openai.com`, `api.anthropic.com`, `api.deepseek.com`) | appels modèle | clés dans l'environnement du plan de gestion (`OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`) — n'autoriser que ceux dont la clé est fournie |
| Hôte Supabase du projet | authentification / profils | variable `SUPABASE_URL` |
| `api.stripe.com` | facturation (admin client) | présent dans `hermes_cli/web_routers/client_ui.py` |

Tout le reste est refusé (y compris métadonnées cloud et réseaux privés/hôte). Entrant : un seul port applicatif par client
(`-p <port>:9119`), alloué par le plan de gestion (KAN-61) ; aucun autre port publié. Les destinations propres à un outil métier
sont ajoutées **par client, par demande tracée**, jamais globalement.

> Validation attendue en commentaire du ticket (Thibaut / PO). Tant qu'elle n'est pas donnée, ce document n'est pas la politique en vigueur.

## 7. Secrets (CA8)

Aucun secret dans ce lot : clés désignées par nom de variable d'environnement ; injection au conteneur via `--env-file /dev/stdin`
(KAN-65). `test_ca8_no_plaintext_secret_in_new_modules` rejoue le scanner de secrets d'artefacts sur les fichiers ajoutés.
