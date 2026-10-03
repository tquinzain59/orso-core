# Spécification Technique KAN-86 : Préservation du Contexte Conversationnel et Étanchéité des Sessions UI Client

- **Date** : 03 octobre 2026
- **Auteurs** : Antigravity (Architecte Projet), Thibaut (Lead / PO)
- **Ticket Jira** : [KAN-86](https://orso-agents.atlassian.net/browse/KAN-86)
- **Branche** : `KAN-86-ui-client-session-contexte`
- **Charte de Gouvernance** : Respect strict du Sanctuaire (0 altération de la boucle d'inférence, de la persistance `hermes_state*.py`, du cache de prompt ou du registre des outils).

---

## 1. Contexte & Problématique (Constat du 03/10/2026)

Lors d'un test utilisateur de l'interface client Orso dans l'espace **Financia Solutions** avec l'agent **Jérôme** (utilisateur Sophie Martin) :
1. **À 13h42** : L'utilisateur demande des informations sur l'entreprise *Giallo*. Jérôme répond en listant 4 sociétés Giallo distinctes (Sainghin-en-Mélantois 59, Sault-de-Navailles 64, Kremlin-Bicêtre 94, Meudon 92) et demande laquelle l'intéresse.
2. **À 13h53** : Moins de 15 minutes plus tard, l'utilisateur demande à Jérôme de retrouver cet échange. Jérôme répond : *"Je viens de fouiller tout l'historique, et je ne retrouve la trace d'aucune demande sur une société avant notre conversation du 29 septembre. Il semble que cette session ait été la première..."*

### Cause racine identifiée : Deux replis silencieux superposés
1. **Absence d'identifiant côté UI** : `apps/ui-client/src/pages/ChatView.tsx` appelait `sendUserPrompt(activeAgentId, prompt, onDelta)` sans fournir de 4ème paramètre `sessionId`.
2. **Génération éphémère côté client** : Faute d'identifiant, `apps/ui-client/src/lib/api.ts` générait `session_id: sessionId || \`client-session-${Date.now()}\``. Deux messages consécutifs ne pouvaient donc jamais partager le même identifiant.
3. **Génération éphémère côté serveur** : Le point d'entrée FastAPI `hermes_cli/web_routers/client_ui.py` appliquait un second repli : `sid = req.session_id or f"session-{int(time.time())}-{uuid.uuid4().hex[:6]}"`.

Les messages n'échouaient jamais, mais chaque tour ouvrait une session neuve sans mémoire.

---

## 2. Architecture de la Solution

La correction s'effectue strictement aux bords :
1. **Côté UI Client (`apps/ui-client/src/pages/ChatView.tsx`)** :
   - Un identifiant de session pérenne est conservé dans le stockage local du navigateur (`localStorage`), partitionné par tenant, utilisateur et agent : `orso_session_${tenantSlug}_${userId}_${agentId}`.
   - Les messages de la conversation active sont indexés par `sessionId` (`orso_messages_${sessionId}`).
   - La session survit intégralement au rechargement de page (F5 / Cmd+R).
   - Le bouton **"Nouvelle discussion"** est le **seul** événement qui génère un nouvel identifiant de session, sans détruire la session antérieure dans le moteur.
2. **Côté Client API (`apps/ui-client/src/lib/api.ts`)** :
   - Suppression totale du repli silencieux `Date.now()`.
   - `sendUserPrompt` exige un `sessionId` non vide et lève une exception immédiate s'il est manquant.
   - Ajout de la fonction `getSessionMessages(agentId, sessionId)` interrogeant le moteur.
3. **Côté Routeur Backend (`hermes_cli/web_routers/client_ui.py`)** :
   - `req.session_id` est **obligatoire**. Une requête sans session est rejetée avec **HTTP 400 Bad Request** (`detail: "Identifiant de session manquant ou invalide. Une session valide est requise."`).
   - Aucun identifiant de session n'est jamais fabriqué sur le serveur.
   - **Registre d'étanchéité multi-tenant et inter-utilisateurs (`client_chat_sessions.db`)** :
     - Table `client_chat_sessions` enregistrant `(session_id, tenant_id, user_id, agent_id, created_at, last_activity_at)`.
     - **Comportement Fail-Closed** : Toute anomalie ou indisponibilité du registre SQLite lève immédiatement une exception HTTP 500 (`detail: "Erreur interne de contrôle de session : Registre d'étanchéité indisponible."`) bloquant toute fuite potentielle.
     - Rejet **HTTP 403 Forbidden** si un utilisateur d'un autre tenant ou un autre utilisateur du même tenant tente d'utiliser une session existante.
     - Rejet **HTTP 400 Bad Request** en cas d'incohérence d'agent (ex: session créée pour Jérôme soumise à Lucas).
   - Persistance automatique des tours de dialogue dans le magasin `SessionDB` (`state.db`) sous `session_id`, garantissant la réhydratation du contexte au tour suivant.
   - Nouvel endpoint `@router.get("/api/client/chat/messages")` permettant d'inspecter l'historique d'une session depuis le magasin du moteur.

---

## 3. Matrice des Critères d'Acceptation (CA1 à CA8) + Sécurité Fail-Closed

| Critère | Description | Preuve / Validation |
| :--- | :--- | :--- |
| **CA1** | Continuité contextuelle au fil des tours dans une même session | Validé dans `test_ca1_and_ca2_conversation_continuity_and_persistence` : le 2ème tour intègre le contexte du 1er tour sans répétition via le moteur réel `AIAgent`. |
| **CA2** | Messages d'une même session portant le même identifiant côté moteur | Validé dans `test_ca1_and_ca2_conversation_continuity_and_persistence` : lecture de 4 messages dans `SessionDB` sous le même `session_id`. |
| **CA3** | Persistance après rechargement de page | Validé dans `test_ca3_page_reload_persistence_and_resume` : rejeu après rechargement avec le même `session_id` préservé. |
| **CA4** | "Nouvelle discussion" crée une session neuve et préserve l'ancienne | Validé dans `test_ca4_new_discussion_mints_different_session_preserving_previous` : 2 sessions distinctes dans `SessionDB`, antécédent intact. |
| **CA5** | Étanchéité inter-agents (Jérôme vs Lucas) | Validé dans `test_ca5_agent_isolation_no_shared_session` : rejet HTTP 400 Incohérence d'agent si Lucas tente d'utiliser la session de Jérôme. |
| **CA6** | Rejet explicite sans session valide (0 repli silencieux serveur) | Validé dans `test_ca6_rejection_without_valid_session` : rejet HTTP 400 immédiat si `session_id` est absent ou vide. |
| **CA7** | Étanchéité multi-comptes et multi-tenants | Validé dans `test_ca7_multi_user_and_multi_tenant_isolation` : rejet HTTP 403 Forbidden sur toute tentative de reprise illégitime. |
| **CA8** | Rejeu du scénario exact du constat (Giallo 13h42 -> 13h53) | Validé dans `test_ca8_exact_reported_scenario_giallo_15min_recall` : rappel des 4 entités sans message d'oubli via moteur `AIAgent`. |
| **Fail-Closed** | Registre d'étanchéité défaillant bloque hermétiquement (HTTP 500) | Validé dans `test_fail_closed_on_session_db_error` : blocage immédiat en écriture (POST) et en lecture (GET) en cas d'erreur SQLite. |

---

## 4. Publication & Références

- **Page Confluence** : [Spécification Technique KAN-86 (Espace Orsoagents)](https://orso-agents.atlassian.net/wiki/spaces/Orsoagents/pages/7471234)
- **Suite de tests automatisés** : `tests/hermes_cli/test_client_ui_sessions_kan86.py` (8/8 tests réussis en 6.9s).
