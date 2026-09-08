"""Week 4 addition — Reciprocal Rank Fusion (RRF): merge two ranked lists into one.

The two searches produce scores that cannot be compared. Cosine
similarity runs roughly 0 to 1; a BM25 score can be 0.4 or 14.0 depending on how
rare the words are. Averaging them would let BM25's bigger numbers dominate for no
good reason.

RRF sidesteps that by throwing the scores away and using only *position*. A chunk
ranked 1st contributes 1/(k+1), 2nd contributes 1/(k+2), and so on. A chunk that
both searches rank highly adds up two contributions and wins. The constant k (60 by
convention, from the paper that introduced RRF) flattens the curve so the difference
between rank 1 and rank 2 is not overwhelming.
"""


def fuse(ranked_lists: dict, rrf_k: int = 60):
    """Merge named ranked lists of keys into one ranking.

    `ranked_lists` maps a retriever name to its list of keys, best first, e.g.
    {"dense": ["a#1", "b#0"], "keyword": ["b#0", "c#2"]}.

    Returns a list of {"key", "rrf_score", "ranks"}, best first, where "ranks" maps
    each retriever name to the 1-based position it gave that key (absent = not found
    by that retriever).
    """
    # A negative k could make a denominator zero; clamp it rather than divide by zero.
    safe_k = max(int(rrf_k), 0)

    fused_scores: dict[str, float] = {}
    positions: dict[str, dict[str, int]] = {}

    for retriever_name, keys in (ranked_lists or {}).items():
        seen_in_this_list = set()
        for position, key in enumerate(keys or [], start=1):
            if not key or key in seen_in_this_list:
                continue                      # a repeated key must not count twice
            seen_in_this_list.add(key)
            fused_scores[key] = fused_scores.get(key, 0.0) + 1.0 / (safe_k + position)
            positions.setdefault(key, {})[retriever_name] = position

    def sort_key(key: str):
        # Best fused score first; ties broken by the best single rank, then the key
        # itself, so the same inputs always produce the same order.
        best_rank = min(positions[key].values())
        return (-fused_scores[key], best_rank, key)

    return [
        {
            "key": key,
            "rrf_score": round(fused_scores[key], 6),
            "ranks": positions[key],
        }
        for key in sorted(fused_scores, key=sort_key)
    ]
