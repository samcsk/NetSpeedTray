"""Stage the official Windows x64 Codex helper for a source run or PyInstaller build.

The installer targets x64compatible, including x64 emulation on Windows 11 on ARM.
The npm release is OpenAI's native binary distribution. Node and npm are not used.
"""
import base64
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import urllib.request


BUILD = Path(__file__).resolve().parent
MEMBER = "package/vendor/x86_64-pc-windows-msvc/bin/codex.exe"


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def stage(destination, release):
    expected = release["exe_sha256"]
    if destination.is_file() and sha256(destination) == expected:
        return
    version = release["version"]
    url = f"https://registry.npmjs.org/@openai/codex/-/codex-{version}-win32-x64.tgz"
    print(f"Fetching OpenAI Codex {version} for Windows x64", flush=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Same volume for atomic replacement; keep incomplete downloads outside the assets tree.
    with tempfile.TemporaryDirectory(dir=destination.parents[2]) as temp:
        archive = Path(temp) / "codex.tgz"
        with urllib.request.urlopen(url, timeout=120) as response, archive.open("wb") as out:
            shutil.copyfileobj(response, out)
        with archive.open("rb") as stream:
            digest = base64.b64encode(hashlib.file_digest(stream, "sha512").digest()).decode("ascii")
        if digest != release["npm_sha512"]:
            raise ValueError("Codex package does not match the published npm integrity pin")
        candidate = Path(temp) / "codex.exe"
        with tarfile.open(archive, "r:gz") as package:
            member = package.getmember(MEMBER)
            if not member.isfile():
                raise ValueError("Codex package is missing the Windows executable")
            with package.extractfile(member) as source, candidate.open("wb") as out:
                shutil.copyfileobj(source, out)
        if sha256(candidate) != expected:
            raise ValueError("Codex executable does not match the pinned OpenAI-signed binary")
        candidate.replace(destination)


if __name__ == "__main__":
    release = json.loads((BUILD / "codex-release.json").read_text(encoding="utf-8"))
    stage(BUILD.parent / "assets" / "codex" / "codex.exe", release)
