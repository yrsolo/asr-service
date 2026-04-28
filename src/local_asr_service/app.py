from time import perf_counter
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from local_asr_service import __version__
from local_asr_service.backends.base import ASRBackend
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
    TranscribeResponse,
)
from local_asr_service.security import require_api_key
from local_asr_service.streaming import StreamingSession


STATIC_DIR = Path(__file__).resolve().parent / "static"


def _is_gpu_available() -> bool:
    try:
        import ctranslate2

        get_count = getattr(ctranslate2, "get_cuda_device_count", None)
        if get_count is None:
            return False
        return bool(get_count())
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
        profile = cfg.get_profile(cfg.default_model)
        return HealthResponse(
            version=__version__,
            backend=profile.backend,
            default_model=cfg.default_model,
            gpu_available=_is_gpu_available(),
        )

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
    ) -> TranscribeResponse:
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="Empty audio file")
        started = perf_counter()
        backend = _resolve_backend(model_id)
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
        session: StreamingSession | None = None
        try:
            while True:
                msg = await websocket.receive_json()
                msg_type = msg.get("type")
                if msg_type == "start":
                    session = StreamingSession.from_start_message(msg)
                    await websocket.send_json(
                        SessionStartedMessage(
                            session_id=session.session_id,
                            model_id=session.model_id,
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
