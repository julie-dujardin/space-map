<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import SitePage from '../../components/nav/SitePage.svelte';
	import { archiveLabel, archiveRole } from '$lib/credits/archive-labels';
	import { TAXONOMY_SOURCES } from '$lib/credits/taxonomy-sources';
	import { GITHUB_REPO_URL } from '$lib/constants';
	import { REFERENCE_SECTIONS, type BodyCredit, type Credits } from '$lib/credits/credits-payload';
	import { IMAGERY_LAYERS, layerLabel, type ImageryLayer } from '$lib/credits/imagery-layers';

	interface Props {
		data: { credits: Credits };
	}

	let { data }: Props = $props();
	const credits = $derived(data.credits);

	// Merged imagery: one section per system, one row per body+layer. A layer
	// qualifier only appears when a body contributes more than one.
	interface ImageryRow {
		key: string;
		name: string;
		qualifier?: string;
		source: string;
		organisation: string;
		license?: string;
		attribution?: string;
	}

	interface ImagerySystem {
		id: string | null;
		name: string | null;
		rows: ImageryRow[];
	}

	const collator = new Intl.Collator();

	const imagerySystems = $derived.by<ImagerySystem[]>(() => {
		const out: ImagerySystem[] = [];
		for (const group of credits.systems) {
			// Keyed by the export's array names; IMAGERY_LAYERS fixes the row order.
			const lists: Record<ImageryLayer, BodyCredit[] | undefined> = {
				surface: group.textures,
				clouds: group.clouds,
				night: group.night,
				specular: group.specular,
				topography: group.displacement,
				rings: group.rings
			};
			const byBody = new Map<string, Array<{ layer: ImageryLayer; credit: BodyCredit }>>();
			for (const layer of IMAGERY_LAYERS)
				for (const credit of lists[layer] ?? [])
					byBody.set(credit.body_id, [...(byBody.get(credit.body_id) ?? []), { layer, credit }]);

			if (byBody.size === 0) continue;
			const rows: ImageryRow[] = [];
			const bodies = [...byBody.values()].sort((a, b) =>
				collator.compare(a[0].credit.name, b[0].credit.name)
			);
			for (const items of bodies) {
				const multi = items.length > 1;
				for (const [i, { layer, credit }] of items.entries()) {
					rows.push({
						// Body + layer isn't unique: one body can credit several sources
						// for the same layer (e.g. Saturn's ring bundles).
						key: `${credit.body_id}-${layer}-${i}`,
						name: credit.name,
						qualifier: multi ? layerLabel(layer) : undefined,
						source: credit.source,
						organisation: credit.organisation,
						license: credit.license,
						attribution: credit.attribution
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
		{label}{#if sub}<span class="text-muted-foreground">&nbsp;— {sub}</span>{/if}
	</a>
{/snippet}

<SitePage current="credits" title={m.credits_page_title()}>
	<div class="text-sm leading-relaxed">
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
						'https://www.johnstonsarchive.net/astro/asteroidmoons.html',
						m.source_johnston_name(),
						m.source_johnston_role()
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
				<!-- Spectral classes sit here, not under Interiors: they say what an
				     asteroid is called, and the composition estimate is downstream of that. -->
				{#each Object.entries(TAXONOMY_SOURCES) as [id, source] (id)}
					<li>{@render link(source.url, source.label(), source.role())}</li>
				{/each}
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
						<li>
							{@render link(cat.url, cat.name)}
							{#if cat.license}<span class="text-xs text-muted-foreground">
									· {cat.license}</span
								>{/if}
						</li>
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
						{#if credits.skybox.license}<span class="text-xs text-muted-foreground">
								· {credits.skybox.license}</span
							>{/if}
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
								{#if r.license}<span class="text-xs text-muted-foreground">
										· {r.license}</span
									>{/if}
								{#if r.attribution}
									<div class="text-xs text-muted-foreground mt-0.5">{r.attribution}</div>
								{/if}
							</li>
						{/each}
					</ul>
				{/each}
			</section>
		{/if}

		{#each REFERENCE_SECTIONS as section (section.key)}
			{@const refs = credits[section.key]}
			{#if refs?.length}
				<section>
					{@render sectionHeader(section.label())}
					<ul class="space-y-1">
						{#each refs as ref (ref.url)}
							<li>{@render link(ref.url, ref.title, ref.contribution)}</li>
						{/each}
					</ul>
				</section>
			{/if}
		{/each}
	</div>
</SitePage>
