# Voice Chatbot Backend

FastAPI backend providing real-time voice streaming with AssemblyAI STT, Gemini 3.7 Flash agent, Cartesia Sonic TTS, and Tavily search.

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

For full system architecture, frontend setup, and end-to-end testing, see the [Root README](../README.md).
