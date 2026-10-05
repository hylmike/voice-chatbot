import contextlib
import re
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from langchain.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

# Ensure backend directory is in sys.path
backend_dir = str(Path(__file__).resolve().parents[1])
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

env_path = Path(backend_dir) / ".env"
load_dotenv(env_path)
load_dotenv()

from api.schemas.chat import ChatRequest, ChatResponse
from api.schemas.events import event_to_dict
from api.voice_agent.agent import agent, pipeline

app = FastAPI(
    title="Lingxi AI API",
    description="Real-time voice chatbot backend with AssemblyAI STT, Gemini Agent, and Cartesia TTS.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _clean_ssml_tags(text: str) -> str:
    """Strip XML/SSML tags like <break time="..."/> from the text."""
    cleaned = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()


def _extract_response_text(message: AIMessage) -> str:
    """Extract plain text response from LangChain AIMessage."""
    raw_text = ""
    if hasattr(message, "text") and message.text:
        raw_text = message.text
    elif isinstance(message.content, str):
        raw_text = message.content
    elif isinstance(message.content, list):
        parts = []
        for part in message.content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and "text" in part:
                parts.append(str(part["text"]))
        raw_text = "".join(parts)
    else:
        raw_text = str(message.content or "")
    return _clean_ssml_tags(raw_text)


@app.get("/health", tags=["System"])
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


@app.post(
    "/chat",
    response_model=ChatResponse,
    summary="Chat with Agent",
    description=(
        "REST endpoint to interact with the conversational AI agent via text.\n\n"
        "- **Request:** `{'user_message': '...'}`\n"
        "- **Response:** `{'response': '...', 'thread_id': '...'}`"
    ),
    tags=["Chat"],
)
async def chat_endpoint(request: ChatRequest) -> ChatResponse:
    """Process a user text query with the conversational agent and return the response."""
    thread_id = request.thread_id or str(uuid4())
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

    try:
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content=request.user_message)]},
            config=config,
        )
        messages = result.get("messages", [])
        if not messages:
            raise HTTPException(
                status_code=500,
                detail="Agent did not produce any response messages.",
            )

        last_message = messages[-1]
        response_text = _extract_response_text(last_message)
        return ChatResponse(response=response_text, thread_id=thread_id)
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Chat endpoint error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate response: {e}",
        ) from e


@app.get(
    "/ws",
    summary="Voice Agent WebSocket Connection",
    description=(
        "WebSocket endpoint for real-time bi-directional voice agent streaming.\n\n"
        "- **Protocol:** WebSocket (`ws://` or `wss://`)\n"
        "- **Input:** 16-bit signed PCM audio bytes (16kHz, mono)\n"
        "- **Output:** Real-time JSON events (`stt_chunk`, `stt_output`, `agent_chunk`, `agent_end`, `tts_chunk`)\n"
    ),
    tags=["WebSockets"],
)
async def websocket_info() -> dict[str, str]:
    """Provides endpoint information and connection instructions for Swagger UI and HTTP clients."""
    return {
        "status": "active",
        "protocol": "websocket",
        "endpoint": "/ws",
        "message": "Connect via WebSocket client (e.g., ws://localhost:3100/ws).",
        "input_format": "PCM 16-bit mono 16kHz audio bytes",
        "output_format": "VoiceAgentEvent JSON streaming",
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()

    async def websocket_audio_stream() -> AsyncIterator[bytes]:
        """Async generator that yields audio bytes from the websocket."""
        try:
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                audio_bytes = message.get("bytes")
                if isinstance(audio_bytes, bytes) and audio_bytes:
                    yield audio_bytes
        except WebSocketDisconnect:
            pass

    try:
        output_stream = pipeline.atransform(websocket_audio_stream())

        # Process all events from the pipeline, send back to client
        async for event in output_stream:
            await websocket.send_json(event_to_dict(event))
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        print(f"[ERROR] WebSocket pipeline error: {e}")
    finally:
        with contextlib.suppress(Exception):
            await websocket.close()


if __name__ == "__main__":
    uvicorn.run("api.server:app", host="0.0.0.0", port=3100, reload=True)
