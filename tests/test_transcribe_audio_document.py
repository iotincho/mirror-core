from pathlib import Path
from types import SimpleNamespace

from src.services.audio_note_store import FileAudioNoteStore
from src.use_cases.transcribe_audio_note import CreateAudioNote, TranscribeAudioNote


class FakeTranscriber:
    provider_name = "fake"
    model_name = "fake-transcriber"

    def transcribe(self, audio_path: Path) -> str:
        assert audio_path.read_bytes() == b"audio-bytes"
        return "Una reflexión grabada."


class FakeDocumentProcessor:
    def __init__(self, *, fail_once: bool = False) -> None:
        self.fail_once = fail_once
        self.documents = []

    def execute(self, document):
        self.documents.append(document)
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("graph unavailable")
        return SimpleNamespace(document=SimpleNamespace(id=document.id))


def new_note(store: FileAudioNoteStore):
    return CreateAudioNote(store, max_upload_bytes=1024).execute(
        "nota.webm", "audio/webm", b"audio-bytes", None
    )


def test_transcription_creates_a_document_with_audio_provenance(tmp_path: Path) -> None:
    store = FileAudioNoteStore(tmp_path / "audio-notes")
    processor = FakeDocumentProcessor()
    note = new_note(store)

    completed = TranscribeAudioNote(store, FakeTranscriber(), processor).execute(note.id)

    assert completed.status == "completed"
    assert completed.document_id == note.id
    assert completed.document_error is None
    assert processor.documents[0].id == note.id
    assert processor.documents[0].content == "Una reflexión grabada."
    assert processor.documents[0].source == "pwa_audio"
    assert processor.documents[0].metadata["audio_note_id"] == str(note.id)
    assert processor.documents[0].metadata["filename"] == "nota.webm"


def test_completed_audio_can_retry_document_processing_without_retranscribing(
    tmp_path: Path,
) -> None:
    store = FileAudioNoteStore(tmp_path / "audio-notes")
    processor = FakeDocumentProcessor(fail_once=True)
    note = new_note(store)
    use_case = TranscribeAudioNote(store, FakeTranscriber(), processor)

    failed = use_case.execute(note.id)
    completed = use_case.execute(note.id)

    assert failed.status == "completed"
    assert failed.document_id is None
    assert failed.document_error == "document_processing_failed"
    assert completed.document_id == note.id
    assert len(processor.documents) == 2
