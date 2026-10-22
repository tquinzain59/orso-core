"""Extraction de texte et découpage en passages (stdlib uniquement)."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import PurePath

DEFAULT_MAX_CHARS = 1000
DEFAULT_OVERLAP = 100

_TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".log", ".yaml", ".yml", ".xml"}
_HTML_SUFFIXES = {".html", ".htm"}


class UnsupportedFormatError(ValueError):
    """Le format n'a pas d'extracteur : refus explicite plutôt qu'un index vide."""


class _TextOnly(HTMLParser):
    _SKIP = {"script", "style"}
    _BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BLOCK:
            self._parts.append("\n\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self._BLOCK:
            self._parts.append("\n\n")

    def handle_data(self, data):
        if not self._skip_depth:
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def extract_text(name: str, data: bytes) -> str:
    """Texte brut d'un document. Lève :class:`UnsupportedFormatError` hors formats textuels/HTML
    (PDF/Office : pas d'extracteur livré, voir le handoff)."""
    suffix = PurePath(name).suffix.lower()
    if suffix not in _TEXT_SUFFIXES and suffix not in _HTML_SUFFIXES:
        raise UnsupportedFormatError(
            f"format non pris en charge pour {name!r} (acceptés : "
            f"{', '.join(sorted(_TEXT_SUFFIXES | _HTML_SUFFIXES))})"
        )
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UnsupportedFormatError(f"{name!r} n'est pas encodé en UTF-8") from exc
    if suffix in _HTML_SUFFIXES:
        parser = _TextOnly()
        parser.feed(text)
        text = html.unescape(parser.text())
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


@dataclass(frozen=True)
class Chunk:
    ordinal: int  # 1-based, c'est le « § » des citations
    text: str


def _windows(paragraph: str, max_chars: int, overlap: int) -> list[str]:
    step = max_chars - overlap
    return [paragraph[i : i + max_chars].strip() for i in range(0, len(paragraph), step)]


def split_text(text: str, max_chars: int = DEFAULT_MAX_CHARS, overlap: int = DEFAULT_OVERLAP) -> list[Chunk]:
    """Découpe par paragraphes, regroupés jusqu'à ``max_chars``. Un paragraphe plus long que la
    limite est coupé en fenêtres avec recouvrement ``overlap``."""
    if max_chars <= 0 or not 0 <= overlap < max_chars:
        raise ValueError("max_chars > 0 et 0 <= overlap < max_chars requis")
    pieces: list[str] = []
    buffer = ""
    for paragraph in (p.strip() for p in re.split(r"\n\s*\n", text)):
        if not paragraph:
            continue
        if len(paragraph) > max_chars:
            if buffer:
                pieces.append(buffer)
                buffer = ""
            pieces.extend(w for w in _windows(paragraph, max_chars, overlap) if w)
        elif buffer and len(buffer) + 2 + len(paragraph) > max_chars:
            pieces.append(buffer)
            buffer = paragraph
        else:
            buffer = f"{buffer}\n\n{paragraph}" if buffer else paragraph
    if buffer:
        pieces.append(buffer)
    return [Chunk(ordinal=i, text=piece) for i, piece in enumerate(pieces, start=1)]
