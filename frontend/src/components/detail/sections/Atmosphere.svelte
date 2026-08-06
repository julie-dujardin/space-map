<script lang="ts">
	import { getContext } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
	import { atmosphereNote, atmosphereTypeName } from '$lib/charts/atmosphere-layers';
	import { structureLink } from '$lib/charts/structure-link';
	import { isModifiedClick, tabHref } from '$lib/state/focus-link';
	import { formatPressure, EARTH_SEA_LEVEL_PA, formatEarthRatio } from '$lib/format/pressure';
	import { ltrIsolate } from '$lib/format/bidi';
	import Section from './kit/Section.svelte';
	import Row from './kit/Row.svelte';
	import AtmosphereComposition from './kit/AtmosphereComposition.svelte';

	interface Props {
		global: GlobalObjectData | null;
	}

	let { global }: Props = $props();

	const LEVEL_LABEL: Record<string, () => string> = {
		surface: m.atmosphere_pressure_surface,
		sea_level: m.atmosphere_pressure_sea_level,
		areoid: m.atmosphere_pressure_areoid,
		cloud_top: m.atmosphere_pressure_cloud_top,
		one_bar: m.atmosphere_pressure_one_bar,
		photosphere: m.atmosphere_pressure_photosphere
	};

	const appState = getContext<AppState>('appState');

	let atmosphere = $derived(global?.atmosphere);
	let pressure = $derived(atmosphere?.pressure);
	let note = $derived(atmosphereNote(atmosphere?.note));

	let link = $derived(structureLink(global));
	let structureHref = $derived(link ? tabHref(appState, 'structure') : undefined);
	let linkLabel = $derived(link?.layers ? m.structure_see_layers() : m.structure_see_more());

	function openStructure(e: MouseEvent) {
		if (isModifiedClick(e)) return;
		e.preventDefault();
		appState.setTab('structure');
	}

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
	<Section
		title={m.atmosphere()}
		activateHref={structureHref}
		onActivate={openStructure}
		activateLabel={linkLabel}
	>
		{#snippet header()}
			<AtmosphereComposition composition={atmosphere.composition} />
		{/snippet}

		<Row label={m.atmosphere_classification()} value={atmosphereTypeName(atmosphere.type)} />
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
