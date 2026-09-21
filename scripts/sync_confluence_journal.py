"""Script de synchronisation du Journal des réalisations vers Confluence (Page 131600)."""

import os
import base64
import json
import urllib.request
import urllib.error
from dotenv import load_dotenv

load_dotenv(".env")

EMAIL = os.environ.get("ATLASSIAN_EMAIL")
TOKEN = os.environ.get("ATLASSIAN_API_TOKEN")
DOMAIN = os.environ.get("ATLASSIAN_DOMAIN", "orso-agents")
PAGE_ID = "131600"

if not EMAIL or not TOKEN:
    raise ValueError("Identifiants Atlassian manquants dans .env")

auth_str = base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()
headers = {
    "Authorization": f"Basic {auth_str}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# 1. Récupération de la page actuelle
url = f"https://{DOMAIN}.atlassian.net/wiki/rest/api/content/{PAGE_ID}?expand=body.storage,version,title"
req = urllib.request.Request(url, headers=headers)
with urllib.request.urlopen(req) as resp:
    page_data = json.loads(resp.read().decode())

current_version = page_data["version"]["number"]
current_title = page_data["title"]
storage_value = page_data["body"]["storage"]["value"]

print(f"Page trouvée : '{current_title}', Version actuelle : {current_version}")

# Vérification si le jalon du 20/09 est déjà présent
if "Industrialisation Routage Multi-Tenant (Option B - KAN-28)" in storage_value:
    print("La page Confluence contient déjà les mentions du 20/09.")
    exit(0)

new_rows = """<tr>
<td>16/09</td>
<td>Architecture</td>
<td><strong>Cadrage securite IAM &amp; isolation multi-tenant (KAN-26 &amp; KAN-27)</strong> : arbitrage Supabase Auth souverain, schema PostgreSQL deploye, migration des 5 comptes clients POC, guard JWT en memoire (<code>client_jwt.py</code>) et validation E2E avec l'agent Jerome (200 OK) et rejet cross-tenant (403 Forbidden)</td>
<td><code>orso-core</code> / Supabase / OVH</td>
</tr>
<tr>
<td>16/09</td>
<td>Architecture &amp; IAM</td>
<td><strong>Aiguillage conteneurs Docker &amp; Alerte Support</strong> : enrichissement Supabase (<code>tenant_instances</code>, <code>support_alerts</code>), detection automatique de l'environnement cible, alerte critique et renvoi du message exact &quot;Environnement non trouve, le support Orso-agents est alerte&quot;</td>
<td><code>orso-core</code> / Supabase</td>
</tr>
<tr>
<td>20/09</td>
<td>Architecture &amp; Ingress</td>
<td><strong>Industrialisation Routage Multi-Tenant (Option B - KAN-28)</strong> : Choix de l'URL unique <code>app.orso-agents.fr</code>, Ingress dynamique Nginx Zero-Reload via resolveur Docker DNS (<code>127.0.0.11</code>), support complet streaming SSE sans buffering et WebSockets <code>/t/{slug}/ws</code></td>
<td><code>docker/ingress/</code> (<code>nginx.ingress.conf</code>)</td>
</tr>
<tr>
<td>20/09</td>
<td>Orchestration &amp; Flotte</td>
<td><strong>Superviseur Olympe (Port 9230)</strong> : Module de gestion de cycle de vie (<code>olympe/lifecycle_manager.py</code>) et serveur FastAPI (<code>olympe/server.py</code>) assurant le provisioning automatique, le reveil a la demande (<em>Wake-on-Demand</em>), la mise en veille (<em>Scale-to-Zero</em>) et la telemetrie consolidee (10 tests unitaires)</td>
<td><code>olympe/</code>, <code>docker-compose.olympe.yml</code></td>
</tr>
<tr>
<td>20/09</td>
<td>Client &amp; Vitrine</td>
<td><strong>Unification de l'acces client &amp; fin du bypass (KAN-29)</strong> : UI PWA (<code>apps/ui-client</code>) adaptee au prefixe dynamique <code>/t/{tenant_slug}/</code> avec detection de reveil Olympe. Assainissement complet du site vitrine (<code>Site_Hermes-core/client.html</code>) : suppression definitive des mots de passe en clair / bypass POC, passage a Supabase IAM souverain et redirection unifiee</td>
<td><code>apps/ui-client</code>, <code>Site_Hermes-core</code></td>
</tr>
</tbody>
</table>"""

# Remplacement dans la table
if "</tbody>\n</table>" in storage_value:
    updated_storage = storage_value.replace("</tbody>\n</table>", new_rows)
elif "</tbody></table>" in storage_value:
    updated_storage = storage_value.replace("</tbody></table>", new_rows)
else:
    raise ValueError("Balise de fermeture de table introuvable dans la page.")

# 2. Mise à jour de la page sur Confluence
update_payload = {
    "version": {
        "number": current_version + 1,
        "message": "Ajout des jalons du 16/09 (IAM Supabase KAN-26/27) et 20/09 (Option B Ingress KAN-28, Olympe et Vitrine KAN-29)",
    },
    "title": current_title,
    "type": "page",
    "body": {
        "storage": {
            "value": updated_storage,
            "representation": "storage",
        }
    },
}

put_url = f"https://{DOMAIN}.atlassian.net/wiki/rest/api/content/{PAGE_ID}"
put_req = urllib.request.Request(
    put_url,
    data=json.dumps(update_payload).encode(),
    headers=headers,
    method="PUT",
)

try:
    with urllib.request.urlopen(put_req) as put_resp:
        result = json.loads(put_resp.read().decode())
        print(f"Page mise à jour avec succès sur Confluence ! Nouvelle version : {result.get('version', {}).get('number')}")
except urllib.error.HTTPError as e:
    err_body = e.read().decode()
    print("Erreur HTTP lors de la mise à jour :", e.code, err_body)
    raise
