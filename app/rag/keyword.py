"""Week 4 addition — keyword search (BM25) over the same chunks the vector store holds.

The Week 3 search was "dense" (by meaning). It is very good at
paraphrases but weak at exact strings like `ERR-4032` or `security@northwind.example`,
because a code carries almost no meaning to embed. BM25 is the classic keyword
scorer: a chunk scores well when it contains the *rare* words from your question.
Running both searches and merging the two ranked lists is what "hybrid search" means.

No new package is needed — BM25 is about forty lines of arithmetic, written out below
so you can read exactly what it rewards.

Two things to know about the design: the index is held in memory and built from the
chunks already in the vector store, so there is no second copy of the corpus to keep in
sync, but memory does grow with corpus size. And it is cached in a module-level global,
so each worker process builds its own copy; two threads racing to rebuild it merely
duplicate the work, they cannot corrupt it.
"""
import math
import re

from app.config import settings
from app.rag import store

# Split text into searchable words. The inner group deliberately keeps a compound
# like "err-4032" or "settings/connections" together as ONE token, so exact codes
# match as a unit instead of dissolving into "err" + "4032".
_WORD_RE = re.compile(r"[a-z0-9]+(?:[-_./][a-z0-9]+)*")

# Characters that join a compound token; used to also index its individual parts.
_SEPARATORS = "-_./"

_index = None   # the cached BM25 index; rebuilt whenever the store's chunk count changes


def tokenize(text: str) -> list[str]:
    """Lowercase and split text into tokens, emitting both compounds and their parts.

    "ERR-4032" becomes ["err-4032", "err", "4032"], so a question asking for either
    the full code or just the number still matches. Documents and questions are
    tokenized by this same function, so the two sides always agree.
    """
    tokens: list[str] = []
    for word in _WORD_RE.findall((text or "").lower()):
        tokens.append(word)
        if any(sep in word for sep in _SEPARATORS):
            tokens.extend(part for part in re.split(r"[-_./]", word) if part)
    return tokens


class Bm25Index:
    """An in-memory BM25 index: which words each chunk contains, and how often."""

    def __init__(self, chunks):
        self.chunks = chunks
        self.total_docs = len(chunks)

        # Per-chunk token lists and lengths (length matters: BM25 penalises long chunks).
        token_lists = [tokenize(c.get("text", "")) for c in chunks]
        self.doc_len = [len(tokens) for tokens in token_lists]
        self.avg_len = (sum(self.doc_len) / self.total_docs) if self.total_docs else 0.0

        # term_freqs[i][word] = how many times `word` appears in chunk i.
        # doc_freq[word]      = in how many chunks `word` appears at all (drives rarity).
        self.term_freqs: list[dict[str, int]] = []
        self.doc_freq: dict[str, int] = {}
        for tokens in token_lists:
            freqs: dict[str, int] = {}
            for token in tokens:
                freqs[token] = freqs.get(token, 0) + 1
            self.term_freqs.append(freqs)
            for token in freqs:                      # once per chunk, not per occurrence
                self.doc_freq[token] = self.doc_freq.get(token, 0) + 1

    def _idf(self, token: str) -> float:
        """Rarity weight: a word in few chunks is worth more than a word in every chunk.

        This "+1 inside the log" form is always positive, so a very common word can
        never drag a chunk's total score below zero.
        """
        appears_in = self.doc_freq.get(token, 0)
        if appears_in == 0:                          # word not in the corpus at all
            return 0.0
        return math.log(1 + (self.total_docs - appears_in + 0.5) / (appears_in + 0.5))

    def search(self, question: str, top_k: int):
        """Return up to top_k chunks sharing rare words with the question, best first.

        Each item is {"chunk_id", "text", "source", "keyword_score"}. Chunks that share
        no words with the question are left out entirely rather than scored zero.
        """
        if top_k <= 0 or self.total_docs == 0 or self.avg_len <= 0:
            return []
        query_tokens = set(tokenize(question))       # each query word counts once
        if not query_tokens:
            return []

        k1, b = settings.bm25_k1, settings.bm25_b
        scored: list[tuple[float, int]] = []
        for i, freqs in enumerate(self.term_freqs):
            score = 0.0
            for token in query_tokens:
                count = freqs.get(token, 0)
                if not count:
                    continue
                # Classic BM25: more occurrences help but saturate (k1), and long
                # chunks are penalised relative to the average length (b).
                denominator = count + k1 * (1 - b + b * (self.doc_len[i] / self.avg_len))
                score += self._idf(token) * (count * (k1 + 1)) / denominator
            if score > 0:
                scored.append((score, i))

        # Sort by score, then by chunk index, so equal scores order deterministically.
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        results = []
        for score, i in scored[:top_k]:
            chunk = self.chunks[i]
            results.append({
                "chunk_id": chunk.get("chunk_id", ""),
                "text": chunk.get("text", ""),
                "source": chunk.get("source", "unknown"),
                "keyword_score": round(score, 4),
            })
        return results


def invalidate() -> None:
    """Forget the cached index. Called after ingest, because the chunks just changed."""
    global _index
    _index = None


def get_index() -> Bm25Index:
    """Return the cached index, rebuilding it if the store's chunk count no longer matches.

    The count check makes the cache self-healing: re-ingesting with a different chunk
    size changes the count, so the stale index is dropped without anyone remembering to.

    If the chunks cannot be read at all, this returns an EMPTY index rather than raising.
    Keyword search is an enhancement on top of the meaning search, so a failure here
    should quietly cost you the keyword half — not the whole answer.
    """
    global _index
    current_count = store.count_chunks()
    if _index is None or _index.total_docs != current_count:
        try:
            _index = Bm25Index(store.get_all_chunks())
        except Exception as exc:
            print(f"  ! keyword index unavailable, using meaning search only: {exc}")
            _index = Bm25Index([])
    return _index


def search(question: str, top_k: int):
    """Keyword-search the indexed chunks. Returns [] if nothing has been ingested."""
    return get_index().search(question, top_k)
