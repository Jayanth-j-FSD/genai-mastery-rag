"""Download the free offline embedding model (about 90 MB), once.

Embeddings can come from a paid API or from a small model that runs on your own
machine. This fetches that small model (all-MiniLM-L6-v2, the ONNX export published by the
Xenova project on HuggingFace) into the folder the app looks in, and checks every file's size and
the big file's SHA-256, so a half-finished or tampered download is caught instead of producing
mysteriously bad search results.

It uses only the standard library, so it works before anything else is set up beyond Python.
It skips files that are already complete, so running it twice is harmless.

Run:
    python scripts/download_model.py
    python scripts/download_model.py --dir D:\\models\\minilm      # somewhere else (set LOCAL_EMBED_DIR to match)
"""
import argparse
import hashlib
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.console import make_output_safe   # noqa: E402
from app.rag.local_embedder import model_dir  # noqa: E402

BASE_URL = "https://huggingface.co/Xenova/all-MiniLM-L6-v2/resolve/main/"

# file -> expected size in bytes, from HuggingFace's own listing of the repository.
FILES = {
    "onnx/model.onnx": 90387606,
    "tokenizer.json": 711661,
    "config.json": 650,
    "tokenizer_config.json": 366,
    "special_tokens_map.json": 125,
    "vocab.txt": 231508,
}
# The SHA-256 HuggingFace lists for onnx/model.onnx.
MODEL_SHA256 = "759c3cd2b7fe7e93933ad23c4c9181b7396442a2ed746ec7c1d46192c469c46e"


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_complete(path, size):
    if not os.path.exists(path) or os.path.getsize(path) != size:
        return False
    return _sha256(path) == MODEL_SHA256 if path.endswith("model.onnx") else True


def _download(name, destination):
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    partial = destination + ".part"                     # never leave a half file under the real name
    with urllib.request.urlopen(BASE_URL + name, timeout=60) as response, open(partial, "wb") as out:
        for block in iter(lambda: response.read(1 << 20), b""):
            out.write(block)
    os.replace(partial, destination)


def main():
    parser = argparse.ArgumentParser(description="Download the offline embedding model.")
    parser.add_argument("--dir", default=None, help="where to put it (default: LOCAL_EMBED_DIR or ~/.cache/ai-task-minilm)")
    args = parser.parse_args()
    make_output_safe()
    target = args.dir or model_dir()
    print(f"Model folder: {target}")

    for name, size in FILES.items():
        path = os.path.join(target, *name.split("/"))
        if _is_complete(path, size):
            print(f"  ok       {name}")
            continue
        print(f"  fetching {name} ({size / 1e6:.1f} MB)...", flush=True)
        try:
            _download(name, path)
        except OSError as exc:                          # URLError, timeouts and disk errors all land here
            print(f"Error: could not download {name}: {exc}")
            print("Check your internet connection and try again; finished files are kept.")
            return 1
        if not _is_complete(path, size):
            os.remove(path)
            print(f"Error: {name} downloaded but its size or checksum is wrong, so it was deleted. Try again.")
            return 1
        print(f"  done     {name}")

    print("\nThe offline model is ready. Set EMBED_PROVIDER=local in .env, then run: python scripts/ingest.py")
    if args.dir:
        print(f"Because you chose a folder, also set LOCAL_EMBED_DIR={args.dir} in .env.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
