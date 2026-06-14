<script lang="ts">
	import { getContext } from 'svelte';
	import SearchIcon from '@lucide/svelte/icons/search';
	import XIcon from '@lucide/svelte/icons/x';
	import ChevronUpIcon from '@lucide/svelte/icons/chevron-up';
	import SlidersIcon from '@lucide/svelte/icons/sliders-horizontal';
	import * as m from '$lib/paraglide/messages.js';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import {
		localizedName,
		localizedDescription,
		fetchGroupCatalog,
		catalogCount,
		catalogFacets,
		isSearchEnabled,
		type SearchHit,
		type GroupHit,
		type FacetDistribution
	} from '$lib/search/client';
	import { compact } from '$lib/search/format';
	import { SearchModel, type FilterToken } from '$lib/search/model.svelte';
	import type { FilterCategory } from '$lib/search/tree';
	import { groupTypeLabel } from '$lib/format/group';
	import { classNameFromSlug, orbitClassLabel } from '$lib/charts/orbit-zones';
	import type { GroupType } from '$lib/fetch/groups/registry';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import SortMenu from './SortMenu.svelte';
	import FilterDrill from './FilterDrill.svelte';
	import SearchResults from './SearchResults.svelte';

	type Props = {
		onSelect: (hit: SearchHit) => void;
		onExpandedChange?: (expanded: boolean) => void;
	};

	let { onSelect, onExpandedChange }: Props = $props();

	const ctx = getContext<ContextManager>('ctx');
	const enabled = isSearchEnabled();

	const model = new SearchModel();
	let expanded = $state(false);
	// Let the parent raise the search panel above the detail drawer while it's
	// open, and drop it back under the drawer once collapsed.
	$effect(() => onExpandedChange?.(expanded));
	let filterOpen = $state(false);
	let groupCatalog = $state<GroupHit[]>([]);
	let catalogTotal = $state(0);
	let facetUniverse = $state<FacetDistribution>({});
	let inputEl: HTMLInputElement | undefined = $state();

	const groupBySlug = $derived(new Map(groupCatalog.map((g) => [g.slug, g])));

	// Group/collection taxonomy for the filter tree + token labels (one fetch).
	$effect(() => {
		if (enabled) fetchGroupCatalog(getLocale()).then((g) => (groupCatalog = g));
	});

	// Total catalog size for the idle hint (one stats call, locale-agnostic).
	$effect(() => {
		if (enabled) catalogCount().then((n) => (catalogTotal = n));
	});

	// Full facet vocabulary (locale-agnostic codes) so bounded facets can list
	// every value even once a query/filter narrows the live distribution.
	$effect(() => {
		if (enabled) catalogFacets().then((d) => (facetUniverse = d));
	});

	// Page size follows the visible panel height so a full page fills it (no big
	// empty gap below a short result list). ~52px rows; the constant accounts for
	// the header/count/pagination chrome. Biased to slightly overfill (scroll)
	// rather than underfill.
	let viewportH = $state(0);
	$effect(() => {
		const update = () => (viewportH = window.innerHeight);
		update();
		window.addEventListener('resize', update);
		return () => window.removeEventListener('resize', update);
	});
	$effect(() => {
		if (viewportH <= 0) return;
		const rows = Math.floor((viewportH - 120) / 52);
		model.setPageSize(Math.min(40, Math.max(6, rows)));
	});

	// Debounced query. Snapshot deps synchronously; runQuery only writes result.
	let debounceTimer: ReturnType<typeof setTimeout> | undefined;
	$effect(() => {
		const snap = {
			query: model.query,
			filters: model.filters,
			sort: model.sort,
			reverse: model.reverse,
			page: model.page,
			pageSize: model.pageSize,
			locale: getLocale()
		};
		clearTimeout(debounceTimer);
		debounceTimer = setTimeout(() => model.runQuery(snap), 150);
		return () => clearTimeout(debounceTimer);
	});

	// ── label helpers ──────────────────────────────────────────────────
	const messages = m as unknown as Record<
		string,
		((args?: Record<string, unknown>) => string) | undefined
	>;

	const HELIOCENTRIC_TYPES = new Set([
		'planet',
		'dwarf_planet',
		'comet',
		'asteroid',
		'asteroid_inner',
		'asteroid_main_belt',
		'asteroid_trojan',
		'asteroid_centaur',
		'asteroid_tno'
	]);
	const SELF_EXPLANATORY_TYPES = new Set(['star', 'spacecraft', 'undocumented']);

	function typeLabel(type: string): string {
		const key = type.startsWith('asteroid') ? 'type_asteroid' : `type_${type}`;
		return messages[key]?.() ?? type.replace(/_/g, ' ');
	}
	function featureTypeLabel(code: string): string {
		return messages[`feature_type_label_${code}`]?.() ?? code;
	}
	function bodyName(bodyId: string): string {
		return ctx.getBody(bodyId)?.data.name ?? bodyId;
	}
	function kindLabel(k: string): string {
		if (k === 'object') return m.search_kind_object();
		if (k === 'feature') return m.search_kind_feature();
		if (k === 'group') return m.search_kind_group();
		return k;
	}
	// Localized group/collection name. Orbit classes resolve via the frontend
	// `orbit_class_*` keys (the export leaves QID-less classes as the raw slug);
	// other kinds use their `group_name_<slug>` key, else the exported name.
	function groupName(g: GroupHit, locale: string): string {
		const className = classNameFromSlug(g.slug);
		if (className != null) return orbitClassLabel(className);
		const fn = messages[`group_name_${g.slug}`];
		if (fn) return fn();
		return localizedName(g, locale);
	}
	function rowName(hit: SearchHit): string {
		return localizedName(hit, getLocale());
	}
	function secondaryText(hit: SearchHit): string {
		const desc = localizedDescription(hit, getLocale());
		if (desc) return desc;
		if (hit.kind === 'feature') {
			return m.search_secondary_feature_on({
				type: featureTypeLabel(hit.feature_type),
				parent: bodyName(hit.body_id)
			});
		}
		if (hit.kind === 'group') return '';
		if (hit.id.startsWith('norad_satcat-')) {
			return hit.type === 'debris' ? m.type_earth_debris() : m.type_earth_satellite();
		}
		const label = typeLabel(hit.type);
		if (HELIOCENTRIC_TYPES.has(hit.type) || SELF_EXPLANATORY_TYPES.has(hit.type)) return label;
		if (hit.parent_id) {
			return m.search_secondary_orbiting({ type: label, parent: bodyName(hit.parent_id) });
		}
		return label;
	}

	// ── filter tree (categories) ───────────────────────────────────────
	const categories = $derived.by((): FilterCategory[] => {
		const f = model.result.facets;
		// Bounded facets (kind, type, flags) list their full value set always; the
		// live distribution gives counts (0 when narrowed away), falling back to the
		// whole-catalog universe while idle (no query/filters).
		const small = model.hasResults ? f : facetUniverse;
		const locale = getLocale();
		const cats: FilterCategory[] = [];

		// Kind — the fixed trio, always shown; 0 when none match.
		const kindDist = small['kind'] ?? {};
		cats.push({
			id: 'kind',
			label: m.search_facet_kind(),
			leaves: (['object', 'feature', 'group'] as const).map((k) => ({
				id: `kind-${k}`,
				kind: 'array',
				facet: 'kind',
				values: [k],
				label: kindLabel(k),
				count: kindDist[k] ?? 0
			}))
		});

		// Type — full vocabulary from the universe, merged by display label; live
		// counts fill in (0 when none match the current query/filters).
		const typeVocab = facetUniverse['object.type'];
		if (typeVocab) {
			const typeDist = small['object.type'] ?? {};
			const byLabel = new Map<string, { values: string[]; count: number }>();
			for (const raw of Object.keys(typeVocab)) {
				const lbl = typeLabel(raw);
				const e = byLabel.get(lbl) ?? { values: [], count: 0 };
				e.values.push(raw);
				e.count += typeDist[raw] ?? 0;
				byLabel.set(lbl, e);
			}
			const leaves = [...byLabel.entries()]
				.sort((a, b) => b[1].count - a[1].count)
				.map(([lbl, e]) => ({
					id: `type-${lbl}`,
					kind: 'array' as const,
					facet: 'type' as const,
					values: e.values,
					label: lbl,
					count: e.count
				}));
			if (leaves.length) cats.push({ id: 'type', label: m.search_facet_type(), leaves });
		}

		// Collections — one category per group type, leaves are the groups. Counts
		// come from the same catalog facet distribution as every other facet
		// (whole-catalog universe while idle, disjunctive live count once selected),
		// so a group's number never jumps between its stored member tally and the
		// actually-indexed count. Too many groups to list every empty one, so drop
		// 0-count leaves — but always keep a currently-selected group visible.
		const gf = small['object.groups'];
		if (gf) {
			const selectedGroups = new Set(model.filters.groups ?? []);
			const byType = new Map<string, GroupHit[]>();
			for (const g of groupCatalog) {
				const list = byType.get(g.type);
				if (list) list.push(g);
				else byType.set(g.type, [g]);
			}
			for (const [type, gs] of byType) {
				let leaves = gs
					.map((g) => ({ slug: g.slug, label: groupName(g, locale), count: gf[g.slug] ?? 0 }))
					.filter((l) => l.count > 0 || selectedGroups.has(l.slug));
				leaves.sort((a, b) => b.count - a.count);
				leaves = leaves.slice(0, 60);
				if (!leaves.length) continue;
				cats.push({
					id: `grp-${type}`,
					// Fall back to the raw type for any group kind the frontend doesn't
					// know (e.g. stale docs from a pre-merge export) rather than `undefined`.
					label: groupTypeLabel(type as GroupType) ?? type,
					leaves: leaves.map((l) => ({
						id: `grp-${type}-${l.slug}`,
						kind: 'array',
						facet: 'groups',
						values: [l.slug],
						label: l.label,
						count: l.count
					}))
				});
			}
		}

		// Properties — small-body flags; always shown, 0 when none match.
		cats.push({
			id: 'props',
			label: m.search_facet_properties(),
			leaves: [
				{
					id: 'prop-neo',
					kind: 'bool',
					facet: 'neo',
					label: m.search_prop_neo(),
					count: small['object.neo']?.['true'] ?? 0
				},
				{
					id: 'prop-pha',
					kind: 'bool',
					facet: 'pha',
					label: m.search_prop_pha(),
					count: small['object.pha']?.['true'] ?? 0
				}
			]
		});

		return cats;
	});

	const tokens = $derived.by((): FilterToken[] => {
		const locale = getLocale();
		const out: FilterToken[] = [];
		for (const v of model.filters.kind ?? [])
			out.push({ key: 'kind', value: v, label: kindLabel(v) });
		for (const v of model.filters.type ?? [])
			out.push({ key: 'type', value: v, label: typeLabel(v) });
		for (const slug of model.filters.groups ?? []) {
			const g = groupBySlug.get(slug);
			out.push({ key: 'groups', value: slug, label: g ? groupName(g, locale) : slug });
		}
		if (model.filters.neo) out.push({ key: 'neo', label: m.search_prop_neo() });
		if (model.filters.pha) out.push({ key: 'pha', label: m.search_prop_pha() });
		return out;
	});

	// ── interaction ────────────────────────────────────────────────────
	function pick(hit: SearchHit) {
		onSelect(hit);
		collapse();
		model.setQuery('');
		inputEl?.blur();
	}

	function collapse() {
		expanded = false;
		filterOpen = false;
	}

	// Close the filter popover on an outside click. focusout can't be used: a
	// drill that swaps its list (root → leaves) unmounts the just-clicked button,
	// dropping focus to <body> and reading as "left the cluster".
	let filterWrapEl: HTMLElement | undefined = $state();
	$effect(() => {
		if (!filterOpen) return;
		const onDown = (e: MouseEvent) => {
			if (filterWrapEl && !filterWrapEl.contains(e.target as Node)) filterOpen = false;
		};
		const t = setTimeout(() => document.addEventListener('mousedown', onDown), 0);
		return () => {
			clearTimeout(t);
			document.removeEventListener('mousedown', onDown);
		};
	});

	function onInputKeyDown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			model.setQuery('');
			collapse();
			inputEl?.blur();
		}
	}

	// Outside-click on the whole panel: collapse an empty/unfiltered panel, else
	// keep it (sticky once results show — close via minimize/Escape) and just
	// dismiss any open popover. mousedown (not focusout) so an internal list swap
	// that drops focus to <body> can't read as "left the panel".
	let wrapperEl: HTMLElement | undefined = $state();
	$effect(() => {
		if (!expanded) return;
		const onDown = (e: MouseEvent) => {
			if (wrapperEl && wrapperEl.contains(e.target as Node)) return;
			if (model.hasResults) filterOpen = false;
			else collapse();
		};
		const t = setTimeout(() => document.addEventListener('mousedown', onDown), 0);
		return () => {
			clearTimeout(t);
			document.removeEventListener('mousedown', onDown);
		};
	});

	const panelTall = $derived(expanded && model.hasResults);
