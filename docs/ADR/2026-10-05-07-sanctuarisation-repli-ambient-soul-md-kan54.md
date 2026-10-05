# ADR 2026-10-05-07 : Sanctuarisation du Chemin de Repli Ambient de SOUL.md dans le Moteur Hermès

- **Date** : 05 octobre 2026
- **Statut** : Accepté et Validé par le PO Thibaut (Option A : Garde-fou à la marge en Zone B - Ticket KAN-54)
- **Auteurs** : Thibaut (Lead / PO), Antigravity (Architecte Projet)
- **Référence Documents** : Charte de Gouvernance du Fork (Section Sanctuaire Zone A vs Zone B), Charte Globale Développeur (A1.1, A1.5, A1.7, P1.3, R1.1), ADR 2026-09-30-03 (Personas & Intégrité KAN-33).
- **Ticket Jira associé** : [KAN-54](https://orso-agents.atlassian.net/browse/KAN-54) (Dette technique : sanctuarisation du chemin de repli ambient de SOUL.md)

---

## 1. Contexte et Diagnostic Technique Vérifié

### 1.1 Mécanisme du repli ambient constaté
Dans le code de construction du prompt système hérité d'Hermès :
- `agent/system_prompt.py` (`_identity_parts`) appelle `_pb.load_soul_md(ctx_len, home_override=_agent_home(agent))`.
- La fonction `_agent_home(agent)` extrait le home de profil soit depuis la `ContextVar` `_HERMES_HOME_OVERRIDE`, soit depuis `agent._session_db.db_path`.
- Lorsqu'un fil d'exécution ou un appel ne dispose ni de l'un ni de l'autre (par exemple un worker sur thread détaché ayant perdu sa `ContextVar` ou une invocation sur l'agent par défaut), `_agent_home` retourne `None`.
- Dans `agent/prompt_builder.py` (`load_soul_md`) :
  ```python
  soul_path = (Path(home_override) if home_override is not None else get_hermes_home()) / "SOUL.md"
  ```
- Quand `home_override` est `None`, la résolution retombe silencieusement sur le chemin ambient : `<HERMES_HOME>/SOUL.md`.

### 1.2 Vulnérabilité en environnement de production Orso
En production conteneurisée :
- `HERMES_HOME` pointe vers `/app/data/hermes_home/`.
- Contrairement au répertoire `/app/profiles/` qui est scellé par permissions root `0444`, monté en lecture seule stricte (`:ro`) et vérifié par le manifeste cryptographique `personas.lock.json` (KAN-33), le répertoire `/app/data/` est un volume inscriptible (RW) nécessaire à la persistance d'Hermès (sessions, logs, cache).
- **Vecteur de risque (scénario CARBONATO)** : Si un fichier `SOUL.md` illégitime est créé ou injecté dans `/app/data/hermes_home/SOUL.md` (ou `~/.hermes/SOUL.md`), un appel d'inférence en repli ambient le chargera silencieusement à la place de la persona officielle vérifiée.

---

## 2. Alerte de Gouvernance : Règle de Vigilance Active sur le Sanctuaire

Conformément à la **Charte de Gouvernance du Fork Orso** (`docs/3_Technique/charte_gouvernance_fork.md`) et à l'article A1.5 de la Charte Globale :
- Le répertoire `agent/` (`agent/prompt_builder.py`, `agent/system_prompt.py`) fait partie intégrante du **Sanctuaire (Zone A)**.
- Toute altération directe du Sanctuaire pour un besoin spécifique à un déploiement métier est soumise à un mandat d'alerte immédiate :
  1. **Risque de divergence et de conflits Git amont** : Le dépôt `nousresearch/hermes-agent` est en évolution très rapide (plusieurs dizaines de commits par jour sur `agent/`). Une modification du moteur crée une dette de maintenance et des risques de régression à chaque rebasage.
  2. **Risque de régression du mode Standalone** : Dans un usage standard d'Hermès (CLI utilisateur individuel), le fichier de persona se trouve légitimement à la racine `~/.hermes/SOUL.md`. Casser ou interdire inconditionnellement ce chemin dans le cœur casse le comportement upstream nominal.
  3. **Invariance du Prompt Caching** : Toute modification dans `agent/prompt_builder.py` doit préserver rigoureusement le caractère byte-stable du prompt système pour ne pas dégrader le prompt caching fournisseur.

---

## 3. Analyse Comparative des Voies Techniques (CA1)

| Critère | Voie 1 : Garde-fou à la marge (Zone B - Recommandation Architecte) | Voie 2 : Amendement chirurgical du moteur (Zone A - Sanctuaire) | Voie 3 : Hybride (Garde-fou Zone B + PR Upstream) |
| :--- | :--- | :--- | :--- |
| **Principe** | Détection, alerte et refus proactif de tout `SOUL.md` hors `profiles/` via les briques de sécurité périphériques (`scripts/security/persona_integrity.py`, `tools/file_tools_write_guards.py`, `docker/orso-entrypoint.sh`). | Modification directe de `agent/prompt_builder.py` pour refuser tout repli ambient si une variable de durcissement (ex: `ORSO_STRICT_PROFILES=1`) est active. | Mise en place immédiate de la Voie 1 dans Orso + soumission d'une contribution propre sur `nousresearch/hermes-agent` pour conditionner le repli ambient. |
| **Atteinte au Sanctuaire** | **0 ligne modifiée** dans le Sanctuaire (Zone A intacte). | **Modification directe** de `agent/prompt_builder.py` (nécessite accord écrit formel A1.5). | **0 ligne modifiée** en local dans le Sanctuaire. |
| **Couverture temporelle** | Synchrone pour les outils d'écriture internes et le boot ; périodique (moniteur) pour les dépôts directs sur disque. | **Synchrone absolue** à la microseconde de l'inférence. | Synchrone sur boot et outils, puis synchrone native dès intégration upstream. |
| **Coût de maintenance rebase** | **Nul (0 %)** : aucun conflit Git lors des synchronisations avec Nous Research. | **Récurrent** : risque de conflit ou d'écrasement à chaque rebase de `prompt_builder.py`. | **Nul** à terme, standardisé. |
| **Effet de bord upstream** | **Aucun** : le moteur Hermès conserve son comportement universel. | **Risque de régression** si le repli n'est pas strictement conditionné. | Aucun. |

---

## 4. Recommandation de l'Architecte

L'Architecte recommande la **Voie 1 (Garde-fou à la marge en Zone B)** pour les raisons suivantes :
1. **Respect absolu du Sanctuaire** : Préservation totale de l'alignement upstream avec Nous Research sans accumuler de dette de patchs locaux.
2. **Durcissement multicouche** :
   - *Couche 1 (Écriture agent)* : Dans `tools/file_tools_write_guards.py`, blocage universel et catégorique de toute création/modification d'un fichier `SOUL.md` en dehors de `profiles/` (déjà protégé en lecture seule).
   - *Couche 2 (Démarrage)* : Dans `scripts/security/persona_integrity.py` (`verify`), scan exhaustif interdisant tout `SOUL.md` dans l'arborescence inscriptible (`/app/data/`, `HERMES_HOME`, etc.) avec échec Fail-Closed (`PER-INTEGRITY-004`).
   - *Couche 3 (Surveillance continue)* : Dans `persona_integrity.py` (`monitor`), détection de tout `SOUL.md` orphelin apparu en cours d'exécution et arrêt d'urgence immédiat du conteneur.
   - *Couche 4 (Boot)* : Maintien et durcissement de la purge dans `docker/orso-entrypoint.sh`.

Si Thibaut arbitre formellement pour la **Voie 2**, elle devra impérativement être implémentée sous forme d'une clause conditionnelle stricte :
```python
# Uniquement si ORSO_STRICT_PROFILES=1 est explicite dans l'environnement
if os.environ.get("ORSO_STRICT_PROFILES") == "1" and home_override is None:
    logger.warning("SOUL.md ambient fallback rejected under strict profile isolation")
    return None
```
afin de ne jamais altérer le fonctionnement standalone d'Hermès.

---

## 5. Limite Résiduelle Reconnue (CA6)

- **Pour la Voie 1 (Garde-fou à la marge)** : Si un acteur malveillant dispose d'un accès direct au système de fichiers de l'hôte (hors outils de l'agent) et dépose un `SOUL.md` dans `/app/data/hermes_home/`, il existe une fenêtre d'exposition maximale égale à la période de scrutation du moniteur d'intégrité (par exemple 60s ou 300s) pendant laquelle un appel sans `home_override` pourrait lire ce fichier avant que le moniteur ne déclenche l'arrêt d'urgence du conteneur.
- **Pour la Voie 2 (Amendement moteur)** : L'amendement local dans `agent/prompt_builder.py` est dépendant de la pérennité du patch lors des rebases upstream ; un rebase non vigilant (`git checkout --ours`) réintroduirait silencieusement la vulnérabilité.

---

## 6. Préservation des Acquis KAN-33 (CA5)

Le dispositif complet de KAN-33 demeure intact et vérifié :
- Manifeste cryptographique `profiles/personas.lock.json` (hashes SHA-256 et signatures HMAC-SHA256).
- Montage Docker `:ro` et permissions strictes `root:root` `0444` sur `/app/profiles`.
- Purge préventive au démarrage dans `docker/orso-entrypoint.sh`.
- Garde-fou d'écriture dans `tools/file_tools_write_guards.py`.
