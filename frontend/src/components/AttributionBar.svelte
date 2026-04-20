<script lang="ts">
	import { getContext } from 'svelte';
	import type { ContextManager } from '$lib/scene/context-manager.svelte';
	import { OrbitalSource } from '$lib/fetch/elements/constants';
	import * as m from '$lib/paraglide/messages.js';
	import * as Popover from '$lib/components/ui/popover';
	import AttributionPopover from './AttributionPopover.svelte';

	const ctx = getContext<ContextManager>('ctx');

	// Horizons / SBDB / NASA SPICE are all NASA-produced — collapse them into a
	// single "NASA" chip so the bar reads "NASA · CelesTrak" instead of listing
	// every sub-product. `ORBIT_ORDER` pins display order post-dedup.
	const ORBIT_LABELS: Record<Exclude<OrbitalSource, OrbitalSource.UNKNOWN>, () => string> = {
		[OrbitalSource.HORIZONS]: m.provider_nasa,
		[OrbitalSource.SBDB]: m.provider_nasa,
		[OrbitalSource.CELESTRAK]: m.provider_celestrak,
		[OrbitalSource.SPICE]: m.provider_nasa
	};

	const ORBIT_ORDER: OrbitalSource[] = [
		OrbitalSource.HORIZONS,
		OrbitalSource.SBDB,
		OrbitalSource.SPICE,
		OrbitalSource.CELESTRAK
	];

	const orbitLabels = $derived.by(() => {
		const seen = new Set<string>();
		const out: string[] = [];
		for (const src of ORBIT_ORDER) {
			if (!ctx.orbitSources.has(src)) continue;
			const label = ORBIT_LABELS[src as Exclude<OrbitalSource, OrbitalSource.UNKNOWN>]();
			if (seen.has(label)) continue;
			seen.add(label);
			out.push(label);
		}
		return out;
	});

	const textureOrgs = $derived.by(() => {
		void ctx.textureCreditsVersion;
		const sysId = ctx.focusedSystemId;
		if (!sysId) return [] as string[];
		const orgs = new Set<string>();
		for (const credit of ctx.textureCredits.values()) {
			if (credit.systemId === sysId) orgs.add(credit.organisation);
		}
		return [...orgs].sort();
	});
</script>

<Popover.Root>
	<Popover.Trigger
		class="pointer-events-auto flex cursor-pointer items-center gap-3 rounded-s-sm
			bg-black/40 px-1 py-0 text-[11px] leading-tight text-white/75 backdrop-blur-sm
			hover:bg-black/55 hover:text-white transition-colors whitespace-nowrap"
		aria-label={m.attribution_title()}
	>
		{#if orbitLabels.length > 0}
			<span>
				<span class="text-white/50">{m.attribution_orbits()}:</span>
				{orbitLabels.join(' · ')}
			</span>
		{/if}
		{#if textureOrgs.length > 0}
			<span>
				<span class="text-white/50">{m.attribution_imagery()}:</span>
				{textureOrgs.join(' · ')}
			</span>
		{/if}
	</Popover.Trigger>
	<Popover.Content align="end" side="top" sideOffset={8} class="w-auto">
		<AttributionPopover />
	</Popover.Content>
</Popover.Root>
