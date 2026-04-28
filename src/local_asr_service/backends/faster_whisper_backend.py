from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from local_asr_service.backends.base import ASRBackend, TranscriptionResult
from local_asr_service.schemas import AudioSource, SegmentStatus, Speaker, TranscriptSegment


class FasterWhisperBackend(ASRBackend):
    """faster-whisper backend.

    Skeleton implementation writes incoming bytes to a temp file.
    Later optimization: accept PCM arrays directly where possible.
    """

    def __init__(self, profile):
        super().__init__(profile)
        self._model = None

    def _load_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self.profile.model_name,
                device=self.profile.device,
                compute_type=self.profile.compute_type,
            )
        return self._model

    def transcribe_bytes(
        self,
        data: bytes,
        *,
        language: str = "auto",
        source: AudioSource = AudioSource.UNKNOWN,
        start_ms: int = 0,
    ) -> TranscriptionResult:
        model = self._load_model()
        lang_arg = None if language == "auto" else language
        speaker = Speaker.USER if source == AudioSource.MIC else Speaker.OTHER

        tmp_path: Path | None = None
        try:
            with NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(data)
                tmp_path = Path(tmp.name)

            # PyAV reopens the path internally; on Windows the temp file must be closed first.
            assert tmp_path is not None
            segments_iter, info = model.transcribe(
                str(tmp_path),
                language=lang_arg,
                vad_filter=self.profile.vad_filter,
                beam_size=self.profile.beam_size,
            )

            segments = []
            texts = []
            for seg in segments_iter:
                text = seg.text.strip()
                if not text:
                    continue
                segment = TranscriptSegment(
                    id=str(uuid4()),
                    source=source,
                    speaker=speaker,
                    start_ms=start_ms + int(seg.start * 1000),
                    end_ms=start_ms + int(seg.end * 1000),
                    text=text,
                    status=SegmentStatus.FINAL,
                    confidence=None,
                    revision=0,
                )
                segments.append(segment)
                texts.append(text)
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

        duration_ms = None
        if getattr(info, "duration", None) is not None:
            duration_ms = int(info.duration * 1000)
        return TranscriptionResult(segments=segments, text=" ".join(texts), duration_ms=duration_ms)
