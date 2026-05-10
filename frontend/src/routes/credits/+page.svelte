<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import ArrowLeftIcon from '@lucide/svelte/icons/arrow-left';
	import type { Credits } from './+page';

	interface Props {
		data: { credits: Credits };
	}

	let { data }: Props = $props();
	const credits = $derived(data.credits);
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
			{@render sectionHeader(m.attribution_section_orbits())}
			<ul class="space-y-1">
				<li>{@render link('https://ssd.jpl.nasa.gov/horizons/', m.source_horizons_name())}</li>
				<li>
					{@render link('https://ssd.jpl.nasa.gov/tools/sbdb_query.html', m.source_sbdb_name())}
				</li>
				<li>
					{@render link('https://naif.jpl.nasa.gov/naif/', m.source_spice_ephemeris_name())}
				</li>
				<li>{@render link('https://celestrak.org/', m.source_celestrak_name())}</li>
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
				<li>{@render link('https://www.wikidata.org/', m.source_wikidata_name())}</li>
				<li>{@render link('https://www.wikipedia.org/', m.source_wikipedia_name())}</li>
				<li>
					{@render link('https://planetarynames.wr.usgs.gov/', m.source_iau_naming_name())}
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

		{#if credits.systems.some((g) => g.textures && g.textures.length > 0)}
			<section>
				{@render sectionHeader(m.attribution_section_imagery())}
				{#each credits.systems as group (group.id ?? '__standalone__')}
					{#if group.textures && group.textures.length > 0}
						<h3 class="text-xs font-semibold text-foreground mt-3 mb-1">
							{group.name ?? m.credits_other_bodies()}
						</h3>
						<ul class="space-y-1">
							{#each group.textures as t (t.body_id)}
								<li>
									{@render link(t.source, t.name, t.organisation)}
									{#if t.attribution}
										<div class="text-xs text-muted-foreground mt-0.5">{t.attribution}</div>
									{/if}
								</li>
							{/each}
						</ul>
					{/if}
				{/each}
			</section>
		{/if}

		{#if credits.systems.some((g) => g.rings && g.rings.length > 0)}
			<section>
				{@render sectionHeader(m.attribution_section_rings())}
				{#each credits.systems as group (group.id ?? '__standalone__')}
					{#if group.rings && group.rings.length > 0}
						<h3 class="text-xs font-semibold text-foreground mt-3 mb-1">
							{group.name ?? m.credits_other_bodies()}
						</h3>
						<ul class="space-y-1">
							{#each group.rings as r (r.body_id)}
								<li>
									{@render link(r.source, r.name, r.organisation)}
									{#if r.attribution}
										<div class="text-xs text-muted-foreground mt-0.5">{r.attribution}</div>
									{/if}
								</li>
							{/each}
						</ul>
					{/if}
				{/each}
			</section>
		{/if}
	</div>
</div>