</script>

{#if enabled}
	<div
		class="w-full {expanded
			? 'fixed inset-0 z-50 flex flex-col rounded-none border-0 bg-popover md:absolute md:inset-auto md:start-0 md:top-0 md:w-[min(400px,calc(100vw-7rem))] md:rounded-2xl md:border md:border-border md:shadow-xl ' +
				(panelTall ? 'md:h-[calc(100dvh-2rem)]' : 'md:max-h-[80vh]')
			: 'relative md:w-[240px]'}"
		role="search"
		bind:this={wrapperEl}
	>
		<!-- header chrome: input · controls (count/sort/filter) · applied tokens -->
		<div class={expanded ? 'shrink-0 border-b border-border' : ''}>
			<div
				class={expanded
					? 'flex h-[46px] items-center gap-2 px-3'
					: 'flex items-center gap-2 rounded-full border border-border bg-popover/90 px-3 py-2 shadow-lg backdrop-blur-md focus-within:ring-2 focus-within:ring-ring/40'}
			>
				<SearchIcon class="size-4 shrink-0 text-muted-foreground" />
				<input
					bind:this={inputEl}
					value={model.query}
					oninput={(e) => model.setQuery(e.currentTarget.value)}
					onfocus={() => (expanded = true)}
					onkeydown={onInputKeyDown}
					type="text"
					class="min-w-0 flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
					placeholder={m.search_placeholder()}
					autocomplete="off"
					spellcheck="false"
				/>
				{#if model.query}
					<button
						type="button"
						class="rounded-full p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
						onclick={() => {
							model.setQuery('');
							inputEl?.focus();
						}}
						aria-label={m.search_clear()}
					>
						<XIcon class="size-4" />
					</button>
				{/if}
				{#if expanded}
					<button
						type="button"
						class="rounded-full p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
						onclick={collapse}
						aria-label={m.search_minimize()}
						title={m.search_minimize()}
					>
						<ChevronUpIcon class="size-4" />
					</button>
				{/if}
			</div>

			{#if expanded}
				<!-- count · sort · filter — kept directly under the fixed-height input
				     (token chips moved below) so the Filter popover opens at a constant
				     height no matter how many token rows pile up -->
				<div class="flex items-center gap-2 px-3 pt-2 pb-2">
					<span class="min-w-0 flex-1 truncate text-xs tabular-nums text-muted-foreground">
						{#if model.hasResults}
							<span class="font-medium text-foreground"
								>{compact(model.result.estimatedTotalHits)}</span
							>
							{m.search_results_label()}
						{:else}
							{m.search_catalog_count({ count: catalogTotal.toLocaleString(getLocale()) })}
						{/if}
					</span>
					{#if model.hasResults}
						<SortMenu {model} />
					{/if}
					<div class="relative shrink-0" bind:this={filterWrapEl}>
						<button
							type="button"
							class="inline-flex h-[30px] items-center gap-1.5 rounded-lg border px-2.5 text-xs whitespace-nowrap text-foreground transition-colors hover:bg-accent {model.activeCount ||
							filterOpen
								? 'border-foreground bg-accent'
								: 'border-border'}"
							onclick={() => (filterOpen = !filterOpen)}
						>
							<SlidersIcon class="size-3.5" />
							{m.search_filter()}
							{#if model.activeCount > 0}
								<span
									class="grid h-[17px] min-w-[17px] place-items-center rounded-full bg-foreground px-1 text-[10px] tabular-nums text-background"
									>{model.activeCount}</span
								>
							{/if}
						</button>
						{#if filterOpen}
							<FilterDrill {model} {categories} />
						{/if}
					</div>
				</div>

				{#if tokens.length > 0}
					<div class="flex flex-wrap gap-1.5 px-3 pb-2.5">
						{#each tokens as t (t.key + (t.value ?? ''))}
							<span
								class="inline-flex h-[26px] items-center gap-1.5 rounded-full border border-primary/30 bg-primary/10 ps-2.5 pe-1.5 text-xs whitespace-nowrap text-foreground"
							>
								{t.label}
								<button
									type="button"
									class="grid size-[17px] place-items-center rounded-full bg-foreground/10 hover:bg-foreground/20"
									aria-label={m.search_clear()}
									onclick={() => model.removeToken(t)}
								>
									<XIcon class="size-2.5" />
								</button>
							</span>
						{/each}
						<button
							type="button"
							class="h-[26px] px-2 text-xs text-muted-foreground hover:text-foreground"
							onclick={() => model.clearFilters()}>{m.search_clear()}</button
						>
					</div>
				{/if}
			{/if}
		</div>

		<!-- results -->
		{#if expanded && model.hasResults}
			<SearchResults {model} name={rowName} secondary={secondaryText} onselect={pick} />
		{/if}
	</div>
{/if}
