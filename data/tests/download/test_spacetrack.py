"""Unit tests for the Space-Track GP downloader."""

from datetime import datetime, timezone

import httpx
import pytest

from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.objects import spacetrack
from space_map_data.download.providers.objects.spacetrack import SpaceTrackDownloader

_GP_CSV = (
    "OBJECT_NAME,OBJECT_ID,EPOCH,MEAN_MOTION,ECCENTRICITY,INCLINATION,"
    "RA_OF_ASC_NODE,ARG_OF_PERICENTER,MEAN_ANOMALY,NORAD_CAT_ID,ELEMENT_SET_NO,"
    "REV_AT_EPOCH,BSTAR,MEAN_MOTION_DOT,MEAN_MOTION_DDOT\r\n"
    "VANGUARD 1,1958-002B,2026-06-13T03:35:44.322720,10.85997349,0.18354928,"
    "34.2465,326.7899,120.2934,259.1949,5,999,44284,0.00040821,3.03e-06,0.0\r\n"
)


class _Resp:
    def __init__(self, text: str = "", status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)  # type: ignore[arg-type]


class _Client:
    """Minimal stand-in for httpx.Client recording the GP query it received."""

    def __init__(self, login: _Resp, gp: _Resp) -> None:
        self._login, self._gp = login, gp
        self.gp_url: str | None = None

    def post(self, url: str, data: dict) -> _Resp:
        return self._login

    def get(self, url: str) -> _Resp:
        self.gp_url = url
        return self._gp


@pytest.fixture
def out_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(spacetrack, "SOURCES_POSITION_DIR", tmp_path)
    monkeypatch.setenv("SPACETRACK_IDENTITY", "u")
    monkeypatch.setenv("SPACETRACK_PASSWORD", "p")
    return tmp_path / "spacetrack" / "current"


def test_missing_credentials_raises(out_dir, monkeypatch):
    monkeypatch.delenv("SPACETRACK_IDENTITY", raising=False)
    dl = SpaceTrackDownloader(_Client(_Resp(), _Resp(_GP_CSV)))  # type: ignore[arg-type]
    with pytest.raises(DownloadError, match="SPACETRACK_IDENTITY"):
        dl.download()


def test_login_failure_raises(out_dir):
    client = _Client(_Resp('{"Login":"Failed"}'), _Resp(_GP_CSV))
    dl = SpaceTrackDownloader(client)  # type: ignore[arg-type]
    with pytest.raises(DownloadError, match="login failed"):
        dl.download()


def test_download_writes_catalogue_and_metadata(out_dir):
    # A successful Space-Track login returns an empty-string body (`""`).
    client = _Client(_Resp('""'), _Resp(_GP_CSV))
    dl = SpaceTrackDownloader(client)  # type: ignore[arg-type]
    dl.download()

    today = datetime.now(timezone.utc).date()
    day_dir = out_dir / f"{today.year:04d}" / f"{today.month:02d}" / f"{today.day:02d}"
    written = (day_dir / "gp-active.csv").read_text()
    assert "NORAD_CAT_ID" in written
    assert "VANGUARD 1" in written
    # Single query, properly scoped to non-decayed recent elements.
    assert client.gp_url is not None and "decay_date/null-val" in client.gp_url
    assert dl.is_complete(None) is True


def test_unexpected_gp_response_raises(out_dir):
    client = _Client(_Resp(), _Resp("<html>login</html>"))
    dl = SpaceTrackDownloader(client)  # type: ignore[arg-type]
    with pytest.raises(DownloadError, match="Unexpected GP response"):
        dl.download()
