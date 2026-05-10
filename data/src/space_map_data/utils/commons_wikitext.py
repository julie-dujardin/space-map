"""Parse Wikimedia Commons file-page wikitext for derivative-of / other-versions links.

Commons files often record relationships between images that no API exposes as
structured data:

- ``{{Information|other_versions=...}}`` — free-form pointer to "see also"
  alternates: crops, recolors, variants in different aspect ratios.
- ``{{derived from|File:A|File:B}}`` — explicit declaration that THIS file is
  derived from those parents (typically used inside ``other_versions=``).
- ``{{Extracted from|File:X}}``, ``{{Retouched picture|File:X}}``,
  ``{{Image extracted|File:X}}`` — single-parent variants.
- ``{{derivative versions|File:A|File:B}}`` — opposite direction: lists
  derivatives of THIS file.

Structured Data on Commons (P144 "based on", P4969 "derivative work") covers
some of this, but is sparsely populated. Parsing the wikitext catches the rest.

The parser is best-effort: it recognises these specific templates and any
``[[File:...]]`` / ``[[Image:...]]`` wikilinks inside ``other_versions=``.
Anything outside those patterns is ignored — stray File: links elsewhere on
the page are usually unrelated.
"""

import re

from space_map_data.utils.commons_images import canonical_filename


# Templates whose positional args list PARENT files (this file is derived from them).
_PARENT_TEMPLATES_POSITIONAL = (
    "derived from",
    "extracted from",
    "image extracted",
)

# Templates whose positional args list CHILD files (derivatives of this file).
_CHILD_TEMPLATES_POSITIONAL = ("derivative versions",)

# {{Retouched picture}} can take the original as positional arg 1 OR as
# ``orig=...``. Handled separately.
_RETOUCHED_TEMPLATE = "retouched picture"

# Match [[File:X]], [[Image:X]], [[:File:X]], [[:Image:X]] — capture filename
# up to the first | (display text) or the closing ]].
_FILE_LINK_RE = re.compile(
    r"\[\[\s*:?\s*(?:File|Image)\s*:\s*([^\]|]+?)\s*(?:\||\]\])",
    re.IGNORECASE,
)


def parse_wikitext(wikitext: str) -> tuple[list[str], list[str]]:
    """Extract ``(derived_from, other_versions)`` from a Commons file-page wikitext.

    Both lists are deduped and contain canonical (underscore-form) filenames
    without the ``File:`` prefix. ``derived_from`` lists declared parents;
    ``other_versions`` lists siblings/children mentioned in the
    ``other_versions=`` field of ``{{Information}}``.

    Returns ``([], [])`` for empty or unparseable input.
    """
    if not wikitext:
        return [], []

    derived_from: list[str] = []
    other_versions: list[str] = []

    # Templates anywhere in the page: parent and child declarations.
    for tpl_name in _PARENT_TEMPLATES_POSITIONAL:
        for args in _find_template_calls(wikitext, tpl_name):
            derived_from.extend(_filenames_from_positional_args(args))

    for tpl_name in _CHILD_TEMPLATES_POSITIONAL:
        for args in _find_template_calls(wikitext, tpl_name):
            other_versions.extend(_filenames_from_positional_args(args))

    for args in _find_template_calls(wikitext, _RETOUCHED_TEMPLATE):
        derived_from.extend(_retouched_picture_parents(args))

    # The ``other_versions=`` field of {{Information}} (or {{Artwork}}, etc.)
    # may contain free-form text with [[File:X]] links pointing to siblings.
    for value in _extract_field_values(wikitext, "other_versions"):
        for filename in _FILE_LINK_RE.findall(value):
            other_versions.append(canonical_filename(_clean_filename(filename)))

    return (
        _dedupe([f for f in derived_from if _looks_like_filename(f)]),
        _dedupe([f for f in other_versions if _looks_like_filename(f)]),
    )


def _find_template_calls(wikitext: str, template_name: str) -> list[list[str]]:
    """Return the args of every ``{{template_name|...}}`` call (case-insensitive).

    Each entry is the list of pipe-separated args (positional and named, in
    source order). The leading template name is stripped. Brace depth is
    tracked so nested templates split correctly.
    """
    calls: list[list[str]] = []
    name_re = re.compile(
        r"\{\{\s*" + re.escape(template_name) + r"\s*(?=[|}])",
        re.IGNORECASE,
    )
    for match in name_re.finditer(wikitext):
        end = _find_template_end(wikitext, match.start())
        if end is None:
            continue
        body = wikitext[match.end() : end - 2]  # exclude the trailing }}
        calls.append(_split_template_args(body))
    return calls


def _find_template_end(wikitext: str, start: int) -> int | None:
    """Return the index *just past* the matching ``}}`` for ``{{`` at ``start``.

    Tracks ``{{`` / ``}}`` and ``[[`` / ``]]`` so nested templates and
    wikilinks don't terminate early. Returns ``None`` if unbalanced.
    """
    i = start + 2
    depth = 1
    n = len(wikitext)
    while i < n:
        two = wikitext[i : i + 2]
        if two == "{{":
            depth += 1
            i += 2
        elif two == "}}":
            depth -= 1
            i += 2
            if depth == 0:
                return i
        elif two == "[[":
            # Skip wikilinks atomically: don't let a pipe inside [[X|Y]]
            # be mistaken for an arg separator (split happens later).
            i += 2
            link_depth = 1
            while i < n and link_depth > 0:
                t = wikitext[i : i + 2]
                if t == "[[":
                    link_depth += 1
                    i += 2
                elif t == "]]":
                    link_depth -= 1
                    i += 2
                else:
                    i += 1
        else:
            i += 1
    return None


