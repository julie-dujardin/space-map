<script lang="ts">
	import { getContext } from 'svelte';
	import ExternalLinkIcon from '@lucide/svelte/icons/external-link';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import { OrbitalSource } from '$lib/fetch/position/format';
	import * as m from '$lib/paraglide/messages.js';

	const ctx = getContext<ContextManager>('ctx');

	interface SourceEntry {
		name: string;
		url: string;
	}

	// Only listed entries whose OrbitalSource is present in `ctx.orbitSources`
	// are rendered, so the popover matches whatever the minor-body + major
	// pipeline has actually contributed so far.
	const ORBIT_ENTRIES: Array<{ source: OrbitalSource; entry: () => SourceEntry }> = [
		{
			source: OrbitalSource.HORIZONS,
			entry: () => ({ name: m.source_horizons_name(), url: 'https://ssd.jpl.nasa.gov/horizons/' })
		},
		{
			source: OrbitalSource.SBDB,
			entry: () => ({
				name: m.source_sbdb_name(),
				url: 'https://ssd.jpl.nasa.gov/tools/sbdb_query.html'
			})
		},
		{
			source: OrbitalSource.SPICE,
			entry: () => ({
				name: m.source_spice_ephemeris_name(),
				url: 'https://naif.jpl.nasa.gov/naif/'
			})
		},
		{
			source: OrbitalSource.CELESTRAK,
			entry: () => ({ name: m.source_celestrak_name(), url: 'https://celestrak.org/' })
		}
	];

	const orbitEntries = $derived.by(() => {
		// CelesTrak only covers Earth satellites — suppress its credit outside
		// the Earth-Moon system, mirroring the bar's scoping.
		const inEarthSystem = ctx.visibility.isFocusedOnEarthSystem();
		return ORBIT_ENTRIES.filter(
			({ source }) =>
				ctx.credits.orbitSources.has(source) &&
				(source !== OrbitalSource.CELESTRAK || inEarthSystem)
		).map(({ entry }) => entry());
	});

	// Scoped to what's actually on screen: the focused planetary system plus
	// the focused body itself (covers standalones like Bennu/Ceres whose
	// credits come via loadBodyTexture, not loadSystemData).
	const textureList = $derived.by(() => {
		void ctx.credits.textureVersion;
		const sysId = ctx.visibility.focusedSystemId;
		const bodyId = ctx.visibility.focusedBodyId;
		return [...ctx.credits.texture.values()]
			.filter((c) => c.bodyId === bodyId || (sysId && c.systemId === sysId))
			.sort((a, b) => bodyName(a.bodyId).localeCompare(bodyName(b.bodyId)));
	});

	const ringList = $derived.by(() => {
		void ctx.credits.ringVersion;
		const sysId = ctx.visibility.focusedSystemId;
		const bodyId = ctx.visibility.focusedBodyId;
		return [...ctx.credits.ring.values()]
			.filter((c) => c.bodyId === bodyId || (sysId && c.systemId === sysId))
			.sort((a, b) => bodyName(a.bodyId).localeCompare(bodyName(b.bodyId)));
	});

	const cloudList = $derived.by(() => {
		void ctx.credits.cloudVersion;
		const sysId = ctx.visibility.focusedSystemId;
		const bodyId = ctx.visibility.focusedBodyId;
		return [...ctx.credits.cloud.values()]
			.filter((c) => c.bodyId === bodyId || (sysId && c.systemId === sysId))
			.sort((a, b) => bodyName(a.bodyId).localeCompare(bodyName(b.bodyId)));
	});

	function bodyName(id: string): string {
		return ctx.getBody(id)?.data.name ?? id;
	}
</script>

{#snippet sectionHeader(label: string)}
	<h3 class="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
		{label}
	</h3>
{/snippet}

{#snippet link(href: string, label: string, sub?: string)}
	<a
		{href}
		target="_blank"
		rel="noopener noreferrer"
		class="text-foreground hover:underline underline-offset-2 inline-flex items-baseline gap-1"
	>
		<span>
			{label}{#if sub}<span class="text-muted-foreground"> — {sub}</span>{/if}
		</span>
		<ExternalLinkIcon class="size-3 shrink-0 self-center" />
	</a>
{/snippet}

<div class="flex max-h-[70dvh] w-72 flex-col gap-3 overflow-y-auto text-xs">
	<h2 class="text-sm font-semibold">{m.attribution_title()}</h2>

	{#if orbitEntries.length > 0}
		<section class="space-y-1">
			{@render sectionHeader(m.attribution_section_orbits())}
			<ul class="space-y-0.5">
				{#each orbitEntries as e (e.url)}
					<li>{@render link(e.url, e.name)}</li>
				{/each}
			</ul>
		</section>
	{/if}

	<section class="space-y-1">
		{@render sectionHeader(m.attribution_section_rotation())}
		<ul class="space-y-0.5">
			<li>{@render link('https://naif.jpl.nasa.gov/naif/', m.source_spice_pck_name())}</li>
			<li>
				{@render link('https://www.iau.org/WG100/WG100/Home.aspx', m.source_iau_wgccre_name())}
			</li>
		</ul>
	</section>

	{#if ctx.credits.skybox}
		<section class="space-y-1">
			{@render sectionHeader(m.attribution_section_skybox())}
			<ul class="space-y-0.5">
				<li>{@render link(ctx.credits.skybox.source, ctx.credits.skybox.organisation)}</li>
			</ul>
		</section>
	{/if}

	{#if ringList.length > 0}
		<section class="space-y-1">
			{@render sectionHeader(m.attribution_section_rings())}
			<ul class="space-y-0.5">
				{#each ringList as r (r.bodyId)}
					<li>{@render link(r.source, bodyName(r.bodyId), r.organisation)}</li>
				{/each}
			</ul>
		</section>
	{/if}

	{#if cloudList.length > 0}
		<section class="space-y-1">
			{@render sectionHeader(m.attribution_section_clouds())}
			<ul class="space-y-0.5">
				{#each cloudList as c (c.bodyId)}
					<li>{@render link(c.source, bodyName(c.bodyId), c.organisation)}</li>
				{/each}
			</ul>
		</section>
	{/if}

	{#if textureList.length > 0}
		<section class="space-y-1">
			{@render sectionHeader(m.attribution_section_imagery())}
			<ul class="space-y-0.5">
				{#each textureList as t (t.bodyId)}
					<li>{@render link(t.source, bodyName(t.bodyId), t.organisation)}</li>
				{/each}
			</ul>
		</section>
	{/if}

	<section class="space-y-1">
		{@render sectionHeader(m.attribution_section_metadata())}
		<ul class="space-y-0.5">
			<li>{@render link('https://www.wikidata.org/', m.source_wikidata_name())}</li>
			<li>{@render link('https://www.wikipedia.org/', m.source_wikipedia_name())}</li>
			<li>
				{@render link('https://planetarynames.wr.usgs.gov/', m.source_iau_naming_name())}
			</li>
		</ul>
	</section>

	<section class="space-y-1">
		{@render sectionHeader(m.attribution_section_images())}
		<ul class="space-y-0.5">
			<li>
				{@render link('https://commons.wikimedia.org/', m.source_wikimedia_commons_name())}
			</li>
		</ul>
	</section>

	<a
		href="/credits"
		class="text-muted-foreground hover:text-foreground hover:underline underline-offset-2 pt-1"
	>
		{m.credits_see_all()} →
	</a>
</div>
