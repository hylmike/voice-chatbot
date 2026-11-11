# Deepgram Flux Voice Agent Backend

FastAPI backend providing real-time voice streaming with [Deepgram Flux STT (`/v2/listen`)](https://developers.deepgram.com/docs/flux/quickstart), Gemini 3.7 Flash agent, [Deepgram Flux TTS (`/v2/speak`)](https://developers.deepgram.com/docs/flux-tts/overview), and Tavily search.

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

## Deepgram Flux Speech Stack

- **STT (`api/services/deepgram_stt.py`)**: Streams 16kHz 16-bit mono `linear16` PCM audio to Deepgram Flux `/v2/listen` (`flux-general-en`), emitting `SpeechStartedEvent` on `StartOfTurn`, `STTChunkEvent` on interim `Update` / `EagerEndOfTurn` / `TurnResumed` events, and `STTOutputEvent` on `EndOfTurn`.
- **TTS (`api/services/deepgram_tts.py`)**: Streams LLM text tokens directly into Deepgram Flux `/v2/speak` (`flux-wade-en`, `linear16`, `24000` Hz) using `Speak` and `Flush` frames, yielding 24kHz 16-bit PCM `TTSChunkEvent` frames and handling barge-in via `Interrupt`.
