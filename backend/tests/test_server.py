"""Unit tests for FastAPI server and endpoints."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from langchain.messages import AIMessage

from api.schemas.events import InterruptEvent, STTOutputEvent
from api.server import _clean_ssml_tags, _extract_response_text, app

client = TestClient(app)


def test_clean_ssml_tags() -> None:
    text = 'Hello <break time="300ms"/> world! <speed rate="fast">How are you?</speed>'
    cleaned = _clean_ssml_tags(text)
    assert cleaned == "Hello world! How are you?"
    assert "<" not in cleaned


def test_extract_response_text() -> None:
    # 1. Message with text string content
    msg1 = AIMessage(content="Hello from text attribute")
    assert _extract_response_text(msg1) == "Hello from text attribute"

    # 2. Message with list content
    msg2 = AIMessage(
        content=["First part ", {"text": "second part"}]  # type: ignore[arg-type]
    )
    assert _extract_response_text(msg2) == "First part second part"

    # 3. Empty message
    msg3 = AIMessage(content="")
    assert _extract_response_text(msg3) == ""


def test_health_endpoint() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ws_info_endpoint() -> None:
    response = client.get("/ws")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "active"
    assert data["protocol"] == "websocket"


def test_chat_endpoint_success() -> None:
    mock_ai_msg = AIMessage(content="Hello! How can I help you today?")
    mock_ainvoke = AsyncMock(return_value={"messages": [mock_ai_msg]})

    with patch("api.server.agent.ainvoke", mock_ainvoke):
        response = client.post(
            "/chat",
            json={"user_message": "Hi", "thread_id": "thread-1"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["response"] == "Hello! How can I help you today?"
        assert data["thread_id"] == "thread-1"


def test_chat_endpoint_empty_messages() -> None:
    mock_ainvoke = AsyncMock(return_value={"messages": []})

    with patch("api.server.agent.ainvoke", mock_ainvoke):
        response = client.post(
            "/chat",
            json={"user_message": "Hi", "thread_id": "thread-1"},
        )
        assert response.status_code == 500
        assert "did not produce any response messages" in response.json()["detail"]


def test_websocket_endpoint_audio_and_interrupt() -> None:
    async def mock_atransform(input_stream):
        async for item in input_stream:
            if isinstance(item, bytes):
                yield STTOutputEvent.create("audio received")
            elif isinstance(item, InterruptEvent):
                yield InterruptEvent.create()

    mock_pipeline = MagicMock()
    mock_pipeline.atransform = mock_atransform

    with (
        patch("api.server.pipeline", mock_pipeline),
        client.websocket_connect("/ws") as websocket,
    ):
        # 1. Send binary audio chunk
        websocket.send_bytes(b"\x00\x01\x02\x03")
        data1 = websocket.receive_json()
        assert data1["type"] == "stt_output"
        assert data1["transcript"] == "audio received"

        # 2. Send text interrupt message
        websocket.send_text(json.dumps({"type": "interrupt"}))
        data2 = websocket.receive_json()
        assert data2["type"] == "interrupt"