def _split_template_args(body: str) -> list[str]:
    """Split a template body on ``|`` at depth 0 only.

    Skips pipes nested inside ``{{...}}`` or ``[[...]]``. The body excludes
    the leading template name (caller has already advanced past it).
    """
    args: list[str] = []
    depth_t = 0
    depth_l = 0
    buf: list[str] = []
    i = 0
    n = len(body)
    while i < n:
        two = body[i : i + 2]
        if two == "{{":
            depth_t += 1
            buf.append(two)
            i += 2
        elif two == "}}":
            depth_t -= 1
            buf.append(two)
            i += 2
        elif two == "[[":
            depth_l += 1
            buf.append(two)
            i += 2
        elif two == "]]":
            depth_l -= 1
            buf.append(two)
            i += 2
        elif body[i] == "|" and depth_t == 0 and depth_l == 0:
            args.append("".join(buf))
            buf = []
            i += 1
        else:
            buf.append(body[i])
            i += 1
    args.append("".join(buf))
    # First "arg" is everything between the template name and the first pipe;
    # for ``{{name|a|b}}`` that's empty. For ``{{name}}`` (no pipe) it's also
    # empty. Either way, drop the leading empty placeholder.
    if args and not args[0].strip():
        args = args[1:]
    return args


def _filenames_from_positional_args(args: list[str]) -> list[str]:
    """Pick filenames out of a template's positional args.

    Skips named args (``key=value``) and obvious display-control options
    (``display``, ``size``, ``align``, etc.). Strips ``File:`` / ``Image:``
    prefixes. Returns canonical filenames.
    """
    out: list[str] = []
    for raw in args:
        arg = raw.strip()
        if not arg:
            continue
        if "=" in arg:
            # Named arg — these are typically display options, not filenames.
            # We could handle ``orig=File:X`` here for {{Retouched picture}},
            # but that template gets its own handler.
            continue
        cleaned = _clean_filename(arg)
        if cleaned:
            out.append(canonical_filename(cleaned))
    return out


def _retouched_picture_parents(args: list[str]) -> list[str]:
    """Extract parent filenames from a {{Retouched picture}} call.

    The original can be the first positional arg or named ``orig=...``.
    """
    out: list[str] = []
    seen_positional = False
    for raw in args:
        arg = raw.strip()
        if not arg:
            continue
        if "=" in arg:
            key, _, value = arg.partition("=")
            if key.strip().lower() in ("orig", "original"):
                cleaned = _clean_filename(value.strip())
                if cleaned:
                    out.append(canonical_filename(cleaned))
        elif not seen_positional:
            seen_positional = True
            cleaned = _clean_filename(arg)
            if cleaned:
                out.append(canonical_filename(cleaned))
    return out


def _extract_field_values(wikitext: str, field_name: str) -> list[str]:
    """Return values of ``|field_name=...`` across ALL templates in wikitext.

    Walks every top-level template and inspects its named args. Doesn't
    descend into nested templates because Commons puts ``other_versions=``
    on the outer ``{{Information}}`` / ``{{Artwork}}``.
    """
    values: list[str] = []
    i = 0
    n = len(wikitext)
    while i < n:
        if wikitext[i : i + 2] != "{{":
            i += 1
            continue
        end = _find_template_end(wikitext, i)
        if end is None:
            break
        # Skip past ``{{NAME`` to start splitting from the first ``|``.
        body_start = i + 2
        # Find the first ``|`` or ``}}`` to mark the end of the template name.
        j = body_start
        while j < end - 2 and wikitext[j] != "|":
            if wikitext[j : j + 2] == "{{":
                # Nested template before any pipe — give up, no named args.
                j = end - 2
                break
            j += 1
        if j < end - 2:
            args = _split_template_args(wikitext[j : end - 2])
            for arg in args:
                key, sep, value = arg.partition("=")
                if sep and key.strip().lower() == field_name.lower():
                    values.append(value)
        i = end
    return values


def _clean_filename(text: str) -> str:
    """Strip leading colons, ``File:`` / ``Image:`` prefixes, and HTML noise."""
    s = text.strip()
    # Drop leading colons (``[[:File:X]]`` form).
    while s.startswith(":"):
        s = s[1:].lstrip()
    # Strip File: / Image: prefix (case-insensitive).
    lower = s.lower()
    for prefix in ("file:", "image:"):
        if lower.startswith(prefix):
            s = s[len(prefix) :].lstrip()
            break
    # Filenames don't contain newlines; trim at first newline if any leaked in.
    s = s.split("\n", 1)[0].strip()
    return s


def _dedupe(items: list[str]) -> list[str]:
    """Order-preserving dedupe; drops empties."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


_FILE_EXTENSION_RE = re.compile(r"\.[A-Za-z0-9]{2,5}$")


def _looks_like_filename(name: str) -> bool:
    """Heuristic: real Commons filenames end in ``.<ext>`` (jpg, svg, webm, ...).

    Filters out template args that are display labels or descriptions
    rather than filenames — e.g. ``cropped_from_original``,
    ``Apollo_landing_sites``, ``low_resolution_vectorized_version``. These
    sneak in as positional args of ``{{derived from|...}}`` or as stale
    wikilinks in ``other_versions=`` and would otherwise cause spurious
    ``missing on Commons`` API calls during graph expansion.
    """
    return bool(_FILE_EXTENSION_RE.search(name))
