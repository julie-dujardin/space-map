<script lang="ts">
	import { getContext } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import { ScrollArea } from '$lib/components/ui/scroll-area/index.js';
	import { Switch } from '$lib/components/ui/switch';
	import {
		cultureName,
		fetchPickableCultures,
		pickedCulture,
		type SkyCultureEntry
	} from '$lib/fetch/extrasolar/skycultures';
	import { quantityIsolate } from '$lib/format/bidi';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { constellationsAsked } from '$lib/scene/settings.svelte';
	import { getSettings, type ViewMode } from '$lib/state/settings.svelte';
	import { pickCulture } from './sky-culture-list';
	import SkyCulturePage from './SkyCulturePage.svelte';

	let { onPicked }: { onPicked?: () => void } = $props();

	const settings = getSettings();
	const appState = getContext<AppState>('appState');

	let cultures = $state.raw<readonly SkyCultureEntry[]>([]);
	let choosing = $state(false);
	// A sky page draws its own culture, and leaves the reader's pick alone.
	const pageSky = $derived(settings.pageSky);
	const culture = $derived(
		pickedCulture(cultures, pageSky?.culture ?? settings.constellationCulture)
	);
	const constellationsOn = $derived(constellationsAsked(settings));
	const immersive = $derived(settings.viewMode === 'immersive');
	const cultureLine = $derived(
		culture
			? m.layers_sky_culture_line({
					name: quantityIsolate(cultureName(culture, getLocale())),
					figures: m.layers_sky_culture_figures({ count: culture.figures })
				})
			: ''
	);

	$effect(() => {
		fetchPickableCultures()
			.then((list) => (cultures = list ?? []))
			.catch((err) => console.warn('[layers] no sky cultures:', err));
	});

	// Immersive has no way in, so it has no page to be left on.
	$effect(() => {
		if (immersive) choosing = false;
	});

	function pick(culture: SkyCultureEntry): void {
		pickCulture(culture, getLocale(), settings, appState);
		onPicked?.();
	}

	function switchConstellations(on: boolean): void {
		settings.setShowConstellations(on);
		if (pageSky) settings.setPageSky({ ...pageSky, hidden: !on });
	}

	const viewOptions: { value: ViewMode; label: () => string; desc: () => string }[] = [
		{ value: 'map', label: () => m.layers_view_map(), desc: () => m.layers_view_map_desc() },
		{
			value: 'immersive',
			label: () => m.layers_view_immersive(),
			desc: () => m.layers_view_immersive_desc()
		}
	];

	const layerToggles: {
		id: string;
		label: () => string;
		desc?: () => string;
		checked: () => boolean;
		set: (on: boolean) => void;
		/** Whether the current view mode leaves the layer out whatever the switch says. */
		disabled?: () => boolean;
	}[] = [
		{
			id: 'clouds',
			label: () => m.layers_clouds(),
			desc: () => m.layers_clouds_desc(),
			checked: () => settings.showClouds,
			set: (on) => settings.setShowClouds(on)
		},
		{
			id: 'atmosphere',
			label: () => m.layers_atmosphere(),
			desc: () => m.layers_atmosphere_desc(),
			checked: () => settings.showAtmospheres,
			set: (on) => settings.setShowAtmospheres(on)
		},
		{
			id: 'high-ambient',
			label: () => m.layers_high_ambient(),
			desc: () => m.layers_high_ambient_desc(),
			checked: () => settings.highAmbient,
			set: (on) => settings.setHighAmbient(on)
		},
		{
			id: 'panoramas',
			label: () => m.layers_panoramas(),
			desc: () => m.layers_panoramas_desc(),
			checked: () => settings.showPanoramaTraces,
			set: (on) => settings.setShowPanoramaTraces(on),
			disabled: () => settings.viewMode === 'immersive'
		}
	];
</script>

{#if choosing}
	<SkyCulturePage
		{cultures}
		picked={culture?.key}
		onPick={pick}
		onBack={() => (choosing = false)}
	/>
{:else}
	<div class="flex min-h-0 flex-1 flex-col">
		<header class="px-5 pt-5 pb-3">
			<h2 class="text-base font-semibold">{m.layers_title()}</h2>
		</header>

		<ScrollArea class="flex min-h-0 flex-1 flex-col" viewportClasses="min-h-0 flex-1">
			<div class="flex flex-col gap-5 px-5 pb-5">
				<section class="flex flex-col gap-3">
					<h3
						id="layers-view-mode-label"
						class="text-[10px] font-semibold tracking-[0.12em] text-muted-foreground uppercase"
					>
						{m.layers_view_mode()}
					</h3>
					<div
						class="flex flex-col gap-3"
						role="radiogroup"
						aria-labelledby="layers-view-mode-label"
					>
						{#each viewOptions as opt (opt.value)}
							{@const active = settings.viewMode === opt.value}
							<button
								type="button"
								role="radio"
								aria-checked={active}
								class="text-start rounded-md border p-3 transition-colors cursor-pointer
							{active
									? 'border-primary bg-primary/5'
									: 'border-input hover:bg-accent hover:text-accent-foreground'}"
								onclick={() => settings.setViewMode(opt.value)}
							>
								<div class="text-sm font-medium">{opt.label()}</div>
								<div class="text-xs text-muted-foreground mt-0.5">{opt.desc()}</div>
							</button>
						{/each}
					</div>
				</section>

				<section class="flex flex-col gap-3">
					<h3 class="text-[10px] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
						{m.layers_section_layers()}
					</h3>
					{#each layerToggles as toggle (toggle.id)}
						{@const disabled = toggle.disabled?.() ?? false}
						<label
							class="flex items-center justify-between gap-3
						{disabled ? 'cursor-not-allowed' : 'cursor-pointer'}"
						>
							<!-- The switch dims itself. -->
							<div class="flex flex-col min-w-0 {disabled ? 'opacity-50' : ''}">
								<span class="text-sm font-medium">{toggle.label()}</span>
								{#if toggle.desc}
									<span class="text-xs text-muted-foreground">{toggle.desc()}</span>
								{/if}
							</div>
							<Switch checked={toggle.checked()} onCheckedChange={toggle.set} {disabled} />
						</label>
					{/each}
					<!-- Not a label as its neighbours: the second line opens a page. -->
					<div class="flex items-center justify-between gap-3">
						<div class="flex min-w-0 flex-col {immersive ? 'opacity-50' : ''}">
							<label
								for="layers-constellations"
								class="text-sm font-medium {immersive ? 'cursor-not-allowed' : 'cursor-pointer'}"
							>
								{m.layers_constellations()}
							</label>
							{#if immersive}
								<span class="truncate text-xs text-muted-foreground">{cultureLine}</span>
							{:else if culture}
								<button
									type="button"
									class="flex min-h-11 min-w-0 cursor-pointer items-center gap-1 text-start text-xs text-muted-foreground hover:text-foreground md:min-h-4"
									onclick={() => (choosing = true)}
								>
									<span class="min-w-0 truncate">{cultureLine}</span>
									<ChevronRightIcon class="size-3.5 shrink-0 rtl:rotate-180" aria-hidden="true" />
								</button>
							{/if}
						</div>
						<Switch
							id="layers-constellations"
							checked={constellationsOn}
							onCheckedChange={switchConstellations}
							disabled={immersive}
						/>
					</div>
				</section>
			</div>
		</ScrollArea>
	</div>
{/if}
