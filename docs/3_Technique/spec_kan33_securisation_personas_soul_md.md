# Spécification Technique & Handoff : Sécurisation et Intégrité des Personas SOUL.md (KAN-33)

> **Ticket Jira associé** : [KAN-33](https://orso-agents.atlassian.net/browse/KAN-33)  
> **Composants** : `Personas (profiles/)`, `Sécurité (scripts/security/persona_integrity.py)`, `Outils Modèle (tools/file_tools_write_guards.py)`, `Docker & Entrypoint (docker/orso-entrypoint.sh, Dockerfile.orso, docker-compose.orso.yml)`, `Moteur CLI (hermes_cli/config.py)`, `Télémétrie (skills/telemetry.py)`, `CI (security_persona_integrity.yml)`  
> **Statut** : Validé et Testé à 100% (Green CI - Run 36700799240)  
> **Auteur / Responsable d'instruction** : Antigravity (Architecte Système & Sécurité)  
> **Date** : 30 Septembre 2026 (Version 2 - Levée intégrale des réserves)  
> **Source de la Menace Référencée** : ThreatDown, *"CARBONATO: a botnet built around an AI agent"*, 23/09/2026  
> **Source de Vérité ADR** : Le fichier versionné `docs/ADR/2026-09-30-03-personas-et-securite-des-prompts.md` sous Git constitue la référence technique souveraine. La page Confluence ID 5603337 en est la projection documentaire collaborative.

---

## 1. Contexte & Menace Réelle

Le 23 septembre 2026, ThreatDown a documenté la campagne malveillante **CARBONATO** ciblant des frameworks d'agents IA (notamment Hermes Agent). Le vecteur d'attaque identifié ne modifie pas le code du moteur : il infecte ou remplace le fichier de personnalité `SOUL.md` par un prompt hostile qui détourne l'agent pour :
1. Piloter l'agent depuis des canaux externes non autorisés (ex: bots Telegram).
2. Collecter et exfiltrer en priorité les clés d'API LLM (14 fournisseurs ciblés) et secrets d'entreprise.
3. Se maintenir en place de manière silencieuse et persistante.

Dans l'architecture Orso Agents, les personas des 4 agents officiels (**Jérôme**, **Lucas**, **Clara**, **Victor**) résident dans `profiles/<agent>/SOUL.md`. Bien que le Sanctuaire du moteur (Zone A) soit strictement préservé, les personas vivaient en Zone B sans verrou d'intégrité ni contrôle d'immutabilité physique au démarrage.

Le ticket **KAN-33** met en place un dispositif de défense en profondeur à 6 barrières étanches rendant les personnalités non modifiables à chaud, vérifiables au boot, protégées par signature cryptographique et surveillées en continu.

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
  - **OUI (Vulnérabilité initiale confirmée)**.
  - Test initial sous `orso` avant KAN-33 : `touch /app/profiles/jerome/.test` renvoyait `ECRITURE-POSSIBLE`.

* **Constat 3 - Existe-t-il un rechargement de persona à chaud (hot reload) en cours de session ?**
  - **NON**. Le prompt système est mis en cache sur l'instance de l'agent (`agent._cached_system_prompt`) au premier tour de conversation (`agent/conversation_loop.py:687, 751`). Conformément à la Charte de Gouvernance, per-conversation prompt caching is sacred.

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

### R3 & R4 : Manifeste d'Intégrité, Signatures HMAC Obligatoires & Zero Fallback
- Manifeste `profiles/personas.lock.json` recensant le nom, la version, la date, l'empreinte SHA-256 et la signature HMAC-SHA256 de chaque agent.
- Module de vérification `scripts/security/persona_integrity.py` :
  - **Zero Fallback en dur** : La clé secrète doit être injectée exclusivement via la variable d'environnement `ORSO_PERSONA_HMAC_KEY`. Aucune constante par défaut n'est tolérée dans le code source. Si la clé est absente, l'exécution échoue immédiatement avec le code `PER-INTEGRITY-003`.
  - Exécuté au démarrage du conteneur dans `orso-entrypoint.sh` via `python3 scripts/security/persona_integrity.py verify --fail-fast`.
  - En cas d'incohérence : émission du code d'erreur `PER-INTEGRITY-001`, journalisation immédiate et arrêt du conteneur (code de sortie 1).

### Élimination de la faille de repli ambient inscriptible
- `docker/orso-entrypoint.sh` purge préventivement tout `SOUL.md` illégitime dans `/app/data/hermes_home`, `/app/data` ou `/home/orso/.hermes`.
- `hermes_cli/config.py` (`_ensure_default_soul_md`) neutralise l'auto-seeding du moteur upstream dans `HERMES_HOME` dès lors qu'un environnement Orso est actif.
- `scripts/security/persona_integrity.py` détecte de façon bloquante tout fichier `SOUL.md` présent dans les répertoires inscriptibles.

### R5 & R6 : Surveillance Continue à l'Exécution & Arrêt d'Urgence Infaillible
- Processus démon d'arrière-plan lancé au boot : `python3 scripts/security/persona_integrity.py monitor --interval 300 &`.
- Recalcul périodique de l'empreinte SHA-256 et du HMAC toutes les 5 minutes (300 secondes).
- En cas d'altération en direct :
  - Déclenchement de l'événement critique `PER-INTEGRITY-002`.
  - Écriture d'un drapeau d'urgence `/app/data/EMERGENCY_STOP_PER_INTEGRITY`.
  - Journalisation dans `telemetry/personas_integrity.log` et `telemetry_export.json`.
  - Arrêt d'urgence immédiat et forcé du conteneur via `os.kill(1, signal.SIGKILL)`, `kill -9 1` et `pkill -9 -f hermes` (surmonte l'absence de handler SIGTERM sur PID 1).

