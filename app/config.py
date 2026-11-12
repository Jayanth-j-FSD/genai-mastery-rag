"""App settings — model names, chunk sizes, and folder paths, all in one place.

Think of this as the app's control panel. Every other file reads
its settings from here, so you change behaviour (like chunk size) in ONE place.
Any value can be overridden in a `.env` file without editing code.
"""
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The AI-Task project root = the folder ABOVE this app/ folder.
# Anchoring paths to it means the app works no matter which folder you launch from.
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # Load overrides from AI-Task/.env; ignore any keys we don't recognise.
    model_config = SettingsConfigDict(env_file=str(BASE_DIR / ".env"), extra="ignore")

    # --- your OpenAI key (put the real value in .env, never in code) ---
    openai_api_key: str = ""

    # Optional: point at any OpenAI-COMPATIBLE endpoint instead of OpenAI itself.
    # Leave blank for real OpenAI. For a free Google Gemini key, set:
    #   OPENAI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
    openai_base_url: str = ""

    # --- which OpenAI models to use ---
    llm_model: str = "gpt-4o-mini"                 # writes the final answer
    embed_model: str = "text-embedding-3-small"    # turns text into vectors

    # Where embeddings come from:
    #   "openai" = the embed_model above, via the API (needs a key + quota)
    #   "local"  = a small model that runs on THIS machine: free, unlimited, offline
    embed_provider: str = "openai"
    # Throttle API embeddings to this many texts per minute (0 = no limit).
    # Google Gemini's free tier allows 100 embed requests/min, so set 90 to be safe.
    embed_rpm: int = 0
    # Folder holding the offline embedding model (onnx/model.onnx + tokenizer.json),
    # used when embed_provider = "local". Blank = ~/.cache/ai-task-minilm.
    local_embed_dir: str = ""

    # --- chat-call limits (see app/llm.py) ---
    # Free tiers allow only a few chat requests per minute PER MODEL (Gemini's free tier
    # measured 5). Set this a little below your limit; 0 = no limit.
    llm_rpm: int = 0
    # How many times a failed chat call is retried (rate limit, 5xx, dropped connection).
    llm_max_retries: int = 4
    # Give up on a single chat call after this many seconds. Without a limit one hung
    # request would stall a whole run, and an agent could never "stop safely".
    llm_timeout_seconds: float = 60.0

    # --- Week 6: the AI judge that grades answers (evals/judge.py) ---
    # A DIFFERENT model from llm_model grades more fairly: a model tends to like its own family's output.
    # Blank = use llm_model (works, but then the model grades itself). Quotas are per model, so a judge on
    # another model also gets its own per-minute allowance (judge_rpm; 0 = use llm_rpm).
    judge_model: str = ""
    judge_rpm: int = 0

    # --- Week 6: two experiments in cleaning the index (neither raised the score; docs/week6/CHANGES.md) ---
    # Drop a chunk whose text is an exact copy of an earlier chunk in the SAME document (whitespace
    # ignored) when the index is built. The handbook repeats one block of boilerplate 136 times; the
    # copies are identical, so they tie in every search and can fill every slot of the top results,
    # pushing out the one chunk that answers the question. Off by default: it changes what ingest
    # stores, so a run opts in (DEDUPE_CHUNKS=true) and the eval measures the difference.
    dedupe_chunks: bool = False
    # Remove every non-heading line that appears at least this many times in ONE document, before it is
    # cut into chunks (0 = off). It targets boilerplate: the handbook repeats seven lines 136 times each
    # under every subsection, so the chunks differ only by their heading and tie in every search,
    # crowding out the document that answers. Exact-duplicate removal (above) cannot touch those chunks
    # because each starts with its own heading. Off by default for the same reason as above.
    boilerplate_min_repeats: int = 0

    # --- pipeline knobs (the graded chunk-size experiment lives here) ---
    chunk_size: int = 800       # characters per chunk
    chunk_overlap: int = 120    # characters shared between neighbouring chunks
    top_k: int = 4              # how many chunks to fetch per question
    min_relevance: float = 0.0  # safety net: if the best chunk scores below this,
                                # answer "I don't know" instead of guessing.
                                # 0.0 = off; enable (e.g. 0.2) after seeing real scores.

    # --- Week 4: which retrieval strategy to use (this week's ONE change) ---
    # "dense"  = meaning-only search. Reproduces Week 3 behaviour exactly.
    # "hybrid" = meaning search + keyword (BM25) search, fused with RRF.
    # Keeping both switchable is what makes the before/after measurement possible.
    retrieval_mode: str = "hybrid"

    # How the dense (meaning) search finds the nearest chunks:
    #   "exact" = compare the question with EVERY stored vector. Always correct, and for a
    #             few thousand chunks it takes milliseconds. This is the default.
    #   "ann"   = Chroma's approximate HNSW index (what Week 3 originally used). It is faster
    #             on huge collections but can miss the right chunk, and on this corpus (136
    #             identical chunks) it did, differently on every run. See docs/hardening/.
    dense_search: str = "exact"

    # --- Week 4: hybrid search knobs ---
    hybrid_candidates: int = 10   # candidates EACH retriever contributes before fusion
    rrf_k: int = 60               # RRF damping constant (60 is the value from the RRF paper)
    bm25_k1: float = 1.5          # BM25: how fast repeated words stop adding score
    bm25_b: float = 0.75          # BM25: how much to penalise long chunks
    eval_k: int = 3               # the k in "hit-rate@k" — the mentor asks for @3

    # --- folders (absolute, so the current directory never matters) ---
    corpus_dir: str = str(BASE_DIR / "data" / "corpus")                 # your documents
    chroma_dir: str = str(BASE_DIR / "data" / "chroma")                 # the saved index
    collection: str = "ask_my_docs"                                     # index "table" name
    traces_path: str = str(BASE_DIR / "data" / "traces" / "traces.jsonl")  # request log

    @field_validator("embed_provider")
    @classmethod
    def _check_embed_provider(cls, value: str) -> str:
        """Only two providers exist; reject a typo instead of failing mid-ingest."""
        allowed = {"openai", "local"}
        cleaned = (value or "").strip().lower()
        if cleaned not in allowed:
            raise ValueError(f"embed_provider must be one of {sorted(allowed)}, got {value!r}")
        return cleaned

    @field_validator("retrieval_mode")
    @classmethod
    def _check_retrieval_mode(cls, value: str) -> str:
        """Reject a typo in .env loudly at startup instead of silently searching wrongly."""
        allowed = {"dense", "hybrid"}
        cleaned = (value or "").strip().lower()
        if cleaned not in allowed:
            raise ValueError(f"retrieval_mode must be one of {sorted(allowed)}, got {value!r}")
        return cleaned

    @field_validator("dense_search")
    @classmethod
    def _check_dense_search(cls, value: str) -> str:
        """Reject a typo at startup instead of silently falling back to a different search."""
        allowed = {"exact", "ann"}
        cleaned = (value or "").strip().lower()
        if cleaned not in allowed:
            raise ValueError(f"dense_search must be one of {sorted(allowed)}, got {value!r}")
        return cleaned

    @field_validator("llm_rpm", "llm_max_retries", "chunk_overlap", "judge_rpm")
    @classmethod
    def _check_not_negative(cls, value: int) -> int:
        """A negative limit, retry count or overlap has no meaning."""
        if value < 0:
            raise ValueError(f"must be 0 or greater, got {value}")
        return value

    @field_validator("boilerplate_min_repeats")
    @classmethod
    def _check_boilerplate_repeats(cls, value: int) -> int:
        """0 turns it off; 1 would delete every line, so anything below 2 (but 0) is a mistake."""
        if value != 0 and value < 2:
            raise ValueError(f"boilerplate_min_repeats must be 0 (off) or at least 2, got {value}")
        return value

    @field_validator("llm_timeout_seconds")
    @classmethod
    def _check_timeout(cls, value: float) -> float:
        """A zero or negative timeout would make every call fail instantly."""
        if value <= 0:
            raise ValueError(f"llm_timeout_seconds must be greater than 0, got {value}")
        return value

    @field_validator("chunk_size")
    @classmethod
    def _check_chunk_size(cls, value: int) -> int:
        """A chunk has to hold at least one character."""
        if value < 1:
            raise ValueError(f"chunk_size must be 1 or greater, got {value}")
        return value

    @model_validator(mode="after")
    def _check_overlap_fits(self):
        """Overlap must be smaller than the chunk, or the splitter cannot move forward.

        Checked here as well as in the chunker, so a bad .env fails at startup with a clear
        message instead of crashing in the middle of an ingest.
        """
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError(
                f"chunk_overlap ({self.chunk_overlap}) must be smaller than chunk_size ({self.chunk_size})"
            )
        return self

    @field_validator("bm25_b")
    @classmethod
    def _check_bm25_b(cls, value: float) -> float:
        """BM25's b is a proportion. Outside 0..1 the score formula can divide by zero."""
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"bm25_b must be between 0.0 and 1.0, got {value}")
        return value

    @field_validator("bm25_k1")
    @classmethod
    def _check_bm25_k1(cls, value: float) -> float:
        """A negative k1 would invert the meaning of a repeated word."""
        if value < 0.0:
            raise ValueError(f"bm25_k1 must be 0.0 or greater, got {value}")
        return value

    @field_validator("top_k", "hybrid_candidates", "eval_k")
    @classmethod
    def _check_positive(cls, value: int) -> int:
        """These are counts. Zero or less would silently retrieve nothing to measure."""
        if value < 1:
            raise ValueError(f"must be 1 or greater, got {value}")
        return value

    @field_validator("rrf_k")
    @classmethod
    def _check_rrf_k(cls, value: int) -> int:
        """RRF's k damps the rank curve; negative values would divide by zero at rank 1."""
        if value < 0:
            raise ValueError(f"rrf_k must be 0 or greater, got {value}")
        return value


settings = Settings()   # one shared settings object the whole app imports
