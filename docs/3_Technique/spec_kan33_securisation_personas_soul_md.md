# Spécification Technique & Handoff : Sécurisation et Intégrité des Personas SOUL.md (KAN-33)

> **Ticket Jira associé** : [KAN-33](https://orso-agents.atlassian.net/browse/KAN-33)  
> **Composants** : `Personas (profiles/)`, `Sécurité (scripts/security/persona_integrity.py)`, `Outils Modèle (tools/file_tools_write_guards.py)`, `Docker & Entrypoint (docker/orso-entrypoint.sh, Dockerfile.orso, docker-compose.orso.yml)`, `Télémétrie (skills/telemetry.py)`  
> **Statut** : Validé et Testé à 100% (Green CI)  
> **Auteur / Responsable d'instruction** : Antigravity (Architecte Système & Sécurité)  
> **Date** : 30 Septembre 2026  
> **Source de la Menace Référencée** : ThreatDown, *"CARBONATO: a botnet built around an AI agent"*, 23/09/2026  

---

## 1. Contexte & Menace Réelle

Le 23 septembre 2026, ThreatDown a documenté la campagne malveillante **CARBONATO** ciblant des frameworks d'agents IA (notamment Hermes Agent). Le vecteur d'attaque identifié ne modifie pas le code du moteur : il infecte ou remplace le fichier de personnalité `SOUL.md` par un prompt hostile qui détourne l'agent pour :
1. Piloter l'agent depuis des canaux externes non autorisés (ex: bots Telegram).
2. Collecter et exfiltrer en priorité les clés d'API LLM (14 fournisseurs ciblés) et secrets d'entreprise.
3. Se maintenir en place de manière silencieuse et persistante.

Dans l'architecture Orso Agents, les personas des 4 agents officiels (**Jérôme**, **Lucas**, **Clara**, **Victor**) résident dans `profiles/<agent>/SOUL.md`. Bien que le Sanctuaire du moteur (Zone A) soit strictement préservé, les personas vivaient en Zone B sans verrou d'intégrité ni contrôle d'immutabilité physique au démarrage.

Le ticket **KAN-33** met en place un dispositif de défense en profondeur à 5 niveaux pour rendre les personnalités non modifiables à chaud, vérifiables au boot et surveillées en continu.

---

## 2. Constats Préalables (Établis avant toute modification)

Conformément aux exigences strictes du ticket KAN-33, l'état initial a été mécaniquement prouvé :

* **Constat 1 - Chemin exact où le moteur lit le persona au démarrage** :
  - `agent/system_prompt.py`, fonction `_identity_parts`, lignes 488-494 :
    ```python
    def _identity_parts(agent: Any, ctx_len: Optional[int]) -> Tuple[List[str], bool]:
        wants_soul = agent.load_soul_identity or not agent.skip_context_files
        _soul_content = _pb.load_soul_md(ctx_len, home_override=_agent_home(agent)) if wants_soul else None
        return ([_soul_content], True) if _soul_content else ([DEFAULT_AGENT_IDENTITY], False)
    ```
  - `agent/prompt_builder.py`, fonction `load_soul_md`, lignes 1449-1481 :
    ```python
    soul_path = (Path(home_override) if home_override is not None else get_hermes_home()) / "SOUL.md"
    ```

* **Constat 2 - Le dossier des profils était-il inscriptible par l'utilisateur du conteneur ?**
  - **OUI (Vulnérabilité confirmée)**.
  - Commande de test exécutée sur le conteneur `orso_financia_backend` :
    ```bash
    docker exec -u orso orso_financia_backend sh -c 'touch /app/profiles/jerome/.test && echo ECRITURE-POSSIBLE && rm -f /app/profiles/jerome/.test'
    ```
  - Sortie obtenue :
    ```
    ECRITURE-POSSIBLE
    ```

* **Constat 3 - Existe-t-il un rechargement de persona à chaud (hot reload) en cours de session ?**
  - **NON**. Le prompt système est mis en cache sur l'instance de l'agent (`agent._cached_system_prompt`) au premier tour de conversation (`agent/conversation_loop.py:687, 751`). Conformément à la Charte de Gouvernance, per-conversation prompt caching is sacred : aucune mutation dynamique n'intervient en cours de session active. En revanche, à chaque nouvelle session ou re-démarrage, `SOUL.md` était relu directement depuis le disque sans vérification d'intégrité préalable.

* **Constat 4 - Le persona était-il journalisé quelque part (version, empreinte) ?**
  - **NON** : Aucun journal d'intégrité probant n'existait avant KAN-33.

---

## 3. Dispositif de Sécurité & Règles Implémentées

### R1 & R2 : Immutabilité physique et montage en lecture seule stricte
1. **Docker Compose (`docker-compose.orso.yml`)** :
   - Montage de `./profiles` avec l'option `:ro` (read-only) sur `/app/profiles`, `/app/data/hermes_home/profiles` et `/home/orso/.hermes/profiles`.
   - Activation de `security_opt: [no-new-privileges:true]`.
2. **Dockerfile & Entrypoint (`Dockerfile.orso`, `docker/orso-entrypoint.sh`)** :
   - Propriété `root:root` garantie sur `/app/profiles`.
   - Droits stricts `0555` sur les répertoires et `0444` (`-r--r--r--`) sur tous les fichiers `SOUL.md`.

### R3 & R4 : Manifeste d'Intégrité & Vérification au Boot (Fail-Closed)
- Création du manifeste `profiles/personas.lock.json` recensant le nom, la version, la date et l'empreinte SHA-256 de chaque agent.
- Module de vérification `scripts/security/persona_integrity.py` :
  - Exécuté au démarrage du conteneur dans `orso-entrypoint.sh` via `python3 scripts/security/persona_integrity.py verify --fail-fast`.
  - En cas d'incohérence : émission du code d'erreur `PER-INTEGRITY-001`, journalisation immédiate et arrêt du conteneur (code de sortie 1).
  - Support de signature HMAC-SHA256 avec la clé d'environnement `ORSO_PERSONA_HMAC_KEY`.

### R5 & R6 : Surveillance Continue à l'Exécution
- Processus démon d'arrière-plan lancé au boot : `python3 scripts/security/persona_integrity.py monitor --interval 300 &`.
- Recalcul périodique de l'empreinte SHA-256 toutes les 5 minutes (300 secondes).
- En cas d'altération en direct :
  - Déclenchement de l'événement critique `PER-INTEGRITY-002`.
  - Notification critique inscrite dans `telemetry_export.json` et `personas_integrity.log`.
  - Arrêt d'urgence du conteneur (`os.kill(1, signal.SIGTERM)` / `sys.exit(1)`).

### R7 : Journal d'Intégrité Probant
- À chaque vérification et démarrage, écriture structurée dans :
  - `/app/data/telemetry/personas_integrity.log` (format audit textuel).
  - `/app/data/telemetry/personas_integrity.jsonl` (format JSON Lines).
  - Intégration directe dans l'agrégateur de télémétrie (`skills/telemetry.py`).

### R8 & R9 : Cloisonnement des Outils & Absence de Secrets
- Durcissement de `tools/file_tools_write_guards.py` (`_check_sensitive_path`) : tout appel à `write_file`, `patch` ou manipulation ciblant `profiles/`, `SOUL.md` ou `personas.lock.json` est hard-refusé avec le message :
  `Refusing to write to protected agent profile path: ... Persona files in profiles/ are read-only and immutable. Modifications require reviewed git commits.`
- Aucun secret, jeton ou mot de passe n'est présent dans aucun des 4 `SOUL.md` (validé par `check_no_secrets.py`).

---

## 4. Preuves Mécaniques des Critères d'Acceptation (CA1 à CA8)

### CA1 - Chemin de lecture documenté et pointant vers le montage lecture seule
- Code : `agent/system_prompt.py:493` et `agent/prompt_builder.py:1465`.
- Dans le conteneur, `HERMES_HOME/profiles` pointe vers `/app/profiles` monté avec le flag `:ro`.

### CA2 - Dossier monté en lecture seule et permissions root root 0444
- `docker-compose.orso.yml` : `./profiles:/app/profiles:ro`
- Permissions configurées :
  ```bash
  ls -la profiles/*/SOUL.md
  # -r--r--r-- root root
  ```

### CA3 - Test négatif d'écriture
- Avec le montage `:ro` et les droits `root:root 0444`, toute tentative de modification (`touch`, `echo >>`) par l'utilisateur `orso` échoue avec `Read-only file system` ou `Permission denied`.

### CA4 - Test négatif d'intégrité (Altération volontaire -> Fail-Closed)
- Test automatisé `test_ca4_tampered_soul_fails_with_per_integrity_001` :
  - Modification d'un `SOUL.md` sans mise à jour du lockfile.
  - Résultat : `valid == False`, code d'événement `PER-INTEGRITY-001`, exit code 1.

### CA5 - Cohérence du manifeste d'intégrité
- Sorties alignées :
  ```
  8b08185b1f486bf0c34918fa8952796e72239878b2e851f432b7401bf19ba8f2  profiles/clara/SOUL.md
  3028885bc107cf1f372d6e198e8fc4605fabfbbf155269a8ae670ac76ead803e  profiles/jerome/SOUL.md
  5a12dc6d5531b630ef6f7a67cb84622f966c405c40080f178ce4eb2fbfa39d90  profiles/lucas/SOUL.md
  d74deb79ab52681c5d740606be3f213b32747d5f5ae1cb986545cf12d2bc628f  profiles/victor/SOUL.md

  8b08185b1f486bf0c34918fa8952796e72239878b2e851f432b7401bf19ba8f2  profiles/clara/SOUL.md (manifeste)
  3028885bc107cf1f372d6e198e8fc4605fabfbbf155269a8ae670ac76ead803e  profiles/jerome/SOUL.md (manifeste)
  5a12dc6d5531b630ef6f7a67cb84622f966c405c40080f178ce4eb2fbfa39d90  profiles/lucas/SOUL.md (manifeste)
  d74deb79ab52681c5d740606be3f213b32747d5f5ae1cb986545cf12d2bc628f  profiles/victor/SOUL.md (manifeste)
  ```

### CA6 - Surveillance à l'exécution opérationnelle
- Test automatisé `test_ca6_runtime_surveillance_detects_alteration` :
  - Altération d'un `SOUL.md` pendant l'exécution.
  - Déclenchement de l'événement `PER-INTEGRITY-002`, journalisation et appel d'arrêt du conteneur.

### CA7 - Aucune écriture possible depuis les outils d'agent
- Test automatisé `test_ca7_file_tools_blocks_persona_and_profiles_write` :
  - Tentatives d'écriture sur `profiles/jerome/SOUL.md`, `/app/profiles/...`, `personas.lock.json`.
  - Rejet systématique avec message explicite.

### CA8 - Journal d'intégrité exploitable
- Test automatisé `test_ca8_integrity_journal_logging` :
  - Génération des entrées structurées avec horodatage ISO, agent, version, SHA-256 et status.
  - Intégration validée dans `skills/telemetry.py` (`export_telemetry`).

---

## 5. Matrice des Fichiers Modifiés

| Fichier | Modification | Rôle |
|---|---|---|
| `profiles/personas.lock.json` | Création | Manifeste cryptographique d'intégrité (R3, CA5) |
| `scripts/security/persona_integrity.py` | Création | Moteur de vérification au boot et moniteur périodique (R3, R4, R6, R7) |
| `tests/security/test_persona_integrity.py` | Création | Suite de tests automatisés couvrant CA4 à CA8 (100% green) |
| `docker/orso-entrypoint.sh` | Modification | Intégration du contrôle au boot et lancement du moniteur d'arrière-plan |
| `Dockerfile.orso` | Modification | Permissions root:root 0555 et 0444 sur /app/profiles |
| `docker-compose.orso.yml` | Modification | Montages `./profiles:...:ro` et `security_opt: no-new-privileges` |
| `tools/file_tools_write_guards.py` | Modification | Garde-fou strict interdisant l'écriture sur `profiles/` et `personas.lock.json` |
| `skills/telemetry.py` | Modification | Intégration de la section `persona_integrity` dans l'export télémétrique |
| `docs/ADR/2026-09-30-03-personas-et-securite-des-prompts.md` | Modification | Statut passé à "Accepté et Mis en œuvre" |
