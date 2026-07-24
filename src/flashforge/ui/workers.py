"""QThread workers for generation, import, regeneration, template sync, and deck loading."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from PySide6.QtCore import QObject, Signal

from flashforge.anki import AnkiConnectClient, AnkiConnectError, ImportResult
from flashforge.config import AppSettings
from flashforge.models import Flashcard
from flashforge.pipeline import CardPipeline


class GenerationWorker(QObject):
    generated = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        settings: AppSettings,
        material: str,
        image_path: Path | None = None,
        document_mode: bool = False,
        socratopia_mode: bool = False,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.material = material
        self.image_path = image_path
        self.document_mode = document_mode
        self.socratopia_mode = socratopia_mode

    def run(self) -> None:
        try:
            pipeline = CardPipeline(self.settings)
            cards = (
                pipeline.generate_from_image(self.image_path)
                if self.image_path is not None
                else pipeline.generate_from_text(
                    self.material,
                    document_mode=self.document_mode,
                    socratopia_mode=self.socratopia_mode,
                )
            )
            self.generated.emit(cards)
        except Exception as exc:  # Exposed to the user without terminating the Qt event loop.
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class ImportWorker(QObject):
    progressed = Signal(int, int)
    imported = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, settings: AppSettings, cards: Sequence[Flashcard]) -> None:
        super().__init__()
        self.settings = settings
        self.cards = list(cards)

    def run(self) -> None:
        try:
            result = CardPipeline(self.settings).import_to_anki(self.cards, self.progressed.emit)
            self.imported.emit(result)
        except Exception as exc:  # Exposed to the user without terminating the Qt event loop.
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class RegenerationWorker(QObject):
    regenerated = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        settings: AppSettings,
        card: Flashcard,
        feedback: str,
        material: str,
        image_path: Path | None,
        document_mode: bool = False,
        socratopia_mode: bool = False,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.card = card
        self.feedback = feedback
        self.material = material
        self.image_path = image_path
        self.document_mode = document_mode
        self.socratopia_mode = socratopia_mode

    def run(self) -> None:
        try:
            card = CardPipeline(self.settings).regenerate_card(
                self.card,
                self.feedback,
                material=self.material,
                image_path=self.image_path,
                document_mode=self.document_mode,
                socratopia_mode=self.socratopia_mode,
            )
            self.regenerated.emit(card)
        except Exception as exc:  # Exposed to the user without terminating the Qt event loop.
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class TemplateSyncWorker(QObject):
    updated = Signal(int)
    failed = Signal(str)
    finished = Signal()

    def run(self) -> None:
        try:
            self.updated.emit(AnkiConnectClient().ensure_and_upgrade_note_types())
        except AnkiConnectError as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class DeckLoadWorker(QObject):
    loaded = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def run(self) -> None:
        try:
            self.loaded.emit(AnkiConnectClient().deck_names())
        except AnkiConnectError as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()
