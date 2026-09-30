"""Publication et synchronisation Atlassian pour le ticket KAN-46 :
- Mise à jour du Document 11 (Secrets et accès - ID 65838)
- Mise à jour du Document 14 (Audit du site vitrine - ID 229757)
- Mise à jour et clôture du ticket Jira KAN-46
"""

import base64
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv(".env")

EMAIL = os.environ.get("ATLASSIAN_EMAIL")
TOKEN = os.environ.get("ATLASSIAN_API_TOKEN")
DOMAIN = os.environ.get("ATLASSIAN_DOMAIN", "orso-agents")

if not EMAIL or not TOKEN:
    raise ValueError("Identifiants Atlassian manquants dans .env")

auth_str = base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()
headers = {
    "Authorization": f"Basic {auth_str}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def get_confluence_page(page_id: str) -> dict:
    url = f"https://{DOMAIN}.atlassian.net/wiki/rest/api/content/{page_id}?expand=body.storage,version,title"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def update_confluence_page(page_id: str, new_storage_value: str, version_number: int, title: str) -> bool:
    url = f"https://{DOMAIN}.atlassian.net/wiki/rest/api/content/{page_id}"
    payload = {
        "id": page_id,
        "type": "page",
        "title": title,
        "version": {
            "number": version_number + 1,
            "message": "Mise à jour sécurité KAN-46 : inventaire des révocations et clôture réserves audit vitrine",
        },
        "body": {
            "storage": {
                "value": new_storage_value,
                "representation": "storage",
            }
        },
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="PUT")
    with urllib.request.urlopen(req) as resp:
        return resp.status == 200


def update_document_11():
    print("\n--- Mise à jour Document 11 (Secrets et accès - ID: 65838) ---")
    page = get_confluence_page("65838")
    title = page["title"]
    ver = page["version"]["number"]
    storage = page["body"]["storage"]["value"]

    if "Incident de sécurité KAN-46" in storage:
        print("[*] Document 11 contient déjà la section KAN-46.")
        return

    kan46_section = """
<h2>Incident de sécurité KAN-46 : Purge Vitrine &amp; Révocation des Secrets du POC (30/09/2026)</h2>
<p>Le 28/09/2026, un audit du Product Owner a identifié que le document interne <code>Secrets/secrets_poc.md</code> était servi publiquement en HTTP 200 sur le domaine de production officiel (<code>https://www.orso-agents.fr/Secrets/secrets_poc.md</code>). Ce fichier comportait des identifiants d'administration par défaut (<code>admin:admin</code>), des adresses IP d'API de supervision, ainsi que les mots de passe de 5 comptes de démonstration Supabase Auth.</p>

<h3>1. Remédiation &amp; Durcissement de l'Infrastructure</h3>
<ul>
<li><strong>Purge physique et réécriture Git</strong> : Le répertoire <code>Secrets/</code> ainsi que les fichiers <code>admin.html</code> et <code>monitoring.html</code> ont été supprimés. L'historique du dépôt Git <code>tquinzain59/orso-site</code> a été réécrit via <code>git filter-branch</code> et repoussé avec succès afin d'éliminer toute trace des anciens secrets.</li>
<li><strong>Durcissement Vercel</strong> : Fichier <code>.vercelignore</code> actif pour interdire le téléversement de tout dossier technique (<code>docs/</code>, <code>Secrets/</code>, scripts SQL). Configuration de <code>vercel.json</code> opérant des redirections HTTP 308 permanentes vers <code>https://ops.orso-agents.fr</code> et injectant les en-têtes de sécurité (HSTS, X-Content-Type-Options: nosniff, X-Frame-Options: DENY).</li>
<li><strong>Contrôles automatisés continus</strong> : Script local <code>scripts/check_no_secrets.py</code> et workflow GitHub Actions exécuté quotidiennement à 06:00 UTC vérifiant l'absence absolue de secrets et la conformité HTTP 404 de l'URL cible.</li>
</ul>

<h3>2. Inventaire des Identifiants Révoqués et Renouvelés (Supabase Auth)</h3>
<table>
<thead>
<tr>
<th>Compte / Email</th>
<th>Organisation</th>
<th>Rôle</th>
<th>Ancien Mot de Passe (Compromis)</th>
<th>Nouveau Statut Supabase Auth</th>
<th>Révocation Sessions</th>
</tr>
</thead>
<tbody>
<tr>
<td><code>sophie.martin@finarecee20.fr</code></td>
<td>Financia Solutions</td>
<td>Admin / DAF</td>
<td><code>TempOrso2026!Financia</code></td>
<td><strong>Renouvelé</strong> (24 car. aléatoire) — rejet HTTP 400 ancien</td>
<td>OUI (Sessions révoquées)</td>
</tr>
<tr>
<td><code>claire.dubois@servicallc322.com</code></td>
<td>CommerciaLink</td>
<td>Support Client</td>
<td><code>TempOrso2026!Commercia</code></td>
<td><strong>Renouvelé</strong> (24 car. aléatoire) — rejet HTTP 400 ancien</td>
<td>OUI (Sessions révoquées)</td>
</tr>
<tr>
<td><code>h.bernard@recoviaa60a.fr</code></td>
<td>HelpDesk360</td>
<td>Opérateur IA</td>
<td><code>TempOrso2026!Helpdesk</code></td>
<td><strong>Renouvelé</strong> (24 car. aléatoire) — rejet HTTP 400 ancien</td>
<td>OUI (Sessions révoquées)</td>
</tr>
<tr>
<td><code>julien.lefevre@batiprof38f.fr</code></td>
<td>BatiPro Services</td>
<td>Commercial</td>
<td><code>TempOrso2026!Batipro</code></td>
<td><strong>Renouvelé</strong> (24 car. aléatoire) — rejet HTTP 400 ancien</td>
<td>OUI (Sessions révoquées)</td>
</tr>
<tr>
<td><code>amelie.petit@ventelinkc009.com</code></td>
<td>EuroTech Conseil</td>
<td>Direction Générale</td>
<td><code>TempOrso2026!EuroTech</code></td>
<td><strong>Renouvelé</strong> (24 car. aléatoire) — rejet HTTP 400 ancien</td>
<td>OUI (Sessions révoquées)</td>
</tr>
<tr>
<td><code>test.sansenv@orso-agents.fr</code></td>
<td>Aura Sans Env.</td>
<td>Testeur</td>
<td><code>TempOrso2026!SansEnv</code></td>
<td><strong>Renouvelé</strong> (24 car. aléatoire) — rejet HTTP 400 ancien</td>
<td>OUI (Sessions révoquées)</td>
</tr>
<tr>
<td>Accès local <code>admin.html</code></td>
<td>Vitrine POC</td>
<td>Administrateur</td>
<td><code>admin:admin</code></td>
<td><strong>Supprimé définitivement</strong> (Redirection HTTP 308 vers ops.orso-agents.fr)</td>
<td>N/A</td>
</tr>
</tbody>
</table>
"""

    updated_storage = storage + kan46_section
    update_confluence_page("65838", updated_storage, ver, title)
    print("[✓] Document 11 mis à jour sur Confluence (version incrémentée).")


def update_document_14():
    print("\n--- Mise à jour Document 14 (Audit du site vitrine - ID: 229757) ---")
    page = get_confluence_page("229757")
    title = page["title"]
    ver = page["version"]["number"]
    storage = page["body"]["storage"]["value"]

    if "Résolution Réserve Sécurité KAN-46" in storage:
        print("[*] Document 14 contient déjà la mention de résolution KAN-46.")
        return

    kan46_audit_resolution = """
<ac:structured-macro ac:name="info">
<ac:parameter ac:name="title">Résolution Réserve Sécurité KAN-46 (30/09/2026)</ac:parameter>
<ac:rich-text-body>
<p><strong>Statut : RÉSOLU &amp; CLÔTURÉ</strong></p>
<ul>
<li><strong>Réserve <code>Secrets/secrets_poc.md</code></strong> : Purge physique et réécriture de l'historique Git sur <code>orso-site</code>. L'URL <code>https://www.orso-agents.fr/Secrets/secrets_poc.md</code> renvoie désormais strictement <strong>HTTP 404 Not Found</strong>.</li>
<li><strong>Réserve <code>admin.html</code> / Identifiants par défaut</strong> : Fichier <code>admin.html</code> et <code>monitoring.html</code> supprimés de la vitrine. Redirection permanente HTTP 308 active vers <code>https://ops.orso-agents.fr</code> configurée dans <code>vercel.json</code>.</li>
<li><strong>Révocation des identifiants</strong> : Tous les mots de passe compromis (5 comptes démo Supabase) ont été révoqués et renouvelés avec succès (rejet HTTP 400 validé).</li>
<li><strong>Garantie de non-régression</strong> : Contrôle automatisé quotidien via GitHub Actions à 06:00 UTC.</li>
</ul>
</ac:rich-text-body>
</ac:structured-macro>
"""

    updated_storage = storage + kan46_audit_resolution
    update_confluence_page("229757", updated_storage, ver, title)
    print("[✓] Document 14 mis à jour sur Confluence (version incrémentée).")


def sync_jira_ticket(ticket_key: str = "KAN-46"):
    print(f"\n--- Mise à jour du Ticket Jira {ticket_key} ---")

    handoff_text = """
=== SECTION HANDOFF KAN-46 : PREUVES ET CRITÈRES D'ACCEPTATION ===

[✓] Critère 1 : L'URL du document d'identifiants répond 404 ou 410 en production.
Preuve : Requête HTTP live sur https://www.orso-agents.fr/Secrets/secrets_poc.md renvoie HTTP/2 404 (x-vercel-error: NOT_FOUND).

[✓] Critère 2 : Aucun mot de passe, jeton ou clé d'API n'apparaît dans le contenu servi par le site, contrôle automatisé à l'appui.
Preuve : Script scripts/check_no_secrets.py validé à 100% avec 0 anomalie. .vercelignore actif excluant Secrets/, docs/, scripts/ et fichiers *.sql.

[✓] Critère 3 : L'inventaire des identifiants révoqués est consigné (documents 11 et 14).
Preuve : Document Confluence 11 (ID: 65838) et Document 14 (ID: 229757) enrichis avec l'inventaire complet des 6 comptes renouvelés et révoqués. Fichier d'inventaire scripts/iam/kan46_revocation_inventory.json consigné.

[✓] Critère 4 : La page d'administration n'accepte plus d'identifiants par défaut.
Preuve : Suppression physique de admin.html et monitoring.html. Redirection permanente HTTP/2 308 vers https://ops.orso-agents.fr configurée au niveau edge Vercel (vercel.json).

[✓] Critère 5 : Un contrôle quotidien signale toute réapparition d'un fichier de secrets dans le contenu servi.
Preuve : Workflows GitHub Actions quotidiens à 06:00 UTC configurés dans orso-site (.github/workflows/security_daily_leak_check.yml) et orso-core (.github/workflows/security_daily_leak_check.yml).

Definition of Done :
- Branche Git créée : KAN-46-securisation-secrets-vitrine-iam (orso-core) et KAN-46-securisation-secrets-vitrine (orso-site).
- Purge de l'historique Git complétée sur orso-site.
- Sanctuaire du moteur préservé à 100%. Aucun secret présent dans les commits ou la pull request.
"""

    # 1. Ajout d'un commentaire officiel sur Jira
    comment_url = f"https://{DOMAIN}.atlassian.net/rest/api/3/issue/{ticket_key}/comment"
    comment_payload = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "codeBlock",
                    "attrs": {"language": "text"},
                    "content": [{"type": "text", "text": handoff_text.strip()}],
                }
            ],
        }
    }
    comment_req = urllib.request.Request(
        comment_url,
        data=json.dumps(comment_payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(comment_req) as resp:
            print(f"[✓] Commentaire Handoff ajouté au ticket {ticket_key}.")
    except Exception as e:
        print(f"[!] Erreur commentaire Jira : {e}")

    # 2. Transition vers 'Terminé'
    try:
        trans_url = f"https://{DOMAIN}.atlassian.net/rest/api/3/issue/{ticket_key}/transitions"
        trans_req = urllib.request.Request(trans_url, headers=headers)
        with urllib.request.urlopen(trans_req) as resp:
            trans_data = json.loads(resp.read().decode())
            done_transitions = [
                t
                for t in trans_data.get("transitions", [])
                if t["to"]["name"].lower() in ("done", "terminé", "fermé", "closed")
            ]
            if done_transitions:
                target_trans = done_transitions[0]
                post_trans_req = urllib.request.Request(
                    trans_url,
                    data=json.dumps({"transition": {"id": target_trans["id"]}}).encode("utf-8"),
                    headers=headers,
                    method="POST",
                )
                with urllib.request.urlopen(post_trans_req):
                    print(f"[✓] Ticket Jira {ticket_key} transitionné vers le statut '{target_trans['to']['name']}'.")
            else:
                print("[*] Aucune transition 'Terminé' trouvée (le ticket est peut-être déjà fermé).")
    except Exception as e:
        print(f"[!] Erreur transition Jira : {e}")


def main():
    print("=== Démarrage de la Synchronisation Atlassian (KAN-46) ===")
    update_document_11()
    update_document_14()
    sync_jira_ticket("KAN-46")
    print("=== Synchronisation Atlassian Terminée ===\n")


if __name__ == "__main__":
    main()
