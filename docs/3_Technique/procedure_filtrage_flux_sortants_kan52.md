# Procédure d'Exploitation : Filtrage des Flux Sortants Conteneurs (KAN-52)

## 1. Contexte & Objectif
Pour interdire l'exfiltration de clés d'API ou la communication avec des serveurs de commande et contrôle (C2) par un agent compromis (campagne CARBONATO), les conteneurs clients Orso sont soumis à un filtrage strict de leurs flux sortants sur l'hôte d'exécution via la chaîne pare-feu `DOCKER-USER`.

---

## 2. Liste Blanche des Destinations Autorisées (CA1)

| Catégorie | Destinations / Domaines | Ports / Protocoles | Demandeur |
| :--- | :--- | :--- | :--- |
| **Résolution DNS** | Serveurs DNS configurés sur l'hôte | 53 (UDP / TCP) | Système / Core |
| **Horodatage** | Serveurs NTP système | 123 (UDP) | Horodatage souverain |
| **Inférence LLM** | `openrouter.ai`, `api.openai.com`, `api.anthropic.com`, `generativelanguage.googleapis.com` | 443 (TCP) | Agents Orso (Jérôme, Lucas, Clara, Victor) |
| **Facturation** | `api.stripe.com` | 443 (TCP) | Olympe / Provisioning |
| **ERPs Clients** | `app.pennylane.com`, `apiv2.sellsy.com`, `api.odoo.com` | 443 (TCP) | Jérôme (Recouvrement) |

*Toute autre destination sortante est formellement interdite et rejetée.*

---

## 3. Configuration Pare-feu sur l'Hôte (`DOCKER-USER`) (CA2)

Docker insère automatiquement les paquets des conteneurs dans la chaîne `DOCKER-USER` avant tout routage NAT :
```bash
# 1. Autoriser les flux déjà établis
sudo iptables -I DOCKER-USER 1 -i docker0 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# 2. Autoriser DNS & NTP
sudo iptables -A DOCKER-USER -i docker0 -p udp --dport 53 -j ACCEPT
sudo iptables -A DOCKER-USER -i docker0 -p tcp --dport 53 -j ACCEPT
sudo iptables -A DOCKER-USER -i docker0 -p udp --dport 123 -j ACCEPT

# 3. Autoriser HTTPS vers port 443
sudo iptables -A DOCKER-USER -i docker0 -p tcp --dport 443 -j ACCEPT

# 4. Journaliser les refus avec préfixe explicite (CA3)
sudo iptables -A DOCKER-USER -i docker0 -m limit --limit 5/min -j LOG --log-prefix '[ORSO-EGRESS-DROP]: ' --log-level 4

# 5. Rejet final de tout flux non autorisé (CA2)
sudo iptables -A DOCKER-USER -i docker0 -j DROP
```

---

## 4. Surveillance & Alertes des Rejets (CA3 / CA6)

Les tentatives d'exfiltration ou de connexion hors liste blanche sont consignées dans les journaux système du noyau (`dmesg` / `/var/log/kern.log`) :
```bash
dmesg | grep '\[ORSO-EGRESS-DROP\]'
```
* **Format journalisé** :
  `[ORSO-EGRESS-DROP]: IN=docker0 OUT=eth0 MAC=... SRC=172.17.0.2 DST=198.51.100.23 PROTO=TCP SPT=48212 DPT=8080 ...`
* **Seuil d'alerte** : Si plus de 3 rejets consécutifs sont détectés sur un même conteneur en moins de 5 minutes, une alerte est transmise au canal de supervision Ops.

---

## 5. Procédure de Retour Arrière (Rollback) (CA5)

En cas de besoin de neutralisation immédiate du filtrage (ex: diagnostic réseau) :
```bash
# Réinitialisation de la chaîne DOCKER-USER
sudo iptables -F DOCKER-USER
sudo iptables -A DOCKER-USER -j RETURN
```
*Vérification : les conteneurs retrouvent immédiatement l'accès sortant par défaut sans coupure des flux légitimes.*
