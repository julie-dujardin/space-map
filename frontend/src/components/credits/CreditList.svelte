<!--
  The credit list itself: one section per kind of source, in a few groups. The page around it
  draws before this does, so it takes the payload already resolved.
-->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import { archiveLabel, archiveRole } from '$lib/credits/archive-labels';
	import { TAXONOMY_SOURCES } from '$lib/credits/taxonomy-sources';
	import { GITHUB_REPO_URL } from '$lib/constants';
	import { REFERENCE_SECTIONS, type BodyCredit, type Credits } from '$lib/credits/credits-payload';
	import { IMAGERY_LAYERS, layerLabel, type ImageryLayer } from '$lib/credits/imagery-layers';
	import { tileCredit } from '$lib/credits/tile-credit';

	interface Props {
		credits: Credits;
	}

	let { credits }: Props = $props();

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
				surface: group.textures?.flatMap((credit) => {
					const tiles = tileCredit(credit);
					return tiles ? [credit, { ...credit, ...tiles }] : [credit];
				}),
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

	const references = $derived(REFERENCE_SECTIONS.filter((section) => credits[section.key]?.length));

	const hasModels = $derived(!!credits.models?.length || !!credits.model_contributors?.length);
	const hasImagery = $derived(imagerySystems.length > 0 || !!credits.skybox);

	interface Entry {
		id: string;
		label: string;
		children?: Entry[];
	}

	// Only what draws: an entry for an absent section would link nowhere.
	const contents = $derived<Entry[]>([
		{ id: 'source', label: m.attribution_section_source() },
		{
			id: 'data',
			label: m.credits_group_data(),
			children: [
				{ id: 'orbits', label: m.attribution_section_orbits() },
				{ id: 'rotation', label: m.attribution_section_rotation() },
				{ id: 'metadata', label: m.attribution_section_metadata() }
			]
		},
		{
			id: 'media',
			label: m.credits_group_media(),
			children: [
				{ id: 'images', label: m.attribution_section_images() },
				...(hasModels ? [{ id: 'models', label: m.attribution_section_models() }] : []),
				...(hasImagery ? [{ id: 'imagery', label: m.attribution_section_imagery_all() }] : [])
			]
		},
		...(references.length
			? [
					{
						id: 'references',
						label: m.credits_group_references(),
						children: references.map((section) => ({ id: section.key, label: section.label() }))
					}
				]
			: [])
	]);
</script>

{#snippet groupHeader(id: string, label: string)}
	<h2 {id} class="text-base font-semibold text-foreground mt-10 mb-1 scroll-mt-10">
		{label}
	</h2>
{/snippet}

{#snippet sectionHeader(id: string, label: string)}
	<h3
		{id}
		class="text-xs font-semibold uppercase tracking-wider text-muted-foreground mt-6 mb-2 scroll-mt-10"
	>
		{label}
	</h3>
{/snippet}

{#snippet systemHeader(label: string)}
	<h4 class="text-xs font-semibold text-foreground mt-3 mb-1">{label}</h4>
{/snippet}

{#snippet contentsLink(entry: Entry)}
	<a href="#{entry.id}" class="hover:text-foreground">{entry.label}</a>
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

<div class="relative text-sm leading-relaxed">
	<!-- In the page margin, so it only shows where the margin can hold it. -->
	<nav
		aria-label={m.credits_contents()}
		class="absolute inset-y-0 end-full me-8 hidden w-44 xl:block"
	>
		<ul class="sticky top-10 space-y-3 text-xs leading-snug text-muted-foreground">
			{#each contents as group (group.id)}
				<li>
					<span class="font-medium text-foreground">{@render contentsLink(group)}</span>
					{#if group.children}
						<ul class="mt-1.5 space-y-1.5">
							{#each group.children as entry (entry.id)}
								<li>{@render contentsLink(entry)}</li>
							{/each}
						</ul>
					{/if}
				</li>
			{/each}
		</ul>
	</nav>

	<section>
		{@render groupHeader('source', m.attribution_section_source())}
		<ul class="mt-2 space-y-1">
			<li>{@render link(GITHUB_REPO_URL, m.credits_source_code())}</li>
		</ul>
	</section>

	<section>
		{@render groupHeader('data', m.credits_group_data())}
		<section>
			{@render sectionHeader('orbits', m.attribution_section_orbits())}
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
			{@render sectionHeader('rotation', m.attribution_section_rotation())}
			<ul class="space-y-1">
				<li>{@render link('https://naif.jpl.nasa.gov/naif/', m.source_spice_pck_name())}</li>
				<li>
					{@render link('https://www.iau.org/WG100/WG100/Home.aspx', m.source_iau_wgccre_name())}
				</li>
			</ul>
		</section>

		<section>
			{@render sectionHeader('metadata', m.attribution_section_metadata())}
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
	</section>

	<section>
		{@render groupHeader('media', m.credits_group_media())}
		<section>
			{@render sectionHeader('images', m.attribution_section_images())}
			<ul class="space-y-1">
				<li>
					{@render link('https://commons.wikimedia.org/', m.source_wikimedia_commons_name())}
				</li>
			</ul>
			<p class="text-xs text-muted-foreground mt-2">{m.credits_images_individual_note()}</p>
		</section>

		{#if hasModels}
			<section>
				{@render sectionHeader('models', m.attribution_section_models())}
				<ul class="space-y-1">
					{#each credits.models ?? [] as cat (cat.url)}
						<li>
							{@render link(cat.url, cat.name)}
							{#if cat.license}<span class="text-xs text-muted-foreground">
									· {cat.license}</span
								>{/if}
						</li>
					{/each}
					{#each credits.model_contributors ?? [] as author (author.name)}
						<li>
							{#if author.url}
								{@render link(author.url, author.name)}
							{:else}
								{author.name}
							{/if}
							{#if author.licenses.length > 0}<span class="text-xs text-muted-foreground">
									· {author.licenses.join(', ')}</span
								>{/if}
						</li>
					{/each}
				</ul>
			</section>
		{/if}

		{#if hasImagery}
			<section>
				{@render sectionHeader('imagery', m.attribution_section_imagery_all())}
				{#each imagerySystems as group (group.id ?? '__standalone__')}
					{@render systemHeader(group.name ?? m.credits_other_bodies())}
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
				{#if credits.skybox}
					{@render systemHeader(m.attribution_section_skybox())}
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
				{/if}
			</section>
		{/if}
	</section>

	{#if references.length > 0}
		<section>
			{@render groupHeader('references', m.credits_group_references())}
			{#each references as section (section.key)}
				<section>
					{@render sectionHeader(section.key, section.label())}
					<ul class="space-y-1">
						{#each credits[section.key] ?? [] as ref (ref.url)}
							<li>{@render link(ref.url, ref.title, ref.contribution)}</li>
						{/each}
					</ul>
				</section>
			{/each}
		</section>
	{/if}
</div>