### R7 : Journal d'Intégrité Probant
- Écriture structurée dans :
  - `/app/data/telemetry/personas_integrity.log` (format audit textuel).
  - `/app/data/telemetry/personas_integrity.jsonl` (format JSON Lines).
  - Intégration directe dans l'agrégateur de télémétrie (`skills/telemetry.py`).

### R8 & R9 : Cloisonnement des Outils & Absence de Secrets
- Durcissement de `tools/file_tools_write_guards.py` (`_check_sensitive_path`) : tout appel à `write_file`, `patch` ou manipulation ciblant `profiles/`, `SOUL.md` ou `personas.lock.json` est hard-refusé.
- Aucun secret dans les 4 `SOUL.md` (validé par `check_no_secrets.py`).

---

## 4. Preuves Mécaniques des Critères d'Acceptation (CA1 à CA8)

### CA1 - Chemin de lecture documenté et pointant vers le montage lecture seule
- Code : `agent/system_prompt.py:493` et `agent/prompt_builder.py:1465`.
- Dans le conteneur, `HERMES_HOME/profiles` pointe vers `/app/profiles` monté avec le flag `:ro`.

### CA2 - Dossier monté en lecture seule (:ro) - Preuve Docker Inspect
```bash
$ docker inspect orso_financia_backend --format '{{json .Mounts}}'
```
**Sortie JSON brute vérifiable :**
```json
[
  {"Destination":"/app/config","Mode":"","Propagation":"rprivate","RW":true,"Source":"/Users/tquinzain/Documents/Dev Projects/orso-core/config","Type":"bind"},
  {"Destination":"/app/scripts","Mode":"ro","Propagation":"rprivate","RW":false,"Source":"/Users/tquinzain/Documents/Dev Projects/orso-core/scripts","Type":"bind"},
  {"Destination":"/app/skills","Mode":"ro","Propagation":"rprivate","RW":false,"Source":"/Users/tquinzain/Documents/Dev Projects/orso-core/skills","Type":"bind"},
  {"Destination":"/app/profiles","Mode":"ro","Propagation":"rprivate","RW":false,"Source":"/Users/tquinzain/Documents/Dev Projects/orso-core/profiles","Type":"bind"},
  {"Destination":"/app/data/hermes_home/profiles","Mode":"ro","Propagation":"rprivate","RW":false,"Source":"/Users/tquinzain/Documents/Dev Projects/orso-core/profiles","Type":"bind"},
  {"Destination":"/home/orso/.hermes/profiles","Mode":"ro","Propagation":"rprivate","RW":false,"Source":"/Users/tquinzain/Documents/Dev Projects/orso-core/profiles","Type":"bind"},
  {"Destination":"/app/templates","Mode":"ro","Propagation":"rprivate","RW":false,"Source":"/Users/tquinzain/Documents/Dev Projects/orso-core/templates","Type":"bind"},
  {"Destination":"/app/hermes_cli","Mode":"ro","Propagation":"rprivate","RW":false,"Source":"/Users/tquinzain/Documents/Dev Projects/orso-core/hermes_cli","Type":"bind"},
  {"Destination":"/app/apps/ui-client/dist","Mode":"ro","Propagation":"rprivate","RW":false,"Source":"/Users/tquinzain/Documents/Dev Projects/orso-core/apps/ui-client/dist","Type":"bind"},
  {"Destination":"/app/data","Mode":"","Propagation":"rprivate","RW":true,"Source":"/Users/tquinzain/Documents/Dev Projects/orso-core/data","Type":"bind"}
]
```
> Tous les points de montage vers `profiles` sont confirmés avec `"Mode":"ro"` et `"RW":false`.

