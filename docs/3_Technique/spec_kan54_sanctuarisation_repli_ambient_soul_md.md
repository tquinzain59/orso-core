# Spécification Technique & Handoff : Sanctuarisation du Chemin de Repli Ambient de SOUL.md (KAN-54)

> **Ticket Jira associé** : [KAN-54](https://orso-agents.atlassian.net/browse/KAN-54)  
> **Composants** : `Sécurité (scripts/security/persona_integrity.py)`, `Outils Modèle (tools/file_tools_write_guards.py)`, `Docker & Entrypoint (docker/orso-entrypoint.sh)`, `Tests (tests/security/test_kan54_ambient_soul_fallback.py)`  
> **Statut** : Validé et Testé à 100% (15/15 tests sécurité unitaires et d'intégration au vert)  
> **Auteurs / Responsables** : Thibaut (Lead / PO), Antigravity (Architecte Projet)  
> **Date** : 05 Octobre 2026  
> **Source de Vérité ADR** : `docs/ADR/2026-10-05-07-sanctuarisation-repli-ambient-soul-md-kan54.md`  
> **Branche Git** : `KAN-54-sanctuarisation-repli-ambient-soul-md`

---

## 1. Contexte & Problématique Technique

Lors de la revue de clôture du ticket **KAN-33** (30/09/2026), le Product Owner a émis la réserve n°2 quant à l'existence d'une classe de défaut résiduelle dans le moteur Hermès hérité :
- Dans `agent/system_prompt.py` (`_identity_parts`), l'appel `_pb.load_soul_md(ctx_len, home_override=_agent_home(agent))` transmet le résultat de `_agent_home(agent)`.
- Si `_agent_home` renvoie `None` (thread détaché ayant perdu sa `ContextVar`, invocation sur l'agent par défaut), `load_soul_md` retombe sur la résolution ambiante :
  ```python
  soul_path = (Path(home_override) if home_override is not None else get_hermes_home()) / "SOUL.md"
  ```
- En production conteneurisée, `get_hermes_home()` résout `/app/data/hermes_home/`.
- Ce chemin appartient au volume persistant inscriptible (RW) `/app/data/`, hors du périmètre scellé `:ro` et du manifeste d'intégrité de `profiles/` (KAN-33).
- Un fichier `SOUL.md` pirate déposé dans ce volume inscriptible (vecteur d'attaque CARBONATO) pouvait ainsi être chargé silencieusement par le moteur lors d'une session sans `home_override`.

---

## 2. Décision d'Architecture & Arbitrage PO (CA1)

L'Architecte a formalisé l'arbitrage dans l'ADR **2026-10-05-07** et sur le ticket Jira KAN-54 avant toute modification de code :
- **Alerte de Gouvernance** : `agent/prompt_builder.py` appartient au **Sanctuaire (Zone A)**. Tout amendement local y crée une divergence Git permanente avec le dépôt amont `nousresearch/hermes-agent` et risquerait de casser l'usage nominal d'Hermès standalone (qui utilise `~/.hermes/SOUL.md`).
- **Arbitrage de Thibaut (05/10/2026)** : **Option A retenue (Garde-fou à la marge en Zone B)**.
  - Le Sanctuaire (Zone A) demeure **100 % intact** (0 modification dans le cœur).
  - Durcissement périphérique exhaustif en Zone B.

---

## 3. Dispositif de Durcissement Mis en Œuvre (Option A)

### 3.1 Détection exhaustive et Code d'événement stable `PER-INTEGRITY-004` (CA3)
Dans `scripts/security/persona_integrity.py` :
1. **Création de la fonction `find_rogue_personas(profiles_dir, scan_roots)`** :
   - Recherche ciblée des candidats prioritaires dans les volumes de données :
     - `/app/data/hermes_home/SOUL.md`
     - `/app/data/SOUL.md`
     - `./data/hermes_home/SOUL.md`
     - `./data/SOUL.md`
     - `HERMES_HOME / "SOUL.md"` (si `HERMES_HOME` est configuré et distinct de `profiles/`)
     - `<profiles_parent>/data/**/SOUL.md`
   - Scan récursif de `/app/data` et `./data` pour déceler tout fichier nommé `SOUL.md` ou `soul.md` qui ne se trouve pas sous le répertoire légitime `profiles/`.
2. **Code d'événement stable (CA3)** :
   - Introduction de la constante officielle `EVENT_ROGUE_PERSONA_DETECTED = "PER-INTEGRITY-004"`.
3. **Contrôle au démarrage (Fail-Closed)** :
   - `verify_all_personas` échoue immédiatement (`valid is False`, code retour 1) dès qu'un `SOUL.md` hors `profiles/` est détecté, consignant l'alerte `PER-INTEGRITY-004` dans `personas_integrity.log`, `personas_integrity.jsonl` et `telemetry_export.json`.
4. **Surveillance périodique continue (`monitor_loop`)** :
   - Le moniteur d'arrière-plan inspecte les hashs et la présence de tout rogue persona. Dès détection, il journalise l'alerte avec horodatage probant et déclenche l'arrêt d'urgence du conteneur.

### 3.2 Garde-fou d'écriture universel dans les volumes inscriptibles (CA5)
Dans `tools/file_tools_write_guards.py` (`_check_sensitive_path`) :
- Tout chemin ciblant un fichier `soul.md` (insensible à la casse) dans `profiles/`, `HERMES_HOME`, `/data/hermes_home/`, `/app/data/`, `./data/`, `data/` ou `/home/orso/` est **strictement et inconditionnellement refusé** :
  ```python
  f"Refusing to write to protected agent profile path: {filepath}\n"
  "Agent cannot modify its own persona, SOUL.md, or profiles directory (Orso KAN-33/KAN-54). "
  "Persona files are read-only and immutable. Modifications require reviewed git commits."
  ```
- Les fichiers de travail normaux de l'agent (`notes.txt`, `reports/*.csv`, `*.pdf`) et les contrôles d'approbation d'instruction standard demeurent pleinement fonctionnels.

### 3.3 Purge préventive récursive au démarrage
Dans `docker/orso-entrypoint.sh` :
- Purge récursive de tout fichier nommé `SOUL.md` sous `/app/data` et `/home/orso/.hermes` avant le démarrage d'Hermès :
  ```bash
  find /app/data /home/orso/.hermes -name "[Ss][Oo][Uu][Ll].[Mm][Dd]" -delete 2>/dev/null || true
  rm -f /app/data/hermes_home/SOUL.md /app/data/SOUL.md /home/orso/.hermes/SOUL.md ./data/hermes_home/SOUL.md ./data/SOUL.md ./SOUL.md 2>/dev/null || true
  ```

---

## 4. Matrice de Conformité aux Critères d'Acceptation

| Critère d'Acceptation | Statut | Preuve de Réalisation & Localisation |
| :--- | :--- | :--- |
| **CA1 - Décision écrite et datée avant tout code** | **Validé** | Commentaire officiel consigné sur Jira KAN-54 le 05/10/2026 à 16:19 UTC. ADR `docs/ADR/2026-10-05-07-sanctuarisation-repli-ambient-soul-md-kan54.md` approuvé par Thibaut. |
| **CA2 - Amendement moteur (si retenu)** | **N/A** | Option A (Garde-fou à la marge) retenue par arbitrage PO. Sanctuaire intact à 100 %. |
| **CA3 - Détection en cours d'exécution & code stable** | **Validé** | Code stable `PER-INTEGRITY-004`. Test unitaire `test_ca3_runtime_rogue_soul_detection_and_stable_event_code` prouvant l'horodatage de création vs détection et la journalisation probante. Test `test_ca3_startup_verify_rejects_rogue_soul` prouvant le Fail-Closed au démarrage. |
| **CA4 - Test de non-régression dédié** | **Validé** | Suite complète `tests/security/test_kan54_ambient_soul_fallback.py` (5 tests au vert à 100 %). |
| **CA5 - Maintien du dispositif KAN-33** | **Validé** | Suite complète `tests/security/test_persona_integrity.py` (10 tests au vert à 100 %). Suite `test_file_write_safety.py` (59 tests au vert). |
| **CA6 - Limite résiduelle explicitée** | **Validé** | Voir Section 5 ci-après. |

---

## 5. Limite Résiduelle Déclarée (CA6)

Conformément à l'exigence CA6 :
> **Limite résiduelle** : *Dans l'Option A (Garde-fou à la marge), le moteur Hermès conserve son code nominal sans modification du Sanctuaire. Par conséquent, si un acteur disposant d'un accès physique direct à l'hôte écrit un fichier `SOUL.md` dans le volume inscriptible `/app/data/hermes_home/` pendant que le conteneur tourne, il existe une fenêtre d'exposition théorique égale à l'intervalle de scrutation du moniteur de surveillance (300 secondes par défaut, réductible par configuration). Pendant cet intervalle, une inférence déclenchée par un thread orphelin sans `home_override` pourrait théoriquement lire ce fichier pirate avant que le moniteur n'arrête d'urgence le conteneur.*
> *Cette limite est contrebalancée par le durcissement de l'hôte (KAN-51), l'absence de droits root du conteneur (UID 10001) et le blocage inconditionnel de tous les outils d'écriture internes de l'agent (file_tools_write_guards).*

---

## 6. Procédure de Retour Arrière (Rollback)

Si une régression ou un comportement inattendu apparaissait :
1. **Code Git** :
   ```bash
   git revert HEAD
   ```
   Restaure `scripts/security/persona_integrity.py`, `tools/file_tools_write_guards.py` et `docker/orso-entrypoint.sh` dans leur état KAN-33 antérieur.
2. **Conteneur Docker** :
   Redémarrer le conteneur avec l'image antérieure ou purger manuellement les volumes de données hôte :
   ```bash
   docker restart <container_id>
   ```
