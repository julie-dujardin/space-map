"""Synchronous TAP queries, with an optional uploaded table.

A query reads the uploaded table as `TAP_UPLOAD.sent`. The table has one
column.
"""

import csv
import io
import logging
import re
import time
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Literal
from xml.sax.saxutils import escape

import httpx

from space_map_data.download.downloader import DownloadError

logger = logging.getLogger(__name__)

_UPLOAD_NAME = "sent"
# The largest table starts to arrive after about 25 s.
TIMEOUT_SECONDS = 180.0
# A service sometimes accepts a query and never answers it.
ATTEMPTS = 3
RETRY_PAUSE_SECONDS = 20.0
_FIELDS = {
    "char": '<FIELD name="{}" datatype="char" arraysize="*"/>',
    "long": '<FIELD name="{}" datatype="long"/>',
}
_ERROR_RE = re.compile(r'<INFO name="QUERY_STATUS" value="ERROR">(.*?)</INFO>', re.S)

Rows = tuple[list[str], list[list[str]]]


class _Busy(Exception):
    """The service refused the query for now. The query can be sent again."""


def votable(
    column: str, datatype: Literal["char", "long"], values: Iterable[object]
) -> bytes:
    """Build a VOTable with one column."""
    rows = "".join(f"<TR><TD>{escape(str(value))}</TD></TR>" for value in values)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<VOTABLE version="1.3" xmlns="http://www.ivoa.net/xml/VOTable/v1.3">'
        f"<RESOURCE><TABLE>{_FIELDS[datatype].format(column)}"
        f"<DATA><TABLEDATA>{rows}</TABLEDATA></DATA></TABLE></RESOURCE></VOTABLE>"
    ).encode()


def _form(query: str) -> dict[str, str]:
    return {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": query}


def _check(url: str, status: int, body: str) -> None:
    """Raise if the answer is not a CSV table."""
    # A TAP service answers a failed query with a VOTable, whatever the format.
    error = _ERROR_RE.search(body)
    if error:
        raise DownloadError(f"TAP query failed at {url}: {error.group(1).strip()}")
    if status == 429 or status >= 500:
        raise _Busy(f"HTTP {status}")
    if status >= 400 or body.lstrip().startswith("<"):
        raise DownloadError(f"TAP query failed at {url}: {body[:300]}")
    if not body.strip():
        raise DownloadError(f"TAP service at {url} sent an empty answer")


def _with_retry[T](url: str, send: Callable[[], T]) -> T:
    """Call `send`. Call it again after a pause if the service does not answer."""
    reason = ""
    for attempt in range(1, ATTEMPTS + 1):
        if attempt > 1:
            time.sleep(RETRY_PAUSE_SECONDS)
        try:
            return send()
        except (httpx.TransportError, _Busy) as exc:
            reason = str(exc) or type(exc).__name__
            logger.warning(
                "TAP query to %s got no answer (%s), attempt %d of %d",
                url,
                reason,
                attempt,
                ATTEMPTS,
            )
    raise DownloadError(f"TAP service at {url} did not answer: {reason}")


def tap_sync(
    client: httpx.Client, url: str, query: str, *, upload: bytes | None = None
) -> str:
    """Run one ADQL query and return the CSV body."""
    data = _form(query)
    files = None
    if upload is not None:
        data["UPLOAD"] = f"{_UPLOAD_NAME},param:{_UPLOAD_NAME}"
        files = {_UPLOAD_NAME: ("sent.xml", upload, "application/x-votable+xml")}

    def send() -> str:
        response = client.post(url, data=data, files=files, timeout=TIMEOUT_SECONDS)
        _check(url, response.status_code, response.text)
        return response.text

    return _with_retry(url, send)


def tap_to_file(client: httpx.Client, url: str, query: str, path: Path) -> None:
    """Run one ADQL query and stream the CSV body to `path`."""

    def send() -> None:
        with client.stream(
            "POST", url, data=_form(query), timeout=TIMEOUT_SECONDS
        ) as response:
            if response.status_code >= 400:
                _check(url, response.status_code, response.read().decode())
            with path.open("wb") as fh:
                for chunk in response.iter_bytes(chunk_size=1 << 20):
                    fh.write(chunk)
        with path.open("rb") as fh:
            head = fh.read(4096).decode(errors="replace")
        _check(url, 200, head)

    _with_retry(url, send)


def parse_csv(body: str) -> Rows:
    """Split a CSV body into its header and its rows."""
    reader = csv.reader(io.StringIO(body))
    header = next(reader, None)
    if not header:
        raise DownloadError(f"CSV answer has no header: {body[:80]!r}")
    return header, list(reader)


def tap_rows(client: httpx.Client, url: str, query: str) -> Rows:
    """Run one ADQL query and return the header and the rows."""
    return parse_csv(tap_sync(client, url, query))


def tap_join(
    client: httpx.Client,
    url: str,
    query: str,
    column: str,
    datatype: Literal["char", "long"],
    values: Sequence[object],
    chunk: int,
) -> Rows:
    """Run `query` against `values`, uploaded `chunk` at a time."""
    if not values:
        raise DownloadError(f"No {column} to send to {url}")
    header: list[str] = []
    rows: list[list[str]] = []
    for start in range(0, len(values), chunk):
        upload = votable(column, datatype, values[start : start + chunk])
        header, part = parse_csv(tap_sync(client, url, query, upload=upload))
        rows.extend(part)
    return header, rows


def write_csv(path: Path, header: list[str], rows: Iterable[Sequence[object]]) -> None:
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