### CA3 - Test d'écriture directe en conteneur sous l'utilisateur non-root orso
```bash
$ docker exec -u orso orso_financia_backend sh -c 'echo test >> /app/profiles/jerome/SOUL.md'
sh: 1: cannot create /app/profiles/jerome/SOUL.md: Read-only file system
$ echo $?
2
```
> Rejet strict et franc par le système de fichiers (Code retour : 2).

### CA4 / CA5 / R3 - Vérification d'intégrité et détection au boot
```bash
$ docker exec orso_financia_backend python3 /app/scripts/security/persona_integrity.py verify --fail-fast
[PER-INTEGRITY-000] Intégrité des 4 personas vérifiée avec succès (SHA-256 + HMAC-SHA256).
  ✓ clara (v1.0.0) : 8b08185b1f486bf0c34918fa8952796e72239878b2e851f432b7401bf19ba8f2
  ✓ jerome (v1.0.0) : 3028885bc107cf1f372d6e198e8fc4605fabfbbf155269a8ae670ac76ead803e
  ✓ lucas (v1.0.0) : 5a12dc6d5531b630ef6f7a67cb84622f966c405c40080f178ce4eb2fbfa39d90
  ✓ victor (v1.0.0) : d74deb79ab52681c5d740606be3f213b32747d5f5ae1cb986545cf12d2bc628f
```
En cas de modification volontaire ou d'absence de clé :
```bash
[PER-INTEGRITY-001] Échec de vérification d'intégrité des personas :
  - Clé secrète HMAC absente : variable ORSO_PERSONA_HMAC_KEY requise pour la vérification (R3 - Zero Fallback).
$ echo $?
1
```

### CA6 - Surveillance à l'exécution opérationnelle
- Test automatisé `test_ca6_runtime_surveillance_detects_alteration` :
  - Déclenchement de l'événement `PER-INTEGRITY-002`, journalisation et arrêt d'urgence immédiat.

### CA7 - Garde-fous outils modèles
- Test automatisé `test_ca7_file_tools_blocks_persona_and_profiles_write` :
  - 59/59 tests passés dans `tests/tools/test_file_write_safety.py`.

### CA8 - Intégration Télémétrique
- `skills/telemetry.py` consolide l'état de `persona_integrity` dans `telemetry_export.json`.

### CI GitHub Actions
- **Workflow** : `Security Persona Integrity CI (KAN-33)`
- **Run ID** : `36700799240` (Commit `3803ead699`)
- **Statut** : **`completed / success` (100% Vert)**
  - Tests unitaires et intégration intégrité : 10/10 passés.
  - Tests de garde-fous d'écriture : 59/59 passés.

---

## 5. Matrice des Fichiers Modifiés

| Fichier | Nature | Description |
|---|---|---|
| `.github/workflows/security_persona_integrity.yml` | Création | Workflow CI bloquant avec `astral-sh/setup-uv`, secret `ORSO_PERSONA_HMAC_KEY` |
| `profiles/personas.lock.json` | Création | Manifeste cryptographique SHA-256 + HMAC-SHA256 (R3, CA5) |
| `scripts/security/persona_integrity.py` | Création | Moteur cryptographique, zéro fallback HMAC, détection rogue file et arrêt d'urgence |
| `tests/security/test_persona_integrity.py` | Création | Suite de 10 tests automatisés validés à 100% |
| `docker/orso-entrypoint.sh` | Modification | Purge repli ambient, contrôle boot bloquant et moniteur d'arrière-plan |
| `Dockerfile.orso` | Modification | Permissions root:root 0555 et 0444 sur `/app/profiles` |
| `docker-compose.orso.yml` | Modification | Montages `./profiles:...:ro`, variable `ORSO_PERSONA_HMAC_KEY`, `no-new-privileges` |
| `hermes_cli/config.py` | Modification | Neutralisation de `_ensure_default_soul_md` en mode Orso |
| `tools/file_tools_write_guards.py` | Modification | Hard write refusal sur `profiles/`, `personas.lock.json` et `SOUL.md` |
| `skills/telemetry.py` | Modification | Export de `persona_integrity` même en l'absence de `state.db` |
| `docs/ADR/2026-09-30-03-personas-et-securite-des-prompts.md` | Création | Architecture Decision Record n°03 sous Git |
| `scripts/publish_kan33_atlassian.py` | Création | Outil d'alignement et de publication Atlassian |
| `docs/21_journal_realisations_orso.md` | Modification | Entrée KAN-33 consolidée |
