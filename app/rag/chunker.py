"""Pipeline stage 2 of 6 - CHUNK.

A whole document is too big to search well, so we cut it into
small overlapping pieces called "chunks". Chunk size + overlap are the numbers
the mentor asks you to experiment with (check #4).
"""
from langchain_text_splitters import RecursiveCharacterTextSplitter


def chunk_documents(docs, chunk_size: int, chunk_overlap: int):
    """Split every document into chunks, each remembering which file it came from."""
    # Overlap must be smaller than the chunk, or the splitter can't move forward.
    if chunk_overlap >= chunk_size:
        raise ValueError(
            f"chunk_overlap ({chunk_overlap}) must be smaller than chunk_size ({chunk_size})."
        )

    # Recursive splitter: tries to break on blank lines first, then lines, then
    # sentences, then spaces — so a chunk rarely ends in the middle of an idea.
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    chunks = []
    for doc in docs:
        for i, piece in enumerate(splitter.split_text(doc["text"])):
            piece = piece.strip()
            if not piece:
                continue
            chunks.append({
                "text": piece,
                "source": doc["source"],
                "chunk_id": f"{doc['source']}#{i}",   # a unique id per chunk
            })
    return chunks
