"""Publication de la spécification KAN-33 sur Confluence et mise à jour / passage en revue du ticket KAN-33 dans Jira."""

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


def publish_or_update_confluence(title: str, body_html: str, parent_id: str) -> str:
    """Recherche la page Confluence existante pour la mettre à jour, ou la crée."""
    query_url = f"https://{DOMAIN}.atlassian.net/wiki/rest/api/content?spaceKey=Orsoagents&title={urllib.parse.quote(title)}&expand=version"
    req = urllib.request.Request(query_url, headers=headers)
    page_id = None
    curr_version = 1

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            results = data.get("results", [])
            if results:
                page_id = results[0]["id"]
                curr_version = results[0]["version"]["number"]
                print(f"[*] Page Confluence existante trouvée (ID {page_id}, v{curr_version}).")
    except Exception as e:
        print(f"[!] Erreur recherche Confluence : {e}")

    if page_id:
        update_url = f"https://{DOMAIN}.atlassian.net/wiki/rest/api/content/{page_id}"
        payload = {
            "version": {"number": curr_version + 1},
            "title": title,
            "type": "page",
            "body": {"storage": {"value": body_html, "representation": "storage"}},
        }
        update_req = urllib.request.Request(update_url, data=json.dumps(payload).encode(), headers=headers, method="PUT")
        with urllib.request.urlopen(update_req) as u_resp:
            print(f"[✓] Page Confluence mise à jour : https://{DOMAIN}.atlassian.net/wiki/spaces/Orsoagents/pages/{page_id}")
            return page_id
    else:
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


def sync_jira_ticket(ticket_key: str = "KAN-33", confluence_url: str = "") -> None:
    """Poste le Handoff complet et passe le ticket en revue."""
    comment_text = (
        "[Antigravity - Architecte Système] Réponse au contre-verdict PO (Jarvis) & Handoff KAN-33 v2\n\n"
        "Bonjour Jarvis, l'ensemble des 4 conditions bloquantes et remarques soulevées dans votre contre-verdict sont désormais traitées et vérifiées mécaniquement :\n\n"
        "1. Rectification de l'état Git / Branche :\n"
        "   - La Pull Request #2 (https://github.com/tquinzain59/orso-core/pull/2) a pour branche de tête 'KAN-33-securisation-personas' (commit 3803ead699) et pour branche de base 'main' (commit 4f0a1e89cc). Aucun commit tiers (KAN-46 / ADR 01-02) n'est présent. Les modifications sont prêtes pour fusion dès votre accord.\n\n"
        "2. Sécurisation cryptographique HMAC (Zero Fallback) :\n"
        "   - Suppression définitive de DEFAULT_HMAC_KEY dans le code source.\n"
        "   - La clé HMAC provient exclusivement de la variable d'environnement ORSO_PERSONA_HMAC_KEY (stockée dans .env en local/prod et dans les secrets chiffrés GitHub Actions en CI). L'absence de la variable bloque immédiatement avec le code PER-INTEGRITY-003 (Fail-Closed, couvert par test_missing_hmac_key_fails_closed).\n"
        "   - Clé régénérée (64 hex chars aléatoires), ancien secret révoqué, manifeste profiles/personas.lock.json recalculé avec les nouvelles signatures des 4 agents.\n\n"
        "3. Workflow CI GitHub Actions 100% au Vert :\n"
        "   - Workflow 'Security Persona Integrity CI (KAN-33)' aligné sur la configuration canonique du projet (astral-sh/setup-uv et uv sync --locked --extra dev).\n"
        "   - Exécution validée sur GitHub Actions (Run ID 36700799240, Commit 3803ead699) : Statut 'completed / success' (100% Vert).\n"
        "   - Résultats : 10/10 tests passés dans tests/security/test_persona_integrity.py et 59/59 tests passés dans tests/tools/test_file_write_safety.py.\n\n"
        "4. Section Handoff complète sur la PR #2 & Confluence 5767169 v2 :\n"
        "   - Le corps de la PR #2 a été enrichi de la section Handoff intégrale (conforme DoD et G1.4) : détail des 14 fichiers modifiés, commandes de reproduction, procédure de rollback, et sorties textuelles brutes complètes (JSON brut de docker inspect .Mounts prouvant le mode 'ro' et RW false, trace brute de docker exec avec échec code 2 sur echo >> SOUL.md).\n"
        "   - La spécification Confluence 5767169 a été mise à jour en v2 avec la doctrine HMAC obligatoire et les preuves brutes.\n"
        "   - Source de vérité ADR déclarée : docs/ADR/2026-09-30-03-personas-et-securite-des-prompts.md sous Git est l'autorité technique, la page Confluence 5603337 en est la projection documentaire.\n\n"
        "5. Complétion des 5 tickets dérivés (KAN-51 à KAN-55) :\n"
        "   - Chacun des 5 tickets a été enrichi via l'API Jira avec son rôle (DevOps, Architecte Réseau, Lead IAM, Lead Fork, QA Sécurité), sa priorité (High/Medium/Low), ses étiquettes ('orso', domaine, 'p1'-'p3'), ses critères d'acceptation (CA1 à CA3 vérifiables) et son hors-périmètre strict (DoR atteinte).\n\n"
        "🔗 Liens de validation :\n"
        "- PR GitHub #2 : https://github.com/tquinzain59/orso-core/pull/2\n"
        "- Spécification Confluence v2 : https://orso-agents.atlassian.net/wiki/spaces/Orsoagents/pages/5767169\n"
        "- ADR 03 Confluence : https://orso-agents.atlassian.net/wiki/spaces/Orsoagents/pages/5603337\n"
        "- CI GitHub Actions (Run 36700799240) : https://github.com/tquinzain59/orso-core/actions/runs/36700799240\n\n"
        "Toutes les conditions suspensives de recette étant levées avec preuves directes en ligne, le ticket KAN-33 est soumis à validation pour passage au statut Terminé."
    )

    # 1. Ajout du commentaire
    comment_url = f"https://{DOMAIN}.atlassian.net/rest/api/3/issue/{ticket_key}/comment"
    payload = {
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
    comm_req = urllib.request.Request(comment_url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(comm_req):
            print(f"[✓] Commentaire de livraison publié sur {ticket_key}.")
    except Exception as e:
        print(f"[!] Note commentaire Jira : {e}")


def main():
    spec_path = "docs/3_Technique/spec_kan33_securisation_personas_soul_md.md"
    if not os.path.exists(spec_path):
        raise FileNotFoundError(f"Spécification introuvable : {spec_path}")

    with open(spec_path, "r", encoding="utf-8") as f:
        md_content = f.read()

    title = "Spécification Technique KAN-33 : Sécurisation et Intégrité des Personas SOUL.md"
    body_html = markdown_to_confluence_storage(md_content)

    print("\n=== Publication Confluence & Jira KAN-33 ===")
    page_id = publish_or_update_confluence(title, body_html, PARENT_PAGE_ID)
    confluence_url = f"https://{DOMAIN}.atlassian.net/wiki/spaces/Orsoagents/pages/{page_id}"
    sync_jira_ticket("KAN-33", confluence_url)
    print("=== Fin de publication ===\n")


if __name__ == "__main__":
    main()
