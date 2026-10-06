# Procédure Opérationnelle : Ajout et Rattachement d'un Hôte d'Exécution Client (Hôte N)

- **Date** : 04 octobre 2026
- **Auteurs** : Équipe Infrastructure & Architecture Orso Agents
- **Référence Tickets** : [KAN-61](https://orso-agents.atlassian.net/browse/KAN-61) (DoD : Procédure d'ajout d'un second hôte), [KAN-62](https://orso-agents.atlassian.net/browse/KAN-62), [KAN-63](https://orso-agents.atlassian.net/browse/KAN-63), [KAN-51](https://orso-agents.atlassian.net/browse/KAN-51) (Durcissement hôte Docker)
- **Cible** : Provisionnement et intégration sécurisée d'un nouvel hôte d'exécution dédié aux espaces conteneurisés clients (ex: `prod-fr-003`, `prod-fr-004`, etc.) au plan de gestion Olympe.

---

## 1. Prérequis & Dimensionnement Matériel

Conformément à la politique de dimensionnement d'Orso Agents (Document 27 & KAN-59) :
- **Fournisseur** : OVHcloud Public Cloud ou VPS d'infrastructure souveraine en France (Gravelines / Roubaix / Strasbourg).
- **Gabarit minimal recommandé** :
  - Vague 0 (Banc d'essai) : VPS KVM 2 vCPU, 4 Go RAM, 40 Go SSD NVMe (`d2-2` ou `d2-4`).
  - Vague 1 (25 clients) : Instance Compute `b2-15` (4 vCPU, 15 Go RAM) ou `b2-30` (8 vCPU, 30 Go RAM).
- **Système d'exploitation** : Ubuntu 24.04 LTS ou Ubuntu 26.04 LTS (x86_64), noyau Linux standard.
- **Réseau** : IP publique IPv4 dédiée fixe, enregistrement DNS inverse configuré (ex: `prod-fr-003.orso-agents.fr`).

---

## 2. Étape 1 : Initialisation Système & Swapfile Obligatoire

Se connecter en SSH sur le nouvel hôte :
```bash
ssh ubuntu@<NOUVELLE_IP_HOTE>
```

### 2.1 Mises à jour de sécurité de base
```bash
sudo apt-get update && sudo apt-get -y dist-upgrade
sudo apt-get -y install ufw fail2ban curl jq iptables-persistent
```

### 2.2 Création du swapfile de secours (2 Go)
*Règle d'or Document 27 / KAN-59 : L'absence de swapfile transforme une saturation mémoire transitoire en meurtre brutal de conteneur (`OOMKilled`) au lieu d'un ralentissement contrôlé.*
```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
sudo sysctl vm.swappiness=10
echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.d/99-orso-swap.conf
```

---

## 3. Étape 2 : Installation du Moteur Docker & Configuration du Démon

### 3.1 Installation officielle Docker Engine
```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
```

### 3.2 Vérification de la non-exposition du port TCP Docker
Vérifier impérativement que `dockerd` n'écoute sur aucun port réseau public :
```bash
sudo ss -tulpn | grep dockerd || echo "CONFORME : Aucun port Docker TCP ouvert"
```
*Le démon Docker doit écouter EXCLUSIVEMENT sur la socket UNIX locale `/var/run/docker.sock`.*

---

## 4. Étape 3 : Durcissement SSH & Déploiement de la Clé d'Orchestration

### 4.1 Injection de la clé publique de gestion Olympe
Sur l'Hôte 1 (plan de gestion), récupérer la clé publique d'orchestration :
```bash
cat /home/ubuntu/.ssh/id_ed25519_olympe.pub
```
Sur le nouvel hôte client, ajouter cette clé dans `/home/ubuntu/.ssh/authorized_keys` :
```bash
echo "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5... olympe-orchestration@prod-fr-002" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

### 4.2 Verrouillage absolu de l'authentification par mot de passe
Éditer `/etc/ssh/sshd_config.d/99-hardened.conf` :
```ini
PasswordAuthentication no
ChallengeResponseAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
X11Forwarding no
MaxAuthTries 3
```
Redémarrer le service SSH :
```bash
sudo systemctl restart ssh
```

---

## 5. Étape 4 : Durcissement Réseau & Règle iptables DOCKER-USER

*Point de vigilance Jarvis (PO) : Les règles NAT de Docker contournent le pare-feu UFW standard. Il est impératif d'injecter la règle dans la chaîne `DOCKER-USER` pour protéger les ports applicatifs des conteneurs clients.*

### 5.1 Restriction des ports conteneurs clients (9200-9299) à l'Hôte Ingress

**Étape 5.1.0 - Lire le nom de l'interface réseau.** Les commandes ci-dessous ne protègent que si l'interface nommée est bien celle qui reçoit le trafic Internet. La lire sur l'hôte, ne pas la supposer :

```bash
ip -br link        # prod-fr-003 : ens3
```

Un nom d'interface absent de l'hôte (`eth0` sur `prod-fr-003`) est accepté par iptables sans erreur, ne matche aucun paquet et se lit comme actif dans `iptables -S` : c'est un contrôle décoratif, vérifié le 06/10/2026.

**Étape 5.1.1 - Vérifier la persistance.** Le paquet `iptables-persistent` est un prérequis de l'étape 2.1 ; le contrôler ici, car `netfilter-persistent save` échoue sans lui et la règle disparaît au premier redémarrage. Le cas s'est présenté sur `prod-fr-003`, provisionné avant l'inscription de cette ligne : le poser si le contrôle est négatif.

```bash
dpkg -l iptables-persistent | tail -1                                          # doit rendre ii iptables-persistent
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y iptables-persistent     # si absent
```

**Étape 5.1.2 - Poser les règles.** Remplacer `<iface>` par l'interface lue à l'étape 5.1.0 :

```bash
# Autoriser les connexions établies
sudo iptables -I DOCKER-USER -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# Autoriser EXCLUSIVEMENT l'Hôte 1 (Ingress / Olympe : 92.222.68.80) sur la plage 9200-9299
sudo iptables -A DOCKER-USER -i <iface> -p tcp --dport 9200:9299 -s 92.222.68.80 -j ACCEPT

# Bloquer toute autre source Internet sur cette plage
sudo iptables -A DOCKER-USER -i <iface> -p tcp --dport 9200:9299 -j DROP
```

**Étape 5.1.3 - Sauvegarder, puis vérifier le contenu de la chaîne.** La vérification porte sur ce que contient la chaîne, jamais sur le code retour des commandes : une chaîne qui rend `-N DOCKER-USER` seul signifie que rien n'est posé.

```bash
sudo netfilter-persistent save
sudo iptables -S DOCKER-USER                    # doit rendre les trois règles, dans cet ordre
sudo grep -A3 'DOCKER-USER' /etc/iptables/rules.v4
```

**Portée et limite.** Le filtre évalue le port de destination *après* la traduction NAT de Docker : la plage 9200-9299 ne protège que si le port publié sur l'hôte porte le même numéro que le port du conteneur. Le régime de publication des ports clients est porté par KAN-97.

---

## 6. Étape 5 : Authentification au Registre GHCR Privé

Pour permettre au nouvel hôte de tirer l'image immuable du moteur Orso sans stocker de secret dans le code :
```bash
echo "$GHCR_READ_TOKEN" | docker login ghcr.io -u tquinzain59 --password-stdin
```
*Le token utilisé doit être à portée strictement minimale : `read:packages` uniquement.*

Tirer l'image de référence épinglée par digest SHA-256 :
```bash
docker pull ghcr.io/tquinzain59/orso-engine@sha256:4506ccd6f51e68d3bf799c2a5b17d82916dc5cc285080f2fcf9c07046e2b904f
```

---

## 7. Étape 6 : Enregistrement dans Olympe & Test de Sondage Non-Interactif

Sur l'Hôte 1 (ou dans la configuration d'Olympe `olympe/hosts.yaml` ou variables d'environnement) :
1. Déclarer le nouvel hôte dans la flotte :
   ```yaml
   hosts:
     prod-fr-003:
       host_name: "Serveur Clients OVH 01"
       ip: "57.131.196.106"
       ssh_target: "ssh://ubuntu@57.131.196.106"
       port_range: "9231-9299"
       max_memory_mb: 3302
       max_cpus: 2.0
   ```
2. Valider le sondage non-interactif depuis l'Hôte 1 :
   ```bash
   docker -H ssh://ubuntu@57.131.196.106 info
   ```
3. Si la commande renvoie les spécifications de l'hôte sans demander de saisie interactive, le nouvel hôte est prêt pour la mise en service.
