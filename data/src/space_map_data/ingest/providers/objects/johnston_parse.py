"""Parse one Johnston's Archive per-object page into system + companion rows.

The pages are hand-maintained HTML with no machine-readable form: every value
sits after a labelled ``<b>``/``<sub>`` run and is followed by ``± sigma``, a
unit, and a bracketed source code. Tags are collapsed to ``|`` so a label like
``diameter <b>d<sub>p</sub>:</b>`` reads as ``diameter |d|p|:|`` and can be
matched literally.

Values the archive doesn't have are printed as ``?``; assumed, derived and
estimated ones are flagged ``[*A]``, ``[*D]``, ``[*E]``. We keep all of them —
the source code travels with the number in ``*_ref`` columns nowhere yet, so
for now a derived value is not distinguished from a measured one.
"""

import html
import logging
import re

logger = logging.getLogger(__name__)

# Trailing bracket is the source code; `?` means the archive has no value.
_VALUE = r"\s*(\?|[-+]?[\d.]+(?:x10\|-?\d+\|)?)"
# An angle carries its degree sign on the value *and* on the sigma
# ("94.18° ± 0.42°"), where a length puts the unit after both ("1098.6 ± 6.1 km").
_SIGMA = r"(?:°?\s*±\s*([\d.]+(?:x10\|-?\d+\|)?))?"


def flatten(page: str) -> str:
    """Collapse markup to ``|`` separators and normalise whitespace."""
    text = html.unescape(re.sub(r"<[^>]+>", "|", page))
    return re.sub(r"\s+", " ", re.sub(r"\|{2,}", "|", text))


def _number(raw: str | None) -> float | None:
    """Parse a printed value, including the ``8.13x10|15|`` superscript form."""
    if raw is None or raw == "?":
        return None
    exponent = re.match(r"([-+]?[\d.]+)x10\|(-?\d+)\|", raw)
    if exponent is not None:
        return float(exponent.group(1)) * 10 ** int(exponent.group(2))
    try:
        return float(raw)
    except ValueError:
        return None


def _field(text: str, label: str) -> tuple[float | None, float | None]:
    """Return ``(value, sigma)`` for a numeric label, both None when absent."""
    found = re.search(label + _VALUE + _SIGMA, text)
    if found is None:
        return None, None
    return _number(found.group(1)), _number(found.group(2))


def _text_field(text: str, label: str) -> str | None:
    """Return the raw run after a label, minus its source code and units."""
    found = re.search(label + r"([^|]*)", text)
    if found is None:
        return None
    value = re.sub(r"\[[^\]]*\]", "", found.group(1)).strip(" .,")
    return value or None


def _block(text: str, heading: str) -> str:
    """Text of one ``orbital data,``/``other data,`` block, else empty."""
    found = re.search(
        r"\|%s:(.*?)(?=\|orbital data,|\|other data,|\|--|$)" % re.escape(heading), text
    )
    return found.group(1) if found else ""


def companion_labels(text: str) -> list[str]:
    """Block labels for each companion, in page order.

    A page carries ``orbital data, <label>`` and ``other data, <label>`` per
    companion. Some pages give a companion only one of the two, so the labels
    are unioned rather than taken from the orbital blocks alone.
    """
    labels: list[str] = []
    for kind in ("orbital data", "other data"):
        for label in re.findall(r"\|%s, ([^:|]{1,40}):" % kind, text):
            label = label.strip()
            if label in ("primary", "system (combined)") or label.startswith(
                "primary "
            ):
                continue
            if label not in labels:
                labels.append(label)
    return labels


