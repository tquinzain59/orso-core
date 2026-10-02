#!/usr/bin/env python3
"""Publication de la spécification KAN-59 sur Confluence (page ID 6946818) avec parser XHTML propre (0 raw **)."""

import os
import re
import base64
import json
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if (PROJECT_ROOT / ".env").exists():
    with open(PROJECT_ROOT / ".env", "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))

EMAIL = os.environ.get("ATLASSIAN_EMAIL")
TOKEN = os.environ.get("ATLASSIAN_API_TOKEN")
DOMAIN = os.environ.get("ATLASSIAN_DOMAIN", "orso-agents")
TARGET_PAGE_ID = "6946818"

if not EMAIL or not TOKEN:
    raise ValueError("Identifiants Atlassian manquants dans .env")

auth_str = base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()
headers = {
    "Authorization": f"Basic {auth_str}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def format_inline(text: str) -> str:
    """Formatte le Markdown inline en XHTML Confluence valide (0 résidu ** ou markdown brut)."""
    # Échappement XML
    t = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Code inline: `code`
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    # Math blocks: $$...$$ ou $...$
    t = re.sub(r"\$\$([^\$]+)\$\$", r"<code>\1</code>", t)
    t = re.sub(r"\$([^\$]+)\$", r"<code>\1</code>", t)
    # Bold: **bold**
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    # Italic: *italic* or _italic_
    t = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", t)
    # Links: [text](url)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', t)
    return t


def markdown_to_confluence_storage(md_text: str) -> str:
    """Conversion propre et robuste du Markdown vers le format de stockage XHTML Confluence."""
    lines = md_text.splitlines()
    html_lines = []
    in_code_block = False
    code_lang = ""
    code_content = []
    in_table = False
    list_type = None  # "ul" or "ol"
    in_macro = False
    macro_content = []
    macro_name = "info"

    def close_list():
        nonlocal list_type
        if list_type == "ul":
            html_lines.append("</ul>")
            list_type = None
        elif list_type == "ol":
            html_lines.append("</ol>")
            list_type = None

    def close_table():
        nonlocal in_table
        if in_table:
            html_lines.append("</tbody></table>")
            in_table = False

    def close_macro():
        nonlocal in_macro, macro_content, macro_name
        if in_macro:
            body = "".join(f"<p>{format_inline(p)}</p>" for p in macro_content if p.strip())
            html_lines.append(
                f'<ac:structured-macro ac:name="{macro_name}">'
                f'<ac:rich-text-body>{body}</ac:rich-text-body>'
                f'</ac:structured-macro>'
            )
            in_macro = False
            macro_content = []

    for line in lines:
        stripped = line.strip()

        # 1. Blocs de code
        if stripped.startswith("```"):
            close_list()
            close_table()
            close_macro()
            if in_code_block:
                escaped_code = "\n".join(code_content).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                html_lines.append(
                    f'<ac:structured-macro ac:name="code"><ac:parameter ac:name="language">{code_lang or "text"}</ac:parameter>'
                    f'<ac:plain-text-body><![CDATA[{escaped_code}]]></ac:plain-text-body></ac:structured-macro>'
                )
                in_code_block = False
                code_content = []
                code_lang = ""
            else:
                in_code_block = True
                code_lang = stripped[3:].strip()
            continue

        if in_code_block:
            code_content.append(line)
            continue

        # 2. Admonitions / Callouts (> [!IMPORTANT], > [!NOTE], etc.)
        if stripped.startswith("> [!"):
            close_list()
            close_table()
            close_macro()
            alert_tag = stripped[4:].split("]")[0].strip().upper()
            macro_name = "warning" if alert_tag in ("WARNING", "CAUTION", "IMPORTANT") else "info"
            in_macro = True
            macro_content = []
            continue

        if in_macro:
            if stripped.startswith(">"):
                macro_content.append(stripped.lstrip("> ").strip())
                continue
            else:
                close_macro()

        # 3. Lignes horizontales
        if stripped in ("---", "***", "___"):
            close_list()
            close_table()
            close_macro()
            html_lines.append("<hr/>")
            continue

        # 4. Tables Markdown
        if stripped.startswith("|") and stripped.endswith("|"):
            close_list()
            close_macro()
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            # Ligne de séparation (| :--- | :---: |)
            if all(set(c).issubset({"-", ":", " "}) for c in cells):
                continue
            if not in_table:
                html_lines.append("<table><tbody>")
                in_table = True
                html_lines.append("<tr>" + "".join(f"<th>{format_inline(c)}</th>" for c in cells) + "</tr>")
            else:
                html_lines.append("<tr>" + "".join(f"<td>{format_inline(c)}</td>" for c in cells) + "</tr>")
            continue
        else:
            close_table()

        # 5. Ligne vide
        if not stripped:
            close_list()
            close_macro()
            continue

        # 6. Titres (Headings)
        if stripped.startswith("# "):
            close_list()
            html_lines.append(f"<h1>{format_inline(stripped[2:].strip())}</h1>")
        elif stripped.startswith("## "):
            close_list()
            html_lines.append(f"<h2>{format_inline(stripped[3:].strip())}</h2>")
        elif stripped.startswith("### "):
            close_list()
            html_lines.append(f"<h3>{format_inline(stripped[4:].strip())}</h3>")
        elif stripped.startswith("#### "):
            close_list()
            html_lines.append(f"<h4>{format_inline(stripped[5:].strip())}</h4>")

        # 7. Listes à puces (- ou *)
        elif stripped.startswith("- ") or stripped.startswith("* "):
            if list_type != "ul":
                close_list()
                html_lines.append("<ul>")
                list_type = "ul"
            html_lines.append(f"<li>{format_inline(stripped[2:].strip())}</li>")

        # 8. Listes ordonnées (1. , 2. )
        elif re.match(r"^\d+\.\s+", stripped):
            if list_type != "ol":
                close_list()
                html_lines.append("<ol>")
                list_type = "ol"
            item_content = re.sub(r"^\d+\.\s+", "", stripped)
            html_lines.append(f"<li>{format_inline(item_content)}</li>")

        # 9. Paragraphe standard
        else:
            close_list()
            html_lines.append(f"<p>{format_inline(stripped)}</p>")

    close_list()
    close_table()
    close_macro()

    return "\n".join(html_lines)


def update_target_confluence_page(page_id: str, title: str, storage_html: str):
    """Met à jour directement la page Confluence cible par son ID."""
    get_url = f"https://{DOMAIN}.atlassian.net/wiki/rest/api/content/{page_id}?expand=version,ancestors,space"
    req = urllib.request.Request(get_url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())
        current_version = data["version"]["number"]
        page_title = title or data.get("title")
        space_key = data.get("space", {}).get("key", "Orsoagents")

    put_url = f"https://{DOMAIN}.atlassian.net/wiki/rest/api/content/{page_id}"
    payload = {
        "id": page_id,
        "type": "page",
        "title": page_title,
        "space": {"key": space_key},
        "version": {"number": current_version + 1},
        "body": {
            "storage": {
                "value": storage_html,
                "representation": "storage",
            }
        },
    }

    put_req = urllib.request.Request(
        put_url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="PUT",
    )
    with urllib.request.urlopen(put_req) as resp:
        result = json.loads(resp.read().decode())
        print(f"[✓] Page Confluence {page_id} mise à jour avec succès (nouvelle version: {result['version']['number']})")
        print(f"[✓] URL : https://{DOMAIN}.atlassian.net/wiki/spaces/{space_key}/pages/{page_id}")


def main():
    spec_path = PROJECT_ROOT / "docs" / "3_Technique" / "spec_kan59_quotas_ressources_capacite_hote.md"
    if not spec_path.exists():
        raise FileNotFoundError(f"Spécification introuvable : {spec_path}")

    md_content = spec_path.read_text(encoding="utf-8")
    title = "Spécification Technique KAN-59 : Quotas de Ressources & Refus de Provisioning au-delà de la Capacité Hôte"
    storage_html = markdown_to_confluence_storage(md_content)

    print(f"[*] Mise à jour de la page Confluence ID {TARGET_PAGE_ID}...")
    update_target_confluence_page(TARGET_PAGE_ID, title, storage_html)


if __name__ == "__main__":
    main()
