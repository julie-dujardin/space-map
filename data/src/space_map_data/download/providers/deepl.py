"""Translate the hand-authored UI strings in ``frontend/messages/en.json``.

For every target language we maintain a nested cache file at
``DOWNLOAD_DIR/deepl/{lang}.json`` of the form

    {context_label: {substituted_source: restored_translation}}

where ``context_label`` is the message key's prefix bucket (see
``export.deepl.PREFIX_TO_CONTEXT``) and ``substituted_source`` is the text
actually sent to DeepL — placeholders replaced with numeric stand-ins so the
engine treats them as immovable tokens instead of free-floating phrases.
For plural-variant messages, the stand-in for the selector placeholder is a
small representative number (1, 2, 3, 5) chosen for the target CLDR
category, which nudges DeepL toward the right inflection.

Context labels are sent to DeepL via the ``context`` parameter to
disambiguate domain terms (``Amor`` the orbital class, ``decayed`` the
satellite, ``undocumented`` the object).

The API key is read from ``DEEPL_API_KEY``. Free-tier keys end in ``:fx``
and route to ``api-free.deepl.com``. Without a key the downloader logs and
skips API calls; existing caches stay intact.
"""

import json
import logging
import os
import re
from collections import defaultdict
from datetime import UTC, datetime

import httpx
import orjson

from space_map_data.constants.providers import LANGUAGES, PROVIDERS
from space_map_data.download.downloader import Downloader
from space_map_data.export.deepl import (
    CONTEXTS,
    DEEPL_DIR,
    MessageValue,
    context_label_for_key,
    expand_for_target,
    restore_placeholders,
)
from space_map_data.export.localization import (
    GENERATED_PREFIXES,
    MESSAGES_DIR,
)

logger = logging.getLogger(__name__)

# Our internal lang codes → DeepL target language codes.
# DeepL needs uppercase codes; ZH must specify a script variant.
DEEPL_TARGET_LANG: dict[str, str] = {
    "fr": "FR",
    "ja": "JA",
    "zh": "ZH-HANS",
    "ar": "AR",
    "ru": "RU",
}

# DeepL accepts up to 50 text entries per request.
_BATCH_SIZE = 50

_LEGACY_PLACEHOLDER_RE = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")


def _api_endpoint(api_key: str) -> str:
    if api_key.endswith(":fx"):
        return "https://api-free.deepl.com/v2/translate"
    return "https://api.deepl.com/v2/translate"


def _source_entries() -> list[tuple[str, MessageValue]]:
    """Return ``[(message_key, en_value), ...]`` from ``en.json``.

    Drops Wikidata-generated keys and empty values. Keeps both plain strings
    and variant arrays — ``expand_for_target`` will unpack the latter.
    """
    en_file = MESSAGES_DIR / "en.json"
    if not en_file.exists():
        return []
    data = orjson.loads(en_file.read_bytes())
    out: list[tuple[str, MessageValue]] = []
    for k, v in data.items():
        if any(k.startswith(p) for p in GENERATED_PREFIXES):
            continue
        if isinstance(v, str) and v:
            out.append((k, v))
        elif isinstance(v, list) and v:
            out.append((k, v))
    return out


def _missing_per_context(
    entries: list[tuple[str, MessageValue]],
    cache: dict[str, dict[str, str]],
    target_lang: str,
) -> dict[str, list[tuple[str, dict[str, str]]]]:
    """Group untranslated DeepL inputs by context label.

    Each entry expands into one or more ``(substituted_source, inverse)``
    pairs via :func:`expand_for_target`. We then deduplicate within each
    context label (the same substituted source from two messages of the
    same prefix only needs one translation).
    """
    out: dict[str, list[tuple[str, dict[str, str]]]] = defaultdict(list)
    seen: dict[str, set[str]] = defaultdict(set)
    for key, value in entries:
        label = context_label_for_key(key)
        for _target_cat, substituted, inverse in expand_for_target(value, target_lang):
            if substituted in cache.get(label, {}):
                continue
            if substituted in seen[label]:
                continue
            seen[label].add(substituted)
            out[label].append((substituted, inverse))
    return out


