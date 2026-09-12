<script module lang="ts">
	/**
	 * What makes a pair a pair: how far apart, how alike in size, how tightly
	 * bound. Johnston's Archive compiles these per system from the discovery
	 * literature, and it is the only source that has them for most asteroid
	 * moons — SBDB records that a companion exists and little else.
	 *
	 * A host shows its system's figures, a moon its own. The separation is
	 * given against the primary's radius and against the Hill radius rather
	 * than in kilometres alone: 1,100 km says nothing until you know it is
	 * thirteen primary radii out and a fortieth of the way to escaping.
	 */
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
	import { formatKm } from '$lib/format/distance';
	import { formatDuration } from '$lib/format/duration';
	import { formatNumber, formatQuantity } from '$lib/format/quantities';

	const CONFIDENCE_LABEL: Record<string, () => string> = {
		permanent: m.binary_confidence_permanent,
		well_observed: m.binary_confidence_well_observed,
		confirmed: m.binary_confidence_confirmed,
		probable: m.binary_confidence_probable
	};
	// Pravec's classes, as used throughout the binary-asteroid literature.
	const BINARY_TYPE_LABEL: Record<string, () => string> = {
		A: m.binary_type_a,
		B: m.binary_type_b,
		C: m.binary_type_c,
		L: m.binary_type_l,
		O: m.binary_type_o,
		U: m.binary_type_u,
		W: m.binary_type_w
	};

	/** A published value and its ±, where the archive gives one. */
	function withSigma(value: number, sigma: number | undefined): string {
		return sigma != null ? `${formatNumber(value)} ± ${formatNumber(sigma)}` : formatNumber(value);
	}

	interface BinaryRow {
		label: () => string;
		/** What the quantity is — the same definition on every pair that has it. */
		tooltip: () => string;
		/** The published field, so the table is also the section's emptiness
		 *  test: a figure the panel cannot label is still a figure the archive
		 *  has, and the section stands. */
		get: (g: GlobalObjectData) => unknown;
		/** The figure, formatted; undefined leaves the row out. */
		value: (g: GlobalObjectData) => string | undefined;
	}

	function row<T>(
		label: () => string,
		tooltip: () => string,
		get: (g: GlobalObjectData) => T | null | undefined,
		format: (published: T, g: GlobalObjectData) => string | undefined
	): BinaryRow {
		return {
			label,
			tooltip,
			get,
			value: (g) => {
				const published = get(g);
				return published == null ? undefined : format(published, g);
			}
		};
	}

	const ROWS: BinaryRow[] = [
		row(
			m.binary_class,
			m.tooltip_binary_class,
			(g) => g.johnston?.binary_type,
			(type) => BINARY_TYPE_LABEL[type]?.()
		),
		row(
			m.binary_confidence,
			m.tooltip_binary_confidence,
			(g) => g.johnston?.confidence,
			(confidence) => CONFIDENCE_LABEL[confidence]?.()
		),
		row(
			m.binary_size_ratio,
			m.tooltip_binary_size_ratio,
			(g) => g.johnston?.diameter_ratio,
			(ratio, g) => withSigma(ratio, g.johnston?.diameter_ratio_sigma)
		),
		row(
			m.binary_magnitude_difference,
			m.tooltip_binary_magnitude_difference,
			(g) => g.johnston?.mag_difference,
			formatNumber
		),
		row(
			m.binary_mutual_period,
			m.tooltip_binary_mutual_period,
			(g) => g.johnston?.per_d,
			formatDuration
		),
		row(
			m.binary_separation_primary_radii,
			m.tooltip_binary_separation_primary_radii,
			(g) => g.johnston?.a_over_primary_radius,
			formatNumber
		),
		row(
			m.binary_separation_hill,
			m.tooltip_binary_separation_hill,
			(g) => g.johnston?.a_over_hill_radius,
			formatNumber
		),
		row(
			m.binary_hill_radius,
			m.tooltip_binary_hill_radius,
			(g) => g.johnston?.hill_radius_km,
			formatKm
		),
		row(
			m.binary_angular_momentum,
			m.tooltip_binary_angular_momentum,
			(g) => g.johnston?.normalised_ang_mom,
			formatNumber
		),
		row(
			m.binary_secondary_rotation,
			m.tooltip_binary_secondary_rotation,
			(g) => g.johnston?.rotation_h,
			(hours) => formatDuration(hours / 24)
		),
		// The system mass is the pair's together — AsterSat derives it from the
		// fitted orbit, Johnston takes it from whichever paper published one.
		row(
			m.binary_system_mass,
			m.tooltip_binary_system_mass,
			(g) => g.astersat?.system_mass ?? g.johnston?.mass,
			(mass) => formatQuantity(mass)
		)
	];
</script>

<script lang="ts">
	import Link from './kit/Link.svelte';
	import Section from './kit/Section.svelte';
	import Row from './kit/Row.svelte';

	interface Props {
		global: GlobalObjectData | null;
	}

	let { global }: Props = $props();

	// The catalogue page is content of its own: a pair with only that still has
	// somewhere to send the reader.
	let page = $derived(global?.johnston?.page);

	let rows = $derived.by(() => {
		const g = global;
		if (!g) return [];
		return ROWS.map((entry) => ({ entry, value: entry.value(g) })).filter(
			(rendered) => rendered.value !== undefined
		);
	});

	let hasContent = $derived.by(() => {
		const g = global;
		if (!g) return false;
		if (page) return true;
		return ROWS.some((entry) => !!entry.get(g));
	});
</script>

{#if hasContent}
	<Section title={m.binary_system()}>
		{#each rows as { entry, value }, i (i)}
			<Row label={entry.label()} tooltip={entry.tooltip()} {value} />
		{/each}
		{#if page}
			<Row label={m.binary_catalogue_entry()}>
				<Link href={page} external>{m.source_johnston_name()}</Link>
			</Row>
		{/if}
	</Section>
{/if}
