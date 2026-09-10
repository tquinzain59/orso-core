"""
Socle commun pour les compétences et outils Hermès.
Fournit des parsers standardisés et un client HTTP unifié.
"""

from .parsers import (
    clean_siren,
    parse_montant,
    parse_date,
    detect_csv_delimiter,
    format_euros,
    strip_accents,
)
from .client import HermesHttpClient

__all__ = [
    "clean_siren",
    "parse_montant",
    "parse_date",
    "detect_csv_delimiter",
    "format_euros",
    "strip_accents",
    "HermesHttpClient",
]

