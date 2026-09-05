<script lang="ts">
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
	import Link from './kit/Link.svelte';
	import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
	import { formatKm } from '$lib/format/distance';
	import { formatDuration } from '$lib/format/duration';
	import { formatNumber, formatQuantity } from '$lib/format/quantities';
	import Section from './kit/Section.svelte';
	import Row from './kit/Row.svelte';

	interface Props {
		global: GlobalObjectData | null;
	}

	let { global }: Props = $props();

	let johnston = $derived(global?.johnston);
	let astersat = $derived(global?.astersat);

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

	/** A published value and its ± , where the archive gives one. */
	function withSigma(value: number, sigma: number | undefined, unit?: string): string {
		const figure =
			sigma != null ? `${formatNumber(value)} ± ${formatNumber(sigma)}` : formatNumber(value);
		return unit ? `${figure} ${unit}` : figure;
	}

	// The system mass is the pair's together — AsterSat derives it from the
	// fitted orbit, Johnston takes it from whichever paper published one.
	let systemMass = $derived(astersat?.system_mass ?? johnston?.mass);

	let hasContent = $derived(
		!!(
			johnston?.binary_type ||
			johnston?.confidence ||
			johnston?.diameter_ratio != null ||
			johnston?.mag_difference != null ||
			johnston?.a_over_primary_radius != null ||
			johnston?.a_over_hill_radius != null ||
			johnston?.hill_radius_km != null ||
			johnston?.normalised_ang_mom != null ||
			johnston?.rotation_h != null ||
			johnston?.per_d != null ||
			systemMass
		)
	);
</script>

{#if hasContent}
	<Section title={m.binary_system()}>
		{#if johnston?.binary_type && BINARY_TYPE_LABEL[johnston.binary_type]}
			<Row
				label={m.binary_class()}
				value={BINARY_TYPE_LABEL[johnston.binary_type]()}
				tooltip={m.tooltip_binary_class()}
			/>
		{/if}
		{#if johnston?.confidence && CONFIDENCE_LABEL[johnston.confidence]}
			<Row
				label={m.binary_confidence()}
				value={CONFIDENCE_LABEL[johnston.confidence]()}
				tooltip={m.tooltip_binary_confidence()}
			/>
		{/if}
		{#if johnston?.diameter_ratio != null}
			<Row
				label={m.binary_size_ratio()}
				value={withSigma(johnston.diameter_ratio, johnston.diameter_ratio_sigma)}
				tooltip={m.tooltip_binary_size_ratio()}
			/>
		{/if}
		{#if johnston?.mag_difference != null}
			<Row
				label={m.binary_magnitude_difference()}
				value={formatNumber(johnston.mag_difference)}
				tooltip={m.tooltip_binary_magnitude_difference()}
			/>
		{/if}
		{#if johnston?.per_d != null}
			<Row
				label={m.binary_mutual_period()}
				value={formatDuration(johnston.per_d)}
				tooltip={m.tooltip_binary_mutual_period()}
			/>
		{/if}
		{#if johnston?.a_over_primary_radius != null}
			<Row
				label={m.binary_separation_primary_radii()}
				value={formatNumber(johnston.a_over_primary_radius)}
				tooltip={m.tooltip_binary_separation_primary_radii()}
			/>
		{/if}
		{#if johnston?.a_over_hill_radius != null}
			<Row
				label={m.binary_separation_hill()}
				value={formatNumber(johnston.a_over_hill_radius)}
				tooltip={m.tooltip_binary_separation_hill()}
			/>
		{/if}
		{#if johnston?.hill_radius_km != null}
			<Row
				label={m.binary_hill_radius()}
				value={formatKm(johnston.hill_radius_km)}
				tooltip={m.tooltip_binary_hill_radius()}
			/>
		{/if}
		{#if johnston?.normalised_ang_mom != null}
			<Row
				label={m.binary_angular_momentum()}
				value={formatNumber(johnston.normalised_ang_mom)}
				tooltip={m.tooltip_binary_angular_momentum()}
			/>
		{/if}
		{#if johnston?.rotation_h != null}
			<Row
				label={m.binary_secondary_rotation()}
				value={formatDuration(johnston.rotation_h / 24)}
				tooltip={m.tooltip_binary_secondary_rotation()}
			/>
		{/if}
		{#if systemMass}
			<Row
				label={m.binary_system_mass()}
				value={formatQuantity(systemMass)}
				tooltip={m.tooltip_binary_system_mass()}
			/>
		{/if}
		{#if johnston?.page}
			<Row label={m.binary_catalogue_entry()}>
				<Link href={johnston.page} external>{m.source_johnston_name()}</Link>
			</Row>
		{/if}
	</Section>
{/if}
