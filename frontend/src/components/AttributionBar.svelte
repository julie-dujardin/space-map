<script lang="ts">
	import { getContext } from 'svelte';
	import { siGithub } from 'simple-icons';
	import type { ContextManager } from '$lib/scene/context-manager.svelte';
	import { OrbitalSource } from '$lib/fetch/position/format';
	import { GITHUB_REPO_URL } from '$lib/constants';
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
		// CelesTrak only covers Earth satellites — hide its credit everywhere
		// except the Earth-Moon system, where those bodies are actually drawn.
		const inEarthSystem = ctx.isFocusedOnEarthSystem();
		const seen = new Set<string>();
		const out: string[] = [];
		for (const src of ORBIT_ORDER) {
			if (!ctx.orbitSources.has(src)) continue;
			if (src === OrbitalSource.CELESTRAK && !inEarthSystem) continue;
			const label = ORBIT_LABELS[src as Exclude<OrbitalSource, OrbitalSource.UNKNOWN>]();
			if (seen.has(label)) continue;
			seen.add(label);
			out.push(label);
		}
		return out;
	});

	// Include credits from (a) the focused planetary system — so the Jupiter
	// system shows every textured Galilean — AND (b) the focused body itself —
	// so standalones like Bennu or Ceres, which never get a systems/{bary}.json
	// entry, still credit their imagery once loadBodyTexture has run.
	const textureOrgs = $derived.by(() => {
		void ctx.textureCreditsVersion;
		const sysId = ctx.focusedSystemId;
		const bodyId = ctx.focusedBodyId;
		const orgs = new Set<string>();
		for (const credit of ctx.textureCredits.values()) {
			if (credit.bodyId === bodyId || (sysId && credit.systemId === sysId)) {
				orgs.add(credit.organisation);
			}
		}
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
