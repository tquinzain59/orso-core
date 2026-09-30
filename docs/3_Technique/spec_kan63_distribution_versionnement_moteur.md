# Spécification Technique KAN-63 : Distribution et Versionnement de l'Image du Moteur vers les Hôtes Clients

- **Date** : 30 septembre 2026
- **Auteurs** : Thibaut (Lead / PO), Antigravity (Architecte Projet)
- **Ticket Jira** : [KAN-63](https://orso-agents.atlassian.net/browse/KAN-63) | **Épique associée** : [KAN-62](https://orso-agents.atlassian.net/browse/KAN-62) (POC 2 artefacts)
- **Documents sources** : Confluence Document 27 (sections 2, 4, 5), ADR 2026-09-30-04, Charte de Gouvernance du Fork (Sanctuaire inviolable)

---

## 1. Contexte et Objectifs

Suite à la décision d'hébergement du 30/09/2026, l'infrastructure Orso Agents est scindée en deux types d'hôtes :
1. **Hôte 1 (Serveur de Gestion / Supervision)** : Héberge Olympe (port 9230), le Cockpit OPS (`ops.orso-agents.fr`), les bases de données et les pipelines d'intégration / build.
2. **Hôte 2 (Serveur d'Exécution Client)** : Nouveau serveur OVH dédié hébergeant exclusivement les conteneurs étanches des clients.

L'objectif de cette spécification est de définir, outiller et valider la distribution fiable, versionnée et sécurisée de l'image Docker du moteur Hermès / Orso depuis son lieu de construction vers les hôtes d'exécution clients, en respectant les 5 critères d'acceptation du ticket KAN-63.

```
                      +------------------------------------------+
                      |         Hôte 1 (Build & Olympe)          |
                      |  - Code source & Dockerfile.orso         |
                      |  - docker build -> orso-engine:<tag>     |
                      +--------------------+---------------------+
                                           |
                              docker push  | (Write / Admin)
                                           v
                      +------------------------------------------+
                      |    GitHub Container Registry (GHCR)      |
                      |    ghcr.io/tquinzain59/orso-engine       |
                      |    @sha256:d8a5... (Digest Immuable)     |
                      +--------------------+---------------------+
                                           |
                              docker pull  | (Read-Only: read:packages)
                                           v
                      +------------------------------------------+
                      |       Hôte 2 (Exécution Clients)         |
                      |  - Docker daemon (port non exposé)       |
                      |  - Conteneurs clients :                  |
                      |      Financia Solutions (9229/9300)      |
                      |      Client-B (9231/9301)                |
                      |      Client-C (9232/9302)                |
                      +------------------------------------------+
```

---

## 2. Stratégie d'Étiquetage et d'Épinglage par Digest (CA2)

### 2.1 Immuabilité stricte par Digest OCI
Pour éviter tout risque d'attaque par substitution ou dérive due à un tag flottant (`:latest` ou `:stable`), **tout déploiement en production est impérativement épinglé par son digest cryptographique SHA-256** :
```bash
ghcr.io/tquinzain59/orso-engine@sha256:<sha256_64_hex_digits>
```

### 2.2 Convention d'étiquetage humain
Lors de la publication, l'image reçoit deux étiquettes pour la traçabilité humaine :
1. `v<major>.<minor>.<patch>-<git_sha>` (ex: `v1.0.0-3e990d4`) : référence formelle du commit Git source.
2. `release-<date>` (ex: `release-20260930`) : jalon calendaire.

Le tag `:latest` peut être généré à titre indicatif pour le développement local, mais **Olympe refuse formellement d'instancier un conteneur client basé sur un tag flottant sans digest validé** (rejet immédiat `ERR_DIGEST_REQUIRED` dans `olympe/lifecycle_manager.py`).
La variable de référence est alignée canoniquement sur `ORSO_TARGET_ENGINE_DIGEST` (avec repli de compatibilité sur `ORSO_BACKEND_IMAGE_DIGEST`).

---

## 3. Authentification et Moindre Privilège (CA5)

1. **Jeton d'infrastructure dédié (Machine User Token)** :
   - Portée unique : `read:packages` (Lecture seule sur les packages de l'organisation).
   - Zéro accès aux dépôts Git (`repo`), zéro droit d'écriture (`write:packages`), zéro droit d'administration.
2. **Stockage sur l'hôte client** :
   - Fichier local `/etc/orso/registry.env` en permissions strictes `0600 root:root`.
   - Jamais commité dans Git, jamais injecté dans les couches de l'image Docker.
3. **Absence d'exposition du démon Docker** :
   - Le démon Docker de l'Hôte 2 écoute exclusivement sur le socket UNIX local `/var/run/docker.sock`. Aucun port TCP `2375/2376` n'est ouvert sur internet.

---

## 4. Procédures Opérationnelles Écrites (CA4)

### 4.1 Procédure d'onboarding d'un nouvel hôte client (Hôte N)
1. Connexion SSH à l'hôte client :
   ```bash
   ssh root@<IP_HOTE_CLIENT>
   ```
2. Installation et démarrage du runtime Docker officiel.
3. Configuration des identifiants de registre en lecture seule :
   ```bash
   echo "<GHCR_READ_TOKEN>" | docker login ghcr.io -u <GITHUB_USER> --password-stdin
   ```
4. Téléchargement préalable (*pre-pull*) de l'image moteur de référence par son digest :
   ```bash
   docker pull ghcr.io/tquinzain59/orso-engine@sha256:<REFERENCE_DIGEST>
   ```
5. Enregistrement de l'hôte dans la table de supervision Olympe.

### 4.2 Procédure de mise à jour d'un hôte vers une nouvelle version du moteur
1. **Notification et gel préventif** : Olympe signale l'opération de maintenance.
2. **Téléchargement de la nouvelle version** sur l'hôte cible :
   ```bash
   docker pull ghcr.io/tquinzain59/orso-engine@sha256:<TARGET_DIGEST>
   ```
3. **Vérification cryptographique** :
   ```bash
   PULLED_DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' ghcr.io/tquinzain59/orso-engine@sha256:<TARGET_DIGEST> | cut -d'@' -f2)
   if [ "$PULLED_DIGEST" != "sha256:<TARGET_DIGEST>" ]; then
       echo "ERREUR : Divergence d'empreinte !" && exit 1
   fi
   ```
4. **Bascule des conteneurs clients** :
   - Arrêt gracieux du conteneur client : `docker stop -t 15 orso-client-<slug>`
   - Démarrage du conteneur avec la nouvelle image épinglée par digest.
   - Validation de la sonde de santé HTTP (`/api/client/health` -> `200 OK`).

### 4.3 Procédure de retour arrière (*Rollback*) d'urgence
Si une régression ou anomalie est détectée sur la nouvelle version :
1. Arrêt du conteneur incidenté :
   ```bash
   docker stop -t 5 orso-client-<slug>
   ```
2. Relance immédiate du conteneur en pointant sur le **digest précédent** (qui est déjà en cache local Docker sur l'hôte, garantissant un redémarrage en moins de 3 secondes) :
   ```bash
   # Relance instantanée sur l'ancien digest stable
   docker run ... ghcr.io/tquinzain59/orso-engine@sha256:<PREVIOUS_DIGEST>
   ```
3. Vérification du rétablissement du service et consignation dans le journal OPS.

### 4.4 Procédure de secours hors-ligne (Air-Gapped Fallback)
En cas de panne générale de GHCR ou de coupure du transit réseau externe :
1. Sur Hôte 1 : Export et compression de l'image locale :
   ```bash
   docker save orso-engine:<tag> | gzip -9 > /tmp/orso-engine-<tag>.tar.gz
   sha256sum /tmp/orso-engine-<tag>.tar.gz > /tmp/orso-engine-<tag>.tar.gz.sha256
   ```
2. Transfert SCP sécurisé vers Hôte 2 :
   ```bash
   scp /tmp/orso-engine-<tag>.tar.gz* root@<IP_HOTE_2>:/opt/orso/incoming/
   ```
3. Sur Hôte 2 : Vérification de l'empreinte de l'archive avant chargement :
   ```bash
   cd /opt/orso/incoming/
   sha256sum -c orso-engine-<tag>.tar.gz.sha256
   gunzip -c orso-engine-<tag>.tar.gz | docker load
   ```

---

## 5. Surveillance et Détection de Dérive de Version (CA3)

Pour garantir qu'aucun hôte ne dérive silencieusement dans le cluster, un outillage d'audit automatisé compare en permanence les versions :
- **Entrées** : L'inventaire des hôtes actifs et le digest cible validé par Olympe (`ORSO_TARGET_ENGINE_DIGEST`).
- **Sondage** : Chaque hôte renvoie le digest SHA-256 de l'image effectivement utilisée par ses conteneurs clients actifs.
- **Règles de détection** :
  - `OK` : Digest de l'hôte == Digest cible.
  - `DRIFT_DETECTED` : Digest de l'hôte != Digest cible. Alerte de sévérité Haute émise vers le cockpit OPS.
  - `UNKNOWN / UNREACHABLE` : L'hôte ne répond pas ou l'image n'est pas trouvée.

---

## 6. Durcissement de l'Image et Zéro Donnée Client (CA5)

1. **Assainissement du `.dockerignore`** :
   - Blocage strict de tous les fichiers d'environnement (`.env*` sauf template `!.env.example`).
   - Blocage de tout document confidentiel, clé SSH (`*.pem`, `*.key`), jetons de session, logs de transactions.
   - Blocage des espaces de travail de test et des dossiers de stockage client (`data/`, `runtime/`, `profiles/*/logs/`, `profiles/*/*.db*`).
2. **Audit statique et dynamique de l'image** :
   - Contrôle du manifest d'image : zéro secret codé en dur dans les instructions `ENV` ou `LABEL`.
   - Inspection de l'arborescence résultante dans le conteneur (`/app`) confirmant l'absence totale de données spécifiques à un client.