def parse_system(text: str) -> dict:
    """System-wide and primary-body columns of one page."""
    combined = _block(text, "other data, system (combined)")
    primary = _block(text, "other data, primary")
    row: dict = {}

    row["h_mag"], _ = _field(combined, r"absolute mag\. \|H:\|")
    row["slope_g"], _ = _field(combined, r"slope parameter \|G:\|\|?\(?")
    row["diameter_km"], row["diameter_km_sigma"] = _field(
        combined, r"effective diameter \|d\|E\|:\|"
    )
    row["albedo"], row["albedo_sigma"] = _field(combined, r"geometric albedo\|:\|")
    row["mass_kg"], row["mass_kg_sigma"] = _field(combined, r"mass \|m:\|")
    row["density_g_cm3"], row["density_g_cm3_sigma"] = _field(
        combined, r"density \|ρ:\|"
    )
    row["hill_radius_km"], _ = _field(combined, r"Hill radius \|r\|H\|:\|")
    row["colour_ub"], _ = _field(combined, r"color index \|U-B:\|")
    row["colour_bv"], _ = _field(combined, r"color index \|B-V:\|")
    row["colour_vr"], _ = _field(combined, r"color index \|V-R:\|")
    row["colour_vi"], _ = _field(combined, r"color index \|V-I:\|")
    taxonomy = re.findall(r"([A-Za-z:+/*-]+)\s*\((SMASSII|Tholen|G-mode)\)", combined)
    if taxonomy:
        row["taxonomy"] = ", ".join(f"{cls} ({system})" for cls, system in taxonomy)

    row["primary_diameter_km"], row["primary_diameter_km_sigma"] = _field(
        primary, r"diameter \|d\|p\|:\|"
    )
    row["primary_dimensions"] = _text_field(primary, r"dimensions \|:\|")
    row["primary_axial_ratios"] = _text_field(primary, r"axial ratios \|a/b, b/c:\|")
    row["primary_rotation_h"], row["primary_rotation_h_sigma"] = _field(
        primary, r"rotation period \|RP\|p\|:\|"
    )
    row["primary_amplitude_mag"], _ = _field(
        primary, r"amplitude in mag\., rotational \|ΔM:\|"
    )
    pole = re.search(
        r"pole direction \|Β, λ:\|" + _VALUE + r"[^|]*?,\s*(\?|[-+]?[\d.]+)", primary
    )
    if pole is not None:
        row["pole_beta_deg"] = _number(pole.group(1))
        row["pole_lambda_deg"] = _number(pole.group(2))

    row["dynamical_type"] = _text_field(text, r"\|dynamical type, primary:\|")
    updated = re.search(r"last updated\s*\|?\s*([0-9]{1,2} \w+ [0-9]{4})", text)
    if updated is not None:
        row["last_updated"] = updated.group(1)
    return {k: v for k, v in row.items() if v is not None}


def parse_companion(text: str, label: str) -> dict:
    """Mutual-orbit and component columns for one companion block."""
    orbit = _block(text, "orbital data, %s" % label)
    other = _block(text, "other data, %s" % label)
    row: dict = {"label": label}

    row["binary_type"] = _text_field(orbit, r"binary dynamical type\|:\|")
    row["a_km"], row["a_km_sigma"] = _field(orbit, r"semimajor axis \|a\|s\|:\|")
    row["a_over_primary_radius"], _ = _field(
        orbit, r"separation/primary radius \|a\|s\|/r\|p\|:\|"
    )
    row["a_over_hill_radius"], _ = _field(
        orbit, r"separation/Hill radius \|a\|s\|/r\|H\|:\|"
    )
    row["per_d"], row["per_d_sigma"] = _field(orbit, r"orbital period \|P\|s\|:\|")
    row["e"], row["e_sigma"] = _field(orbit, r"eccentricity \|e\|s\|:\|")
    row["i"], row["i_sigma"] = _field(orbit, r"inclination \|i\|s\|:\|")
    row["om"], row["om_sigma"] = _field(orbit, r"ascending node \|Ω\|s\|:\|")
    row["w"], row["w_sigma"] = _field(orbit, r"argument of pericenter \|ω\|s\|:\|")
    row["ma"], row["ma_sigma"] = _field(orbit, r"mean anomaly \|M:\|")
    row["epoch"] = _text_field(orbit, r"Epoch\|:\|")
    row["normalised_ang_mom"], _ = _field(orbit, r"normalized ang\. mom\. \|α\|L\|:\|")

    row["diameter_km"], row["diameter_km_sigma"] = _field(
        other, r"diameter \|d\|s\|:\|"
    )
    row["diameter_ratio"], row["diameter_ratio_sigma"] = _field(
        other, r"diameter ratio \|d\|s\|/d\|p\|:\|"
    )
    row["dimensions"] = _text_field(other, r"dimensions \|:\|")
    row["mag_difference"], _ = _field(other, r"component mag\. difference \|ΔM:\|")
    row["rotation_h"], _ = _field(other, r"rotation period \|RP\|s\|:\|")
    return {k: v for k, v in row.items() if v is not None}


