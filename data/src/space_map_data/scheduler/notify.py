"""Send a download-run summary via Pushover and Resend email.

Channels are configured via env vars; missing config means that channel is
silently skipped (logged at INFO).

    PUSHOVER_TOKEN, PUSHOVER_USER
    RESEND_API_KEY, NOTIFY_EMAIL_FROM, NOTIFY_EMAIL_TO
"""

import logging
import os

import httpx

from space_map_data.download.common import ProviderResult

logger = logging.getLogger(__name__)


def _status(r: ProviderResult) -> str:
    if not r.ok:
        return "FAIL"
    if r.skipped:
        return "SKIP"
    return "OK  "


def _format(results: list[ProviderResult]) -> tuple[str, str]:
    failed = [r for r in results if not r.ok]
    skipped = [r for r in results if r.ok and r.skipped]
    done = [r for r in results if r.ok and not r.skipped]
    n_total = len(results)
    if failed:
        title = f"space-map download: {len(failed)}/{n_total} failed"
    else:
        title = f"space-map download: {len(done)}/{n_total} OK ({len(skipped)} skipped)"
    lines = [
        f"{_status(r)} {r.name}" + (f": {r.error}" if r.error else "") for r in results
    ]
    return title, "\n".join(lines)


def _send_pushover(title: str, body: str, *, priority: int) -> None:
    token = os.environ.get("PUSHOVER_TOKEN")
    user = os.environ.get("PUSHOVER_USER")
    if not token or not user:
        logger.info("Pushover not configured (PUSHOVER_TOKEN/USER), skipping")
        return
    try:
        resp = httpx.post(
            "https://api.pushover.net/1/messages.json",
            data={
                "token": token,
                "user": user,
                "title": title,
                "message": body,
                "priority": priority,
            },
            timeout=30.0,
        )
        resp.raise_for_status()
    except Exception:
        logger.exception("Failed to send Pushover notification")


def _send_email(title: str, body: str) -> None:
    api_key = os.environ.get("RESEND_API_KEY")
    sender = os.environ.get("NOTIFY_EMAIL_FROM")
    recipient = os.environ.get("NOTIFY_EMAIL_TO")
    if not api_key or not sender or not recipient:
        logger.info(
            "Resend not configured (RESEND_API_KEY/NOTIFY_EMAIL_FROM/NOTIFY_EMAIL_TO), skipping"
        )
        return
    try:
        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "from": sender,
                "to": [recipient],
                "subject": title,
                "text": body,
            },
            timeout=30.0,
        )
        resp.raise_for_status()
    except Exception:
        logger.exception("Failed to send Resend email")


def notify_download_run(results: list[ProviderResult]) -> None:
    """Send pushover + email summary. Pushover priority 1 if any failure, else -2.

    No-op when every provider was skipped (already complete) — we only notify
    on actual work or failures, not on idle wake-ups.
    """
    any_failed = any(not r.ok for r in results)
    any_work = any(r.ok and not r.skipped for r in results)
    if not any_failed and not any_work:
        logger.info(
            "All %d provider(s) already complete; skipping notification", len(results)
        )
        return
    title, body = _format(results)
    priority = 1 if any_failed else -2
    _send_pushover(title, body, priority=priority)
    _send_email(title, body)


if __name__ == "__main__":
    import logging.config
    import tomllib

    from space_map_data.utils.paths import DATA_DIR

    with open(DATA_DIR / "logging.toml", "rb") as f:
        logging.config.dictConfig(tomllib.load(f))

    notify_download_run(
        [
            ProviderResult("test_ok", ok=True),
            ProviderResult("test_fail", ok=False, error="RuntimeError: simulated"),
        ]
    )
