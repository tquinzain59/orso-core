"""
Utilitaires de normalisation et d'analyse de données financières et comptables.
"""

import re
from datetime import datetime, date
from typing import Any, Optional


def clean_siren(siren: Any) -> Optional[str]:
    """
    Nettoie et valide un numéro SIREN (9 chiffres).
    Retourne la chaîne normalisée ou None si invalide.
    """
    if not siren:
        return None
    cleaned = re.sub(r"[\s\.\-_]", "", str(siren)).strip()
    if len(cleaned) == 9 and cleaned.isdigit():
        return cleaned
    return None


def parse_montant(val: Any, default: float = 0.0) -> float:
    """
    Parse et normalise un montant monétaire en flottant.
    Gère les devises (€, EUR), les espaces ordinaires et insécables,
    et les conventions de séparateurs françaises ("1 250,50") ou anglo-saxonnes ("1250.50").
    """
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)

    s = str(val).strip().upper()
    s = s.replace("EUR", "").replace("€", "").replace("$", "")
    # Espaces insécables, fines ou ordinaires
    s = s.replace("\u00a0", "").replace("\u202f", "").replace(" ", "")

    if not s:
        return default

    # Détection des séparateurs
    if "," in s and "." in s:
        # Ex: "1,250.50" (EN) vs "1.250,50" (FR/DE)
        if s.rfind(",") > s.rfind("."):
            # Format FR: point pour milliers, virgule pour décimales
            s = s.replace(".", "").replace(",", ".")
        else:
            # Format EN: virgule pour milliers, point pour décimales
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")

    try:
        return float(s)
    except (ValueError, TypeError):
        return default


def parse_date(val: Any, fallback: Optional[date] = None) -> Optional[date]:
    """
    Parse une date issue d'un export ERP, CSV ou API vers un objet datetime.date.
    Supporte les formats courants : ISO (YYYY-MM-DD), FR (DD/MM/YYYY, DD-MM-YYYY), etc.
    Retourne `fallback` si le parsing échoue.
    """
    if val is None:
        return fallback
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val

    s = str(val).strip()[:10]
    formats = (
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y/%m/%d",
        "%d.%m.%Y",
        "%d%m%Y",
    )
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).date()
        except (ValueError, TypeError):
            continue

    return fallback


def detect_csv_delimiter(filepath: str, default: str = ";") -> str:
    """
    Détecte automatiquement le séparateur d'un fichier CSV (virgule ou point-virgule).
    Donne la priorité au point-virgule (courant dans les exports comptables FR) si présent.
    """
    try:
        with open(filepath, "r", encoding="utf-8-sig", errors="replace") as f:
            first_line = f.readline()
            if not first_line:
                return default
            # Comptage des séparateurs potentiels
            count_semicolon = first_line.count(";")
            count_comma = first_line.count(",")
            count_tab = first_line.count("\t")

            if count_semicolon > count_comma and count_semicolon > count_tab:
                return ";"
            if count_comma > count_semicolon and count_comma > count_tab:
                return ","
            if count_tab > 0:
                return "\t"
    except Exception:
        pass
    return default


def format_euros(val: Any) -> str:
    """
    Formate un montant numérique au standard monétaire français (ex: 1 250,50 €).
    """
    if val is None:
        return "N/A"
    try:
        flt = float(val)
        return f"{flt:,.2f} €".replace(",", " ").replace(".", ",")
    except (ValueError, TypeError):
        return str(val)


def strip_accents(text: Any) -> str:
    """
    Supprime les accents et met en minuscules un texte pour faciliter la recherche de colonnes.
    Exemple: 'Date Échéance' -> 'date echeance'
    """
    import unicodedata
    if text is None:
        return ""
    normalized = unicodedata.normalize("NFKD", str(text))
    ascii_bytes = normalized.encode("ascii", "ignore")
    return ascii_bytes.decode("utf-8").lower().strip()

