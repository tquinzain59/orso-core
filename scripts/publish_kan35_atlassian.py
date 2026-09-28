"""Publication de la spécification KAN-35 sur Confluence et création / clôture du ticket KAN-35 dans Jira."""

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
            cols = [c.strip() for c in line.split("|")[1:-1]]
            if all(re.match(r"^:?-+:?$", c) for c in cols):
                continue
            if not in_table:
                html_lines.append("<table><tbody>")
                in_table = True
                html_lines.append("<tr>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr>")
            else:
                html_lines.append("<tr>" + "".join(f"<td>{c}</td>" for c in cols) + "</tr>")
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


def publish_or_update_confluence(title: str, body_html: str, parent_id: str) -> str:
    """Crée ou met à jour la page de spécification sur Confluence."""
    search_url = f"https://{DOMAIN}.atlassian.net/wiki/rest/api/content?spaceKey=Orsoagents&title={urllib.parse.quote(title)}"
    req = urllib.request.Request(search_url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        results = json.loads(resp.read().decode()).get("results", [])

    if results:
        page_id = results[0]["id"]
        version = results[0]["version"]["number"] + 1
        print(f"[*] Mise à jour de la page existante '{title}' (ID: {page_id}, v{version})...")
        update_url = f"https://{DOMAIN}.atlassian.net/wiki/rest/api/content/{page_id}"
        payload = {
            "id": page_id,
            "type": "page",
            "title": title,
            "version": {"number": version},
            "body": {"storage": {"value": body_html, "representation": "storage"}},
        }
        update_req = urllib.request.Request(update_url, data=json.dumps(payload).encode(), headers=headers, method="PUT")
        with urllib.request.urlopen(update_req) as update_resp:
            res = json.loads(update_resp.read().decode())
            print(f"[✓] Page Confluence mise à jour : https://{DOMAIN}.atlassian.net/wiki/spaces/Orsoagents/pages/{page_id}")
            return page_id
    else:
        print(f"[*] Création de la page '{title}' sous le parent {parent_id}...")
        create_url = f"https://{DOMAIN}.atlassian.net/wiki/rest/api/content"
        payload = {
            "type": "page",
            "title": title,
            "ancestors": [{"id": parent_id}],
            "space": {"key": "Orsoagents"},
            "body": {"storage": {"value": body_html, "representation": "storage"}},
        }
        create_req = urllib.request.Request(create_url, data=json.dumps(payload).encode(), headers=headers, method="POST")
        with urllib.request.urlopen(create_req) as create_resp:
            res = json.loads(create_resp.read().decode())
            page_id = res["id"]
            print(f"[✓] Nouvelle page Confluence créée : https://{DOMAIN}.atlassian.net/wiki/spaces/Orsoagents/pages/{page_id}")
            return page_id


def sync_jira_ticket(ticket_key: str = "KAN-35") -> None:
    """Crée ou met à jour le ticket KAN-35 dans Jira et le passe à Terminé."""
    jira_url = f"https://{DOMAIN}.atlassian.net/rest/api/3/issue/{ticket_key}"
    req = urllib.request.Request(jira_url, headers=headers)
    exists = False
    try:
        with urllib.request.urlopen(req) as resp:
            if resp.status == 200:
                exists = True
                print(f"[*] Ticket Jira {ticket_key} déjà existant.")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            exists = False
        else:
            print(f"[!] Erreur consultation Jira: {e}")

    summary = "Accès Machine Drone de Test au Cockpit OPS et Périmètre des Surfaces (Client-X-Orso)"
    desc_adf = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "Préparation et sécurisation d'un accès machine « drone » au cockpit OPS pour le mandat d'automatisation Client-X-Orso (Least Privilege, scopes stricts, quotas, destruction idempotente, vérification webhooks Stripe et étanchéité client).",
                    }
                ],
            }
        ],
    }

    if not exists:
        print(f"[*] Création du ticket {ticket_key} dans Jira...")
        create_issue_url = f"https://{DOMAIN}.atlassian.net/rest/api/3/issue"
        create_payload = {
            "fields": {
                "project": {"key": "KAN"},
                "summary": summary,
                "description": desc_adf,
                "issuetype": {"name": "Task"},
            }
        }
        create_req = urllib.request.Request(create_issue_url, data=json.dumps(create_payload).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(create_req) as resp:
                created = json.loads(resp.read().decode())
                print(f"[✓] Ticket Jira créé : {created.get('key')}")
                ticket_key = created.get("key", ticket_key)
        except Exception as e:
            print(f"[!] Note création Jira : {e}")

    # Transition vers 'Terminé'
    try:
        trans_url = f"https://{DOMAIN}.atlassian.net/rest/api/3/issue/{ticket_key}/transitions"
        trans_req = urllib.request.Request(trans_url, headers=headers)
        with urllib.request.urlopen(trans_req) as resp:
            trans_data = json.loads(resp.read().decode())
            done_transitions = [t for t in trans_data.get("transitions", []) if t["to"]["name"].lower() in ("done", "terminé", "fermé", "closed")]
            if done_transitions:
                target_trans = done_transitions[0]
                post_trans_req = urllib.request.Request(
                    trans_url,
                    data=json.dumps({"transition": {"id": target_trans["id"]}}).encode(),
                    headers=headers,
                    method="POST",
                )
                with urllib.request.urlopen(post_trans_req):
                    print(f"[✓] Ticket {ticket_key} passé en statut '{target_trans['to']['name']}'.")
    except Exception as e:
        print(f"[!] Note transition Jira : {e}")


def main():
    spec_path = "docs/3_Technique/spec_kan35_acces_drone_test_ops.md"
    if not os.path.exists(spec_path):
        raise FileNotFoundError(f"Spécification introuvable : {spec_path}")

    with open(spec_path, "r", encoding="utf-8") as f:
        md_content = f.read()

    title = "Spécification Technique KAN-35 : Accès Drone Machine de Test & Périmètre OPS"
    body_html = markdown_to_confluence_storage(md_content)

    print("\n=== Publication Confluence & Jira KAN-35 ===")
    page_id = publish_or_update_confluence(title, body_html, PARENT_PAGE_ID)
    sync_jira_ticket("KAN-35")
    print("=== Fin de publication ===\n")


if __name__ == "__main__":
    main()
