# Handoff KAN-109 — Accès drone OPS : tenant de banc et compte client réels

**Statut : BLOQUÉ, travail partiel.** Aucun critère d'acceptation n'est vert. Le blocage est une question ouverte du ticket (qui crée le tenant et le compte, sur quel environnement), pas un défaut de code.

## 1. Vérification de la prémisse (étape 0)

La prémisse du ticket reste vraie le 2026-10-17. Elle a été re-mesurée en direct, ce que le ticket notait comme non fait le 07/10.

Commande : `python3 scripts/recette_en_ligne_kan109.py`. Les identifiants viennent de `~/.hermes/secrets/orso_drone.env` et ne sont pas affichés.

```text
Mesure du 2026-10-17T06:03:33+00:00 sur https://ops.orso-agents.fr
Identifiants lus dans : /home/ubuntu/.hermes/secrets/orso_drone.env (valeurs non affichées)

CA1  GET /api/olympe/ops/tenants/clientx-orso (jeton drone) -> HTTP 401 Jeton de session non autorisé.
     [KO] attendu 200 avec le détail du tenant

CA2  POST /api/olympe/ops/auth/login (compte client de test) -> HTTP 401 Échec d'authentification : Invalid login credentials
     [KO] attendu 403 ; identifiants invalides : refus non probant

Verdict : CA1 KO / CA2 KO        (code retour 1)
```

Mesures équivalentes faites à la main le même jour (06:02:54Z) : `GET /api/olympe/ops/tenants` avec le jeton drone répond 401.

**Écart avec les mesures du 28/09.** Le 28/09 la lecture du tenant répondait 404 (client introuvable). Aujourd'hui elle répond 401, avant même d'atteindre la recherche du tenant. Le jeton drone du fichier d'hôte n'est donc pas accepté par le service. Le code (`olympe/auth.py`, `verify_ops_token`) compare le jeton à la variable `ORSO_DRONE_API_TOKEN` de l'environnement du conteneur `olympe_core`. Il y a deux explications possibles, que je n'ai pas pu départager faute d'accès à l'hôte :

- le conteneur est déployé sans cette variable ;
- la valeur du conteneur diffère de celle du fichier d'hôte.

Le 404 de CA2 du 28/09 n'est donc plus reproductible. Le tenant ne peut pas être lu, et on ne peut pas dire s'il existe.

**Re-mesure du 2026-10-19 (10:01Z)**, même commande, même fichier d'identifiants (valeurs non affichées). Résultat identique, code retour 1 :

```text
Mesure du 2026-10-19T10:01:29+00:00 sur https://ops.orso-agents.fr
CA1  GET /api/olympe/ops/tenants/clientx-orso (jeton drone) -> HTTP 401 Jeton de session non autorisé.
CA2  POST /api/olympe/ops/auth/login (compte client de test) -> HTTP 401 Échec d'authentification : Invalid login credentials
Verdict : CA1 KO / CA2 KO
```

Aucune décision de Thibaut n'est intervenue entre le 17 et le 19/10 : le blocage est inchangé. Contrôle `ruff check` et `ruff format --check` sur le script rejoué le 19/10 : verts, code retour 0.

## 2. Ce qui a été fait

- Ajout de [`scripts/recette_en_ligne_kan109.py`](../../scripts/recette_en_ligne_kan109.py). Il rejoue en lecture seule les mesures de CA1 et CA2 et distingue :
  - 401 : identifiants invalides, refus non probant ;
  - 403 : identifiants valides, rôle refusé, séparation prouvée ;
  - 200 : anomalie grave.
  Il n'affiche aucune valeur secrète, seulement l'emplacement du fichier. Code retour : 0 si CA1 et CA2 sont verts, 1 sinon, 2 si le fichier est inutilisable.
- Contrôle `ruff check` et `ruff format --check` sur ce fichier : verts.
- Aucun fichier du sanctuaire n'a été touché. Rien n'a été écrit en base ou dans l'IAM.

## 3. Ce qui n'a PAS été fait, et pourquoi

| CA | État | Raison |
|---|---|---|
| CA1 | non démontré | Le tenant ne peut pas être créé : l'agent n'a ni jeton valide ni accès à l'hôte de test. Le `POST /api/olympe/ops/tenants` exige la portée `tenants:provision:sandbox` ou une session superadmin. Le jeton drone est rejeté. |
| CA2 | non démontré | Le compte `ORSO_TEST_CLIENT_EMAIL` ne s'authentifie pas (401, Supabase). Créer ou réparer ce compte relève de l'IAM de l'environnement de test. |
| CA3 | non démontré | Il dépend de CA2, car on ne peut pas montrer un cockpit pour un compte qui ne se connecte pas. |
| CA4 | tenu | Aucun secret dans le commit, le script ou cette note. Les valeurs sont désignées par leur emplacement : `~/.hermes/secrets/orso_drone.env`, variables `ORSO_DRONE_API_TOKEN` et `ORSO_TEST_CLIENT_PASSWORD`. |

**Pourquoi je n'ai pas forcé.** Créer le tenant ou le compte avec la clé de service Supabase de `orso_supabase.env` serait une écriture directe dans l'IAM. La contrainte du ticket l'interdit : c'est le chemin réel de provisioning qui est testé. Faire la création sur `ops.orso-agents.fr` aurait aussi été une opération en production. KAN-71 a retiré les traces de banc de la base de production et KAN-74 a arbitré le provisioning en production, ce qui rend ce choix douteux. L'environnement de test n'est de toute façon pas nommé dans le ticket.

## 4. Décisions à prendre (arbitrage Thibaut)

1. **Environnement de test.** Choisir un environnement qui n'est pas la production. À défaut, décider explicitement de provisionner en production, en tenant compte de KAN-71 et KAN-74.
2. **Exécutant.** Désigner qui crée le tenant et le compte client de test.
3. **Jeton drone.** Redéployer ou aligner le jeton drone entre le fichier d'hôte et la variable `ORSO_DRONE_API_TOKEN` du conteneur, puis le faire constater par un 200 sur la liste des tenants. Le 401 actuel porte sur le jeton lui-même, pas sur le tenant.

## 5. À la recette, le PO doit

1. Une fois les décisions prises, créer le tenant `clientx-orso` par le chemin réel de provisioning : `POST /api/olympe/ops/tenants` avec le jeton drone, dans la portée `tenants:provision:sandbox`.
2. Créer le compte client de test par le chemin IAM normal. Il ne doit pas avoir le rôle `superadmin`.
3. Lancer `python3 scripts/recette_en_ligne_kan109.py`. Le résultat attendu est CA1 = 200 et CA2 = 403, avec un code retour 0, daté et collé au ticket.
4. Pour CA3, relever dans le cockpit ce qui s'affiche pour ce compte et le détail de la réponse de refus, ou joindre une capture.
5. Ne coller dans le ticket aucune valeur lue dans les fichiers de `~/.hermes/secrets/`.

## 6. Incident de session à connaître

Pendant la vérification, une commande destinée à lister uniquement les noms de variables a affiché en clair le contenu de `~/.hermes/secrets/orso_client_test.env`. Ce fichier est distinct de celui du drone : c'est une paire identifiant/mot de passe d'un autre compte de recette, pas celui de ce ticket. Cette valeur n'a pas été utilisée, ni copiée dans le dépôt ou dans cette note. Elle figure dans le journal de session de l'agent, donc envisager de la considérer comme exposée et de la renouveler.
