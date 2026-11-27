"""Exercise build-time integrity checks without downloading the Windows release."""
import base64
import hashlib
import io
from pathlib import Path
import runpy
import tarfile
import urllib.request

import pytest


BUILD = Path(__file__).resolve().parents[4] / "build"
helper = runpy.run_path(str(BUILD / "fetch_codex.py"))


@pytest.fixture
def package(monkeypatch):
    payload = b"stand-in for the signed executable"
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        member = tarfile.TarInfo(helper["MEMBER"])
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
    data = stream.getvalue()
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(data))
    return payload, {
        "version": "test",
        "npm_sha512": base64.b64encode(hashlib.sha512(data).digest()).decode("ascii"),
        "exe_sha256": hashlib.sha256(payload).hexdigest(),
    }


def test_pinned_helper_can_build_again_offline(tmp_path, package, monkeypatch):
    payload, pins = package
    exe = tmp_path / "assets" / "codex" / "codex.exe"
    helper["stage"](exe, pins)
    assert exe.read_bytes() == payload
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: pytest.fail("unexpected download"))
    helper["stage"](exe, pins)


@pytest.mark.parametrize("bad_pin", ["npm_sha512", "exe_sha256"])
def test_bad_download_preserves_existing_helper(tmp_path, package, bad_pin):
    _, pins = package
    exe = tmp_path / "assets" / "codex" / "codex.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"old version")
    with pytest.raises(ValueError, match="does not match"):
        helper["stage"](exe, {**pins, bad_pin: "wrong"})
    assert exe.read_bytes() == b"old version"
