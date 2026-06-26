<script lang="ts" module>
	import type { NotableMemberEntry } from '$lib/fetch/groups/details';
	import { CLASS_SLUG_PREFIX, SMALL_BODY_FLAG_SLUG_PREFIX } from '$lib/fetch/groups/registry';

	/** Group slug → the key `smallBodyColor` keys its per-group default on
	 *  (OrbitClass name, NEO/PHA flag, or bare category). */
	export function groupColorKey(slug: string | undefined): string | undefined {
		if (!slug) return undefined;
		if (slug.startsWith(CLASS_SLUG_PREFIX)) return slug.slice(CLASS_SLUG_PREFIX.length);
		if (slug.startsWith(SMALL_BODY_FLAG_SLUG_PREFIX))
			return slug.slice(SMALL_BODY_FLAG_SLUG_PREFIX.length);
		return slug.replace(/^cat-/, '');
	}

	/** The body's lineup geometry, sized off the same radius the 3D scene renders:
	 *  PCK triaxial radii (equatorial a + c/a oblateness, like the planet lineup),
	 *  else the SBDB equivalent-sphere diameter, else the Wikidata render radius.
	 *  `null` when the body carries no size — it can't be drawn. */
	export function lineupGeometry(
		m: NotableMemberEntry
	): { radiusKm: number; polarRatio?: number } | null {
		if (m.radii) {
			const { a, b, c } = m.radii;
			const eq = Math.max(a, b, c);
			return { radiusKm: eq, polarRatio: c / eq };
		}
		if (m.diameter_km != null) return { radiusKm: m.diameter_km / 2 };
		if (m.radius_km != null) return { radiusKm: m.radius_km };
		return null;
	}

	/** Renderable = has an id and a resolvable radius. Colour always resolves, so
	 *  the radius is the binding requirement; the caller gates on this count. */
	export function renderableCount(members: NotableMemberEntry[] | undefined): number {
		if (!members) return 0;
		return members.filter((m) => m.id && lineupGeometry(m)).length;
	}
</script>

<script lang="ts">
	import { BODY_COLORS } from '$lib/constants';
	import { smallBodyColor } from '$lib/constants/small-body-colors';
	import BodyLineup, { type LineupBody } from './BodyLineup.svelte';

	interface Props {
		members: NotableMemberEntry[];
		/** Group slug, e.g. "class-MBA" / "flag-neo" / "cat-asteroids". */
		slug: string;
		ariaLabel: string;
		localizedNames?: Record<string, string>;
		localizedDescriptions?: Record<string, string>;
	}
	let { members, slug, ariaLabel, localizedNames, localizedDescriptions }: Props = $props();

	let key = $derived(groupColorKey(slug));

	let bodies = $derived.by<LineupBody[]>(() => {
		const out: LineupBody[] = [];
		for (const m of members) {
			if (!m.id) continue;
			const geom = lineupGeometry(m);
			if (!geom) continue;
			const id = m.id;
			out.push({
				id,
				name: localizedNames?.[id] ?? m.name,
				description: localizedDescriptions?.[id],
				...geom,
				// Known bodies (dwarf planets) keep their curated colour/texture;
				// the rest get the taxonomy/albedo/class-default heuristic.
				color: BODY_COLORS[id] ? undefined : smallBodyColor(m, key)
			});
		}
		return out;
	});
</script>

<!-- perPage paginates into size bands once there are more than a page's worth;
     a single short page (e.g. a sparse zone) shows no controls. -->
<BodyLineup {bodies} {ariaLabel} perPage={8} />
