from __future__ import annotations

import io
import shutil
from pathlib import Path
from urllib.parse import urlencode

import pytest
import requests

WORTEL = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


def fixture(naam: str) -> bytes:
    return (FIXTURES / naam).read_bytes()


class _Raw:
    def __init__(self, data: bytes):
        self._b = io.BytesIO(data)

    def read(self, amt=None, decode_content=False):
        return self._b.read(amt) if amt else self._b.read()

    def close(self):
        pass


def maak_antwoord(url: str, status: int = 200, inhoud: bytes = b"", headers: dict | None = None) -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r.url = url
    r.raw = _Raw(inhoud)
    r.headers.update(headers or {})
    r.encoding = "utf-8"
    return r


class FakeSessie:
    """Vervangt requests.Session: antwoorden per URL-fragment, zonder netwerk."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.verzoeken: list[tuple[str, dict]] = []
        self.headers: dict = {}

    def get(self, url, headers=None, timeout=None, allow_redirects=True, stream=False, params=None):
        if params:
            url = f"{url}?{urlencode(params)}"
        self.verzoeken.append((url, dict(headers or {})))
        for patroon, antwoord in self.routes.items():
            if patroon in url:
                if callable(antwoord):
                    return antwoord(url, headers or {})
                status, inhoud, kop = antwoord
                return maak_antwoord(url, status, inhoud, kop)
        return maak_antwoord(url, 404, b"niet gevonden")

    def post(self, *args, **kwargs):
        raise AssertionError("onverwachte POST")


@pytest.fixture
def wortel(tmp_path: Path) -> Path:
    for naam in ("categorieen.yml", "instellingen.yml"):
        shutil.copy(WORTEL / naam, tmp_path / naam)
    (tmp_path / "site" / "data").mkdir(parents=True)
    return tmp_path
