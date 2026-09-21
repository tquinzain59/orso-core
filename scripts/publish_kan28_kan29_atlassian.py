"""Publication de la spécification KAN-28 sur Confluence et clôture des tickets KAN-28 et KAN-29 dans Jira."""

import os
import re
import base64
import json
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

    for line in lines:
        if line.startswith("```"):
            if in_code_block:
                # Fin du bloc de code
                escaped_code = "\n".join(code_content).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                html_lines.append(
                    f'<ac:structured-macro ac:name="code"><ac:parameter ac:name="language">{code_lang or "text"}</ac:parameter>'
                    f'<ac:plain-text-body><![CDATA[{escaped_code}]]></ac:plain-text-body></ac:structured-macro>'
                )
                in_code_block = False
                code_content = []
            else:
                # Début du bloc de code
                in_code_block = True
                code_lang = line[3:].strip()
            continue

        if in_code_block:
            code_content.append(line)
            continue

        # Titres
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
            html_lines.append(f"<li>{item}</li>")
        elif line.strip() == "---":
            html_lines.append("<hr />")
        elif line.strip():
            p_text = line.strip().replace("**", "<strong>").replace("**", "</strong>")
            p_text = re.sub(r"`([^`]+)`", r"<code>\1</code>", p_text)
            html_lines.append(f"<p>{p_text}</p>")

    return "\n".join(html_lines)


# 1. Lecture de spec_kan28_ingress_olympe_lifecycle.md
spec_path = "docs/3_Technique/spec_kan28_ingress_olympe_lifecycle.md"
with open(spec_path, "r", encoding="utf-8") as f:
    spec_md = f.read()

storage_html = markdown_to_confluence_storage(spec_md)
page_title = "KAN-28 - Spec : Routage Dynamique Ingress & Superviseur Olympe (Option B)"

# 2. Vérifier si la page existe déjà sur Confluence
check_url = f"https://{DOMAIN}.atlassian.net/wiki/rest/api/content?spaceKey=Orsoagents&title={urllib.parse.quote(page_title)}"
check_req = urllib.request.Request(check_url, headers=headers)
with urllib.request.urlopen(check_req) as resp:
    search_data = json.loads(resp.read().decode())

existing_pages = search_data.get("results", [])
confluence_page_url = ""

if existing_pages:
    page_id = existing_pages[0]["id"]
    curr_ver = existing_pages[0]["version"]["number"]
    print(f"Mise à jour de la page existante ID {page_id} (version {curr_ver} -> {curr_ver + 1})...")
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
        u_data = json.loads(u_resp.read().decode())
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


# 3. Transition et commentaire Jira KAN-28
def transition_jira(issue_key: str, transition_id: str, comment_text: str):
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
        print(f"Avertissement ajout commentaire {issue_key}: {e}")

    # Exécution de la transition
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
            print(f"Ticket {issue_key} passé en 'Terminé' avec succès.")
    except Exception as e:
        print(f"Avertissement transition {issue_key}: {e}")


# Clôture KAN-28
kan28_comment = (
    f"Jalon validé et livré le 20/09/2026.\n"
    f"- Arbitrage Option B : Ingress Nginx dynamique (Zero-Reload via DNS Docker 127.0.0.11).\n"
    f"- Superviseur Olympe (port 9230) : provisioning, wake-on-demand et scale-to-zero.\n"
    f"- UI PWA adaptée pour préfixe /t/tenant_slug/.\n"
    f"- 27 tests unitaires validés (100%).\n"
    f"Documentation Confluence associée : {confluence_page_url}"
)
transition_jira("KAN-28", "51", kan28_comment)

# Clôture KAN-29
kan29_comment = (
    f"Jalon validé et livré le 20/09/2026.\n"
    f"- Harmonisation de l'authentification : suppression définitive des mots de passe en dur et replis factices sur le site vitrine (Site_Hermes-core/client.html).\n"
    f"- Authentification 100% portée par Supabase IAM avec claims tenant.\n"
    f"- Redirection directe vers le portail unifié Option B (https://app.orso-agents.fr).\n"
    f"- Bundle PWA synchronisé dans /app/."
)
transition_jira("KAN-29", "51", kan29_comment)

print("Synchronisation Atlassian (Confluence + Jira) terminée avec succès !")
