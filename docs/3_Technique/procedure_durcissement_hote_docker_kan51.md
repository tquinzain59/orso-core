# Procédure d'Exploitation : Durcissement de l'Hôte Docker (KAN-51)

## 1. Objectif & Contexte de Sécurité
Dans le cadre de la protection contre les vecteurs d'exfiltration et de prise de contrôle (campagne CARBONATO / ThreatDown), l'hôte Docker hébergeant les conteneurs clients doit être hermétiquement isolé :
- Zéro exposition TCP du démon Docker (ports 2375/2376).
- Zéro accès au socket Docker `/var/run/docker.sock` ou aux répertoires racines (`/`, `/etc`) depuis un conteneur client.
- Tirage exclusif des images depuis le registre privé authentifié GHCR (`ghcr.io/tquinzain59/...`).

---

## 2. Commandes de Vérification

### 2.1 Vérification de l'écoute réseau (CA1)
Sur l'hôte Docker (ex: `prod-fr-003`) :
```bash
ss -lntp | grep -E '2375|2376'
```
* **Résultat attendu** : Aucune sortie. Si une ligne apparaît, le démon écoute sur le réseau et doit être immédiatement désactivé.

### 2.2 Exécution de l'audit automatique (CA2 / CA3)
```bash
python3 scripts/security/docker_host_hardening_preflight.py --json
```
* **Résultat attendu** : Code retour 0 (`"status": "PASSED"`).

### 2.3 Vérification des montages et privilèges des conteneurs (CA4)
```bash
docker inspect $(docker ps -q) --format '{{.Name}}: Privileged={{.HostConfig.Privileged}} Mounts={{range .Mounts}}{{.Source}}->{{.Destination}} {{end}}'
```
* **Résultat attendu** : `Privileged=false`, aucun montage de `/var/run/docker.sock` ni de la racine `/`.

---

## 3. Remédiation Immédiate en Cas d'Anomalie

Si un port 2375/2376 écoute sur le réseau :
1. Éditer la configuration du démon `/etc/docker/daemon.json` :
   ```json
   {
     "hosts": ["unix:///var/run/docker.sock"]
   }
   ```
2. Vérifier que `/lib/systemd/system/docker.service` ou `/etc/systemd/system/docker.service.d/override.conf` ne porte pas d'option `-H tcp://0.0.0.0:2375`.
3. Recharger et redémarrer Docker :
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart docker
   ```

---

## 4. Procédure de Retour Arrière (Rollback)

Si un composant d'administration légitime requiert temporairement l'accès distant :
1. Ne **JAMAIS** exposer le port 2375 en clair sur `0.0.0.0`.
2. Utiliser exclusivement un tunnel SSH chiffré et authentifié par clé :
   ```bash
   ssh -N -L 127.0.0.1:23750:/var/run/docker.sock admin@<hote_ip>
   ```
3. En cas de blocage d'un conteneur légitime au redémarrage :
   - Vérifier les permissions de son volume de données dans `/var/orso/spaces/<client>`.
   - Relancer le provisioning via le script Olympe : `python3 -m olympe.lifecycle_manager wake <slug>`.

---

## 5. Contact en Cas d'Incident
- **Responsable Sécurité / Direction** : Thibaut Quinzain (`thibaut@orso-agents.fr`)
- **Supervision Ops** : Alerte automatique via le canal d'astreinte et journalisation dans `olympe_ops.db`.
