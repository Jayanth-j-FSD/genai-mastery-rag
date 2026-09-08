"""The RAG pipeline, one module per stage: loader -> chunker -> embedder
-> store -> retriever -> generator, wired together in pipeline.py.

Week 4 added three modules that sit beside the six stages rather than inside them:
keyword.py (BM25 search), fusion.py (merge two ranked lists), diagnose.py (label a
failure as a retrieval or a generation problem)."""
