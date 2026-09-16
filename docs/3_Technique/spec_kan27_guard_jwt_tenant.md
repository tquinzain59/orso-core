# Spécification Technique d'Architecture : Guard d'Authentification JWT & Isolation Tenant sur orso-core (/api/client)

> **Ticket Jira associé** : [KAN-27](https://orso-agents.atlassian.net/browse/KAN-27)  
> **Composants** : `Orso Core`  
> **Statut** : En cours (Instruction d'Architecture)  
> **Auteur / Responsable d'instruction** : Antigravity (Architecte Projet)  
> **Validation Métier** : Thibaut QUINZAIN (Direction Orso Agents)  
> **Date** : 16 Septembre 2026  

---

## 1. Contexte & Risque de Sécurité Actuel

Pour permettre les tests initiaux et la liaison rapide de l'UI Client (`apps/ui-client`), le backend unifié `orso-core` contenait une brèche d'authentification :
* Dans `hermes_cli/dashboard_auth/middleware.py`, le préfixe `/api/client/` a été ajouté à `_GATE_PUBLIC_PREFIXES`.
* Dans `hermes_cli/web_server.py`, la condition `and not path.startswith("/api/client/")` court-circuitait le contrôle d'accès.
* N'importe quel client ou script connaissant l'adresse IP et le port du backend pouvait invoquer Jérôme (`/api/client/chat`) ou valider des actions de relance (`/api/client/actions/execute`).

Le ticket **KAN-27** a pour mission de refermer ce bypass et de verrouiller le backend avec un **Guard cryptographique en mémoire** vérifiant que la requête appartient bien au client propriétaire de cette instance.

---

## 2. Analyse et Garanties de Performance

> [!NOTE]
> **Pourquoi cette architecture garantit une latence imperceptible (< 0.1 ms) :**

1. **Vérification 100 % en mémoire (Zéro appel base de données / Zero I/O)** :
   * Contrairement aux architectures de session traditionnelles qui interrogent une base SQL ou Redis à chaque requête HTTP, le décodage d'un jeton JWT se fait **intégralement dans le CPU du conteneur**.
   * La validation cryptographique d'une signature HMAC (HS256) ou RSA (RS256) prend environ **40 à 70 microsecondes** (0,07 ms).
   * La clé publique Supabase (JWKS) est mise en cache localement au démarrage : aucune requête réseau externe n'est émise vers Supabase lors d'un message utilisateur.

2. **Préservation absolue du débit de streaming SSE** :
   * Sur le point d'entrée de chat (`POST /api/client/chat`), la vérification JWT intervient **une seule fois**, lors de l'établissement de la poignée de main HTTP (handshake).
   * Dès que le token est validé, le flux de streaming SSE est ouvert et les morceaux de texte générés par le LLM (tokens de réponse de Jérôme) sont émis en temps réel **sans aucune ré-évaluation de sécurité**, assurant une fluidité textuelle maximale.

3. **Invariance du Prompt Caching (Zone A)** :
   * L'authentification et l'injection du contexte client s'effectuent sur la couche transport HTTP (FastAPI / Zone B).
   * Le prompt système de l'agent et l'historique conversationnel restent **strictement invariants** en mémoire d'inférence, préservant 100 % des bénéfices du prompt caching de Nous Research.

---

## 3. Spécification Fonctionnelle & Algorithmique du Guard

```
               Requête HTTP entrante (ex: POST /api/client/chat)
                                       │
                                       ▼
                     Extraction du Jeton Bearer
                     (Header Authorization ou Cookie)
                                       │
                         [Jeton présent ?]
                            /          \
                         NON            OUI
                          │              │
                          ▼              ▼
                     HTTP 401     Vérification Signature
                   Unauthorized   (Clé secrète / JWKS en cache)
                                         │
                                [Signature Valide ?]
                                   /          \
                                NON            OUI
                                 │              │
                                 ▼              ▼
                            HTTP 401     Contrôle Tenant :
                          Unauthorized   Token.tenant_id == ORSO_CLIENT_ID ?
                                                /          \
                                             NON            OUI
                                              │              │
                                              ▼              ▼
                                         HTTP 403       Autorisé (200 / SSE)
                                         Forbidden      Exécution de l'Agent
```

### 3.1 Dépendance FastAPI (`verify_client_token`)
Une dépendance dédiée est ajoutée au routeur `hermes_cli/web_routers/client_ui.py` :

```python
async def verify_client_token(request: Request) -> Dict[str, Any]:
    """Valide le jeton JWT Supabase Auth et s'assure qu'il correspond
    au client assigné à ce conteneur (ORSO_CLIENT_ID).
    """
    # Mode développement local explicite
    if os.environ.get("ORSO_AUTH_DISABLED") == "1":
        return {"tenant_id": "dev", "user_id": "dev", "role": "admin"}

    # 1. Extraction du token
    token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
    elif "sb-access-token" in request.cookies:
        token = request.cookies["sb-access-token"]

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Authentification requise : Jeton d'accès manquant."
        )

    # 2. Vérification cryptographique en mémoire
    try:
        payload = decode_jwt_token(token)
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expirée, veuillez vous reconnecter.")
    except JWTError:
        raise HTTPException(status_code=401, detail="Jeton d'authentification invalide.")

    # 3. Contrôle d'isolation Tenant
    expected_client_id = os.environ.get("ORSO_CLIENT_ID")
    if expected_client_id:
        token_tenant = payload.get("tenant", {}).get("tenant_id")
        if token_tenant != expected_client_id:
            _log.warning(
                "Tentative d'accès cross-tenant bloquée : token=%s vs container=%s",
                token_tenant, expected_client_id
            )
            raise HTTPException(
                status_code=403,
                detail="Accès refusé : Vos identifiants ne sont pas autorisés sur cette instance."
            )

    # 4. Injection dans l'état de la requête
    request.state.tenant = payload.get("tenant", {})
    request.state.user_id = payload.get("sub")
    return payload
```

---

## 4. Retrait du Bypass et Nettoyage des Middleware

Dans `hermes_cli/dashboard_auth/middleware.py` :
- **Suppression** de `"/api/client/"` dans `_GATE_PUBLIC_PREFIXES`.
- **Maintien** de `"/client"` dans `_GATE_PUBLIC_PREFIXES` : cette route sert uniquement les fichiers statiques de l'application (HTML/JS/CSS de `apps/ui-client/dist`). Le front-end doit pouvoir se charger dans le navigateur avant que l'utilisateur ne transmette son jeton d'accès sur l'API.

Dans `hermes_cli/web_server.py` :
- **Suppression** de l'exemption `and not path.startswith("/api/client/")`.

---

## 5. Critères d'Acceptation & Definition of Done (DoD)

- [ ] **CA 1** : L'appel à `POST /api/client/chat` sans header Authorization renvoie un code HTTP **401 Unauthorized**.
- [ ] **CA 2** : L'appel à `POST /api/client/actions/execute` avec un jeton corrompu ou expiré renvoie un code HTTP **401 Unauthorized**.
- [ ] **CA 3** : Un appel avec un jeton valide mais dont le `tenant_id` diffère de `ORSO_CLIENT_ID` renvoie un code HTTP **403 Forbidden**.
- [ ] **CA 4** : Un appel avec le jeton valide correspondant au client du conteneur ouvre immédiatement le stream SSE sans surcoût de latence (> 5 ms).
- [ ] **CA 5** : Tous les tests unitaires et de non-régression exécutés via `scripts/run_tests.sh` sont verts.
