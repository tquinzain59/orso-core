# Charte de Gouvernance et Règles d'Or Architecturales — Orso agents

Ce document fixe les principes directeurs, les frontières d'isolation et les règles d'or régissant le développement du dépôt `orso-core`, issu du fork de `hermes-agent` (Nous Research).

---

## 1. Contexte et Objectif du Fork

Le projet **Orso agents** ([www.orso-agents.fr](http://www.orso-agents.fr)) s'est approprié le moteur d'agents autonome *Hermes-agent* (licence MIT) afin de fournir aux TPE et PME françaises une suite d'agents métier intelligents (Jérôme - Trésorerie, Lucas - Commercial, Clara - Support, Victor - Marchés publics).

L'objectif de ce fork est de bénéficier de la puissance, de la résilience et des optimisations de la boucle d'agent tout en construisant notre valeur ajoutée propriétaire (profils métiers, connecteurs ERP, applications mobiles/PWA, supervision télémétrique).

---

## 2. Les Deux Zones Inviolables de l'Architecture

### 🛡️ Zone A : Le "Sanctuaire" (Moteur Immuable — Ne Pas Altérer)

Les composants du Sanctuaire constituent la colonne vertébrale du moteur. **Aucune logique métier spécifique à Orso ne doit y être codée en dur.**

1. **La Boucle d'Inférence et d'Exécution (`agent/turn_*.py`, `run_agent.py`, `conversation_loop.py`)** :
   - Ordonnancement des phases de réflexion, détection d'appels d'outils, alternance stricte des rôles (`user` / `assistant` / `tool`).
   - Algorithmes de compression de contexte et gestion des erreurs de boucle.
2. **L'Invariance du Prompt Caching** :
   - Le préfixe du prompt système et des outils ne doit jamais être muté en cours de conversation.
   - Tout rechargement dynamique mid-session brise le cache fournisseur (Anthropic, DeepSeek, OpenAI) et multiplie par 5 à 10 les coûts LLM.
3. **Le Moteur de Persistance SQLite (`hermes_state*.py`)** :
   - Gestion des sessions, écriture WAL, indexation FTS5 des messages, tables d'usage de tokens.
   - On utilise l'API de `hermes_state.py` telle quelle, sans modifier les schémas fondamentaux.
4. **Le Registre d'Outils et Connecteurs LLM (`tools/registry.py`, `model_tools.py`, `providers/`)** :
   - Système d'enregistrement déclaratif d'outils et adaptateurs de modèles.
5. **Maintenabilité Upstream (`git remote upstream`)** :
   - Le socle doit rester propre pour permettre le rebase et l'intégration continue des correctifs de bugs et des patchs de sécurité de Nous Research sans conflits.

---

### 🚀 Zone B : La "Zone d'Évolution" (Valeur Ajoutée Orso agents)

Toutes les évolutions, personnalisations et fonctionnalités Orso doivent être confinées dans cette zone :

1. **Applications Clientes & UI (`App_Hermes Core`)** :
   - Interface PWA mobile et desktop, discussion instantanée, streaming mot à mot.
   - **Cartes d'Actions Interactives (1-clic)** : Propositions structurées de l'agent validées ou décalées par le dirigeant.
   - Notifications push (alertes créances, défaillances BODACC, opportunités BOAMP).
2. **Passerelles & API (`hermes_cli/web_routers/`, `tui_gateway/`, `gateway/`)** :
   - Nouveaux endpoints REST FastAPI et canaux WebSocket pour servir l'application PWA et le portail de supervision (`Site_Hermes-core`).
3. **Profils Métiers Dédiés (`profiles/`)** :
   - Personnalité, prompt système et garde-fous de chaque agent définis via `profiles/<agent>/SOUL.md` et `profile.yaml`.
   - Flotte multi-agents : **Jérôme** (Credit Management), **Lucas** (Commercial/SDR), **Clara** (SAV/Support), **Victor** (Appels d'offres).
4. **Compétences Métiers & Connecteurs (`skills/` et `plugins/`)** :
   - Connecteurs comptables & ERP : Pennylane, Sellsy, Cegid, Odoo, Sage (`skills/credit_management/`).
   - Open Data & Scoring légal : Pappers API (`fiche_credit.py`), BODACC (`veille_bodacc.py`), Sirene.
   - Télémétrie et suivi des coûts : `skills/telemetry.py` alimentant `monitoring.html`.
5. **Conteneurisation et Déploiement (`Dockerfile.orso`, `docker-compose.orso.yml`)** :
   - Orchestration Docker, variables d'environnement pour les secrets, isolation des volumes.

---

## 3. Règle d'Or : "Élargir par les Bords, Préserver la Taille Étroite"

Pour toute nouvelle fonctionnalité, privilégier strictement cet ordre de priorité (*Footprint Ladder*) :
1. **Configuration ou prompt de profil** (`profiles/<agent>/SOUL.md`, `config.yaml`).
2. **Skill / Script modulaire** dans `skills/<domaine>/`.
3. **Outil enregistré via `@register_tool`** dans `tools/` avec `check_fn` ou toolset nommé.
4. **Routeur d'API dédié** dans `hermes_cli/web_routers/`.
5. **Plugin modulaire** dans `plugins/`.
6. ⛔ **JAMAIS** de modification directe du cœur d'agent (`run_agent.py`, `turn_*.py`) pour une règle métier.

---

## 4. Mandat de Sentinelle pour l'Assistant IA (Règle Active)

L'assistant IA agissant sur ce projet a pour consigne permanente d'exercer un rôle de **gardien actif de cette charte** :

* Si une demande ou consigne utilisateur implique directement ou indirectement :
  - La modification d'un fichier du **Sanctuaire** pour un besoin métier,
  - La rupture ou mutation dynamique du prompt en cours de session (invalidation de cache),
  - Le codage en dur d'identités d'agents ou de règles dans le moteur généraliste,
  - Une atteinte à la synchronisation avec le dépôt `upstream`,
* **L'assistant IA DOIT OBLIGATOIREMENT** :
  1. Émettre une **alerte explicite** avant toute action.
  2. Expliquer le risque technique (surcoût tokens, instabilité, conflits amont).
  3. Proposer l'alternative propre conforme à la Zone d'Évolution (via profil, skill, plugin ou routeur API).
