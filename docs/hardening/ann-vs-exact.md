# Approximate vs exact dense search (generated)

Each block is one run of `python scripts/compare_ann_exact.py --save` (optionally with `--ef-search N`). Blocks are appended, so the spread between runs is visible.

## 2026-10-11T01:12:02  `python scripts/compare_ann_exact.py --save`

```
=== approximate (HNSW, Chroma default) vs exact dense search, k=4, 74 questions ===
index: 432 chunks, embeddings: local
top-1 chunk differs from exact : 38/74  (51%)
top-4 set differs from exact : 48/74  (65%)
mean overlap@4                : 0.500   (1.000 means identical)

This run is one draw: run it again and the counts may move. Exact search never does.
```

## 2026-10-11T01:12:05  `python scripts/compare_ann_exact.py --save`

```
=== approximate (HNSW, Chroma default) vs exact dense search, k=4, 74 questions ===
index: 432 chunks, embeddings: local
top-1 chunk differs from exact : 21/74  (28%)
top-4 set differs from exact : 32/74  (43%)
mean overlap@4                : 0.730   (1.000 means identical)

This run is one draw: run it again and the counts may move. Exact search never does.
```

## 2026-10-11T01:12:08  `python scripts/compare_ann_exact.py --save`

```
=== approximate (HNSW, Chroma default) vs exact dense search, k=4, 74 questions ===
index: 432 chunks, embeddings: local
top-1 chunk differs from exact : 49/74  (66%)
top-4 set differs from exact : 57/74  (77%)
mean overlap@4                : 0.341   (1.000 means identical)

This run is one draw: run it again and the counts may move. Exact search never does.
```

## 2026-10-11T01:12:12  `python scripts/compare_ann_exact.py --ef-search 500 --save`

```
=== tuned approximate (HNSW, ef_search=500) vs exact dense search, k=4, 74 questions ===
index: 432 chunks, embeddings: local
top-1 chunk differs from exact : 0/74  (0%)
top-4 set differs from exact : 5/74  (7%)
mean overlap@4                : 0.970   (1.000 means identical)

This run is one draw: run it again and the counts may move. Exact search never does.
```

## 2026-10-11T01:12:15  `python scripts/compare_ann_exact.py --ef-search 500 --save`

```
=== tuned approximate (HNSW, ef_search=500) vs exact dense search, k=4, 74 questions ===
index: 432 chunks, embeddings: local
top-1 chunk differs from exact : 4/74  (5%)
top-4 set differs from exact : 14/74  (19%)
mean overlap@4                : 0.932   (1.000 means identical)

This run is one draw: run it again and the counts may move. Exact search never does.
```

## 2026-10-11T01:12:19  `python scripts/compare_ann_exact.py --ef-search 500 --save`

```
=== tuned approximate (HNSW, ef_search=500) vs exact dense search, k=4, 74 questions ===
index: 432 chunks, embeddings: local
top-1 chunk differs from exact : 0/74  (0%)
top-4 set differs from exact : 4/74  (5%)
mean overlap@4                : 0.970   (1.000 means identical)

This run is one draw: run it again and the counts may move. Exact search never does.
```
