# Voice Chatbot Backend

FastAPI backend providing real-time voice streaming with AssemblyAI STT, Gemini 3.7 Flash agent, Cartesia Sonic / Speechify AI TTS, and Tavily search.

## Setup & Running

1. Configure environment variables in `.env` (see `env.example`):
   ```bash
   cp env.example .env
   ```
2. Install dependencies with `uv`:
   ```bash
   uv sync
   ```
3. Run the development server:
   ```bash
   uv run python api/server.py
   ```
   Or with Docker Compose:
   ```bash
   docker compose up --build
   ```

## Switching TTS Processors

The voice agent pipeline supports both **Speechify AI** and **Cartesia Sonic** streaming text-to-speech engines. Both implementations produce 24kHz 16-bit linear PCM audio compatible with the frontend Web Audio player and support instant barge-in / turn cancellation.

To switch between TTS providers, change the `tts_stream` import in [`backend/api/voice_agent/agent.py`](api/voice_agent/agent.py):

### 1. Speechify AI Streaming TTS (`simba-3.2`)
Streams audio in real time using Speechify's `POST /v1/audio/stream` chunked endpoint.
```python
# In api/voice_agent/agent.py
from ..services.speechifyai_tts import tts_stream
```
*Requires `SPEECHIFY_API_KEY` in `.env`.*

### 2. Cartesia Sonic Streaming TTS (`sonic-3.6`)
Streams audio in real time over Cartesia's bidirectional WebSocket endpoint.
```python
# In api/voice_agent/agent.py
from ..services.cartesia_tts import tts_stream
```
*Requires `CARTESIA_API_KEY` in `.env`.*

---

For full system architecture, frontend setup, and end-to-end testing, see the [Root README](../README.md).
