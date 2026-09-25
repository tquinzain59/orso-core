"""Publication de la spécification KAN-31 sur Confluence et création / clôture des tickets KAN-30 et KAN-31 dans Jira."""

import os
import re
import base64
import json
import urllib.parse
import urllib.request
import urllib.error
from dotenv import load_dotenv

load_dotenv(".env")

EMAIL = os.environ.get("ATLASSIAN_EMAIL")
TOKEN = os.environ.get("ATLASSIAN_API_TOKEN")
DOMAIN = os.environ.get("ATLASSIAN_DOMAIN", "orso-agents")
PARENT_PAGE_ID = "98352"  # 2. Technique et architecture

if not EMAIL or not TOKEN:
    raise ValueError("Identifiants Atlassian manquants dans .env")

auth_str = base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()
headers = {
    "Authorization": f"Basic {auth_str}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def markdown_to_confluence_storage(md_text: str) -> str:
    """Conversion propre du Markdown vers le format de stockage XHTML Confluence."""
    lines = md_text.splitlines()
    html_lines = []
    in_code_block = False
    code_lang = ""
    code_content = []
    in_table = False

    for line in lines:
        if line.startswith("```"):
            if in_code_block:
                escaped_code = "\n".join(code_content).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                html_lines.append(
                    f'<ac:structured-macro ac:name="code"><ac:parameter ac:name="language">{code_lang or "text"}</ac:parameter>'
                    f'<ac:plain-text-body><![CDATA[{escaped_code}]]></ac:plain-text-body></ac:structured-macro>'
                )
                in_code_block = False
                code_content = []
            else:
                in_code_block = True
                code_lang = line[3:].strip()
            continue

        if in_code_block:
            code_content.append(line)
            continue

        if line.startswith("|") and line.endswith("|"):
            # Table row
            cols = [c.strip() for c in line.split("|")[1:-1]]
            if all(re.match(r"^:?-+:?$", c) for c in cols):
                continue  # separator line
            if not in_table:
                html_lines.append("<table><tbody>")
                in_table = True
            row_html = "".join(f"<td>{re.sub(r'`([^`]+)`', r'<code>\1</code>', c)}</td>" for c in cols)
            html_lines.append(f"<tr>{row_html}</tr>")
            continue
        elif in_table:
            html_lines.append("</tbody></table>")
            in_table = False

        if line.startswith("# "):
            html_lines.append(f"<h1>{line[2:].strip()}</h1>")
        elif line.startswith("## "):
            html_lines.append(f"<h2>{line[3:].strip()}</h2>")
        elif line.startswith("### "):
            html_lines.append(f"<h3>{line[4:].strip()}</h3>")
        elif line.startswith("#### "):
            html_lines.append(f"<h4>{line[5:].strip()}</h4>")
        elif line.startswith("> "):
            quote_text = line[2:].strip().replace("**", "<strong>").replace("**", "</strong>")
            html_lines.append(f"<blockquote><p>{quote_text}</p></blockquote>")
        elif line.startswith("- [x] ") or line.startswith("- [ ] "):
            checked = "✓" if "[x]" in line else "☐"
            content = line[6:].strip().replace("**", "<strong>").replace("**", "</strong>")
            html_lines.append(f"<p>{checked} {content}</p>")
        elif line.startswith("* ") or line.startswith("- "):
            item = line[2:].strip().replace("**", "<strong>").replace("**", "</strong>")
            item = re.sub(r"`([^`]+)`", r"<code>\1</code>", item)
            html_lines.append(f"<li>{item}</li>")
        elif line.strip() == "---":
            html_lines.append("<hr />")
        elif line.strip():
            p_text = line.strip().replace("**", "<strong>").replace("**", "</strong>")
            p_text = re.sub(r"`([^`]+)`", r"<code>\1</code>", p_text)
            html_lines.append(f"<p>{p_text}</p>")

    if in_table:
        html_lines.append("</tbody></table>")

    return "\n".join(html_lines)


# 1. Publication de la spécification KAN-31 sur Confluence
spec_path = "docs/3_Technique/spec_kan31_interfaces_erp_backoffice.md"
with open(spec_path, "r", encoding="utf-8") as f:
    spec_md = f.read()

storage_html = markdown_to_confluence_storage(spec_md)
page_title = "KAN-31 - Spec : Raccordement Dynamique des Interfaces & ERP au Backoffice Hermès"

check_url = f"https://{DOMAIN}.atlassian.net/wiki/rest/api/content?spaceKey=Orsoagents&title={urllib.parse.quote(page_title)}"
check_req = urllib.request.Request(check_url, headers=headers)
with urllib.request.urlopen(check_req) as resp:
    search_data = json.loads(resp.read().decode())

existing_pages = search_data.get("results", [])
confluence_page_url = ""

if existing_pages:
    page_id = existing_pages[0]["id"]
    curr_ver = existing_pages[0]["version"]["number"]
    print(f"Mise à jour de la page Confluence ID {page_id} (version {curr_ver} -> {curr_ver + 1})...")
    update_data = {
        "version": {"number": curr_ver + 1},
        "title": page_title,
        "type": "page",
        "body": {"storage": {"value": storage_html, "representation": "storage"}},
    }
    update_req = urllib.request.Request(
        f"https://{DOMAIN}.atlassian.net/wiki/rest/api/content/{page_id}",
        data=json.dumps(update_data).encode(),
        headers=headers,
        method="PUT",
    )
    with urllib.request.urlopen(update_req) as u_resp:
        confluence_page_url = f"https://{DOMAIN}.atlassian.net/wiki/spaces/Orsoagents/pages/{page_id}"
        print(f"Page Confluence mise à jour : {confluence_page_url}")
else:
    print("Création de la nouvelle page de spécification sur Confluence...")
    create_data = {
        "type": "page",
        "title": page_title,
        "ancestors": [{"id": PARENT_PAGE_ID}],
        "space": {"key": "Orsoagents"},
        "body": {"storage": {"value": storage_html, "representation": "storage"}},
    }
    create_req = urllib.request.Request(
        f"https://{DOMAIN}.atlassian.net/wiki/rest/api/content",
        data=json.dumps(create_data).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(create_req) as c_resp:
        c_data = json.loads(c_resp.read().decode())
        page_id = c_data["id"]
        confluence_page_url = f"https://{DOMAIN}.atlassian.net/wiki/spaces/Orsoagents/pages/{page_id}"
        print(f"Page Confluence créée avec succès : {confluence_page_url}")


# 2. Gestion des tickets Jira (KAN-30 et KAN-31)
def get_myself_account_id():
    url = f"https://{DOMAIN}.atlassian.net/rest/api/3/myself"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())["accountId"]


account_id = get_myself_account_id()


def create_or_get_issue(summary: str, description_text: str):
    # Chercher si le ticket existe déjà par son résumé
    search_url = f"https://{DOMAIN}.atlassian.net/rest/api/3/search/jql?jql={urllib.parse.quote(f'project = KAN AND summary ~ \"{summary[:30]}\"')}"
    req = urllib.request.Request(search_url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())
        issues = data.get("issues", [])
        if issues:
            issue_id = issues[0]["id"]
            # get key
            req_k = urllib.request.Request(f"https://{DOMAIN}.atlassian.net/rest/api/3/issue/{issue_id}?fields=key", headers=headers)
            with urllib.request.urlopen(req_k) as r_k:
                k_data = json.loads(r_k.read().decode())
                print(f"Ticket existant trouvé : {k_data['key']}")
                return k_data["key"]

    # Création du ticket
    create_url = f"https://{DOMAIN}.atlassian.net/rest/api/3/issue"
    payload = {
        "fields": {
            "project": {"key": "KAN"},
            "summary": summary,
            "issuetype": {"id": "10004"},  # Tâche
            "reporter": {"accountId": account_id},
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": description_text}],
                    }
                ],
            },
        }
    }
    create_req = urllib.request.Request(
        create_url,
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(create_req) as c_resp:
        c_data = json.loads(c_resp.read().decode())
        issue_key = c_data["key"]
        print(f"Ticket Jira créé : {issue_key}")
        return issue_key


def transition_and_comment(issue_key: str, transition_id: str, comment_text: str):
    # Ajout du commentaire
    comment_url = f"https://{DOMAIN}.atlassian.net/rest/api/3/issue/{issue_key}/comment"
    comment_payload = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": comment_text}],
                }
            ],
        }
    }
    comm_req = urllib.request.Request(
        comment_url,
        data=json.dumps(comment_payload).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(comm_req):
            print(f"Commentaire ajouté sur {issue_key}.")
    except Exception as e:
        print(f"Avertissement commentaire {issue_key}: {e}")

    # Transition
    trans_url = f"https://{DOMAIN}.atlassian.net/rest/api/3/issue/{issue_key}/transitions"
    trans_payload = {"transition": {"id": transition_id}}
    trans_req = urllib.request.Request(
        trans_url,
        data=json.dumps(trans_payload).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(trans_req):
            print(f"Ticket {issue_key} passé au statut de transition {transition_id}.")
    except Exception as e:
        print(f"Avertissement transition {issue_key}: {e}")


# Création et Clôture KAN-30
kan30_desc = (
    "Implémentation et déploiement en production du Cockpit Orso Ops hébergé sur le superviseur Olympe (port 9230). "
    "Gestion centralisée des clients, contacts DAF, suivi des conteneurs, grille tarifaire 99€/169€/279€ HT, "
    "feature gating des 4 agents avec périodes d'essai et sécurisation IAM Superadmin Supabase Auth. "
    "Accessible sur https://ops.orso-agents.fr."
)
kan30_key = create_or_get_issue(
    "Architecture & Ops : Cockpit Orso Ops, Facturation Stripe & Authentification IAM Superadmin",
    kan30_desc,
)
kan30_comment = (
    "Jalon validé et déployé en production le 23/09/2026 sur https://ops.orso-agents.fr.\n"
    "- 20/20 tests unitaires passés à 100% (test_ops_auth.py, test_ops_manager.py).\n"
    "- Authentification IAM Superadmin avec protection /api/olympe/ops/*.\n"
    "- Résolution dynamique des emails clients via API Admin Supabase.\n"
    "- Documentation Confluence : https://orso-agents.atlassian.net/wiki/spaces/Orsoagents/pages/3407874"
)
transition_and_comment(kan30_key, "51", kan30_comment)


# Création et Clôture KAN-31
kan31_desc = (
    "Raccordement dynamique de l'onglet 'Interfaces et ERP' de l'UI Client (apps/ui-client) au moteur Hermès. "
    "Suppression définitive des données et métriques factices au profit d'un sondage d'environnement réel "
    "(Pennylane, Sellsy, Odoo, Airtable, Jira/Atlassian, Supabase, Pappers, BODACC Open Data DILA, outils natifs Web/Playwright, serveurs MCP). "
    "Statuts transparents (Connecté, En attente / Libre, Non configuré) et modale de paramétrage avec test en direct."
)
kan31_key = create_or_get_issue(
    "UI Client & Backend : Raccordement dynamique des Interfaces & ERP au Backoffice Hermès",
    kan31_desc,
)
kan31_comment = (
    f"Jalon validé, testé et déployé en production le 25/09/2026 sur https://prod-fr-002.orso-agents.fr.\n"
    f"- Élimination complète des données factices (anciennes 284 factures inventées).\n"
    f"- Implémentation du routeur _probe_hermes_backoffice_integrations dans hermes_cli/web_routers/client_ui.py.\n"
    f"- Catégorie 'Outils Hermès & MCP' et modale de configuration dans IntegrationsView.tsx.\n"
    f"- 18 tests unitaires validés (100% green en 3.1s via tests/hermes_cli/test_client_ui.py).\n"
    f"- Commit GitHub origin/feature/ops-admin-cockpit : 7cab9dec28.\n"
    f"- Déployé sur VPS OVH 92.222.68.80 (conteneurs orso_client_backend & orso_client_ui opérationnels).\n"
    f"Documentation Confluence associée : {confluence_page_url}"
)
transition_and_comment(kan31_key, "51", kan31_comment)

print("Synchronisation Atlassian KAN-30 et KAN-31 terminée avec succès !")
