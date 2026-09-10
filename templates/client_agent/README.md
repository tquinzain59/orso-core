# Modèles de Profils Clients Hermès-core (Restreints)

Ces fichiers servent de base pour configurer et déployer de nouveaux profils d'agents restreints destinés aux clients finaux (sur le modèle de l'agent **Jerome**).

## Structure des fichiers à copier

Pour créer un nouveau profil d'utilisateur client (ex: `nouveau_client`) :

1. Créez un répertoire dans le dossier des profils de la plateforme Hermès :
   ```bash
   mkdir -p ~/.hermes/profiles/nouveau_client
   ```

2. Copiez les fichiers de ce dossier de templates (`SOUL.md`, `profile.yaml`, `config.yaml`) dans le dossier créé.

3. Adaptez les variables de template dans les fichiers :
   - Dans **`SOUL.md`** :
     - Remplacer `{AGENT_NAME}` par le prénom/nom de l'agent (ex: `Sophie`, `Arthur`).
     - Remplacer `{BUSINESS_DOMAIN}` par le domaine métier (ex: `la facturation et le suivi commercial`, `le support client`).
   - Dans **`profile.yaml`** :
     - Remplacer `{BUSINESS_DOMAIN}` par le descriptif métier.

4. Configurez un mot de passe d'accès unique pour ce profil dans le fichier `.env` du profil ou via l'interface d'administration.

## Sécurité appliquée par défaut
* **`config.yaml`** restreint l'exécution de commandes système au strict minimum (`script execution via heredoc`) pour empêcher l'agent d'exécuter des commandes bash arbitraires.
* Le fichier **`SOUL.md`** instruit l'agent de ne jamais promettre de création d'outils et de rediriger l'utilisateur vers l'administrateur de la plateforme en cas de demande d'automatisation avancée.