# Openers of the per-companion paragraphs in the discovery section. The
# archive writes whichever reads best — "Companion discovered" on a binary,
# "Third component discovered" on a triple, the moon's own name or
# designation elsewhere — so the opener is also the hint that ties a
# paragraph to its companion block.
_ORDINALS = r"(?:Second|Third|Fourth|Fifth|Sixth) (?:component|companion)"
_OPENER = re.compile(
    r"(Companion(?: \"[^\"]+\")?|" + _ORDINALS + r"|S/\d{4} \([^)]+\) \d+|"
    r"[A-Z][\w\'’-]*) discovered\|? ?"
)
_PRIMARY_OPENERS = {"Primary"}


def parse_discoveries(text: str, labels: list[str]) -> list[dict]:
    """One record per companion-discovery paragraph, in page order.

    ``label_hint``, ``provisional_designation`` and ``permanent_name`` are what
    tie a record back to a companion block — page order alone mis-assigns the
    systems whose blocks and paragraphs disagree. A bare-name opener is only
    accepted when it names one of this page's companions, so prose like
    "Both companions were discovered..." doesn't mint a phantom record.
    """
    start = text.find("discovery and notes")
    if start < 0:
        return []
    # Stop at the link lists that follow. The last companion's paragraph runs
    # to the end of the section, and those lists cite circulars of their own —
    # without the cut, every page's final companion is announced in whichever
    # IAUC happens to be linked below it.
    section = text[start:]
    end = section.find("|--")
    if end > 0:
        section = section[:end]
    known = {label.lower() for label in labels}

    spans: list[tuple[str, int, int]] = []
    for match in _OPENER.finditer(section):
        opener = match.group(1)
        if opener in _PRIMARY_OPENERS:
            continue
        generic = opener.startswith("Companion") or re.fullmatch(_ORDINALS, opener)
        if not generic and opener.lower() not in known and not opener.startswith("S/"):
            continue
        spans.append((opener, match.start(), match.end()))

    out: list[dict] = []
    for index, (opener, _, body_start) in enumerate(spans):
        body_end = spans[index + 1][1] if index + 1 < len(spans) else len(section)
        body = section[body_start:body_end]
        record: dict = {"label_hint": opener}
        date = re.match(r"([0-9]{4}(?: \w{3}(?: [0-9.]+)?)?)", body)
        if date is not None:
            record["discovery_date"] = date.group(1)
        by = re.search(r"\|? ?\bby\|? (.*?)(?:\|? ?using|\.\s*\|?Announced|$)", body)
        if by is not None:
            names = re.sub(r"\s+", " ", by.group(1).replace("|", " ")).strip(" .,")
            if names:
                record["discoverers"] = names
        using = re.search(r"using\|? ([^.]*?)(?:\|? ?observations)", body)
        if using is not None:
            record["discovery_method"] = re.sub(
                r"\s+", " ", using.group(1).replace("|", " ")
            ).strip()
        facility = re.search(
            r"observations from\|? (.*?)\.\s*\|?\s*"
            r"(?:Announced|Provisional|Permanent|Named|Reported|$)",
            body,
        )
        if facility is not None:
            record["discovery_facility"] = re.sub(
                r"\s+", " ", facility.group(1).replace("|", " ")
            ).strip()
        # The paragraph gives the announcement date and a bracketed reference
        # code into the archive's own source list; the circular numbers live in
        # the link block further down the page, which belongs to no one
        # companion. Only the date is a fact about this companion.
        announced = re.search(r"Announced\|? ?([0-9]{4}(?: \w{3}(?: [0-9.]+)?)?)", body)
        if announced is not None:
            record["announced"] = announced.group(1)
        designation = re.search(r"[Pp]rovisional designation\|? ?(S/[^.|]+)", body)
        if designation is not None:
            record["provisional_designation"] = re.sub(
                r"\s+", " ", designation.group(1)
            ).strip()
        permanent = re.search(
            r"[Pp]ermanent designation\|? ?(?:[IVX]+ )?([^,.;|]+)", body
        )
        if permanent is not None:
            record["permanent_name"] = permanent.group(1).strip()
        out.append(record)
    return out
