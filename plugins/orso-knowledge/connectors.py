"""Import depuis des services connectés : le connecteur d'origine est tracé sur chaque version."""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from .store import KnowledgeStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RemoteDocument:
    ref: str  # identifiant stable côté source (chemin, id de fichier...) : sert de clé de version
    name: str
    data: bytes


@dataclass(frozen=True)
class RemoteFailure:
    """Document d'une source que le connecteur n'a pas pu livrer : consigné dans le rapport, les
    autres documents continuent."""

    ref: str
    reason: str


class ConnectorError(RuntimeError):
    """Échec du service connecté (identifiants absents, refus, indisponibilité) : l'import s'arrête."""


class Connector(abc.ABC):
    """Contrat d'un connecteur. Les secrets de la source (jeton Drive, clé de la compta) restent
    dans l'environnement du conteneur désignés par leur nom ; jamais passés en argument ni écrits
    dans l'index."""

    name: str

    @abc.abstractmethod
    def fetch(self) -> Iterator[RemoteDocument | RemoteFailure]: ...


class DirectoryConnector(Connector):
    """Lit un dossier d'export (dossier Drive synchronisé, export comptable déposé). ``name`` est
    le connecteur d'origine inscrit sur les versions (ex. ``google-drive``, ``pennylane``)."""

    def __init__(self, name: str, directory: Path | str) -> None:
        self.name = name
        self.directory = Path(directory)

    def fetch(self) -> Iterator[RemoteDocument]:
        if not self.directory.is_dir():
            raise FileNotFoundError(f"dossier d'export introuvable : {self.directory}")
        for path in sorted(p for p in self.directory.rglob("*") if p.is_file()):
            rel = path.relative_to(self.directory).as_posix()
            yield RemoteDocument(ref=rel, name=path.name, data=path.read_bytes())


@dataclass
class ImportReport:
    connector: str
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)


def import_from(store: KnowledgeStore, connector: Connector) -> ImportReport:
    """Ingère tout ce que livre ``connector``. L'échec d'un document est consigné dans le rapport
    sans interrompre les autres. La clé de version est ``<connecteur>:<ref>`` : ré-importer la même
    référence met à jour le même document."""
    report = ImportReport(connector=connector.name)
    for doc in connector.fetch():
        if isinstance(doc, RemoteFailure):
            logger.warning("import %s : %s non livré (%s)", connector.name, doc.ref, doc.reason)
            report.failed[doc.ref] = doc.reason
            continue
        key = f"{connector.name}:{doc.ref}"
        try:
            result = store.ingest(
                doc.name, doc.data, origin_connector=connector.name, origin_ref=doc.ref, doc_key=key
            )
        except ValueError as exc:
            logger.warning("import %s : %s refusé (%s)", connector.name, doc.ref, exc)
            report.failed[doc.ref] = str(exc)
            continue
        getattr(report, result.status).append(key)
    return report
