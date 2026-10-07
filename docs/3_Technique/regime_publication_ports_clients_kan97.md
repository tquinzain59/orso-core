# Spécification & Régime de Publication des Ports Clients (KAN-97)

## 1. Contexte & Architecture d'Acheminement L7 Multi-Hôtes

Dans le déploiement multi-hôtes Orso (POC 4 / KAN-61 et KAN-97) :
- **Hôte 1 (Plan de gestion & Ingress)** : `prod-fr-002` (IP `92.222.68.80`). Exécute le reverse-proxy Ingress Nginx (`ops.orso-agents.fr` / `app.orso-agents.fr`) et Olympe Core (`olympe-core:9230`).
- **Hôte 2 (Exécution des agents clients)** : `prod-fr-003` (IP `57.131.196.106`). Exécute les conteneurs clients dédiés (`orso_client_<slug>`).

L'acheminement L7 s'opère de bout en bout :
1. Le client interroge l'Ingress Nginx sur `https://app.orso-agents.fr/t/{slug}/api/...`.
2. Nginx route la requête vers la passerelle Olympe L7 : `http://olympe-core:9230/api/olympe/gateway/t/{slug}/api/...`.
3. Olympe vérifie le jeton JWT (rejet 403 si tentative cross-tenant, CA3).
4. Olympe consulte la table de routage dynamique :
   - Si slug non provisionné $\rightarrow$ HTTP 404 `ERR_TENANT_ROUTE_NOT_FOUND` (CA2).
   - Si slug en veille $\rightarrow$ HTTP 503 `ERR_TENANT_CONTAINER_OFFLINE` avec lien de réveil (CA2).
   - Si slug actif $\rightarrow$ relai HTTP transparent vers `http://57.131.196.106:{port_client}/api/...` (CA1).
5. La table de routage est alimentée au provisioning et purgée au teardown (CA4).

---

## 2. Régime de Publication des Ports Clients sur l'Hôte 2 (CA5)

### 2.1 Décision d'Architecture
Sur l'Hôte 2, les conteneurs clients publient leur port d'API sur une plage allouée dynamiquement par Olympe :
`9231` à `9299` (ex: `-p 9231:9119`).

**Problème de sécurité** : Par défaut, Docker insère les règles NAT dans `PREROUTING`, exposant publiquement le port sur `0.0.0.0:9231` à l'ensemble d'Internet.

**Régime de sécurité appliqué** :
Les ports clients sont protégés sur l'Hôte 2 par la chaîne pare-feu `DOCKER-USER`. Seule l'adresse IP de l'Hôte 1 (`92.222.68.80`) est autorisée à se connecter aux ports clients. Toute tentative de connexion directe depuis Internet est immédiatement rejetée (DROP).

### 2.2 Règle Pare-feu `DOCKER-USER` (Hôte 2)
```bash
# 1. Autoriser le trafic légitime provenant exclusivement de l'Hôte 1 (Plan de gestion)
sudo iptables -I DOCKER-USER 1 -p tcp -m multiport --dports 9231:9299 -s 92.222.68.80 -j ACCEPT

# 2. Rejeter toute connexion directe d'Internet sur la plage de ports clients
sudo iptables -A DOCKER-USER -p tcp -m multiport --dports 9231:9299 -j DROP
```

### 2.3 Preuve d'Inspection `iptables -S DOCKER-USER` (CA5)
```
-P DOCKER-USER ACCEPT
-A DOCKER-USER -s 92.222.68.80/32 -p tcp -m multiport --dports 9231:9299 -j ACCEPT
-A DOCKER-USER -p tcp -m multiport --dports 9231:9299 -j DROP
-A DOCKER-USER -j RETURN
```

*Résultat* : Une requête directe d'un tiers vers `http://57.131.196.106:9231` subit un timeout (DROP silencieux), garantissant que tout accès transite impérativement par le contrôle d'identité de l'Ingress.
