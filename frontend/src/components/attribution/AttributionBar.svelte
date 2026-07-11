<script lang="ts">
	import { getContext } from 'svelte';
	import { siGithub } from 'simple-icons';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import { OrbitalSource } from '$lib/fetch/position/format';
	import { GITHUB_REPO_URL } from '$lib/constants';
	import * as m from '$lib/paraglide/messages.js';
	import * as Popover from '$lib/components/ui/popover';
	import AttributionPopover from './AttributionPopover.svelte';

	const ctx = getContext<ContextManager>('ctx');

	// All NASA-produced sources collapse to a single "NASA" chip; ORBIT_ORDER pins display order post-dedup.
	const ORBIT_LABELS: Record<Exclude<OrbitalSource, OrbitalSource.UNKNOWN>, () => string> = {
		[OrbitalSource.HORIZONS]: m.provider_nasa,
		[OrbitalSource.SBDB]: m.provider_nasa,
		[OrbitalSource.CELESTRAK]: m.source_celestrak_name,
		[OrbitalSource.SPICE]: m.provider_nasa,
		[OrbitalSource.SBDB_MOON]: m.provider_nasa,
		[OrbitalSource.SPICE_PROBE]: m.provider_nasa,
		[OrbitalSource.SPACETRACK]: m.source_spacetrack_name
	};

	const ORBIT_ORDER: OrbitalSource[] = [
		OrbitalSource.HORIZONS,
		OrbitalSource.SBDB,
		OrbitalSource.SPICE,
		OrbitalSource.SBDB_MOON,
		OrbitalSource.SPICE_PROBE,
		OrbitalSource.CELESTRAK,
		OrbitalSource.SPACETRACK
	];

	// Earth-satellite sources are only relevant inside the Earth-Moon system.
	const EARTH_SAT_SOURCES = new Set([OrbitalSource.CELESTRAK, OrbitalSource.SPACETRACK]);

	const orbitLabels = $derived.by(() => {
		// CelesTrak/Space-Track only cover Earth satellites — hide outside the
		// Earth-Moon system.
		const inEarthSystem = ctx.visibility.isFocusedOnEarthSystem();
		const seen = new Set<string>();
		const out: string[] = [];
		for (const src of ORBIT_ORDER) {
			if (!ctx.credits.orbitSources.has(src)) continue;
			if (EARTH_SAT_SOURCES.has(src) && !inEarthSystem) continue;
			const label = ORBIT_LABELS[src as Exclude<OrbitalSource, OrbitalSource.UNKNOWN>]();
			if (seen.has(label)) continue;
			seen.add(label);
			out.push(label);
		}
		return out;
	});

	// Scoped to the focused system + focused body; rings/clouds/topography/models
	// share the imagery chip here (per-source breakout lives in the popover /
	// credits page).
	const textureOrgs = $derived.by(() => {
		void ctx.credits.textureVersion;
		void ctx.credits.ringVersion;
		void ctx.credits.cloudVersion;
		void ctx.credits.displacementVersion;
		void ctx.credits.modelVersion;
		const sysId = ctx.visibility.focusedSystemId;
		const bodyId = ctx.visibility.focusedBodyId;
		const orgs = new Set<string>();
		const sources = [
			ctx.credits.texture,
			ctx.credits.ring,
			ctx.credits.cloud,
			ctx.credits.displacement
		];
		for (const credits of sources) {
			for (const credit of credits.values()) {
				if (credit.bodyId === bodyId || (sysId && credit.systemId === sysId)) {
					orgs.add(credit.organisation);
				}
			}
		}
		// Models are body-scoped only — a probe's model credit doesn't bleed
		// into the system's other bodies.
		const modelCredit = bodyId ? ctx.credits.model.get(bodyId) : undefined;
		if (modelCredit) orgs.add(modelCredit.organisation);
		return [...orgs].sort();
	});
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
