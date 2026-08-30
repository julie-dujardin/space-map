"""Parse Jonathan McDowell's Deep Space Catalog (tab1 objects, tab2 phases).

The catalogue states, per mission phase, a central body and a peri x apo x inc
at a stated epoch. That is three of six elements, so a phase is not a
trajectory on its own — :mod:`space_map_data.probes.deepcat_solve` pins the
remaining three against a position the phase boundary already implies.

Dates and orbit figures carry their own precision: GCAT writes a trailing `?`
on an uncertain value and truncates a date to the year, month or day it is
actually known to. Both are preserved, because a phase start known only to the
month places the object nowhere useful and has to be rejected rather than
silently propagated.
"""

import datetime
import logging
import re
from dataclasses import dataclass
from enum import Enum

from space_map_data.utils.paths import SOURCES_POSITION_DIR

logger = logging.getLogger(__name__)

DEEPCAT_DIR = SOURCES_POSITION_DIR / "gcat-deep"
OBJECTS_FILE = "tab1.tsv"
PHASES_FILE = "tab2.tsv"

_MONTHS: dict[str, int] = {
    m: i
    for i, m in enumerate(
        "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), start=1
    )
}


class DatePrecision(Enum):
    """How far a GCAT date is written out. The catalogue truncates rather than
    padding, so the shortest form is a genuine statement of ignorance."""

    DECADE = "decade"
    YEAR = "year"
    MONTH = "month"
    DAY = "day"
    MINUTE = "minute"
    SECOND = "second"


# Half-width of the interval a truncated date stands for, in days.
PRECISION_HALF_WIDTH_D: dict[DatePrecision, float] = {
    DatePrecision.DECADE: 1826.0,
    DatePrecision.YEAR: 182.6,
    DatePrecision.MONTH: 15.2,
    DatePrecision.DAY: 0.5,
    DatePrecision.MINUTE: 30.0 / 86400.0,
    DatePrecision.SECOND: 0.5 / 86400.0,
}

# `1970s?` — the coarsest form GCAT writes, for a piece whose fate is known
# only to the decade.
_DECADE_RE = re.compile(r"^(?P<decade>\d{3})0s(?P<uncertain>\?)?$")

_DATE_RE = re.compile(
    r"^(?P<year>\d{4})"
    r"(?:\s+(?P<mon>[A-Z][a-z]{2})"
    r"(?:\s+(?P<day>\d{1,2})"
    r"(?:\s+(?P<hh>\d{2})(?P<mm>\d{2})(?::(?P<ss>\d{2}))?)?)?)?"
    r"(?P<uncertain>\?)?$"
)

# `0.718? x 1.019 AU x 0.58` — any of the three may carry its own `?`.
_ORBIT_RE = re.compile(
    r"^(?P<peri>[\d.]+)(?P<peri_q>\??)\s*x\s*"
    r"(?P<apo>[\d.]+)(?P<apo_q>\??)\s*AU\s*x\s*"
    r"(?P<inc>[-\d.]+)(?P<inc_q>\??)$"
)


@dataclass(frozen=True)
class GcatDate:
    """A GCAT date with the precision it was written to."""

    jd: float
    precision: DatePrecision
    uncertain: bool
    raw: str

    @property
    def half_width_d(self) -> float:
        """Days either side that the written form actually admits. A `?`
        doubles it: the catalogue means the value itself is in doubt, not
        merely rounded."""
        w = PRECISION_HALF_WIDTH_D[self.precision]
        return w * 2.0 if self.uncertain else w


@dataclass(frozen=True)
class SolarElements:
    """Perihelion, aphelion and inclination as GCAT states them."""

    peri_au: float
    apo_au: float
    inc_deg: float
    uncertain: bool

    @property
    def semi_major_au(self) -> float:
        return (self.peri_au + self.apo_au) / 2.0

    @property
    def eccentricity(self) -> float:
        total = self.peri_au + self.apo_au
        return (self.apo_au - self.peri_au) / total if total else 0.0


# `Entered Venus sphere`, the phrase GCAT closes an encounter phase with.
_ARRIVAL_RE = re.compile(r"^Entered\s+(?P<body>.+?)\s+sphere\b")


@dataclass(frozen=True)
class DeepObject:
    """One row of Table I."""

    deep_id: str
    std_id: str
    int_des: str
    name: str
    launch_date: str

    @property
    def norad_id(self) -> int | None:
        """`S00374` is catalogue number 374. `A`-prefixed ids are GCAT's own
        analyst numbers for pieces no agency catalogued, and join to nothing."""
        m = re.fullmatch(r"S(\d+)", self.std_id)
        return int(m.group(1)) if m else None


@dataclass(frozen=True)
class DeepPhase:
    """One row of Table II: an interval during which one body dominates."""

    deep_id: str
    name: str
    phase: int
    body: str
    start: GcatDate | None
    end: GcatDate | None
    dest: str
    epoch: GcatDate | None
    elements: SolarElements | None

    @property
    def arrival_body(self) -> str | None:
        """The body whose sphere the phase ends at, from GCAT's own wording.
        None for a phase that ends by separation, by nothing, or at a small
        body the solver has no ephemeris for."""
        m = _ARRIVAL_RE.match(self.dest)
        return m.group("body") if m else None

    @property
    def is_open_ended(self) -> bool:
        """GCAT writes `-` for a phase still running or ended by nothing it
        tracks."""
        return self.end is None


