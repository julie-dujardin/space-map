<script lang="ts">
	// The Solar System as a SystemMap, every target leading to its page.
	import { getContext, untrack } from 'svelte';
	import SystemMap from './SystemMap.svelte';
	import { siteMapText } from './system-map-text';
	import { displayName, solarSystemModel } from '$lib/systemmap/solar';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import { focusClick, focusHref, groupClick, groupHref } from '$lib/state/focus-link';
	import {
		fetchSolarSystemMap,
		type SolarSystemMapFile,
		type SolarSystemMapObject
	} from '$lib/fetch/groups/solar-system-map';

	interface Props {
		ariaLabel: string;
		/** Object.id → localized label, overriding the exported English name. */
		localizedNames?: Record<string, string>;
		variant?: 'hero' | 'background';
	}
	let { ariaLabel, localizedNames, variant = 'hero' }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');

	let file = $state<SolarSystemMapFile | null>(null);
	$effect(() => {
		untrack(() =>
			fetchSolarSystemMap()
				.then((f) => (file = f))
				.catch((e) => console.error('Solar system map failed to load', e))
		);
	});

	function focusLink(id: string, name: string, tab?: 'members') {
		return {
			href: focusHref(appState, id, name, tab),
			onclick: focusClick(focusObject, id, name, tab && { tab })
		};
	}

	let model = $derived.by(() => {
		if (!file) return null;
		const name = (o: SolarSystemMapObject) => localizedNames?.[o.id] ?? displayName(o.name);
		const sun = file.objects.find((o) => o.kind === 'star');
		return solarSystemModel(file, {
			text: siteMapText(),
			name,
			primaryLink: sun && focusLink(sun.id, name(sun)),
			links: (o, stack) => {
				// The stack opens the moons tab, or the moon itself where there are
				// too few for a tab (Earth).
				const largest = stack?.satellites.toSorted((a, b) => b.radiusKm - a.radiusKm)[0];
				return {
					link: focusLink(o.id, name(o)),
					satellitesLink: stack?.tab
						? focusLink(o.id, name(o), 'members')
						: largest && focusLink(largest.id, largest.name)
				};
			},
			band: (b) => ({
				label: b.label,
				href: groupHref(appState, b.slug, b.label),
				onclick: groupClick(appState, b.slug, b.label)
			})
		});
	});
</script>

{#if model}
	<SystemMap {model} {ariaLabel} {variant} />
{/if}
