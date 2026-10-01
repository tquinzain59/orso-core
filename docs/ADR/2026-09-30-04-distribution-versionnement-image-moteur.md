# ADR 2026-09-30-04 : Distribution et Versionnement de l'Image du Moteur vers les Hôtes Clients

- **Date** : 30 septembre 2026
- **Statut** : Accepté et Validé (Décision d'architecture KAN-63 / Épique KAN-62)
- **Auteurs** : Thibaut (Lead / PO), Antigravity (Architecte-Développeur)
- **Référence Documents** : Confluence Document 27 (sections 2, 4 et 5), Document 06 (Architecture système), Document 21 (Journal des réalisations)
- **Tickets Jira associés** : [KAN-63](https://orso-agents.atlassian.net/browse/KAN-63), [KAN-62](https://orso-agents.atlassian.net/browse/KAN-62), [KAN-61](https://orso-agents.atlassian.net/browse/KAN-61), [KAN-60](https://orso-agents.atlassian.net/browse/KAN-60), [KAN-58](https://orso-agents.atlassian.net/browse/KAN-58)

---

## 1. Contexte et Problématique

Le 30/09/2026, la décision d'hébergement structurante pour Orso Agents a été actée (Document 27, section 4) :
- Le serveur initial OVH (**Hôte 1**) conserve le plan de gestion (**Olympe**, port 9230), le **Cockpit OPS** (`ops.orso-agents.fr`) et la chaîne de build d'images.
- Un nouveau serveur OVH dédié (**Hôte 2**) est provisionné pour exécuter les espaces conteneurisés des clients.
- Les conteneurs clients n'existeront donc plus sur l'hôte qui construit les images.

### Constat d'absence de registre et risques identifiés :
1. **Absence de registre Orso** : Jusqu'à présent, l'image backend était construite localement par `docker compose` (`Dockerfile.orso`) sous l'étiquette par défaut `orso-core-orso-backend:latest`.
2. **Risque de dérive silencieuse de version** : Sur deux hôtes distincts, rien ne garantissait qu'une version identifiée du moteur arrive jusqu'aux espaces clients, ni que les deux hôtes exécutent la même version. Un correctif de sécurité critique appliqué sur l'Hôte 1 pouvait ne jamais atteindre l'Hôte 2, sans qu'aucun mécanisme ne le détecte.
3. **Risque d'exfiltration de secrets ou de données clients** : `Dockerfile.orso` copie l'arborescence du dépôt (`COPY . /app/`). Une image poussée dans un registre public ou mal configuré risquerait d'embarquer des artefacts sensibles. La règle inviolable du Document 27 s'applique sans exception : **aucun secret dans une image, et aucun espace client dans l'image du moteur**.

---

## 2. Décision d'Architecture

L'architecture à **Deux Artefacts** (Document 27) est formalisée :
1. **Artefact Moteur (Socle commun immuable)** : Image Docker unique, contenant le runtime Python d'Orso/Hermes, les connecteurs génériques et les passerelles. Cette image est strictement anonymisée, exempte de tout secret ou configuration client, et référencée de manière immuable par son **empreinte cryptographique (digest SHA-256)** : `image@sha256:...`.
2. **Artefact Espace Client (Données & Spécialisations)** : Contient les personas spécifiques, les compétences métiers sur-mesure, les configurations de canaux et les clés ERP chiffrées du client, injectées au démarrage.

### Mode de distribution retenu : GitHub Container Registry (GHCR) privé avec épinglage par Digest SHA-256

Pour la Vague 0 (5 premiers clients) et la Vague 1 (25 clients), le mode de distribution retenu est :
- **Registre** : **GHCR privé** (`ghcr.io/tquinzain59/orso-engine`).
- **Authentification des hôtes clients** : Personal Access Token (PAT) d'infrastructure à portée strictement restreinte et minimale (`read:packages`), sans aucun droit d'accès au code source (`repo`) ni droit d'administration.
- **Identification & Immuabilité** : Chaque déploiement pointe exclusivement sur un **digest SHA-256** (`ghcr.io/tquinzain59/orso-engine@sha256:<digest>`). Le tag de build (`v1.0.0-<git_sha>`) ne sert que d'étiquette humaine et n'est jamais utilisé seul en production pour prévenir toute attaque par écrasement de tag mutable.
- **Traçabilité & Détection de dérive** : Une sonde d'audit de version interroge les démons Docker de chaque hôte pour comparer les digests en service avec le digest de référence déclaré dans Olympe. En cas d'écart, une alerte est levée.
- **Procédure de secours (Air-Gapped Fallback)** : En cas d'indisponibilité du registre ou de coupure réseau externe, une procédure manuelle de transfert d'archive signée (`docker save | gzip` -> SCP chiffré -> vérification SHA-256 -> `docker load`) est documentée et testée.

---

## 3. Analyse Comparative et Options Écartées (Justification CA1)

| Critère | Option A : GHCR Privé (Retenue) | Option B : Registre Managé OVH (Harbor) | Option C : Transfert d'Archives (Fallback) | Option D : Build local sur Hôte Client (Rejetée) |
| :--- | :--- | :--- | :--- | :--- |
| **Coût mensuel** | **~0 € à 3 € / mois** (inclus dans quota GitHub Pro/Team ; stockage \$0.25/Go au-delà de 500Mo, bande passante \$0.50/Go) | 11 € HT / mois (offre OVH Managed Registry S 200 Go) | 0 € (utilise liaisons existantes) | 0 € direct, mais surcoût CPU/RAM hôte client |
| **Gestion des calques (Layer Caching)** | **Excellente** (standard OCI Docker natif, seuls les layers modifiés sont transférés) | Excellente (standard OCI Docker natif) | Inexistante (télécharge l'image complète ~3-4 Go à chaque patch) | Non applicable |
| **Sécurité d'accès** | **Jeton read-only `read:packages`**, révocable instantanément, aucun port ouvert | Robot account pull-only, possible intégration vRack privé | Nécessite des clés SSH d'hôte à hôte avec droits d'accès fichiers | Risque d'exposition Git et de clés de build sur l'hôte |
| **Complexité d'exploitation** | **Très faible** (zéro serveur supplémentaire à maintenir pour la Vague 0) | Moyenne (un service managé supplémentaire à configurer et superviser) | Élevée (scripts manuels de compression, transfert et décompression) | Inacceptable (outillage de build requis sur l'hôte de production) |
| **Garantie d'immuabilité** | **Absolue** via le digest SHA-256 du manifeste OCI | Absolue via le digest SHA-256 du manifeste OCI | Bonne (via calcul de sha256sum sur l'archive tar) | Nulle (deux builds peuvent différer selon la résolution des paquets) |
| **Verdict** | **Retenu pour Vague 0 & 1** | Conservé comme cible d'échelle pour migration vRack future | Conservé uniquement comme procédure de secours hors-ligne | **Formellement rejeté** |

### Justification détaillée des rejets :
- **Rejet de l'Option D (Build sur hôte client)** : L'hôte de production client doit rester une machine d'exécution purement passive. Installer les dépendances de compilation (`build-essential`, accès Git complet, outils de packaging) accroît la surface d'attaque, gaspille les ressources CPU/RAM allouées aux clients et anéantit toute reproductibilité des versions.
- **Ajournement de l'Option B (Harbor OVH)** : Bien que souverain et doté d'atouts indéniables pour une infrastructure multi-serveurs à grande échelle connectée en vRack, le registre OVH Harbor entraîne un coût fixe mensuel (11 € HT) et une surcharge de configuration superflue pour la Vague 0 (5 clients). L'architecture OCI choisie rendra la transition vers Harbor 100 % transparente le moment venu (simple changement du nom d'hôte de registre).
- **Rétrogradation de l'Option C (Transfert d'archive)** : Le transfert de fichiers `.tar.gz` de plusieurs gigaoctets à chaque itération engorge la bande passante et allonge inutilement le temps de bascule (*downtime*). Il est relégué au statut de procédure de secours.