def parse_gcat_date(raw: str) -> GcatDate | None:
    """`1962 Dec 12 1745?` and every truncation of it. Returns None for the
    blank and `-` forms, which carry no date at all."""
    text = raw.strip()
    if not text or text == "-":
        return None
    dec = _DECADE_RE.match(text)
    if dec:
        jd = (
            datetime.date(int(dec.group("decade")) * 10 + 5, 1, 1).toordinal()
            + 1721424.5
        )
        return GcatDate(jd, DatePrecision.DECADE, dec.group("uncertain") == "?", text)

    m = _DATE_RE.match(text)
    if not m:
        logger.warning("deepcat: unparseable date %r", raw)
        return None

    year = int(m.group("year"))
    mon, day = m.group("mon"), m.group("day")
    hh, mm, ss = m.group("hh"), m.group("mm"), m.group("ss")
    uncertain = m.group("uncertain") == "?"

    # Truncated fields resolve to the midpoint of what they admit, so the
    # error is centred rather than biased to the start of the interval.
    if mon is None:
        return GcatDate(
            datetime.date(year, 7, 2).toordinal() + 1721424.5,
            DatePrecision.YEAR,
            uncertain,
            text,
        )
    month_num = _MONTHS.get(mon)
    if month_num is None:
        logger.warning("deepcat: unknown month in %r", raw)
        return None
    if day is None:
        return GcatDate(
            datetime.date(year, month_num, 16).toordinal() + 1721424.5,
            DatePrecision.MONTH,
            uncertain,
            text,
        )

    base = datetime.date(year, month_num, int(day))
    if hh is None or mm is None:
        precision, frac = DatePrecision.DAY, 0.5
    else:
        precision = DatePrecision.MINUTE if ss is None else DatePrecision.SECOND
        frac = (int(hh) * 3600 + int(mm) * 60 + int(ss or 0)) / 86400.0

    jd = base.toordinal() + 1721424.5 + frac
    return GcatDate(jd, precision, uncertain, text)


def parse_solar_elements(raw: str) -> SolarElements | None:
    """`0.718 x 1.019 AU x 0.58`. Returns None when the field is blank or
    shaped differently, which is how GCAT records an unknown orbit."""
    text = " ".join(raw.split())
    if not text:
        return None
    m = _ORBIT_RE.match(text)
    if not m:
        logger.debug("deepcat: no elements in %r", raw)
        return None
    return SolarElements(
        peri_au=float(m.group("peri")),
        apo_au=float(m.group("apo")),
        inc_deg=float(m.group("inc")),
        uncertain=bool(m.group("peri_q") or m.group("apo_q") or m.group("inc_q")),
    )


def _fields(line: str, count: int) -> list[str]:
    """Split a TSV row and pad it: GCAT drops trailing empty columns."""
    out = [c.strip() for c in line.split("\t")]
    return out + [""] * (count - len(out))


def parse_objects(text: str) -> dict[str, DeepObject]:
    """Table I keyed by DeepID."""
    out: dict[str, DeepObject] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        f = _fields(line, 6)
        out[f[0]] = DeepObject(
            deep_id=f[0], std_id=f[1], int_des=f[2], launch_date=f[3], name=f[4]
        )
    return out


def parse_phases(text: str) -> list[DeepPhase]:
    """Table II in file order, which is DeepID then phase number."""
    out: list[DeepPhase] = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        f = _fields(line, 9)
        try:
            phase_num = int(f[2])
        except ValueError:
            logger.warning("deepcat: non-numeric phase %r for %s", f[2], f[0])
            continue
        out.append(
            DeepPhase(
                deep_id=f[0],
                name=f[1],
                phase=phase_num,
                body=f[3],
                start=parse_gcat_date(f[4]),
                end=parse_gcat_date(f[5]),
                dest=f[6],
                epoch=parse_gcat_date(f[7]),
                elements=parse_solar_elements(f[8]),
            )
        )
    return out


def load_deepcat() -> tuple[dict[str, DeepObject], list[DeepPhase]]:
    """Read both tables off disk."""
    objects = parse_objects((DEEPCAT_DIR / OBJECTS_FILE).read_text(errors="replace"))
    phases = parse_phases((DEEPCAT_DIR / PHASES_FILE).read_text(errors="replace"))
    return objects, phases


__all__ = [
    "DEEPCAT_DIR",
    "OBJECTS_FILE",
    "PHASES_FILE",
    "DatePrecision",
    "DeepObject",
    "DeepPhase",
    "GcatDate",
    "SolarElements",
    "load_deepcat",
    "parse_gcat_date",
    "parse_objects",
    "parse_phases",
    "parse_solar_elements",
]
