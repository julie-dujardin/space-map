<!--
  The objects table: one row for each kind of object, with its count, its
  size, the share of its items that have text in a chosen language, and its
  sources.
-->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import { resolve } from '$app/paths';
	import ChevronDownIcon from '@lucide/svelte/icons/chevron-down';
	import { getLocale, locales } from '$lib/paraglide/runtime.js';
	import { formatBytes } from '$lib/format/bytes';
	import { categoryLabel } from '$lib/format/group';
	import { LOCALE_NAMES } from '$lib/format/locale-names';
	import { formatPercent, ucfirst } from '$lib/format/quantities';
	import { sourceLinks } from '$lib/about/object-sources';
	import {
		CAT_ASTEROIDS,
		CAT_COMETS,
		CAT_DEBRIS,
		CAT_DWARF_PLANETS,
		CAT_MOONS,
		CAT_PLANETS,
		CAT_PROBES,
		CAT_RING_SYSTEMS,
		CAT_SATELLITES,
		CAT_SURFACE_FEATURES
	} from '$lib/fetch/groups/registry';
	import { groupHref } from '$lib/state/page-href';
	import type { ObjectKind } from '$lib/about/data-payload';

	interface Props {
		kinds: ObjectKind[];
	}

	let { kinds }: Props = $props();

	const ANY = 'any';
	let language = $state<string>(getLocale());

	// The category page of each kind that has one.
	const CATEGORIES: Record<string, string> = {
		planet: CAT_PLANETS,
		dwarf_planet: CAT_DWARF_PLANETS,
		moon: CAT_MOONS,
		asteroid: CAT_ASTEROIDS,
		comet: CAT_COMETS,
		ring_system: CAT_RING_SYSTEMS,
		surface_feature: CAT_SURFACE_FEATURES,
		satellite: CAT_SATELLITES,
		probe: CAT_PROBES,
		debris: CAT_DEBRIS
	};

	const NAMES: Record<string, () => string> = {
		star: () => ucfirst(m.search_cat_star()),
		barycenter: () => ucfirst(m.search_cat_barycenter())
	};

	// Column widths, shared by the header and every row.
	const NAME = 'min-w-0 flex-1 2xl:w-60 2xl:flex-none';
	const COUNT = 'hidden w-24 shrink-0 text-end sm:block';
	const SIZE = 'w-20 shrink-0 text-end sm:w-24';
	const LOCALIZED = 'w-20 shrink-0 text-end sm:w-24';
	const SOURCES = 'mt-1 w-full min-w-0 2xl:mt-0 2xl:w-auto 2xl:flex-1';

	function kindName(kind: ObjectKind): string {
		const slug = CATEGORIES[kind.id];
		if (slug) return categoryLabel(slug);
		return NAMES[kind.id]?.() ?? ucfirst(kind.id.replaceAll('_', ' '));
	}

	function count(n: number): string {
		return n.toLocaleString(getLocale());
	}

	function share(part: number, whole: number): string {
		return whole > 0 ? formatPercent(part / whole) : '—';
	}

	function notes(kind: ObjectKind): string[] {
		const out: string[] = [];
		if (kind.systems !== undefined)
			out.push(m.about_data_systems_count({ count: count(kind.systems) }));
		if (kind.position_bytes)
			out.push(m.about_data_positions_size({ size: formatBytes(kind.position_bytes) }));
		return out;
	}
</script>

<!-- Under a row the name of a source is as small as the notes there. -->
{#snippet sources(kind: ObjectKind)}
	{@const style = 'text-xs text-muted-foreground 2xl:text-sm 2xl:text-foreground'}
	<div class="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
		{#each kind.sources as source (source.key)}
			<span>
				{#each sourceLinks(source.key) as link, i (link.label)}
					{#if i > 0}<span class="mx-1 text-muted-subtle">·</span>{/if}
					{#if link.url}
						<a
							href={link.url}
							target="_blank"
							rel="noopener noreferrer"
							class="{style} hover:underline underline-offset-2">{link.label}</a
						>
					{:else}
						<span class={style}>{link.label}</span>
					{/if}
				{/each}
				<span class="text-xs text-muted-subtle tabular-nums">
					{share(source.objects, kind.count)}
				</span>
			</span>
		{/each}
		{#if kind.works}
			<a href={resolve('/credits')} class="{style} hover:underline underline-offset-2">
				{m.about_data_works_count({ count: count(kind.works) })}
			</a>
		{/if}
	</div>
{/snippet}

<div class="mt-4 flex justify-end">
	<label class="flex items-center gap-2 text-xs text-muted-foreground">
		{m.settings_language()}
		<span class="relative">
			<select
				bind:value={language}
				class="cursor-pointer appearance-none rounded-md border border-input bg-background py-1 ps-2 pe-6 text-xs text-foreground transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
			>
				{#each locales as locale (locale)}
					<option value={locale}>{LOCALE_NAMES[locale] ?? locale}</option>
				{/each}
				<option value={ANY}>{m.about_data_any_language()}</option>
			</select>
			<ChevronDownIcon
				class="pointer-events-none absolute end-1.5 top-1/2 size-3 -translate-y-1/2 opacity-50"
			/>
		</span>
	</label>
</div>

<!-- The header stays in view down the length of the table. -->
<div
	class="sticky top-0 z-10 mt-1 flex items-baseline gap-4 border-b border-border bg-bg pt-2 pb-1.5 text-xs font-semibold uppercase tracking-wider text-muted-subtle"
>
	<div class={NAME}>{m.about_data_column_kind()}</div>
	<div class={COUNT}>{m.about_data_column_count()}</div>
	<div class={SIZE}>{m.about_data_column_size()}</div>
	<div class={LOCALIZED}>{m.about_data_column_localized()}</div>
	<div class="hidden min-w-0 flex-1 2xl:block">{m.status_column_source()}</div>
</div>

<!-- The count a narrow screen has no column for goes under the name. -->
{#each kinds as kind (kind.id)}
	{@const name = kindName(kind)}
	{@const slug = CATEGORIES[kind.id]}
	<div class="flex flex-wrap items-baseline gap-x-4 border-b border-border py-2.5">
		<div class="{NAME} wrap-anywhere">
			{#if slug}
				<a href={groupHref(slug, name)} class="font-medium hover:underline underline-offset-2"
					>{name}</a
				>
			{:else}
				<span class="font-medium">{name}</span>
			{/if}
			<div class="text-xs text-muted-subtle tabular-nums sm:hidden">
				{m.about_data_count_stated({ count: count(kind.count) })}
			</div>
			{#each notes(kind) as note (note)}
				<div class="text-xs text-muted-subtle">{note}</div>
			{/each}
		</div>
		<div class="{COUNT} tabular-nums">{count(kind.count)}</div>
		<div class="{SIZE} text-muted-foreground tabular-nums">{formatBytes(kind.size_bytes)}</div>
		<div class="{LOCALIZED} text-muted-foreground tabular-nums">
			{share(kind.localized[language] ?? 0, kind.count)}
		</div>
		<div class={SOURCES}>{@render sources(kind)}</div>
	</div>
{/each}
