import json
import os
import queue
import threading
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from local_asr_service import __version__
from local_asr_service.backends.base import ASRBackend, TranscriptionStreamEvent
from local_asr_service.backends.factory import get_backend
from local_asr_service.config import get_settings
from local_asr_service.config import load_models_config
from local_asr_service.schemas import (
    AudioSource,
    ChunkTranscribeResponse,
    ErrorMessage,
    HealthResponse,
    ModelInfo,
    ModelsResponse,
    SessionStartedMessage,
    StreamMode,
    StreamStartMessage,
    TranscribeResponse,
)
from local_asr_service.security import require_api_key
from local_asr_service.streaming import (
    LiveStreamingSession,
    PhraseEndpointStreamingSession,
    StreamingSession,
)


STATIC_DIR = Path(__file__).resolve().parent / "static"


def _is_gpu_available() -> bool:
    try:
        import ctranslate2

        get_count = getattr(ctranslate2, "get_cuda_device_count", None)
        if get_count is not None and get_count():
            return True

        settings = get_settings()
        device_index = settings.cuda_device_index or 0
        supported = ctranslate2.get_supported_compute_types("cuda", device_index=device_index)
        return bool(supported)
    except Exception:
        return False


def _resolve_backend(model_id: str | None) -> ASRBackend:
    try:
        return get_backend(model_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _backend_failure(exc: Exception) -> HTTPException:
    return HTTPException(status_code=503, detail=f"ASR backend failed: {exc}")


def _websocket_authorized(websocket: WebSocket) -> bool:
    settings = get_settings()
    if not settings.api_key:
        return True
    auth = websocket.headers.get("authorization")
    query_key = websocket.query_params.get("api_key")
    return auth == f"Bearer {settings.api_key}" or query_key == settings.api_key


def _schedule_process_shutdown() -> None:
    timer = threading.Timer(0.5, lambda: os._exit(0))
    timer.daemon = True
    timer.start()


def _ndjson_line(payload: dict) -> bytes:
    return (json.dumps(jsonable_encoder(payload), ensure_ascii=False) + "\n").encode("utf-8")


def _stream_file_transcription(
    *,
    backend: ASRBackend,
    data: bytes,
    request_id: str,
    language: str,
    source: AudioSource,
) -> StreamingResponse:
    events: queue.Queue[TranscriptionStreamEvent | Exception | None] = queue.Queue()
    started = perf_counter()

    def worker() -> None:
        try:
            for event in backend.transcribe_bytes_stream(data, language=language, source=source):
                events.put(event)
        except Exception as exc:
            events.put(exc)
        finally:
            events.put(None)

    def body():
        yield _ndjson_line(
            {
                "type": "accepted",
                "request_id": request_id,
                "model_id": backend.profile.id,
                "language": language,
                "message": "File uploaded, transcription worker started",
            }
        )
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        segments = []
        texts = []
        while True:
            try:
                event = events.get(timeout=5)
            except queue.Empty:
                yield _ndjson_line(
                    {
                        "type": "heartbeat",
                        "request_id": request_id,
                        "elapsed_ms": int((perf_counter() - started) * 1000),
                        "message": "Transcription is still running",
                    }
                )
                continue

            elapsed_ms = int((perf_counter() - started) * 1000)
            if event is None:
                break
            if isinstance(event, Exception):
                yield _ndjson_line(
                    {
                        "type": "error",
                        "request_id": request_id,
                        "elapsed_ms": elapsed_ms,
                        "message": f"ASR backend failed: {event}",
                    }
                )
                break
            if event.type == "progress":
                yield _ndjson_line(
                    {
                        "type": "progress",
                        "request_id": request_id,
                        "elapsed_ms": elapsed_ms,
                        "message": event.message or "Transcription is running",
                    }
                )
            elif event.type == "segment" and event.segment is not None:
                segments.append(event.segment)
                texts.append(event.segment.text)
                yield _ndjson_line(
                    {
                        "type": "segment",
                        "request_id": request_id,
                        "elapsed_ms": elapsed_ms,
                        "seq": event.seq or len(segments),
                        "segment": event.segment,
                        "text": event.segment.text,
                    }
                )
            elif event.type == "completed" and event.result is not None:
                result = event.result
                if not segments:
                    segments = list(result.segments)
                    texts = [segment.text for segment in segments]
                response = TranscribeResponse(
                    request_id=request_id,
                    model_id=backend.profile.id,
                    language=language,
                    duration_ms=result.duration_ms,
                    processing_ms=elapsed_ms,
                    segments=segments,
                    text=result.text or " ".join(texts),
                )
                yield _ndjson_line(
                    {
                        "type": "completed",
                        "request_id": request_id,
                        "elapsed_ms": elapsed_ms,
                        "response": response,
                    }
                )

    return StreamingResponse(
        body(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def create_app() -> FastAPI:
    app = FastAPI(
        title="Local ASR Service",
        version=__version__,
        summary="Standalone local speech-to-text API for Meeting Copilot.",
        description=(
            "Receives audio files or short chunks, runs local ASR, and returns raw transcript "
            "segments with source labels. This service does not generate advice, answer questions, "
            "capture audio, or control the desktop UI."
        ),
        contact={"name": "Meeting Copilot Local ASR"},
        openapi_tags=[
            {"name": "system", "description": "Service health and runtime capabilities."},
            {"name": "models", "description": "Configured local ASR model profiles."},
            {
                "name": "transcription",
                "description": "HTTP file/chunk transcription endpoints for desktop clients and tests.",
            },
        ],
    )

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        cfg = load_models_config()
        settings = get_settings()
        profile = cfg.get_profile(cfg.default_model)
        return HealthResponse(
            version=__version__,
            backend=profile.backend,
            default_model=cfg.default_model,
            gpu_available=_is_gpu_available(),
            cuda_device_index=settings.cuda_device_index,
        )

    @app.post(
        "/shutdown",
        dependencies=[Depends(require_api_key)],
        tags=["system"],
        summary="Stop the local ASR service process",
    )
    async def shutdown() -> dict[str, str]:
        _schedule_process_shutdown()
        return {"status": "shutting_down"}

    @app.get(
        "/v1/models",
        response_model=ModelsResponse,
        dependencies=[Depends(require_api_key)],
        tags=["models"],
        summary="List configured ASR model profiles",
    )
    async def models() -> ModelsResponse:
        cfg = load_models_config()
        return ModelsResponse(
            default_model=cfg.default_model,
            models=[ModelInfo(**m.model_dump()) for m in cfg.models],
        )

    @app.post(
        "/v1/transcribe/file",
        response_model=TranscribeResponse,
        dependencies=[Depends(require_api_key)],
        tags=["transcription"],
        summary="Transcribe a complete audio file",
        description="Accepts multipart audio files such as WAV or MP3 and returns final transcript segments.",
    )
    async def transcribe_file(
        file: UploadFile = File(...),
        model_id: str | None = Form(default=None),
        language: str = Form(default="auto"),
        source: AudioSource = Form(default=AudioSource.UNKNOWN),
        stream: bool = Form(default=False),
    ) -> TranscribeResponse | StreamingResponse:
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="Empty audio file")
        backend = _resolve_backend(model_id)
        if stream:
            return _stream_file_transcription(
                backend=backend,
                data=data,
                request_id=str(uuid4()),
                language=language,
                source=source,
            )

        started = perf_counter()
        try:
            result = backend.transcribe_bytes(data, language=language, source=source)
        except Exception as exc:
            raise _backend_failure(exc) from exc
        processing_ms = int((perf_counter() - started) * 1000)
        return TranscribeResponse(
            request_id=str(uuid4()),
            model_id=backend.profile.id,
            language=language,
            duration_ms=result.duration_ms,
            processing_ms=processing_ms,
            segments=result.segments,
            text=result.text,
        )

    @app.post(
        "/v1/transcribe/file/stream",
        dependencies=[Depends(require_api_key)],
        tags=["transcription"],
        summary="Transcribe a complete audio file with progress events",
        description=(
            "Accepts multipart audio files and streams newline-delimited JSON events: "
            "accepted, progress, heartbeat, segment, completed, or error."
        ),
    )
    async def transcribe_file_stream(
        file: UploadFile = File(...),
        model_id: str | None = Form(default=None),
        language: str = Form(default="auto"),
        source: AudioSource = Form(default=AudioSource.UNKNOWN),
    ) -> StreamingResponse:
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="Empty audio file")
        backend = _resolve_backend(model_id)
        return _stream_file_transcription(
            backend=backend,
            data=data,
            request_id=str(uuid4()),
            language=language,
            source=source,
        )

    @app.post(
        "/v1/transcribe/chunk",
        response_model=ChunkTranscribeResponse,
        dependencies=[Depends(require_api_key)],
        tags=["transcription"],
        summary="Transcribe one short client-managed audio chunk",
        description=(
            "The desktop client owns capture and timing. The service transcribes the supplied "
            "chunk and preserves session, sequence, source, and timestamp metadata."
        ),
    )
    async def transcribe_chunk(
        chunk: UploadFile = File(...),
        seq: int = Form(...),
        session_id: str | None = Form(default=None),
        model_id: str | None = Form(default=None),
        language: str = Form(default="auto"),
        source: AudioSource = Form(default=AudioSource.UNKNOWN),
        start_ms: int = Form(default=0),
    ) -> ChunkTranscribeResponse:
        data = await chunk.read()
        if not data:
            raise HTTPException(status_code=400, detail="Empty audio chunk")
        sid = session_id or str(uuid4())
        started = perf_counter()
        backend = _resolve_backend(model_id)
        try:
            result = backend.transcribe_bytes(data, language=language, source=source, start_ms=start_ms)
        except Exception as exc:
            raise _backend_failure(exc) from exc
        processing_ms = int((perf_counter() - started) * 1000)
        return ChunkTranscribeResponse(
            session_id=sid,
            seq=seq,
            model_id=backend.profile.id,
            segments=result.segments,
            unstable_text="",
            processing_ms=processing_ms,
        )

    @app.websocket("/v1/stream")
    async def stream(websocket: WebSocket):
        await websocket.accept()
        if not _websocket_authorized(websocket):
            await websocket.send_json(
                ErrorMessage(code="unauthorized", message="Invalid or missing API key").model_dump()
            )
            await websocket.close(code=1008)
            return
        session: StreamingSession | LiveStreamingSession | PhraseEndpointStreamingSession | None = None
        try:
            while True:
                msg = await websocket.receive_json()
                msg_type = msg.get("type")
                if msg_type == "start":
                    try:
                        start = StreamStartMessage.model_validate(msg)
                        if start.stream_mode == StreamMode.LIVE_REVISION:
                            session = LiveStreamingSession.from_start_message(msg)
                            effective_config = session.effective_config
                        elif start.stream_mode == StreamMode.PHRASE_ENDPOINT:
                            session = PhraseEndpointStreamingSession.from_start_message(msg)
                            effective_config = session.effective_config
                        else:
                            session = StreamingSession.from_start_message(msg)
                            effective_config = None
                    except Exception as exc:
                        await websocket.send_json(
                            ErrorMessage(code="bad_request", message=str(exc)).model_dump()
                        )
                        continue
                    await websocket.send_json(
                        SessionStartedMessage(
                            session_id=session.session_id,
                            model_id=session.model_id,
                            effective_config=effective_config,
                        ).model_dump(mode="json")
                    )
                elif msg_type == "audio":
                    if session is None:
                        await websocket.send_json(
                            ErrorMessage(code="bad_request", message="Send start first").model_dump()
                        )
                        continue
                    delta = session.handle_audio_message(msg)
                    await websocket.send_json(delta.model_dump(mode="json"))
                elif msg_type == "silence":
                    if session is None:
                        await websocket.send_json(
                            ErrorMessage(code="bad_request", message="Send start first").model_dump()
                        )
                        continue
                    if not isinstance(session, LiveStreamingSession):
                        await websocket.send_json(
                            ErrorMessage(
                                code="bad_request",
                                message="silence messages are only supported in live_revision mode",
                            ).model_dump()
                        )
                        continue
                    delta = session.handle_silence_message(msg)
                    await websocket.send_json(delta.model_dump(mode="json"))
                elif msg_type == "force_decode":
                    if session is None:
                        await websocket.send_json(
                            ErrorMessage(code="bad_request", message="Send start first").model_dump()
                        )
                        continue
                    if not isinstance(session, PhraseEndpointStreamingSession):
                        await websocket.send_json(
                            ErrorMessage(
                                code="bad_request",
                                message="force_decode messages are only supported in phrase_endpoint mode",
                            ).model_dump()
                        )
                        continue
                    delta = session.handle_force_decode_message(msg)
                    await websocket.send_json(delta.model_dump(mode="json"))
                elif msg_type == "flush":
                    if session:
                        delta = session.flush()
                        await websocket.send_json(delta.model_dump(mode="json"))
                elif msg_type == "close":
                    break
                else:
                    await websocket.send_json(
                        ErrorMessage(code="bad_request", message=f"Unknown message type: {msg_type}").model_dump()
                    )
        except WebSocketDisconnect:
            return
        except Exception as exc:
            await websocket.send_json(ErrorMessage(code="internal_error", message=str(exc)).model_dump())

    return app