---

## 4. Conséquences et Engagements Opérationnels

1. **Isolation stricte des secrets** :
   - Aucun token GHCR n'est stocké dans le dépôt Git ni inscrit dans les images Docker.
   - Les tokens de déploiement sont injectés sur l'Hôte 2 via les variables d'environnement locales de la machine (`/etc/orso/engine.env` en permissions `0600 root:root`).
2. **Périmètre du `.dockerignore` durci** :
   - Exclusion systématique de tout fichier `.env`, clé privée, certificat, document stratégique, ou données de profils clients du contexte de build.
3. **Épinglage par Digest obligatoire dans Olympe (KAN-64)** :
   - Le superviseur Olympe (`olympe/lifecycle_manager.py`) applique un refus formel (Fail-Closed, code `ERR_DIGEST_REQUIRED`) lors de tout provisioning demandant une image sur tag flottant sans digest SHA-256 valide.
   - Alignement canonique de la variable de référence : `ORSO_TARGET_ENGINE_DIGEST` (avec repli rétro-compatible sur `ORSO_BACKEND_IMAGE_DIGEST`).
4. **Hôte d'exécution client opérationnel (PROD-FR-003)** :
   - Serveur OVH dédié `prod-fr-003.orso-agents.fr` (IP `57.131.196.106`), Ubuntu 26.04 LTS, noyau 7.0.0-28-generic, Docker 29.8.1, swapfile 2 Go actif, authentification SSH par mot de passe formellement verrouillée (`PasswordAuthentication no`).

---

## 5. Calendrier et Prochaine Revue
- **Date de réexamen** : À l'issue de la Vague 0 (bilan d'exploitation des 5 premiers clients), pour évaluer l'opportunité de bascule vers le registre managé OVH Harbor sur vRack privé.
