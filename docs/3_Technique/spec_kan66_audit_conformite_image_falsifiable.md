# Spécification Technique KAN-66 : Rendre Falsifiable l'Audit de Conformité de l'Image Construite

- **Date** : 04 octobre 2026
- **Auteurs** : Jarvis (PO), Antigravity (Architecte Projet), Thibaut
- **Ticket Jira** : [KAN-66](https://orso-agents.atlassian.net/browse/KAN-66) | **Ticket Parent / Antécédent** : [KAN-64](https://orso-agents.atlassian.net/browse/KAN-64)
- **Documents sources** : Ticket KAN-64 (commentaires 16 et 18), Charte de Gouvernance du Fork, Document 27 Confluence.

---

## 1. Contexte et Constat Vérifié

Le 01/10/2026, lors de la revue d'acceptation du ticket **KAN-64** (commentaires 16 et 18), le PO (Jarvis) a mis en évidence une faiblesse majeure dans l'instrument d'audit de sécurité et de conformité de l'image Docker (`scripts/security/audit_zero_secrets_and_client_data.py`) :

1. **Absence de référence d'image obligatoire** : La commande citée au Handoff ne passait aucune référence d'image. L'instrument s'exécutait sur le dépôt seul et omettait silencieusement l'inspection de l'image.
2. **Inspection superficielle** : Même avec une référence fournie, l'audit se limitait à la lecture de la configuration (`docker inspect` : variables d'environnement et étiquettes), sans inspecter l'arborescence applicative exigée par le critère.
3. **Rattrapage silencieux dangereux** : Les contrôles étaient masqués par des exceptions muettes (`except Exception: pass`). Rejoué sur une machine sans aucun démon Docker, l'audit rendait un statut de succès (`PASSED`) avec un code retour nul (`0`).
4. **Fausse réassurance** : Un audit qui réussit quand il n'a rien pu ouvrir ne distingue pas une image propre d'une image jamais lue.

L'objectif de **KAN-66** est de faire de l'audit de conformité de l'image un **instrument scientifique falsifiable** : son échec doit être possible, visible, immédiat et exigé par les critères d'acceptation.

---

## 2. Périmètre et Hors-Périmètre

### Périmètre (Inclus)
- **Référence d'image obligatoire** : Rejet immédiat avec code retour non nul (`1`) en l'absence de référence d'image explicite sur la ligne de commande ou dans l'appel API.
- **Ouverture physique de l'arborescence applicative** : Instanciation d'un conteneur éphémère (`docker create`), extraction du système de fichiers (`docker export`), parcours du flux `tarfile`, et fourniture de la liste effective des chemins applicatifs inspectés avec leur nombre calculé (et non un simple total annoncé).
- **Suppression définitive des rattrapages silencieux** : Buis des `except Exception: pass`. Toute erreur d'ouverture (démon Docker indisponible, image introuvable, conteneur inconstructible, archive illisible, fichier corrompu) est nommée dans la sortie et dans le rapport JSON avec son motif d'erreur exact.
- **Preuve négative obligatoire** : L'audit sur un artefact inexistant ou dans un environnement sans démon Docker doit échouer avec le statut `FAILED` et un code retour non nul.
- **Compteur de données client calculé** : Maintien strict du compteur dynamique calculé (`len(violations)`), aucune constante en dur, et citation explicite des fonctions alimentant le calcul.

### Hors-Périmètre
- L'intégrité des personas et le verrou de démarrage (traités sous KAN-33).
- L'acheminement sécurisé du secret HMAC vers les hôtes clients (traité sous KAN-65).
- L'élargissement du scan de secrets à l'historique Git (objet de KAN-55).
- La modification du moteur Hermès ou du contenu de l'image : ce ticket porte l'instrument de mesure, pas une refonte du moteur.

---

## 3. Arbitrage de l'Architecte : Valeur de Preuve (Question Ouverte)

> **Question ouverte KAN-66** : *L'audit porte-t-il sur l'image publiée au registre ou sur l'image construite localement ?*

**Décision de l'Architecte (04/10/2026)** :
L'instrument `audit_zero_secrets_and_client_data.py` est agnostique à la source et accepte toute référence Docker valide. Cependant, la doctrine Orso formalise deux niveaux de preuve distincts :

1. **Contrôle Pré-Publication (Shift-Left / Image Locale `orso-engine:tag`)** :
   - *Finalité* : Bloquer la chaîne d'intégration CI avant le `docker push` vers GHCR si des secrets de build ou des fichiers sensibles traînent dans l'arborescence.
   - *Valeur* : Barrière de protection interne.
2. **Preuve d'Intégrité de Production (Image Publiée par Digest `ghcr.io/...@sha256:...`)** :
   - *Finalité* : Inspecter les octets scellés du registre avant ou pendant le déploiement sur les hôtes clients.
   - *Valeur* : **Preuve contractuelle opposable**. Seule cette preuve garantit que l'artefact immuable distribué sur les hôtes de production (`prod-fr-003`, etc.) est certifié 100% exempt de secrets et de données client résiduelles.

---

## 4. Implémentation Technique

