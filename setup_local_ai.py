"""Install the pinned portable Ollama runtime; the app downloads its local model."""

import hashlib
import json
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

from local_ai import ROOT, RUNTIME, RUNTIME_VERSION

RUNTIME_SHA256 = "d52aea2d323bdd324bf66a4b1226844aa5fb665cc5974fbcceceda1ce3d934eb"
RUNTIME_URL = f"https://github.com/ollama/ollama/releases/download/{RUNTIME_VERSION}/ollama-windows-amd64.zip"


def emit(**data):
    print(json.dumps(data), flush=True)


def main():
    marker = RUNTIME.parent/"installation.json"
    if RUNTIME.is_file() and marker.is_file():
        emit(event="complete", message="Portable runtime is already installed")
        return
    downloads = ROOT/".deps/ai/downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    archive = downloads/("ollama-"+RUNTIME_VERSION+".zip")
    if not archive.is_file():
        partial = archive.with_suffix(".part")
        emit(event="status", message="Downloading portable runtime (1.59 GB)…")
        digest = hashlib.sha256()
        with urllib.request.urlopen(RUNTIME_URL, timeout=60) as response, partial.open("wb") as stream:
            total = int(response.headers.get("Content-Length", 1586229413))
            completed, last_update = 0, 0
            while chunk := response.read(4*1024*1024):
                stream.write(chunk)
                digest.update(chunk)
                completed += len(chunk)
                if time.monotonic()-last_update >= 2:
                    emit(event="progress", completed=completed, total=total)
                    last_update = time.monotonic()
        if digest.hexdigest() != RUNTIME_SHA256:
            raise ValueError("Official runtime archive SHA-256 verification failed")
        partial.replace(archive)
    else:
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != RUNTIME_SHA256:
                raise ValueError("Cached runtime archive SHA-256 verification failed")
    emit(event="status", message="Runtime verified. Extracting local files…")
    RUNTIME.parent.mkdir(parents=True, exist_ok=True)
    target = RUNTIME.parent.resolve()
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            if not (target/member.filename).resolve().is_relative_to(target):
                raise ValueError("Invalid archive path")
        package.extractall(target)
    if not RUNTIME.is_file():
        raise ValueError("Runtime executable was not found after extraction")
    marker.write_text(json.dumps({"version": RUNTIME_VERSION, "archive_url": RUNTIME_URL,
        "archive_sha256": RUNTIME_SHA256}, indent=2), encoding="utf-8")
    emit(event="complete", message="Portable runtime installed; ready to download the local model")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        emit(event="error", message=str(error))
        sys.exit(1)
