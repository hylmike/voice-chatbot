from pathlib import Path

from dotenv import load_dotenv
from langchain_tavily import TavilySearch

env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(env_path)
load_dotenv()

# Initialize the Tavily Search tool
tavily_search = TavilySearch(
    max_results=5,
    topic="general",
    search_depth="basic",
)
