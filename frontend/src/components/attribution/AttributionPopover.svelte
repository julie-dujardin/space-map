<script lang="ts">
	import { getContext } from 'svelte';
	import ExternalLinkIcon from '@lucide/svelte/icons/external-link';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import { OrbitalSource } from '$lib/fetch/position/format';
	import { GITHUB_REPO_URL } from '$lib/constants';
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

	// Scoped to the focused system + focused body (covers standalones like
	// Bennu/Ceres that are credited body-by-body, not system-by-system).
	function scopedCredits<T extends { bodyId: string; systemId?: string | null }>(
		all: Iterable<T>
	): T[] {
		const sysId = ctx.visibility.focusedSystemId;
		const bodyId = ctx.visibility.focusedBodyId;
		return [...all]
			.filter((c) => c.bodyId === bodyId || (sysId && c.systemId === sysId))
			.sort((a, b) => bodyName(a.bodyId).localeCompare(bodyName(b.bodyId)));
	}

	// Merged imagery rows: skybox + per-body texture/cloud/night/ring credits.
	// When a single body contributes more than one kind (e.g. Earth: surface +
	// clouds + night, Saturn: surface + rings), each row gets a type qualifier
	// in parentheses; otherwise the body name alone is enough.
	interface ImageryRow {
		key: string;
		label: string;
		qualifier?: string;
		source: string;
		organisation: string;
	}

	const imageryRows = $derived.by<ImageryRow[]>(() => {
		void ctx.credits.textureVersion;
		void ctx.credits.cloudVersion;
		void ctx.credits.nightVersion;
		void ctx.credits.ringVersion;

		// Per-body ordering within the imagery list: surface → clouds → night → rings.
		const byBody = new Map<
			string,
			Array<{
				typeKey: 'surface' | 'clouds' | 'night' | 'rings';
				source: string;
				organisation: string;
			}>
		>();
		const push = (
			bodyId: string,
			typeKey: 'surface' | 'clouds' | 'night' | 'rings',
			source: string,
			organisation: string
		) => {
			const arr = byBody.get(bodyId) ?? [];
			arr.push({ typeKey, source, organisation });
			byBody.set(bodyId, arr);
		};
		for (const c of scopedCredits(ctx.credits.texture.values()))
			push(c.bodyId, 'surface', c.source, c.organisation);
		for (const c of scopedCredits(ctx.credits.cloud.values()))
			push(c.bodyId, 'clouds', c.source, c.organisation);
		for (const c of scopedCredits(ctx.credits.night.values()))
			push(c.bodyId, 'night', c.source, c.organisation);
		for (const c of scopedCredits(ctx.credits.ring.values()))
			push(c.bodyId, 'rings', c.source, c.organisation);

		const typeLabel = (k: 'surface' | 'clouds' | 'night' | 'rings'): string => {
			if (k === 'surface') return m.attribution_type_surface();
			if (k === 'clouds') return m.attribution_type_clouds();
			if (k === 'night') return m.attribution_type_night();
			return m.attribution_type_rings();
		};

		const rows: ImageryRow[] = [];
		if (ctx.credits.skybox) {
			rows.push({
				key: 'skybox',
				label: m.attribution_section_skybox(),
				source: ctx.credits.skybox.source,
				organisation: ctx.credits.skybox.organisation
			});
		}
		const bodies = [...byBody.keys()].sort((a, b) => bodyName(a).localeCompare(bodyName(b)));
		for (const bodyId of bodies) {
			const items = byBody.get(bodyId)!;
			const multi = items.length > 1;
			for (const it of items) {
				rows.push({
					key: `${bodyId}-${it.typeKey}`,
					label: bodyName(bodyId),
					qualifier: multi ? typeLabel(it.typeKey) : undefined,
					source: it.source,
					organisation: it.organisation
				});
			}
		}
		return rows;
	});

	// 3D models are body-scoped (only the focused probe's model is in the
	// scene). The popover shows the focused body's model credit directly.
	const focusedModel = $derived.by(() => {
		void ctx.credits.modelVersion;
		const bodyId = ctx.visibility.focusedBodyId;
		return bodyId ? ctx.credits.model.get(bodyId) : undefined;
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

	{#if imageryRows.length > 0}
		<section class="space-y-1">
			{@render sectionHeader(m.attribution_section_imagery_all())}
			<ul class="space-y-0.5">
				{#each imageryRows as r (r.key)}
					<li>
						{@render link(
							r.source,
							r.qualifier ? `${r.label} (${r.qualifier})` : r.label,
							r.organisation
						)}
					</li>
				{/each}
			</ul>
		</section>
	{/if}

	{#if focusedModel}
		<section class="space-y-1">
			{@render sectionHeader(m.attribution_section_models())}
			<ul class="space-y-0.5">
				<li>
					{@render link(
						focusedModel.source,
						bodyName(focusedModel.bodyId),
						focusedModel.organisation
					)}
				</li>
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

	<section class="space-y-1">
		{@render sectionHeader(m.attribution_section_source())}
		<ul class="space-y-0.5">
			<li>{@render link(GITHUB_REPO_URL, m.credits_source_code())}</li>
		</ul>
	</section>

	<a
		href="/credits"
		class="text-muted-foreground hover:text-foreground hover:underline underline-offset-2 pt-1"
	>
		{m.credits_see_all()} →
	</a>
</div>
