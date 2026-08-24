<script lang="ts">
	/**
	 * The Rings tab's stat trio: how much of it, how thin, when we found it.
	 * None of these restate the panel below — thickness is the one dimension
	 * the radial chart has no axis for, and mass/date aren't on it at all. A
	 * body with nothing for a slot leaves it out.
	 */

	import * as m from '$lib/paraglide/messages.js';
	import StatCardRow from './kit/StatCardRow.svelte';
	import type { Stat } from './kit/StatCard.svelte';
	import type { RingStats } from '$lib/fetch/objects/object-data';
	import { joinParts } from '$lib/format/quantities';
	import { formatRingMass } from '$lib/rings/stats';
	import { formatKm, formatKmRange } from '$lib/format/distance';

	interface Props {
		stats: RingStats | undefined;
	}
	let { stats }: Props = $props();

	let massStat = $derived.by<Stat | null>(() => {
		if (!stats?.mass) return null;
		const { note, ...parts } = formatRingMass(stats.mass);
		return { label: m.property_name_mass(), value: joinParts(parts), tooltip: note };
	});

	let thicknessStat = $derived.by<Stat | null>(() => {
		const value = stats?.thickness;
		if (!value) return null;
		// Stored in metres; the km formatter drops to metres under a kilometre,
		// which is where Saturn's main rings live.
		const text =
			value.high_m !== undefined
				? formatKmRange(value.low_m / 1000, value.high_m / 1000)
				: formatKm(value.low_m / 1000);
		return { label: m.rings_stat_thickness(), value: text, tooltip: m.tooltip_rings_thickness() };
	});

	// Years are labels, not quantities — no thousands separator, as the group
	// cards do it. How the rings were caught is in the article above.
	let discoveryStat = $derived.by<Stat | null>(() => {
		const year = stats?.discovery_year;
		if (!year) return null;
		return { label: m.group_stat_discovered(), value: String(year) };
	});

	let cards = $derived([massStat, thicknessStat, discoveryStat].filter((s) => s !== null));
</script>

<StatCardRow stats={cards} />
