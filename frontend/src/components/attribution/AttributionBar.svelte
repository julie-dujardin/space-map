<script lang="ts">
	import { getContext } from 'svelte';
	import { siGithub } from 'simple-icons';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import { attributionChips, type OrbitSourceLabels } from '$lib/scene/state/attribution';
	import { OrbitalSource } from '$lib/fetch/position/format';
	import { GITHUB_REPO_URL } from '$lib/constants';
	import * as m from '$lib/paraglide/messages.js';
	import * as Popover from '$lib/components/ui/popover';
	import AttributionPopover from './AttributionPopover.svelte';

	const ctx = getContext<ContextManager>('ctx');

	// NASA-produced sources collapse to a single "NASA" chip; the shared
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

	const chips = $derived(attributionChips(ctx, labels));
	const orbitLabels = $derived(chips.orbits);
	const textureOrgs = $derived(chips.imagery);
</script>

<div
	class="pointer-events-auto flex items-center rounded-s-sm bg-black/40 text-[11px]
		leading-tight text-white/75 backdrop-blur-sm whitespace-nowrap"
>
	<Popover.Root>
		<Popover.Trigger
			class="flex cursor-pointer items-center gap-3 px-1 py-0
				hover:text-white transition-colors"
			aria-label={m.attribution_title()}
		>
			{#if orbitLabels.length > 0}
				<span class="inline-block max-w-[50vw] truncate align-bottom">
					<span class="text-white/50">{m.attribution_orbits()}:</span>
					{orbitLabels.join(' · ')}
				</span>
			{/if}
			{#if textureOrgs.length > 0}
				<span class="inline-block max-w-[50vw] truncate align-bottom">
					<span class="text-white/50">{m.attribution_imagery()}:</span>
					{textureOrgs.join(' · ')}
				</span>
			{/if}
		</Popover.Trigger>
		<Popover.Content align="end" side="top" sideOffset={8} class="w-auto">
			<AttributionPopover />
		</Popover.Content>
	</Popover.Root>
	{#if orbitLabels.length > 0 || textureOrgs.length > 0}
		<span class="text-white/40" aria-hidden="true">·</span>
	{/if}
	<a
		href={GITHUB_REPO_URL}
		target="_blank"
		rel="noopener noreferrer"
		class="flex items-center px-1 py-0 hover:text-white transition-colors"
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
