# Note d'Architecture KAN-83 : Historique des Conversations dans l'Interface Client

- **Date** : 07 octobre 2026
- **Auteur** : Antigravity (Architecte Technique)
- **Destinataires** : Thibaut (Lead / Arbitre), Jarvis (PO), Développeur d'implémentation
- **Ticket Jira** : [KAN-83](https://orso-agents.atlassian.net/browse/KAN-83)
- **Branche de travail** : `KAN-83-historique-conversations-client` (dérivée de `main` au commit `588f7ce4df`)
- **Gouvernance & Intégrité** : Respect absolu du Sanctuaire (`agent/turn_*.py`, `hermes_state*.py`, `run_agent.py`, `conversation_loop.py`). Toute logique d'exposition, de cloisonnement et de pilotage métier vit aux bords (Zone d'Évolution Orso).

---

## 1. Relevé Étape 0 : État Observé de la Branche au Démarrage

Conformément à l'Étape 0 du Mandat d'exécution v3, aucun code fonctionnel n'est produit avant ce relevé rigoureusement vérifié sur la branche principale d'exécution.

### 1.1 Empreinte Git & État de Référence
- **Commit HEAD `main`** : `588f7ce4df` (*Merge pull request #23 from tquinzain59/KAN-102-dette-onboarding-stripe-windows-footguns*).
- **Branche locale dédiée** : `KAN-83-historique-conversations-client`.
- **Validation préalable de non-régression (socle KAN-86)** :
  ```bash
  scripts/run_tests.sh tests/hermes_cli/test_client_ui_sessions_kan86.py
  ```
  **Résultat obtenu** : `1 files, 8 tests passed, 0 failed (100% complete) in 6.4s (20 workers)`. Le socle d'étanchéité multi-tenant est 100% intègre.

### 1.2 Cartographie des Fichiers et Lignes Vérifiés

| Composant | Fichier & Lignes réelles | Constat Observé | Écart avec l'hypothèse initiale du Mandat |
| :--- | :--- | :--- | :--- |
| **Registre SQLite des sessions client** | `hermes_cli/web_routers/client_ui.py`<br>Lignes **1829 à 1848** (`_init_client_sessions_db`) | Table `client_chat_sessions (session_id, tenant_id, user_id, agent_id, created_at, last_activity_at)` + index `idx_client_sessions_lookup` sur `(tenant_id, user_id, agent_id)`. | Aucun écart structurel. La table ne porte ni `title`, ni `title_source`, ni `dossier_metier_id`. |
| **Contrôle d'étanchéité & binding** | `hermes_cli/web_routers/client_ui.py`<br>Lignes **1850 à 1911** (`_verify_and_bind_client_session`) | Refus franc HTTP 400 sans `session_id`, HTTP 403 si tentative d'usurpation inter-tenants ou inter-utilisateurs, HTTP 400 si incohérence d'agent. Fail-closed SQLite (HTTP 500). | Aucun écart. |
| **Point d'entrée envoi chat** | `hermes_cli/web_routers/client_ui.py`<br>Lignes **2125 à 2159** (`POST /api/client/chat`) | Exige un `session_id` non vide, appelle le contrôle d'étanchéité puis stream via SSE. | Aucun écart. |
| **Point d'entrée lecture messages** | `hermes_cli/web_routers/client_ui.py`<br>Lignes **2162 à 2216** (`GET /api/client/chat/messages`) | Interroge le moteur via `sdb.get_messages_as_conversation(cleaned_sid)`. | **Écart critique constaté** : Appel sans `include_ancestors=True` ni `include_compacted=True`. Ne renvoie que `{role, content}` ; les horodatages (`timestamp`), les identifiants d'agents et le compteur formel de messages requis par CA2 ne sont pas exposés. |
| **Stockage & Session côté UI** | `apps/ui-client/src/pages/ChatView.tsx`<br>Lignes **18 à 34**, **57 à 85**, **165 à 174** | Clé unique `orso_session_${tenantSlug}_${userId}_${agentId}` écrasée à chaque appel de `handleResetChat`. | Confirme le diagnostic du PO : l'UI n'a aucune vue sur ses sessions passées et écrase le pointeur local dès qu'une nouvelle discussion débute. |
| **Brique moteur : Liste des sessions** | `hermes_state_sessions.py`<br>Lignes **1186 à 1290** (`list_sessions_rich`), **1384 à 1395** (`session_count`) | `list_sessions_rich` supporte le tri chronologique, le filtrage par source/date, l'agrégation de chaîne de compression (`project_compression_tips=True`). | Disponible et opérationnelle dans le moteur. |
| **Brique moteur : Titrage** | `hermes_state_titles.py`<br>Lignes **119 à 138** (`set_session_title`, `set_auto_title`) | `set_auto_title` protège contre l'écrasement des titres saisis manuellement (`title_source == 'user'`). | Disponible et opérationnelle dans le moteur. |
| **Brique moteur : Suppression** | `hermes_state_sessions.py`<br>Lignes **1463 à 1491** (`delete_session`), **1520 à 1550** (`delete_sessions`) | Suppression physique complète (session, messages, index FTS, fichiers de transcription). | Disponible et opérationnelle dans le moteur. |
| **Brique moteur : Maintenance & Purge** | `hermes_state_maintenance.py`<br>Lignes **243 à 264** (`archive_stale_sessions`), **266 à 296** (`prune_sessions`) | `prune_sessions` supprime les sessions inactives. | **Écart critique constaté** : `prune_sessions` exige structurellement `s.ended_at IS NOT NULL` et filtre par défaut les sessions épinglées (`COALESCE(s.pinned, 0) = 0`). Or, les sessions de chat client restent ouvertes (`ended_at IS NULL`). Un appel brut de `prune_sessions` ignorerait donc toutes les sessions clientes. |
| **Brique moteur : Reprise conversation** | `hermes_state_messages.py`<br>Lignes **893 à 940** (`get_messages_as_conversation`) | Supporte `include_ancestors` et `include_compacted`. | Mesuré en direct : la réactivation de ces deux drapeaux reconstitue fidèlement la chaîne de compression complète. |

---

## 2. Note d'Architecture Technique : Les 6 Points Fondamentaux

### Point 1 : Les Briques du Framework Employées
Le framework Hermes dispose déjà des fondations nécessaires à la gestion des sessions d'agent. Aucune brique concurrente ne sera réinventée :
1. **Magasin des messages et ascendance** : `SessionDB.get_messages_as_conversation(session_id, include_ancestors=True, include_compacted=True)` (`hermes_state_messages.py#L893`).
2. **Titrage et autorité** : `SessionDB.set_session_title` et `SessionDB.set_auto_title` (`hermes_state_titles.py#L119-L138`).
3. **Suppression unitaire et en bloc** : `SessionDB.delete_session(session_id)` (`hermes_state_sessions.py#L1463`).
4. **Maintenance et purge** : Mécanismes de suppression par transaction atomique de `SessionDB` (`hermes_state_maintenance.py#L277-L293`).
5. **Recherche plein texte** : Index FTS5 existant (`hermes_state_search.py`) réservé pour les évolutions futures.

### Point 2 : Forme Retenue pour le Module
- **Contrainte du dépôt** : `hermes_cli/web_routers/client_ui.py` atteint déjà **3 081 lignes**. La règle stricte de gouvernance (`AGENTS.md`) proscrit l'extension d'un god-file au-delà de 2 000 lignes et impose un découpage modulaire thématique en sous-modules `<stem>_<topic>.py`.
- **Décision** : Création d'un module dédié et spécialisé :
  `hermes_cli/web_routers/client_chat_history.py`
  Ce module expose le sous-routeur FastAPI `client_history_router` monté dans l'infrastructure web :
  - `GET /api/client/chat/sessions` : Liste paginée des conversations de l'utilisateur pour l'agent concerné (triées de la plus récente à la plus ancienne, bornées à 60 jours).
  - `GET /api/client/chat/sessions/{session_id}` : Métadonnées détaillées d'une session cliente (titre, agent, date de création, dernière activité, statut, dossier métier).
  - `PATCH /api/client/chat/sessions/{session_id}` : Renommage manuel du titre d'une session (`title_source='user'`), lien vers un dossier métier optionnel.
  - `DELETE /api/client/chat/sessions/{session_id}` : Suppression unitaire immédiate et définitive d'une session (suppression dans `client_chat_sessions` ET dans le magasin `state.db` du profil agent).
  - `POST /api/client/chat/sessions/purge` : Point de déclenchement ou de contrôle de la purge des conversations inactives depuis plus de 60 jours.

### Point 3 : Ce qui Change dans le Framework et Répartition par Fichier
- **Sanctuaire Inviolable (0 modification)** :
  - `hermes_state*.py`, `agent/turn_*.py`, `run_agent.py`, `tools/registry.py` ne subissent **aucune modification**.
  - Zéro dette d'alignement avec le dépôt amont (`upstream`).
- **Zone d'Évolution Orso (Fichiers modifiés / créés)** :
  1. `hermes_cli/web_routers/client_chat_history.py` *(nouveau)* : Implémentation du routeur d'historique, titrage automatique 6 mots, purge 60 jours, suppression croisée.
  2. `hermes_cli/web_routers/client_ui.py` :
     - Enrichissement de `_init_client_sessions_db` pour supporter les colonnes `title`, `title_source`, `dossier_metier_id` de manière idempotente.
     - Ajustement de `GET /api/client/chat/messages` pour activer `include_ancestors=True` et `include_compacted=True`, et renvoyer les timestamps et métadonnées conformes à CA2.
     - Montage du sous-routeur d'historique.
  3. `apps/ui-client/src/lib/api.ts` : Ajout des fonctions clientes d'historique (`listClientSessions`, `renameClientSession`, `deleteClientSession`, `getClientSessionMessages`).
  4. `apps/ui-client/src/pages/ChatView.tsx` : Intégration d'un volet latéral / tiroir d'historique des conversations, affichage de l'agent et de l'espace, mention explicite de la conservation 60 jours, sélection de session passée, renommage et suppression.

### Point 4 : Le Sort de la Chaîne de Compression
- **Mesures empiriques réalisées dans le banc de test** :
  - Un fil d'échange soumis à la compression Hermes crée une session enfant dont `parent_session_id` pointe sur l'ancienne session.
  - Sans `include_ancestors`, l'appel `get_messages_as_conversation(child_id)` omet les messages historiques antérieurs à la compression.
  - Avec `include_ancestors=True` et `include_compacted=True`, la méthode `_fetch_conversation_rows` remonte la généalogie complète (`_resume_lineage_ids`) et `_dedupe_display_generations` élimine les doublons de résumé compacté.
- **Règles arrêtées pour KAN-83** :
  1. **Unicité dans la liste (CA2)** : La liste cliente s'appuie sur `client_chat_sessions` qui enregistre l'identifiant racine de la conversation. Les éventuelles sessions enfants de compression technique ne sont pas des conversations distinctes et n'apparaissent jamais en double.
  2. **Restitution exhaustive** : Toute lecture d'un fil d'échange (`GET /api/client/chat/messages`) active `include_ancestors=True` et `include_compacted=True`.
  3. **Comptage réel** : Le compteur retourné reflète l'intégralité des messages visibles restitués à l'utilisateur.

### Point 5 : Le Mécanisme de Conservation (60 Jours Absolus) et sa Surveillance
- **Arbitrage de Thibaut (07/10/2026)** : Conservation stricte de **60 jours** basée sur la dernière activité (`last_activity_at`).
- **Suppression réelle vs Archivage** : La règle proscrit formellement l'archivage ou le simple masquage. Une conversation expirée est purgée de la base de registre `client_chat_sessions` ET supprimée du magasin `SessionDB` (`state.db`) via `sdb.delete_session(session_id)`.
- **Règle absolue sur l'épinglage** : Aucun mécanisme d'épinglage n'est exposé au client. Lors de la purge cliente des 60 jours, aucun contournement par flag `pinned` n'est toléré.
- **Fail-Closed & Refus Franc** :
  - Si une session dépasse 60 jours d'inactivité, toute tentative d'accès direct par son identifiant (`GET /api/client/chat/messages?session_id=...`) est immédiatement refusée avec **HTTP 410 Gone** (ou HTTP 404) avec le motif explicite : *"Cette conversation a expiré selon la politique de conservation de 60 jours."*
  - Le mécanisme de purge `purge_client_expired_sessions` consigne chaque exécution, le nombre de sessions purgées et trace toute anomalie. En cas d'erreur de purge, une exception visible est logguée (zéro échec silencieux).
- **Affichage UI (CA7)** : L'interface client mentionne explicitement dans le panneau d'historique : *"Historique conservé 60 jours"*.

### Point 6 : Portée Cliente et Évolution de `client_chat_sessions`
- **Schéma de données étendu** :
  ```sql
  ALTER TABLE client_chat_sessions ADD COLUMN title TEXT;
  ALTER TABLE client_chat_sessions ADD COLUMN title_source TEXT DEFAULT 'auto';
  ALTER TABLE client_chat_sessions ADD COLUMN dossier_metier_id TEXT;
  ```
  La fonction d'initialisation applique ces ajouts via inspection `PRAGMA table_info` pour une migration transparente et idempotente sans interruption de service.
- **Règle de titrage automatique (moteur borné à 6 mots)** :
  - Dès le premier échange utilisateur/agent, un titre synthétique de 6 mots maximum est généré à partir de l'intention exprimée.
  - Ce titre est enregistré avec `title_source = 'auto'`.
  - Si l'utilisateur renomme la discussion, le titre saisi remplace le titre automatique et passe en `title_source = 'user'`. Le moteur s'interdit d'écraser un titre utilisateur.
- **Cloisonnement strict (CA5)** :
  - Requête de liste : `SELECT session_id, tenant_id, user_id, agent_id, title, title_source, dossier_metier_id, created_at, last_activity_at FROM client_chat_sessions WHERE tenant_id = ? AND user_id = ? AND agent_id = ? AND last_activity_at >= ? ORDER BY last_activity_at DESC`.
  - Aucun utilisateur d'un autre espace client ni aucun autre utilisateur du même espace ne peut lister ou accéder aux conversations d'autrui.

---

## 3. Réponse Attendue au Handoff : Partage Navigateur vs Moteur

- **Autorité souveraine** : Le magasin du moteur (`SessionDB` dans `data/agents/{agent_id}/state.db`) et le registre SQLite d'étanchéité (`client_chat_sessions.db`) font **seuls et strictement foi**.
- **Rôle du stockage navigateur (`localStorage`)** :
  - Le navigateur ne conserve que des clés d'accélération d'affichage local (mise en cache éphémère du fil actif) et l'identifiant de la session en cours.
  - La suppression d'une conversation par l'utilisateur détruit les enregistrements dans `SessionDB` et `client_chat_sessions.db`, puis purge la clé locale `orso_messages_${sessionId}`.
  - En cas de divergence ou après rechargement/reconnexion sur un autre terminal, le fil est intégralement réhydraté depuis le magasin du serveur via `GET /api/client/chat/messages`.
