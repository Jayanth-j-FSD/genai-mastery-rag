"""App settings — model names, chunk sizes, and folder paths, all in one place.

Think of this as the app's control panel. Every other file reads
its settings from here, so you change behaviour (like chunk size) in ONE place.
Any value can be overridden in a `.env` file without editing code.
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# The AI-Task project root = the folder ABOVE this app/ folder.
# Anchoring paths to it means the app works no matter which folder you launch from.
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # Load overrides from AI-Task/.env; ignore any keys we don't recognise.
    model_config = SettingsConfigDict(env_file=str(BASE_DIR / ".env"), extra="ignore")

    # --- your OpenAI key (put the real value in .env, never in code) ---
    openai_api_key: str = ""

    # --- which OpenAI models to use ---
    llm_model: str = "gpt-4o-mini"                 # writes the final answer
    embed_model: str = "text-embedding-3-small"    # turns text into vectors

    # --- pipeline knobs (the graded chunk-size experiment lives here) ---
    chunk_size: int = 800       # characters per chunk
    chunk_overlap: int = 120    # characters shared between neighbouring chunks
    top_k: int = 4              # how many chunks to fetch per question
    min_relevance: float = 0.0  # safety net: if the best chunk scores below this,
                                # answer "I don't know" instead of guessing.
                                # 0.0 = off; enable (e.g. 0.2) after seeing real scores.

    # --- folders (absolute, so the current directory never matters) ---
    corpus_dir: str = str(BASE_DIR / "data" / "corpus")                 # your documents
    chroma_dir: str = str(BASE_DIR / "data" / "chroma")                 # the saved index
    collection: str = "ask_my_docs"                                     # index "table" name
    traces_path: str = str(BASE_DIR / "data" / "traces" / "traces.jsonl")  # request log


settings = Settings()   # one shared settings object the whole app imports
