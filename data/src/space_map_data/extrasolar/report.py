"""The text report of one ingest."""


def _count(value: int) -> str:
    return f"{value:,}"


def render_report(
    entry: dict,
    merges: list[tuple[int, int, str]],
    retired: list[int],
    conflicts: list[str],
    examples: int,
) -> str:
    """Counts of the ingest, and up to `examples` merges, retirements and conflicts."""
    counts = entry["counts"]
    code = entry["commit"] or "unknown commit"
    lines = [
        f"Extrasolar ingest {entry['ingest']}, {entry['date']}",
        f"code {code}{' with changes' if entry['dirty'] else ''}",
        "complete input" if entry["complete"] else "partial input: no ID retired",
        "",
        "source             rows      by id     by claim  by position  new",
    ]
    for source in entry["sources"]:
        lines.append(
            f"{source['source']:<18} {_count(source.get('rows', 0)):>9} "
            f"{_count(source.get('by_id', 0)):>9} {_count(source.get('by_claim', 0)):>9}"
            f" {_count(source.get('by_position', 0)):>12} "
            f"{_count(source.get('new', 0)):>9}"
        )
    lines += [
        "",
        " · ".join(f"{name} {_count(value)}" for name, value in counts.items()),
        "",
        f"merges: {_count(len(merges))}"
        + (", unreviewed: check them before publishing" if merges else ""),
    ]
    lines += [
        f"  {loser} → alias of {survivor}: {evidence}"
        for survivor, loser, evidence in merges[:examples]
    ]
    lines.append(f"retired: {_count(len(retired))}")
    lines += [f"  {id_}" for id_ in retired[:examples]]
    lines.append(f"conflicts: {_count(len(conflicts))}")
    lines += [f"  {text}" for text in conflicts[:examples]]
    return "\n".join(lines) + "\n"
