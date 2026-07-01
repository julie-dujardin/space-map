<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import ArrowLeftIcon from '@lucide/svelte/icons/arrow-left';
	import { archiveLabel, archiveRole } from '$lib/credits/archive-labels';
	import { GITHUB_REPO_URL } from '$lib/constants';
	import type { Credits } from './+page';

	interface Props {
		data: { credits: Credits };
	}

	let { data }: Props = $props();
	const credits = $derived(data.credits);

	// Merged imagery: one section grouped by system, one row per body+type.
	// A type qualifier is only added when a body contributes more than one kind
	// (e.g. Earth: surface + clouds + night), mirroring the attribution popover.
	type ImageryTypeKey = 'surface' | 'clouds' | 'night' | 'topography' | 'rings';

	interface ImageryRow {
		key: string;
		name: string;
		qualifier?: string;
		source: string;
		organisation: string;
		attribution?: string;
	}

	interface ImagerySystem {
		id: string | null;
		name: string | null;
		rows: ImageryRow[];
	}

	function typeLabel(k: ImageryTypeKey): string {
		if (k === 'surface') return m.attribution_type_surface();
		if (k === 'clouds') return m.attribution_type_clouds();
		if (k === 'night') return m.attribution_type_night();
		if (k === 'topography') return m.attribution_type_topography();
		return m.attribution_type_rings();
	}

	const imagerySystems = $derived.by<ImagerySystem[]>(() => {
		interface Interim {
			body_id: string;
			name: string;
			typeKey: ImageryTypeKey;
			source: string;
			organisation: string;
			attribution?: string;
		}
		// Per-body ordering within the list: surface → clouds → night → topography → rings.
		type CreditLike = {
			body_id: string;
			name: string;
			source: string;
			organisation: string;
			attribution?: string;
		};
		const out: ImagerySystem[] = [];
		for (const group of credits.systems) {
			const order: Array<[ImageryTypeKey, CreditLike[]]> = [
				['surface', group.textures ?? []],
				['clouds', group.clouds ?? []],
				['night', group.night ?? []],
				['topography', group.displacement ?? []],
				['rings', group.rings ?? []]
			];
			const byBody = new Map<string, Interim[]>();
			for (const [typeKey, list] of order) {
				for (const c of list) {
					const arr = byBody.get(c.body_id) ?? [];
					arr.push({
						body_id: c.body_id,
						name: c.name,
						typeKey,
						source: c.source,
						organisation: c.organisation,
						attribution: c.attribution
					});
					byBody.set(c.body_id, arr);
				}
			}
			if (byBody.size === 0) continue;
			const rows: ImageryRow[] = [];
			const bodies = [...byBody.values()].sort((a, b) => a[0].name.localeCompare(b[0].name));
			for (const items of bodies) {
				const multi = items.length > 1;
				for (const it of items) {
					rows.push({
						key: `${it.body_id}-${it.typeKey}`,
						name: it.name,
						qualifier: multi ? typeLabel(it.typeKey) : undefined,
						source: it.source,
						organisation: it.organisation,
						attribution: it.attribution
					});
				}
			}
			out.push({ id: group.id, name: group.name, rows });
		}
		return out;
	});
</script>

<svelte:head>
	<title>{m.credits_page_title()} - {m.page_title()}</title>
</svelte:head>

