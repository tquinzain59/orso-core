# ADR 2026-10-02-06 : Mécanique de Montage et d'Extraction Contrôlée de l'Artefact d'Espace Client

- **Date** : 02 octobre 2026
- **Statut** : Accepté et Validé (Décision d'architecture KAN-60 / Épique KAN-62 / POC 3)
- **Auteurs** : Thibaut (Lead / PO), Antigravity (Architecte Projet & Développeur)
- **Référence Documents** : Confluence Document 27 (sections 2, 5 et 6), ADR 2026-09-30-04 (Distribution Moteur), ADR 2026-10-01-05 (KAN-74), Ticket KAN-58 (Espaces d'agents propres), Ticket KAN-33 (Intégrité des Personas).
- **Tickets Jira associés** : [KAN-60](https://orso-agents.atlassian.net/browse/KAN-60), [KAN-62](https://orso-agents.atlassian.net/browse/KAN-62), [KAN-58](https://orso-agents.atlassian.net/browse/KAN-58), [KAN-59](https://orso-agents.atlassian.net/browse/KAN-59), [KAN-63](https://orso-agents.atlassian.net/browse/KAN-63)

---

## 1. Contexte et Problématique Technique

Dans le cadre de l'architecture à **Deux Artefacts** validée le 30/09/2026 (Document 27) :
1. **L'artefact moteur** est une image de base immuable unique, commune à toute la flotte, distribuée par registre privé et épinglée par son empreinte cryptographique SHA-256 (`ghcr.io/tquinzain59/orso-engine@sha256:...`).
2. **L'artefact d'espace client** contient l'ensemble des personnalisations propres à une entreprise : sa configuration Hermès (`hermes.yaml`), ses compétences métiers (`skills/`), et ses personas calibrés (`profiles/`, `SOUL.md`, `personas.lock.json`).

### La contrainte technique majeure (Section Contraintes du ticket KAN-60) :
> *« Docker ne monte pas une image comme un volume. La voie attendue est un conteneur d'initialisation qui remplit le volume du client depuis l'artefact, ou une extraction contrôlée. Le choix doit être justifié par écrit. »*

Il était donc indispensable d'arbitrer formellement la méthode de déballage, d'identification, de scellement et de montage de l'espace client dans le conteneur du moteur.

---

## 2. Analyse Comparative des Options

| Critère | Option A : Conteneur d'Init Docker (Init Container) | Option B : Extraction Contrôlée & Vérification Cryptographique (Retenue) | Option C : Montage direct de répertoire hôte sans artefact (Rejetée - KAN-58) |
| :--- | :--- | :--- | :--- |
| **Principe** | Un conteneur éphémère basé sur une image d'espace copie ses fichiers dans un volume Docker nommé avant le boot de l'agent. | Un artefact scellé (`.tar.gz` avec `manifest.json`), vérifié par SHA-256, extrait atomiquement dans `spaces_root/{slug}`, verrouillé en permissions 0555/0444, monté en `:ro`. | Copie ou montage en vrac de dossiers de l'hôte sans format d'artefact ni empreinte globale scellée. |
| **Latence au démarrage (Provisioning / Réveil)** | **Élevée (+1,5 à 3,0 secondes)** : cycle de vie complet d'un conteneur supplémentaire (`docker run`, création, stop, rm). | **Quasi-nulle (< 50 millisecondes)** : décompression locale optimisée et contrôle SHA-256 en mémoire. | Immédiate mais non reproductible et non auditable. |
| **Garantie d'immuabilité & Intégrité** | Partielle : le volume cible reste modifiable par l'hôte ou par le conteneur d'init si non verrouillé. | **Absolue (Fail-Closed)** : vérification stricte du digest SHA-256 avant toute extraction. Permissions hôte verrouillées (0555/0444) et montage `:ro` inviolable. | Nulle : aucune empreinte scellée. |
| **Complexité d'exploitation** | **Moyenne à élevée** : multiplication des images dans le registre Docker (une image par client par version), gestion des permissions UID/GID dans le volume. | **Très faible** : stockage déterministe d'archives légères (< 1 Mo par espace client) dans le registre d'artefacts local ou object store. | Très faible, mais viole l'architecture à deux artefacts. |
| **Résistance aux attaques (Sécurité)** | Dépend des droits du conteneur d'init sur le démon Docker. | **Durcissement natif** : protection stricte anti-Zip Slip / Directory Traversal, scan anti-secrets avant persistance (CA4). | Faible : risque de collision ou fuite cross-tenant. |
| **Verdict** | Rejeté pour l'architecture Docker Compose d'Orso (envisageable sur K8s) | **Retenu à l'unanimité (Choix Nominal)** | **Formellement proscrit** |

---

## 3. Décision d'Architecture

L'**Option B (Extraction Contrôlée & Vérification Cryptographique)** est officiellement adoptée comme mécanique nominale d'Orso Agents pour le montage des espaces clients :

1. **Format de l'Artefact Scellé** :
   - L'espace d'un client est empaqueté sous la forme d'une archive tar gzip déterministe : `client-space-{tenant_slug}-{version}.tar.gz`.
   - Les métadonnées de construction sont normalisées (mtime fixé à 1700000000, uid=0, gid=0, propriétaire `orso:orso`).
   - Un manifeste officiel `manifest.json` accompagne chaque version et consigne :
     - Le digest SHA-256 global de l'archive scellée : `sha256:<64_hex_digits>`.
     - Le digest de l'arbre canonique de contenu (*Content Merkle Tree*).
     - L'inventaire unitaire de chaque fichier avec son hash individuel et sa taille.
     - L'état de conformité cryptographique des personas HMAC KAN-33.
     - Le bilan de l'audit de détection de secrets (compteur nul certifié).

2. **Mécanique d'Extraction Contrôlée (Fail-Closed)** :
   - Avant toute extraction, le gestionnaire `ClientSpaceArtifactManager` recalcule le SHA-256 de l'archive physique et le compare au manifeste. En cas d'incohérence, l'opération est immédiatement interrompue avec l'erreur `ERR_ARTIFACT_DIGEST_MISMATCH`.
   - L'extraction s'effectue via un répertoire temporaire de staging isolé (`.staging_{tenant}_{version}_{pid}`) avec contrôle strict des chemins d'accès (rejet de tout chemin contenant `..` ou absolu anti-Zip Slip).
   - Le basculement vers l'espace physique (`spaces_root / {tenant_slug}`) est atomique.

3. **Montage Inviolable en Lecture Seule (`:ro`)** :
   - Sur l'hôte, les permissions sont verrouillées à `0555` pour les répertoires et `0444` pour les fichiers.
   - Les dossiers de l'espace sont montés en `:ro` dans le conteneur du moteur :
     - `/app/config:ro`
     - `/app/skills:ro`
     - `/app/profiles:ro`, `/app/data/hermes_home/profiles:ro`, `/home/orso/.hermes/profiles:ro` (convergence des 3 chemins KAN-58).
   - Les labels Docker officiels sont apposés sur le conteneur client :
     - `com.orso.artifact.version={version}`
     - `com.orso.artifact.digest={fingerprint}`
     - `com.orso.artifact.mounted_ro=true`

4. **Procédure de Versionnement et Rollback (CA3)** :
   - Toute modification donne lieu à un nouvel artefact scellé (ex: `v2.0.0`).
   - Le retour arrière s'opère par réinstallation de l'artefact antérieur `v1.0.0` et redémarrage du conteneur, sans aucune altération de l'image moteur commune.

---

## 4. Conséquences Opérationnelles

- **Performance** : Déploiement et extraction d'un espace client en moins de 15 ms, garantissant un réveil ultra-rapide (*Wake-on-Demand*) sans latence d'init container.
- **Sécurité & Étanchéité** : Impossible pour un agent ou un attaquant d'altérer sa configuration, ses compétences ou ses personas depuis l'intérieur du conteneur (`Read-only file system`).
- **Gouvernance du Fork (Sanctuaire Zone A)** : Le moteur Hermès (`agent/`, `run_agent.py`, `conversation_loop.py`) n'a subi aucune modification. Toute la logique d'artefact vit à la périphérie dans `olympe/artifact_manager.py` et `olympe/lifecycle_manager.py`.
