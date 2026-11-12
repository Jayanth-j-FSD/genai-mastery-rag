"""Download the free offline embedding model (about 90 MB), once.

Embeddings can come from a paid API or from a small model that runs on your own
machine. This fetches that small model (all-MiniLM-L6-v2, the ONNX export published by the
Xenova project on HuggingFace) into the folder the app looks in. It downloads one pinned revision
of the repository and checks every file's size and SHA-256, so a half-finished or tampered download
is caught instead of producing mysteriously bad search results.

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

# The exact revision of the HuggingFace repository, so a later upstream commit cannot change what a
# fresh clone downloads (and make the checks below fail forever). Found with:
#   https://huggingface.co/api/models/Xenova/all-MiniLM-L6-v2   (the "sha" field, last modified 2025-07-22)
REVISION = "751bff37182d3f1213fa05d7196b954e230abad9"
BASE_URL = f"https://huggingface.co/Xenova/all-MiniLM-L6-v2/resolve/{REVISION}/"

# file -> (size in bytes, SHA-256). Every file is checked, not only the large one.
FILES = {
    "onnx/model.onnx": (90387606, "759c3cd2b7fe7e93933ad23c4c9181b7396442a2ed746ec7c1d46192c469c46e"),
    "tokenizer.json": (711661, "da0e79933b9ed51798a3ae27893d3c5fa4a201126cef75586296df9b4d2c62a0"),
    "config.json": (650, "7135149f7cffa1a573466c6e4d8423ed73b62fd2332c575bf738a0d033f70df7"),
    "tokenizer_config.json": (366, "9261e7d79b44c8195c1cada2b453e55b00aeb81e907a6664974b4d7776172ab3"),
    "special_tokens_map.json": (125, "b6d346be366a7d1d48332dbc9fdf3bf8960b5d879522b7799ddba59e76237ee3"),
    "vocab.txt": (231508, "07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3"),
}


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_complete(path, size, sha256):
    """The file exists with exactly the expected size and checksum."""
    if not os.path.exists(path) or os.path.getsize(path) != size:
        return False
    return _sha256(path) == sha256


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

    for name, (size, sha256) in FILES.items():
        path = os.path.join(target, *name.split("/"))
        if _is_complete(path, size, sha256):
            print(f"  ok       {name}")
            continue
        print(f"  fetching {name} ({size / 1e6:.1f} MB)...", flush=True)
        try:
            _download(name, path)
        except OSError as exc:                          # URLError, timeouts and disk errors all land here
            print(f"Error: could not download {name}: {exc}")
            print("Check your internet connection and try again; finished files are kept.")
            return 1
        if not _is_complete(path, size, sha256):
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