{#snippet sectionHeader(label: string)}
	<h2 class="text-xs font-semibold uppercase tracking-wider text-muted-foreground mt-6 mb-2">
		{label}
	</h2>
{/snippet}

{#snippet link(href: string, label: string, sub?: string)}
	<a
		{href}
		target="_blank"
		rel="noopener noreferrer"
		class="text-foreground hover:underline underline-offset-2"
	>
		{label}{#if sub}<span class="text-muted-foreground"> — {sub}</span>{/if}
	</a>
{/snippet}

<div class="h-dvh overflow-y-auto bg-bg text-text">
	<div class="mx-auto max-w-2xl px-6 py-10 text-sm leading-relaxed">
		<a
			href="/"
			class="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground mb-6"
		>
			<ArrowLeftIcon class="size-4" />
			{m.credits_back_to_map()}
		</a>

		<h1 class="text-2xl font-semibold">{m.credits_page_title()}</h1>

		<section>
			{@render sectionHeader(m.attribution_section_source())}
			<ul class="space-y-1">
				<li>{@render link(GITHUB_REPO_URL, m.credits_source_code())}</li>
			</ul>
		</section>

		<section>
			{@render sectionHeader(m.attribution_section_orbits())}
			<ul class="space-y-1">
				{#each credits.ephemeris_archives as archive (archive.id)}
					<li>
						{@render link(
							archive.source,
							archiveLabel(archive.id) ?? archive.organisation,
							archiveRole(archive.id) ?? undefined
						)}
					</li>
				{/each}
			</ul>
		</section>

		<section>
			{@render sectionHeader(m.attribution_section_rotation())}
			<ul class="space-y-1">
				<li>{@render link('https://naif.jpl.nasa.gov/naif/', m.source_spice_pck_name())}</li>
				<li>
					{@render link('https://www.iau.org/WG100/WG100/Home.aspx', m.source_iau_wgccre_name())}
				</li>
			</ul>
		</section>

		<section>
			{@render sectionHeader(m.attribution_section_metadata())}
			<ul class="space-y-1">
				<li>
					{@render link(
						'https://www.wikidata.org/',
						m.source_wikidata_name(),
						m.source_wikidata_role()
					)}
				</li>
				<li>
					{@render link(
						'https://www.wikipedia.org/',
						m.source_wikipedia_name(),
						m.source_wikipedia_role()
					)}
				</li>
				<li>
					{@render link(
						'https://planetarynames.wr.usgs.gov/',
						m.source_iau_naming_name(),
						m.source_iau_naming_role()
					)}
				</li>
				<li>
					{@render link(
						'https://www.minorplanetcenter.net/',
						m.source_mpc_name(),
						m.source_mpc_role()
					)}
				</li>
				<li>
					{@render link(
						'https://ssd.jpl.nasa.gov/sats/discovery.html',
						m.source_jpl_satellite_discovery_name(),
						m.source_jpl_satellite_discovery_role()
					)}
				</li>
				<li>
					{@render link(
						'https://celestrak.org/satcat/',
						m.source_celestrak_name(),
						m.source_celestrak_role()
					)}
				</li>
				<li>
					{@render link(
						'https://planet4589.org/space/',
						m.source_jonathan_space_report_name(),
						m.source_jonathan_space_report_role()
					)}
				</li>
				<li>
					{@render link(
						'https://github.com/Askaniy/TrueColorTools',
						m.source_truecolortools_name(),
						m.source_truecolortools_role()
					)}
				</li>
			</ul>
		</section>

		<section>
			{@render sectionHeader(m.attribution_section_images())}
			<ul class="space-y-1">
				<li>
					{@render link('https://commons.wikimedia.org/', m.source_wikimedia_commons_name())}
				</li>
			</ul>
			<p class="text-xs text-muted-foreground mt-2">{m.credits_images_individual_note()}</p>
		</section>

		{#if credits.models && credits.models.length > 0}
			<section>
				{@render sectionHeader(m.attribution_section_models())}
				<ul class="space-y-1">
					{#each credits.models as cat (cat.url)}
						<li>{@render link(cat.url, cat.name)}</li>
					{/each}
				</ul>
			</section>
		{/if}

		{#if credits.skybox}
			<section>
				{@render sectionHeader(m.attribution_section_skybox())}
				<ul class="space-y-1">
					<li>
						{@render link(credits.skybox.source, credits.skybox.organisation)}
						{#if credits.skybox.attribution}
							<div class="text-xs text-muted-foreground mt-0.5">{credits.skybox.attribution}</div>
						{/if}
					</li>
				</ul>
			</section>
		{/if}

		{#if imagerySystems.length > 0}
			<section>
				{@render sectionHeader(m.attribution_section_imagery_all())}
				{#each imagerySystems as group (group.id ?? '__standalone__')}
					<h3 class="text-xs font-semibold text-foreground mt-3 mb-1">
						{group.name ?? m.credits_other_bodies()}
					</h3>
					<ul class="space-y-1">
						{#each group.rows as r (r.key)}
							<li>
								{@render link(
									r.source,
									r.qualifier ? `${r.name} (${r.qualifier})` : r.name,
									r.organisation
								)}
								{#if r.attribution}
									<div class="text-xs text-muted-foreground mt-0.5">{r.attribution}</div>
								{/if}
							</li>
						{/each}
					</ul>
				{/each}
			</section>
		{/if}
	</div>
</div>
