from fastapi.testclient import TestClient

from local_asr_service.app import create_app


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