class DeepLDownloader(Downloader):
    """Pre-translate frontend UI strings via DeepL, caching to the download dir."""

    name = PROVIDERS.DEEPL

    def __init__(self, client: httpx.Client) -> None:
        # Override base: we live under DOWNLOAD_DIR/deepl, not provider-named.
        self.client = client
        self.out_dir = DEEPL_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def _post(
        self,
        texts: list[str],
        target_deepl: str,
        context: str,
        api_key: str,
    ) -> list[str]:
        """POST one batch to DeepL and return raw translated texts (same order)."""
        payload: dict[str, object] = {
            "source_lang": "EN",
            "target_lang": target_deepl,
            "context": context,
            "preserve_formatting": "1",
            "text": texts,
        }
        headers = {"Authorization": f"DeepL-Auth-Key {api_key}"}
        resp = self.client.post(
            _api_endpoint(api_key), headers=headers, data=payload, timeout=60.0
        )
        resp.raise_for_status()
        return [t["text"] for t in resp.json()["translations"]]

    def _translate_context(
        self,
        label: str,
        jobs: list[tuple[str, dict[str, str]]],
        target_lang: str,
        target_deepl: str,
        api_key: str,
        cache_bucket: dict[str, str],
    ) -> int:
        """Translate every (substituted, inverse) job for one context label."""
        context = CONTEXTS[label]
        translated = 0
        for i in range(0, len(jobs), _BATCH_SIZE):
            batch = jobs[i : i + _BATCH_SIZE]
            try:
                raw_outputs = self._post(
                    [substituted for substituted, _ in batch],
                    target_deepl,
                    context,
                    api_key,
                )
            except httpx.HTTPError:
                logger.exception(
                    "DeepL request failed for %r/%s (batch %d); "
                    "%d string(s) left untranslated",
                    target_lang,
                    label,
                    i // _BATCH_SIZE,
                    len(batch),
                )
                continue
            for (substituted, inverse), raw in zip(batch, raw_outputs, strict=True):
                missing = [s for s in inverse if s not in raw]
                if missing:
                    logger.warning(
                        "DeepL response dropped stand-in(s) %s — falling back "
                        "to substituted text (text=%r)",
                        missing,
                        raw,
                    )
                cache_bucket[substituted] = restore_placeholders(raw, inverse)
            translated += len(batch)
        return translated

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        entries = _source_entries()
        if not entries:
            logger.warning("No source strings in %s/en.json — skipping", MESSAGES_DIR)
            return

        api_key = os.environ.get("DEEPL_API_KEY")
        target_langs = [
            lang for lang in LANGUAGES if lang != "en" and lang in DEEPL_TARGET_LANG
        ]

        totals: dict[str, dict[str, int]] = {}
        new_translations = 0

        for lang in target_langs:
            cache = self._load_cache(lang)
            missing = _missing_per_context(entries, cache, lang)

            if not missing:
                logger.info("%s: cache covers all source strings", lang)
                totals[lang] = {k: len(v) for k, v in cache.items()}
                continue

            total_missing = sum(len(v) for v in missing.values())
            if not api_key:
                logger.warning(
                    "DEEPL_API_KEY not set; %d uncached string(s) across %d "
                    "context(s) for %r left untranslated",
                    total_missing,
                    len(missing),
                    lang,
                )
                totals[lang] = {k: len(v) for k, v in cache.items()}
                continue

            target_deepl = DEEPL_TARGET_LANG[lang]
            translated = 0
            for label, jobs in missing.items():
                bucket = cache.setdefault(label, {})
                translated += self._translate_context(
                    label, jobs, lang, target_deepl, api_key, bucket
                )

            if translated:
                self._save_cache(lang, cache)
                logger.info(
                    "%s: translated %d new string(s) across %d context(s)",
                    lang,
                    translated,
                    len(missing),
                )
                new_translations += translated
            totals[lang] = {k: len(v) for k, v in cache.items()}

        self.metadata_file.write_text(
            json.dumps(
                {
                    "downloaded_at": datetime.now(UTC).isoformat(),
                    "source_url": "https://api.deepl.com/v2/translate",
                    "record_count": new_translations,
                    "complete": True,
                    "source_messages": len(entries),
                    "contexts": sorted(CONTEXTS),
                    "cache_size_per_lang": totals,
                    "api_key_present": bool(api_key),
                },
                indent=2,
            )
        )

    def _load_cache(self, target_lang: str) -> dict[str, dict[str, str]]:
        f = DEEPL_DIR / f"{target_lang}.json"
        if not f.exists():
            return {}
        try:
            data = orjson.loads(f.read_bytes())
        except orjson.JSONDecodeError:
            logger.warning("Corrupt DeepL cache at %s, starting fresh", f)
            return {}
        # Legacy flat caches from before the per-context split: lift them into
        # the 'default' bucket. Drop entries whose source contained a
        # ``{placeholder}`` — those were translated with the old <ph> tag
        # scheme and tend to be mangled; let DeepL retry them with numeric
        # stand-ins. Plain-text entries are kept as-is to avoid re-billing.
        if data and not any(isinstance(v, dict) for v in data.values()):
            kept = {
                k: v for k, v in data.items() if not _LEGACY_PLACEHOLDER_RE.search(k)
            }
            dropped = len(data) - len(kept)
            logger.info(
                "Migrating legacy flat cache for %r into 'default' bucket "
                "(%d kept, %d dropped because source has placeholders)",
                target_lang,
                len(kept),
                dropped,
            )
            return {"default": kept}
        return data

    def _save_cache(self, target_lang: str, cache: dict[str, dict[str, str]]) -> None:
        DEEPL_DIR.mkdir(parents=True, exist_ok=True)
        sorted_cache = {
            label: dict(sorted(bucket.items()))
            for label, bucket in sorted(cache.items())
        }
        (DEEPL_DIR / f"{target_lang}.json").write_bytes(
            orjson.dumps(sorted_cache, option=orjson.OPT_INDENT_2)
        )

    def is_complete(self, limit: int | None) -> bool:
        # Always re-run: cheap when source unchanged (zero API calls), and any
        # new string in en.json should propagate without a force flag.
        return False
