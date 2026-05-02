import base64
from array import array

from fastapi.testclient import TestClient

from local_asr_service.app import create_app


def _pcm(amplitude: int, duration_ms: int) -> bytes:
    samples = int(16000 * duration_ms / 1000)
    return array("h", [amplitude] * samples).tobytes()


def test_health() -> None:
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_models() -> None:
    client = TestClient(create_app())
    response = client.get("/v1/models")
    assert response.status_code == 200
    assert "models" in response.json()


def test_index_serves_web_ui() -> None:
    client = TestClient(create_app())
    response = client.get("/")
    assert response.status_code == 200
    assert "Local ASR Service" in response.text
    assert "Live file emulation" in response.text
    assert "Stop service" in response.text
    assert "Final" in response.text
    assert "In work" in response.text
    assert "Raw" in response.text
    assert "Adaptation" in response.text
    assert "RTF" in response.text
    assert "Avg RTF" in response.text
    assert "queueBar" in response.text
    assert "speedHistory" in response.text
    assert "Event filter" in response.text
    assert "Decode jobs with text" in response.text
    assert "Phrase endpointing emulation" in response.text
    assert "Force decode now" in response.text
    assert "VAD" in response.text
    assert "Phrase / VAD events" in response.text
    assert "Last RMS" in response.text
    assert "Thresholds" in response.text
    assert "Phrase ID" in response.text
    assert "Live diagram" in response.text
    assert "Live timeline" in response.text
    assert "Sequence texts" in response.text
    assert "Full event log" in response.text


def test_shutdown_endpoint_schedules_process_exit(monkeypatch) -> None:
    called = []
    monkeypatch.setattr("local_asr_service.app._schedule_process_shutdown", lambda: called.append(True))

    client = TestClient(create_app())
    response = client.post("/shutdown")

    assert response.status_code == 200
    assert response.json() == {"status": "shutting_down"}
    assert called == [True]


def test_transcribe_file_with_mock_backend() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/v1/transcribe/file",
        files={"file": ("sample.wav", b"not-real-audio", "audio/wav")},
        data={"model_id": "mock", "language": "ru", "source": "mic"},
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["model_id"] == "mock"
    assert payload["segments"][0]["source"] == "mic"
    assert "тестовый" in payload["text"]


def test_transcribe_chunk_with_mock_backend() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/v1/transcribe/chunk",
        files={"chunk": ("chunk.wav", b"not-real-audio", "audio/wav")},
        data={"model_id": "mock", "seq": "7", "source": "system", "start_ms": "1000"},
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["seq"] == 7
    assert payload["segments"][0]["speaker"] == "other"
    assert payload["segments"][0]["start_ms"] == 1000


def test_unknown_model_returns_404() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/v1/transcribe/file",
        files={"file": ("sample.wav", b"not-real-audio", "audio/wav")},
        data={"model_id": "missing"},
    )
    assert response.status_code == 404


def test_websocket_stream_with_mock_backend() -> None:
    client = TestClient(create_app())
    with client.websocket_connect("/v1/stream") as websocket:
        websocket.send_json({"type": "start", "model_id": "mock", "source": "mic"})
        started = websocket.receive_json()
        assert started["type"] == "session_started"

        websocket.send_json({"type": "audio", "seq": 1, "audio_b64": "bm90LXJlYWwtYXVkaW8="})
        delta = websocket.receive_json()
        assert delta["type"] == "transcript_delta"
        assert delta["unstable"][0]["source"] == "mic"
        assert delta["unstable"][0]["status"] == "unstable"

        websocket.send_json({"type": "flush"})
        flushed = websocket.receive_json()
        assert flushed["segments"][0]["status"] == "final"


def test_websocket_live_revision_stream_with_mock_backend() -> None:
    client = TestClient(create_app())
    audio_b64 = base64.b64encode(bytes(16000 * 2)).decode("ascii")
    with client.websocket_connect("/v1/stream") as websocket:
        websocket.send_json(
            {
                "type": "start",
                "stream_mode": "live_revision",
                "model_id": "mock",
                "source": "mic",
                "format": "pcm_s16le",
                "sample_rate": 16000,
                "channels": 1,
            }
        )
        started = websocket.receive_json()
        assert started["type"] == "session_started"
        assert started["effective_config"]["stream_mode"] == "live_revision"
        assert started["effective_config"]["window_ms"] == 8000
        assert started["effective_config"]["adaptation_mode"] == "off"

        websocket.send_json({"type": "audio", "seq": 1, "audio_b64": audio_b64})
        first = websocket.receive_json()
        assert first["type"] == "live_delta"
        assert first["raw"][0]["status"] == "unstable"
        assert first["updates"] == []
        assert "stats" in first
        assert first["stats"]["audio_step_ms"] == 1000
        assert first["stats"]["decode_interval_ms"] == 1000
        assert first["stats"]["effective_window_ms"] == 8000
        assert "realtime_factor" in first["stats"]

        websocket.send_json({"type": "audio", "seq": 2, "audio_b64": audio_b64})
        second = websocket.receive_json()
        assert second["type"] == "live_delta"
        assert second["updates"][0]["status"] == "draft"
        assert second["updates"][0]["id"] == "live-draft"


