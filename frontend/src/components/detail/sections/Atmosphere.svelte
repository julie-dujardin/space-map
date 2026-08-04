<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
	import { formatPressure, EARTH_SEA_LEVEL_PA, formatEarthRatio } from '$lib/format/pressure';
	import { ltrIsolate } from '$lib/format/bidi';
	import Section from './kit/Section.svelte';
	import Row from './kit/Row.svelte';
	import AtmosphereComposition from './kit/AtmosphereComposition.svelte';

	interface Props {
		global: GlobalObjectData | null;
	}

	let { global }: Props = $props();

	const TYPE_LABEL: Record<string, () => string> = {
		exosphere: m.atmosphere_type_exosphere,
		tenuous_exosphere: m.atmosphere_type_tenuous_exosphere,
		transient_exosphere: m.atmosphere_type_transient_exosphere,
		tenuous_collisional: m.atmosphere_type_tenuous_collisional,
		thin_atmosphere: m.atmosphere_type_thin_atmosphere,
		thick_atmosphere: m.atmosphere_type_thick_atmosphere,
		gas_giant_envelope: m.atmosphere_type_gas_giant_envelope,
		stellar_atmosphere: m.atmosphere_type_stellar_atmosphere,
		localized_plume: m.atmosphere_type_localized_plume,
		frozen_collapsed: m.atmosphere_type_frozen_collapsed,
		none_detected: m.atmosphere_type_none_detected
	};

	const LEVEL_LABEL: Record<string, () => string> = {
		surface: m.atmosphere_pressure_surface,
		sea_level: m.atmosphere_pressure_sea_level,
		areoid: m.atmosphere_pressure_areoid,
		cloud_top: m.atmosphere_pressure_cloud_top,
		one_bar: m.atmosphere_pressure_one_bar,
		photosphere: m.atmosphere_pressure_photosphere
	};

	// What keeps this atmosphere the way it is — the half the classification
	// leaves unsaid, and the reason a pressure can be "variable".
	const NOTE: Record<string, () => string> = {
		photosphere: m.atmosphere_note_photosphere,
		surface_bounded: m.atmosphere_note_surface_bounded,
		sputtered_ice: m.atmosphere_note_sputtered_ice,
		volcanic: m.atmosphere_note_volcanic,
		seasonal_cap: m.atmosphere_note_seasonal_cap,
		seasonal_orbit: m.atmosphere_note_seasonal_orbit,
		frozen_out: m.atmosphere_note_frozen_out,
		no_detection: m.atmosphere_note_no_detection,
		plume: m.atmosphere_note_plume,
		transient_vapour: m.atmosphere_note_transient_vapour,
		no_surface: m.atmosphere_note_no_surface
	};

	let atmosphere = $derived(global?.atmosphere);
	let pressure = $derived(atmosphere?.pressure);
	let note = $derived(atmosphere?.note ? (NOTE[atmosphere.note]?.() ?? null) : null);

	// Sixteen orders of magnitude of pressure mean nothing on their own; Earth
	// is the ruler everyone carries. Skipped on Earth, where it would read
	// "100% of Earth".
	let earthRatio = $derived(
		pressure && Math.abs(pressure.pa - EARTH_SEA_LEVEL_PA) > 1
			? formatEarthRatio(pressure.pa)
			: null
	);
</script>

{#if atmosphere}
	<Section title={m.atmosphere()}>
		{#snippet header()}
			<AtmosphereComposition composition={atmosphere.composition} />
		{/snippet}

		<Row
			label={m.atmosphere_classification()}
			value={TYPE_LABEL[atmosphere.type]?.() ?? atmosphere.type}
		/>
		{#if note}
			<dd class="text-muted-foreground col-span-2 -mt-1.5 text-[11px] leading-snug">{note}</dd>
		{/if}
		{#if pressure}
			{@const reading = ltrIsolate(
				`${pressure.qualifier === 'upper_limit' ? '<' : '≈'} ${formatPressure(pressure.pa)}`
			)}
			<Row label={LEVEL_LABEL[pressure.level]?.() ?? m.atmosphere_pressure_surface()}>
				{#if earthRatio}
					<Tooltip.Root>
						<Tooltip.Trigger>
							{#snippet child({ props })}
								<span
									class="cursor-help tabular-nums underline decoration-dotted underline-offset-2"
									{...props}>{reading}</span
								>
							{/snippet}
						</Tooltip.Trigger>
						<Tooltip.Content>{earthRatio}</Tooltip.Content>
					</Tooltip.Root>
				{:else}
					<span class="tabular-nums">{reading}</span>
				{/if}
			</Row>
		{/if}
	</Section>
{/if}