### 4.1 CA1 : Référence d'image explicite obligatoire
Dans `scripts/security/audit_zero_secrets_and_client_data.py` :
- Si aucun argument n'est fourni en CLI (`len(sys.argv) < 2`), le script écrit sur `sys.stderr` :
  ```
  ✗ Erreur CA1 : Référence d'image Docker obligatoire. Aucune référence fournie sur la ligne de commande.
  Usage: python3 scripts/security/audit_zero_secrets_and_client_data.py <image_ref>
  ```
  et sort immédiatement avec le code retour `1`. Aucun repli silencieux vers des variables d'environnement.
- Dans l'API `run_full_ca5_audit(image_ref, require_image=True)` :
  Si `image_ref` est vide ou absent, une violation de type `MISSING_REQUIRED_IMAGE` est générée, `status` vaut `FAILED` et `total_violations >= 1`.

### 4.2 CA2 : Ouverture de l'arborescence applicative et liste des chemins
L'inspection exécute :
```python
create_proc = subprocess.run(["docker", "create", image_ref], capture_output=True, text=True)
cid = create_proc.stdout.strip()
export_proc = subprocess.Popen(["docker", "export", cid], stdout=subprocess.PIPE)
with tarfile.open(mode="r|*", fileobj=export_proc.stdout) as tar:
    for member in tar:
        name = member.name.lstrip("./")
        result["scanned_paths"].append(name)
        if is_app_path(name):
            result["applicative_paths"].append(name)
```
- Le rapport JSON expose `scanned_paths_count`, `applicative_paths_count` et la liste exhaustive `applicative_paths`.
- La synthèse console affiche la liste complète des chemins applicatifs parcourus dans l'image et leur nombre calculé.

### 4.3 CA3 & CA4 : Falsifiabilité et suppression des rattrapages silencieux
Chaque étape susceptible d'échouer génère une violation typée avec son motif explicite :
- `docker inspect` échoue $\rightarrow$ `IMAGE_INSPECT_FAILED` avec message `stderr` de Docker.
- `docker create` échoue $\rightarrow$ `CONTAINER_CREATE_FAILED` avec message `stderr`.
- `docker export` échoue $\rightarrow$ `IMAGE_EXPORT_FAILED`.
- Erreur flux tar $\rightarrow$ `IMAGE_TAR_SCAN_ERROR`.
- Erreur de lecture de fichier applicatif $\rightarrow$ `IMAGE_FILE_READ_ERROR` avec message d'exception.
- En cas de violation ou erreur d'ouverture, le rapport passe à `FAILED` et le script sort avec le code de retour `1`.

### 4.4 CA5 : Compteur de données client calculé
Le compteur est calculé dynamiquement par :
```python
client_data_count = len(client_data_violations)
```
Alimenté par :
1. `audit_client_data_in_repository(PROJECT_ROOT)` : détection de persistance Git ou fichiers résiduels (`data/`, `*.db`, `consignes_olympe.jsonl`, etc.).
2. `audit_docker_image_for_secrets_and_client_data(image_ref)` : détection de variables d'environnement (`ORSO_CLIENT_ID`), d'étiquettes (`com.orso.tenant_id`) et de bases SQLite dans l'arborescence.
Le rapport et la synthèse mentionnent explicitement :
`client_data_calculation_source = "len(client_data_violations) via audit_client_data_in_repository + audit_docker_image_for_secrets_and_client_data"`.

---

## 5. Matrice de Traçabilité des Critères d'Acceptation

| Critère | Description | Preuve d'Implémentation | Test Automatisé |
| :--- | :--- | :--- | :--- |
| **CA1** | Référence d'image explicite obligatoire, erreur si absente | Contrôle CLI direct + `require_image=True` | `test_ca1_missing_image_ref_exits_with_error` |
| **CA2** | Ouverture arborescence applicative + liste des chemins | Flux `docker export` + extraction tar + `applicative_paths` | `test_ca2_inspects_applicative_file_tree_with_paths_list` |
| **CA3** | Échec obligatoire si artefact inouvrable (preuve négative) | Sortie `FAILED` et code retour `1` sur image inexistante | `test_ca3_failure_when_artifact_cannot_be_opened` |
| **CA4** | Erreur d'ouverture nommée, aucun `pass` silencieux | Erreurs typées (`IMAGE_INSPECT_FAILED`, etc.) avec motif | `test_ca4_no_silent_fallback_error_named_in_output` |
| **CA5** | Compteur données client calculé + fonctions sources citées | `len(violations)` calculé + mention des deux fonctions | `test_ca5_client_data_counter_calculated_and_source_named` |

---

## 6. Respect de la Charte de Gouvernance Fork

- **Zone Sanctuaire (Zone A)** : 0 modification dans `agent/turn_*.py`, `run_agent.py`, `conversation_loop.py`, `hermes_state*.py`, connecteurs modèles et registres d'outils.
- **Zone d'Évolution (Zone B)** : Modifications strictement circonscrites aux outillages d'audit de conformité (`scripts/security/`) et aux tests de distribution (`tests/distribution/`).