def test_websocket_live_revision_drop_stale_decode_stats() -> None:
    client = TestClient(create_app())
    audio_b64 = base64.b64encode(bytes(16000 * 2)).decode("ascii")
    with client.websocket_connect("/v1/stream") as websocket:
        websocket.send_json(
            {
                "type": "start",
                "stream_mode": "live_revision",
                "model_id": "mock",
                "source": "mic",
                "adaptation_mode": "drop_stale_decode",
            }
        )
        websocket.receive_json()
        websocket.send_json(
            {
                "type": "audio",
                "seq": 1,
                "sent_seq": 1,
                "total_seq": 2,
                "duration_ms": 1000,
                "audio_b64": audio_b64,
            }
        )
        delta = websocket.receive_json()
        assert delta["type"] == "live_delta"
        assert delta["updates"] == []
        assert delta["stats"]["dropped_chunks"] == 1
        assert delta["stats"]["adaptation_action"] == "decode skipped"


def test_websocket_live_revision_can_buffer_frame_without_decode() -> None:
    client = TestClient(create_app())
    audio_b64 = base64.b64encode(bytes(1600)).decode("ascii")
    with client.websocket_connect("/v1/stream") as websocket:
        websocket.send_json(
            {
                "type": "start",
                "stream_mode": "live_revision",
                "model_id": "mock",
                "source": "mic",
            }
        )
        websocket.receive_json()
        websocket.send_json(
            {
                "type": "audio",
                "seq": 1,
                "duration_ms": 50,
                "should_decode": False,
                "audio_b64": audio_b64,
            }
        )
        delta = websocket.receive_json()
        assert delta["type"] == "live_delta"
        assert delta["updates"] == []
        assert delta["raw"] == []
        assert delta["stats"]["audio_received_ms"] == 50
        assert delta["stats"]["adaptation_action"] == "frame buffered"


def test_websocket_live_revision_rejects_non_pcm_format() -> None:
    client = TestClient(create_app())
    with client.websocket_connect("/v1/stream") as websocket:
        websocket.send_json(
            {
                "type": "start",
                "stream_mode": "live_revision",
                "model_id": "mock",
                "format": "wav",
            }
        )
        error = websocket.receive_json()
        assert error["type"] == "error"
        assert error["code"] == "bad_request"
        assert "pcm_s16le" in error["message"]


def test_websocket_phrase_endpoint_returns_effective_config() -> None:
    client = TestClient(create_app())
    with client.websocket_connect("/v1/stream") as websocket:
        websocket.send_json(
            {
                "type": "start",
                "stream_mode": "phrase_endpoint",
                "model_id": "mock",
                "source": "mic",
            }
        )
        started = websocket.receive_json()

        assert started["type"] == "session_started"
        assert started["effective_config"]["stream_mode"] == "phrase_endpoint"
        assert started["effective_config"]["phrase_silence_ms"] == 700


def test_websocket_phrase_endpoint_audio_produces_final() -> None:
    client = TestClient(create_app())
    with client.websocket_connect("/v1/stream") as websocket:
        websocket.send_json(
            {
                "type": "start",
                "stream_mode": "phrase_endpoint",
                "model_id": "mock",
                "source": "mic",
            }
        )
        websocket.receive_json()
        websocket.send_json(
            {
                "type": "audio",
                "seq": 1,
                "duration_ms": 1000,
                "audio_b64": base64.b64encode(_pcm(1200, 1000)).decode("ascii"),
            }
        )
        websocket.receive_json()
        websocket.send_json(
            {
                "type": "audio",
                "seq": 2,
                "duration_ms": 700,
                "audio_b64": base64.b64encode(_pcm(0, 700)).decode("ascii"),
            }
        )
        delta = websocket.receive_json()

        assert delta["type"] == "live_delta"
        assert delta["updates"][0]["status"] == "final"
        assert delta["stats"]["vad_state"] in {"trailing_silence", "silence"}
        assert delta["stats"]["decoded_windows"] == 1


def test_websocket_phrase_endpoint_force_decode_produces_draft() -> None:
    client = TestClient(create_app())
    with client.websocket_connect("/v1/stream") as websocket:
        websocket.send_json(
            {
                "type": "start",
                "stream_mode": "phrase_endpoint",
                "model_id": "mock",
                "source": "mic",
            }
        )
        websocket.receive_json()
        websocket.send_json(
            {
                "type": "audio",
                "seq": 1,
                "duration_ms": 1000,
                "audio_b64": base64.b64encode(_pcm(1200, 1000)).decode("ascii"),
            }
        )
        websocket.receive_json()
        websocket.send_json({"type": "force_decode", "seq": 2, "reason": "urgent"})
        delta = websocket.receive_json()

        assert delta["type"] == "live_delta"
        assert delta["updates"][0]["status"] == "draft"
        assert delta["updates"][0]["id"].startswith("phrase-current-")
