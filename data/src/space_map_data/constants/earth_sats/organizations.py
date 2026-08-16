"""Organizations: the unified company/agency entity behind /g/org-<slug>.

Operators and manufacturers stay defined separately (they drive SATCAT
classification and constellation/bus linkage); this layer unions them by slug
so a company appears once on its group page, tagged ``operator`` and/or
``manufacturer``. Duals share slug and QID across both tables, so slug is a
safe identity key.
"""

from dataclasses import dataclass

from space_map_data.constants.earth_sats.manufacturers import MANUFACTURERS
from space_map_data.constants.earth_sats.operators import OPERATORS

# Prefix so org group slugs don't collide with bare constellation or site-*
# slugs: ``f"{ORGANIZATION_SLUG_PREFIX}{org.slug}"``.
ORGANIZATION_SLUG_PREFIX = "org-"

# Duals whose operated/manufactured sets are *disjoint* — counting both would
# inflate the fleet. CNES is the only case (operates 76, built 18, zero
# overlap); shown as pure operator, dropping the 18 manufactured-only sats
# (they still appear under whoever operates them).
OPERATOR_ONLY_MEMBERSHIP_SLUGS: frozenset[str] = frozenset({"cnes"})


@dataclass(frozen=True)
class OrganizationSpec:
    name: str
    slug: str  # bare slug; group registry prefixes with "org-"
    wikidata_qid: str | None
    is_operator: bool
    is_manufacturer: bool
    fallback_url: str | None = None  # External site when no Wikidata (operators only)

    @property
    def roles(self) -> tuple[str, ...]:
        """Role tags in display order: operator before manufacturer."""
        out: list[str] = []
        if self.is_operator:
            out.append("operator")
        if self.is_manufacturer:
            out.append("manufacturer")
        return tuple(out)


def _build_organizations() -> tuple[OrganizationSpec, ...]:
    """Union OPERATORS + MANUFACTURERS by slug into one tagged registry.

    A dual's name/QID must be identical across the two tables (asserted below),
    so first-writer-wins is safe.
    """
    names: dict[str, str] = {}
    qids: dict[str, str | None] = {}
    urls: dict[str, str | None] = {}
    is_op: dict[str, bool] = {}
    is_mfr: dict[str, bool] = {}
    for o in OPERATORS:
        names.setdefault(o.slug, o.name)
        qids.setdefault(o.slug, o.wikidata_qid)
        urls.setdefault(o.slug, o.url)
        is_op[o.slug] = True
    for m in MANUFACTURERS:
        if m.slug in names:
            assert (m.name, m.wikidata_qid) == (names[m.slug], qids[m.slug]), (
                f"operator/manufacturer dual '{m.slug}' disagrees on name or QID"
            )
        names.setdefault(m.slug, m.name)
        qids.setdefault(m.slug, m.wikidata_qid)
        is_mfr[m.slug] = True
    return tuple(
        OrganizationSpec(
            name=names[slug],
            slug=slug,
            wikidata_qid=qids.get(slug),
            is_operator=is_op.get(slug, False),
            is_manufacturer=is_mfr.get(slug, False),
            fallback_url=urls.get(slug),
        )
        for slug in names
    )


ORGANIZATIONS: tuple[OrganizationSpec, ...] = _build_organizations()
ORGANIZATION_BY_SLUG: dict[str, OrganizationSpec] = {o.slug: o for o in ORGANIZATIONS}
ORGANIZATION_BY_QID: dict[str, OrganizationSpec] = {
    o.wikidata_qid: o for o in ORGANIZATIONS if o.wikidata_qid
}

assert len(ORGANIZATION_BY_SLUG) == len(ORGANIZATIONS), "Duplicate organization slug"
