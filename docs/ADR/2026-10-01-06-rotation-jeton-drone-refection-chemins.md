# ADR 2026-10-01-06 : Rotation du Jeton Machine Drone, Durcissement des Profils et Refection du Chemin de Lecture des Sondes (KAN-75)

- **Statut** : Accepté et Appliqué en Production
- **Date** : 01/10/2026
- **Auteurs** : Antigravity (Architecte-Développeur) & Thibaut QUINZAIN (Direction Orso Agents)
- **Destinataire** : Jarvis (Product Owner)
- **Tickets Jira** : [KAN-75](https://orso-agents.atlassian.net/browse/KAN-75), rattaché à l'incident [KAN-38](https://orso-agents.atlassian.net/browse/KAN-38)

---

## 1. Contexte & Déclaration d'Incident

Lors d'un audit de conformité sur KAN-38 le 01/10/2026, une connexion SSH vers l'hôte du plan de gestion (`PROD-FR-002`, `92.222.68.80`) avec la clé d'agent a déclenché l'exécution d'une commande forcée (`command="cat ~/.hermes/secrets/orso_drone.env"` dans `~/.ssh/authorized_keys`). Cette commande a affiché l'intégralité du fichier de secrets dans la trace de session du PO.

Les constats établis ont mis en lumière trois failles de conception :
1. **Commande forcée inadaptée** : La clé d'agent `jarvis-runner-orso-drone` servait le fichier de secrets en clair à la connexion.
2. **Pollution globale de l'environnement des shells** : Les profils de connexion (`~/.bashrc` et `~/.profile`) sur les hôtes exportaient le contenu de `orso_drone.env` via `set -a` dans chaque session shell interactive.
3. **Machine de revue déconnectée** : Sur la machine de revue (`51.91.120.20`), le fichier `orso_drone.env` portait un jeton de banc mocké (`mock-drone-token-...`) rejeté en HTTP 401 par le service de production. La sonde `orso_sonde.py` n'avait donc jamais pu vérifier les routes protégées en production.

---

## 2. Décisions d'Architecture

### D1. Rotation In-Service & Non-Persistance en Mémoire Volatile
- Le jeton machine (`ORSO_DRONE_API_TOKEN`) est renouvelé côté conteneur `olympe_core` par injection via le fichier d'environnement `/home/ubuntu/orso-core/.env` et recréation du conteneur Docker.
- Le registre mémoire de révocation étant volatil au redémarrage, la rotation effective repose sur le changement de la valeur configurée et vérifiée dans l'environnement du service.

### D2. Suppression Définitive des Exports dans les Profils Utilisateurs (Principe de Moindre Privilège)
- Retrait absolu de tout bloc de chargement de secrets (`set -a; . orso_drone.env; set +a`) de `~/.bashrc` et `~/.profile` sur tous les hôtes (`PROD-FR-002` et `PROD-FR-003`).
- Tout processus nécessitant ces variables doit se voir injecter ses variables de manière ciblée à son exécution. Un shell de connexion neuf doit présenter strictement 0 variable `ORSO_*`.

### D3. Neutralisation de la Commande Forcée SSH
- La clé d'agent dans `~/.ssh/authorized_keys` sur le plan de gestion est configurée avec une commande non divulgatrice : `command="echo 'ORSO-AGENT-AUTH: OK (zero secret exported)'",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty`.
- Aucune variable ni affectation n'est retournée lors d'une connexion distante.

### D4. Renouvellement IAM Supabase Auth pour le Client de Test
- Le mot de passe du compte `dirigeant.clientx@test.orso-agents.fr` est renouvelé directement auprès de Supabase Auth Admin.
- L'ancien mot de passe est formellement invalidé (rejet HTTP 400), et le nouveau validé avec succès (HTTP 200).

### D5. Alignement Machine de Revue & Sondes
- Le fichier `~/.hermes/secrets/orso_drone.env` est aligné avec la nouvelle valeur et fixé en permissions `0600` sur la machine de revue (`51.91.120.20`).
- La sonde `python3 ~/.hermes/scripts/orso_sonde.py` s'exécute avec succès (code de retour `0`) et valide en lecture seule l'ensemble des routes protégées en 200 et routes sans jeton en 401.

---

## 3. Conséquences & Conformité Charte

- **Gouvernance du Fork** : Zéro modification dans le Sanctuaire (`agent/turn_*.py`, etc.).
- **Sécurité & Traçabilité** : Aucune valeur secrète n'apparaît dans les commits, commandes, tickets ou journaux. Seuls les préfixes, longueurs et empreintes SHA-256 tronquées sont consignés.
- **Opérabilité** : Les sondes de supervision en revue sont pleinement opérationnelles sur l'infrastructure de production.
