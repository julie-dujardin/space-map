<script lang="ts">
	import { getContext } from 'svelte';
	import { siGithub } from 'simple-icons';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import { attributionChips, type OrbitSourceLabels } from '$lib/scene/state/attribution';
	import { OrbitalSource } from '$lib/fetch/position/format';
	import { GITHUB_REPO_URL } from '$lib/constants';
	import * as m from '$lib/paraglide/messages.js';
	import * as Popover from '$lib/components/ui/popover';
	import AttributionPopover, { type CreditSection } from './AttributionPopover.svelte';

	export interface AttributionChip {
		label: string;
		names: string[];
	}

	interface Props {
		/** Given by a page whose credits are not the scene's: what the bar
		 *  says, and what the popover behind it lists. */
		chips?: AttributionChip[];
		sections?: CreditSection[];
		/** `sky` is white on a scrim, for a bar over imagery that is dark
		 *  whatever the theme; `surface` inks it from the theme instead. */
		tone?: 'sky' | 'surface';
	}

	let { chips: givenChips, sections, tone = 'sky' }: Props = $props();

	const ink = $derived(
		tone === 'surface'
			? {
					bar: 'bg-background/60 text-muted-foreground',
					hover: 'hover:text-foreground',
					dim: 'text-muted-subtle'
				}
			: { bar: 'bg-black/40 text-white/75', hover: 'hover:text-white', dim: 'text-white/50' }
	);

	const ctx = getContext<ContextManager | undefined>('ctx');

	// The translated half of `ORBIT_SOURCES`, which carries everything else about
	// a source. NASA-produced ones collapse to a single "NASA" chip; the shared
	// derivation dedups on the label, so the translation decides.
	const labels: OrbitSourceLabels = $derived({
		[OrbitalSource.HORIZONS]: m.provider_nasa(),
		[OrbitalSource.SBDB]: m.provider_nasa(),
		[OrbitalSource.SPICE]: m.provider_nasa(),
		[OrbitalSource.SBDB_MOON]: m.provider_nasa(),
		[OrbitalSource.ASTERSAT]: m.source_nsdb_name(),
		[OrbitalSource.SPICE_PROBE]: m.provider_nasa(),
		[OrbitalSource.CELESTRAK]: m.source_celestrak_name(),
		[OrbitalSource.SPACETRACK]: m.source_spacetrack_name()
	});

	const shown = $derived.by<AttributionChip[]>(() => {
		if (givenChips) return givenChips;
		if (!ctx) return [];
		const chips = attributionChips(ctx, labels);
		return [
			{ label: m.attribution_orbits(), names: chips.orbits },
			{ label: m.attribution_imagery(), names: chips.imagery }
		];
	});
	const anyChip = $derived(shown.some((chip) => chip.names.length > 0));
</script>

<div
	class="flex items-center rounded-s-sm text-[11px]
		leading-tight backdrop-blur-sm whitespace-nowrap {ink.bar}"
>
	<Popover.Root>
		<Popover.Trigger
			class="flex cursor-pointer items-center gap-3 px-1 py-0
				transition-colors {ink.hover}"
			aria-label={m.attribution_title()}
		>
			{#each shown as chip (chip.label)}
				{#if chip.names.length > 0}
					<span class="inline-block max-w-[50vw] truncate align-bottom">
						<span class={ink.dim}>{chip.label}:</span>
						{chip.names.join(' · ')}
					</span>
				{/if}
			{/each}
		</Popover.Trigger>
		<Popover.Content align="end" side="top" sideOffset={8} class="w-auto">
			<AttributionPopover {sections} />
		</Popover.Content>
	</Popover.Root>
	{#if anyChip}
		<span class={ink.dim} aria-hidden="true">·</span>
	{/if}
	<a
		href={GITHUB_REPO_URL}
		target="_blank"
		rel="noopener noreferrer"
		class="flex items-center px-1 py-0 transition-colors {ink.hover}"
		aria-label="GitHub"
	>
		<svg
			xmlns="http://www.w3.org/2000/svg"
			viewBox="0 0 24 24"
			fill="currentColor"
			class="h-3.5 w-3.5"
			aria-hidden="true"
		>
			<path d={siGithub.path} />
		</svg>
	</a>
</div>
