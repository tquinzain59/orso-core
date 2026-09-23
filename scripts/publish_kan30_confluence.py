"""Publication de la spécification KAN-30 et mise à jour du journal des réalisations sur Confluence."""

import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dotenv import load_dotenv

load_dotenv(".env")

EMAIL = os.environ.get("ATLASSIAN_EMAIL")
TOKEN = os.environ.get("ATLASSIAN_API_TOKEN")
DOMAIN = os.environ.get("ATLASSIAN_DOMAIN", "orso-agents")
PARENT_TECH_PAGE_ID = "98352"  # 2. Technique et architecture
JOURNAL_PAGE_ID = "131600"  # 21. Journal des réalisations

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


def publish_or_update_page(title: str, body_html: str, parent_id: str) -> str:
    """Crée ou met à jour une page Confluence."""
    check_url = f"https://{DOMAIN}.atlassian.net/wiki/rest/api/content?spaceKey=Orsoagents&title={urllib.parse.quote(title)}"
    check_req = urllib.request.Request(check_url, headers=headers)
    with urllib.request.urlopen(check_req) as resp:
        search_data = json.loads(resp.read().decode())

    existing_pages = search_data.get("results", [])

    if existing_pages:
        page_id = existing_pages[0]["id"]
        curr_ver = existing_pages[0]["version"]["number"]
        print(f"[*] Mise à jour de '{title}' (ID {page_id}, v{curr_ver} -> v{curr_ver + 1})...")
        update_data = {
            "version": {"number": curr_ver + 1},
            "title": title,
            "type": "page",
            "body": {"storage": {"value": body_html, "representation": "storage"}},
        }
        update_req = urllib.request.Request(
            f"https://{DOMAIN}.atlassian.net/wiki/rest/api/content/{page_id}",
            data=json.dumps(update_data).encode(),
            headers=headers,
            method="PUT",
        )
        with urllib.request.urlopen(update_req) as u_resp:
            json.loads(u_resp.read().decode())
            url = f"https://{DOMAIN}.atlassian.net/wiki/spaces/Orsoagents/pages/{page_id}"
            print(f"[+] Page mise à jour : {url}")
            return url
    else:
        print(f"[*] Création de la page '{title}'...")
        create_data = {
            "type": "page",
            "title": title,
            "ancestors": [{"id": parent_id}],
            "space": {"key": "Orsoagents"},
            "body": {"storage": {"value": body_html, "representation": "storage"}},
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
            url = f"https://{DOMAIN}.atlassian.net/wiki/spaces/Orsoagents/pages/{page_id}"
            print(f"[+] Page créée avec succès : {url}")
            return url


def update_journal_page():
    """Met à jour la page 131600 (Journal des réalisations)."""
    with open("docs/21_journal_realisations_orso.md", "r", encoding="utf-8") as f:
        journal_md = f.read()

    storage_html = markdown_to_confluence_storage(journal_md)
    get_url = f"https://{DOMAIN}.atlassian.net/wiki/rest/api/content/{JOURNAL_PAGE_ID}"
    req = urllib.request.Request(get_url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        page_info = json.loads(resp.read().decode())
        curr_ver = page_info["version"]["number"]
        page_title = page_info["title"]

    print(f"[*] Mise à jour de la page Journal ID {JOURNAL_PAGE_ID} (v{curr_ver} -> v{curr_ver + 1})...")
    update_data = {
        "version": {"number": curr_ver + 1},
        "title": page_title,
        "type": "page",
        "body": {"storage": {"value": storage_html, "representation": "storage"}},
    }
    update_req = urllib.request.Request(
        f"https://{DOMAIN}.atlassian.net/wiki/rest/api/content/{JOURNAL_PAGE_ID}",
        data=json.dumps(update_data).encode(),
        headers=headers,
        method="PUT",
    )
    with urllib.request.urlopen(update_req) as u_resp:
        json.loads(u_resp.read().decode())
        url = f"https://{DOMAIN}.atlassian.net/wiki/spaces/Orsoagents/pages/{JOURNAL_PAGE_ID}"
        print(f"[+] Journal Confluence mis à jour : {url}")
        return url


def main():
    # 1. Publication de la spécification KAN-30
    spec_path = "docs/3_Technique/spec_kan30_ops_cockpit_iam.md"
    with open(spec_path, "r", encoding="utf-8") as f:
        spec_md = f.read()

    spec_html = markdown_to_confluence_storage(spec_md)
    page_title = "KAN-30 - Spec : Cockpit Orso Ops, Facturation Stripe & Authentification IAM Superadmin"
    spec_url = publish_or_update_page(page_title, spec_html, PARENT_TECH_PAGE_ID)

    # 2. Mise à jour de la page Journal des Réalisations
    journal_url = update_journal_page()

    print("\n" + "=" * 60)
    print("DOCUMENTATION CONFLUENCE SYNCHRONISÉE AVEC SUCCÈS")
    print(f"-> Spécification KAN-30 : {spec_url}")
    print(f"-> Journal des réalisations : {journal_url}")
    print("=" * 60)


if __name__ == "__main__":
    main()
