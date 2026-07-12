<script lang="ts">
	import { getContext } from 'svelte';
	import { page } from '$app/state';
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
		MAX_TOTAL_HITS,
		type SearchHit,
		type GroupHit,
		type FacetDistribution,
		type RangeFacet,
		type RangeBound,
		hasBound
	} from '$lib/search/client';
	import { capitalize, optionDomId } from '$lib/search/format';
	import { formatCompactNumber } from '$lib/format/quantities';
	import { announce } from '$lib/a11y/announcer.svelte';
	import { rangeDef } from '$lib/search/ranges';
	import { SearchModel, type FilterToken } from '$lib/search/model.svelte';
	import { parseSearchSuffix } from '$lib/search/url';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FilterNode, FilterLeaf } from '$lib/search/tree';
	import { groupTypeLabelPlural } from '$lib/format/group';
	import { ltrIsolate } from '$lib/format/bidi';
	import { classNameFromSlug, orbitClassLabel } from '$lib/charts/orbit-zones';
	import { categoryLabel, CATEGORY_SLUG_PREFIX } from '$lib/fetch/groups/registry';
	import {
		smallBodyCategory,
		CAT_PROBES,
		CAT_SATELLITES,
		type GroupType
	} from '$lib/fetch/groups/registry';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import { Skeleton } from '$lib/components/ui/skeleton/index.js';
	import SortMenu from './SortMenu.svelte';
	import FilterDrill from './FilterDrill.svelte';
	import SearchResults from './SearchResults.svelte';

	type Props = {
		onSelect: (hit: SearchHit) => void;
		onExpandedChange?: (expanded: boolean) => void;
	};

	let { onSelect, onExpandedChange }: Props = $props();

	const ctx = getContext<ContextManager>('ctx');
	const appState = getContext<AppState>('appState');
	const enabled = isSearchEnabled();

	const model = new SearchModel();
	// Hydrate from a shared link / reload: restore query+filters and open the
	// panel so the results are visible. Ephemeral after this — popstate doesn't
	// restore it; only a fresh load does.
	const hydrated = enabled ? parseSearchSuffix(page.url.searchParams) : null;
	if (hydrated) model.applyUrlState(hydrated);
	let expanded = $state(hydrated !== null);
	// Let the parent raise the search panel above the detail drawer while it's
	// open, and drop it back under the drawer once collapsed.
	$effect(() => onExpandedChange?.(expanded));

	// Mirror the live search into the URL while the panel is open with something
	// active; clear it once collapsed/picked. AppState writes via replaceState and
	// dedups, so firing on every keystroke is cheap.
	$effect(() => {
		if (!enabled) return;
		const active = expanded && model.hasResults;
		appState.setSearch(
			active
				? {
						query: model.query,
						filters: model.filters,
						sort: model.sort,
						reverse: model.reverse,
						page: model.page
					}
				: null
		);
	});
	let filterOpen = $state(false);
	// Drill node to open onto when editing a chip; undefined = root level.
	let filterOpenTo = $state<string | undefined>(undefined);

	// Edit a clicked chip: range chips jump to the sliders, the rest to root.
	function editToken(t: FilterToken) {
		filterOpenTo = t.key === 'ranges' ? 'ranges' : undefined;
		filterOpen = true;
	}
	let groupCatalog = $state<GroupHit[]>([]);
	// undefined while the first stats call is in flight, then the count, or null
	// if the catalog index is unreachable (env unset or server down) — null drives
	// the "catalog unavailable" hint instead of a misleading "0 entries".
	let catalogTotal = $state<number | null | undefined>(undefined);
	let facetUniverse = $state<FacetDistribution>({});
	let inputEl: HTMLInputElement | undefined = $state();

	const groupBySlug = $derived(new Map(groupCatalog.map((g) => [g.slug, g])));

	// Group/collection taxonomy for the filter tree + token labels (one fetch).
	$effect(() => {
		if (enabled) fetchGroupCatalog(getLocale()).then((g) => (groupCatalog = g));
	});

	// Catalog size for the idle hint. catalogCount() doesn't cache failures, so a
	// re-call after a null (see onfocus) re-hits the server.
	function loadCatalogCount() {
		if (enabled) catalogCount().then((n) => (catalogTotal = n));
	}
	$effect(loadCatalogCount);

	// Full facet vocabulary (locale-agnostic codes) so bounded facets can list
	// every value even once a query/filter narrows the live distribution.
	$effect(() => {
		if (enabled) catalogFacets().then((d) => (facetUniverse = d));
	});

	// Debounced reset on query/filter/sort change; `page` is not a dep, so
	// scrolling updates the anchor without retriggering a reset.
	let debounceTimer: ReturnType<typeof setTimeout> | undefined;
	$effect(() => {
		const snap = {
			query: model.query,
			filters: model.filters,
			sort: model.sort,
			reverse: model.reverse,
			locale: getLocale()
		};
		clearTimeout(debounceTimer);
		debounceTimer = setTimeout(() => model.runSearch(snap), 150);
		return () => clearTimeout(debounceTimer);
	});

	// Announce the settled result count / "no results" to screen readers (WCAG
	// 4.1.3). Polite channel, and skipped mid-load, so it speaks the final tally
	// once typing pauses rather than every intermediate value. The error case is
	// left to the results panel's role="alert" to avoid a double announcement.
	$effect(() => {
		if (!expanded || model.loading || model.error || !model.hasResults) return;
		announce(
			model.total === 0
				? m.search_no_results()
				: m.search_results_announce({ count: formatCompactNumber(model.total) })
		);
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
	// Plural category labels for the filter tree (standalone headers, e.g.
	// "Asteroids", "Launch sites"). The numeric count sits in its own column, so
	// these are invariant plurals — separate keys, since `type_*`/`group_type_*`
	// are singular for inline/sentence use. Fall back to the singular if missing.
	function typeLabelPlural(type: string): string {
		return messages[`search_cat_${type}`]?.() ?? typeLabel(type);
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
	// Localized group name for filter leaves, tokens and rows. Categories use
	// `category_name_*`, orbit classes `orbit_class_*` (then the index name, then
	// the bare code); other kinds use `group_name_<slug>`, else the exported name.
	function groupName(g: GroupHit, locale: string): string {
		if (g.slug.startsWith(CATEGORY_SLUG_PREFIX)) return categoryLabel(g.slug);
		const className = classNameFromSlug(g.slug);
		if (className != null) {
			const label = orbitClassLabel(className);
			if (label !== className) return label;
			const idx = localizedName(g, locale);
			return idx && idx !== g.slug ? idx : className;
		}
		const fn = messages[`group_name_${g.slug}`];
		if (fn) return fn();
		return localizedName(g, locale);
	}
	function rowName(hit: SearchHit): string {
		if (hit.kind === 'group') return groupName(hit, getLocale());
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

	// ── filter tree (type-first) ───────────────────────────────────────
	// Root nodes are object types (+ surface features, collections); drilling into
	// a type reveals the sub-filters relevant to it (orbit class, org, …) plus an
	// "All" toggle and the small-body flags. Selections stay flat: same facet ORs,
	// different facets AND — the tree only organizes which filters appear where.
	const ASTEROID_TYPES = [
		'asteroid',
		'asteroid_inner',
		'asteroid_main_belt',
		'asteroid_trojan',
		'asteroid_tno',
		'asteroid_centaur'
	];
	const SPACECRAFT_GROUP_TYPES: GroupType[] = [
		'organization',
		'constellation',
		'bus',
		'launch_site',
		'country',
		'earth_orbit_class'
	];

	const tree = $derived.by((): FilterNode => {
		// Live distribution once narrowing, else the whole-catalog universe so every
		// node lists its full value set with idle counts.
		const small = model.hasResults ? model.facets : facetUniverse;
		const locale = getLocale();
		const typeDist = small['object.type'] ?? {};
		const groupDist = small['object.groups'] ?? {};
		const featDist = small['feature.type'] ?? {};
		const gtypeDist = small['group.type'] ?? {};
		const kindDist = small['kind'] ?? {};
		const neoCount = small['object.neo']?.['true'] ?? 0;
		const phaCount = small['object.pha']?.['true'] ?? 0;
		const selGroups = new Set(model.filters.groups ?? []);

		const sumType = (keys: string[]) => keys.reduce((n, k) => n + (typeDist[k] ?? 0), 0);
		const allLeaf = (id: string, values: string[], count: number): FilterLeaf => ({
			id,
			kind: 'array',
			facet: 'type',
			values,
			label: m.search_filter_all(),
			count
		});
		const flagLeaves = (idp: string): FilterLeaf[] => [
			{ id: `${idp}-neo`, kind: 'bool', facet: 'neo', label: m.search_prop_neo(), count: neoCount },
			{ id: `${idp}-pha`, kind: 'bool', facet: 'pha', label: m.search_prop_pha(), count: phaCount }
		];
		// Group memberships → leaves (drop 0-count unless currently selected).
		const groupLeaves = (idp: string, gs: GroupHit[]): FilterLeaf[] =>
			gs
				.map((g) => ({ slug: g.slug, label: groupName(g, locale), count: groupDist[g.slug] ?? 0 }))
				.filter((l) => l.count > 0 || selGroups.has(l.slug))
				.sort((a, b) => b.count - a.count)
				.slice(0, 80)
				.map((l) => ({
					id: `${idp}-${l.slug}`,
					kind: 'array',
					facet: 'groups',
					values: [l.slug],
					label: l.label,
					count: l.count
				}));

		const byType = new Map<string, GroupHit[]>();
		for (const g of groupCatalog) {
			const list = byType.get(g.type);
			if (list) list.push(g);
			else byType.set(g.type, [g]);
		}
		const orbit = byType.get('orbit_class') ?? [];
		const cometClass = (g: GroupHit) =>
			smallBodyCategory(classNameFromSlug(g.slug) ?? '') === 'comet';
		// A drillable sub-category from one group type (null when it has no leaves).
		const groupTypeNode = (id: string, type: GroupType): FilterNode | null => {
			const lv = groupLeaves(id, byType.get(type) ?? []);
			return lv.length ? { id, label: groupTypeLabelPlural(type), leaves: lv } : null;
		};

		const children: FilterNode[] = [];

		// Numeric range sliders — one drill node, applied across all kinds.
		children.push({
			id: 'ranges',
			label: m.search_facet_properties(),
			ranges: ['diameter', 'magnitude', 'inception']
		});

		// Types with no sub-filters — a plain checkbox right at the root level.
		const rootLeaves: FilterLeaf[] = (['planet', 'dwarf_planet', 'moon'] as const).map((type) => ({
			id: `root-${type}`,
			kind: 'array',
			facet: 'type',
			values: [type],
			label: typeLabelPlural(type),
			count: sumType([type])
		}));

		// Asteroids — All / NEO / PHA + SBDB orbit class (asteroid subset).
		{
			const cnt = sumType(ASTEROID_TYPES);
			const cls = groupLeaves(
				'ast-class',
				orbit.filter((g) => !cometClass(g))
			);
			const sub = cls.length
				? [{ id: 'ast-class', label: groupTypeLabelPlural('orbit_class'), leaves: cls }]
				: [];
			children.push({
				id: 'asteroid',
				label: typeLabelPlural('asteroid'),
				count: cnt,
				leaves: [allLeaf('ast-all', ASTEROID_TYPES, cnt), ...flagLeaves('ast')],
				children: sub
			});
		}

		// Comets — All / NEO / PHA + orbit class (comet subset) + fragments.
		{
			const cnt = sumType(['comet']);
			const cls = groupLeaves('com-class', orbit.filter(cometClass));
			const sub: FilterNode[] = [];
			if (cls.length)
				sub.push({
					id: 'com-class',
					label: groupTypeLabelPlural('orbit_class'),
					leaves: cls
				});
			const frag = groupTypeNode('com-frag', 'split_comet');
			if (frag) sub.push(frag);
			children.push({
				id: 'comet',
				label: typeLabelPlural('comet'),
				count: cnt,
				leaves: [allLeaf('com-all', ['comet'], cnt), ...flagLeaves('com')],
				children: sub
			});
		}

		// Spacecraft — All / Probes / Earth satellites / Debris + org/constellation/…
		// Probes & Earth satellites filter on category membership (object.groups =
		// cat-probes / cat-satellites); those counts populate once the export tags
		// objects with their category — until then the leaves read 0.
		{
			const cnt = sumType(['spacecraft']);
			const leaves: FilterLeaf[] = [allLeaf('sc-all', ['spacecraft'], cnt)];
			const cats = byType.get('category') ?? [];
			for (const [id, slug] of [
				['sc-probes', CAT_PROBES],
				['sc-sats', CAT_SATELLITES]
			] as const) {
				const g = cats.find((c) => c.slug === slug);
				if (g)
					leaves.push({
						id,
						kind: 'array',
						facet: 'groups',
						values: [slug],
						label: groupName(g, locale),
						count: groupDist[slug] ?? 0
					});
			}
			const debris = sumType(['debris']);
			if (debris > 0 || (model.filters.type ?? []).includes('debris'))
				leaves.push({
					id: 'sc-debris',
					kind: 'array',
					facet: 'type',
					values: ['debris'],
					label: m.type_earth_debris(),
					count: debris
				});
			const sub = SPACECRAFT_GROUP_TYPES.map((t) => groupTypeNode(`sc-${t}`, t)).filter(
				(n): n is FilterNode => n != null
			);
			children.push({
				id: 'spacecraft',
				label: typeLabelPlural('spacecraft'),
				count: cnt,
				leaves,
				children: sub
			});
		}

		// Surface features — All + the feature types directly (type is the only filter).
		{
			const cnt = kindDist['feature'] ?? 0;
			const fl = Object.keys(featDist)
				.map((code) => ({ code, label: featureTypeLabel(code), count: featDist[code] ?? 0 }))
				.filter((l) => l.count > 0 || (model.filters.featureType ?? []).includes(l.code))
				.sort((a, b) => b.count - a.count)
				.slice(0, 80)
				.map(
					(l): FilterLeaf => ({
						id: `feat-${l.code}`,
						kind: 'array',
						facet: 'featureType',
						values: [l.code],
						label: l.label,
						count: l.count
					})
				);
			children.push({
				id: 'feature',
				label: m.search_kind_feature(),
				count: cnt,
				leaves: [
					{
						id: 'feat-all',
						kind: 'array',
						facet: 'kind',
						values: ['feature'],
						label: m.search_filter_all(),
						count: cnt
					},
					...fl
				]
			});
		}

		// Collections — All + the collection types directly (type is the only filter).
		{
			const cnt = kindDist['group'] ?? 0;
			const gl = Object.keys(gtypeDist)
				.map((t) => ({ t, label: groupTypeLabelPlural(t as GroupType), count: gtypeDist[t] ?? 0 }))
				.filter((l) => l.count > 0 || (model.filters.groupType ?? []).includes(l.t))
				.sort((a, b) => b.count - a.count)
				.map(
					(l): FilterLeaf => ({
						id: `coll-${l.t}`,
						kind: 'array',
						facet: 'groupType',
						values: [l.t],
						label: l.label,
						count: l.count
					})
				);
			children.push({
				id: 'group',
				label: m.search_kind_group(),
				count: cnt,
				leaves: [
					{
						id: 'coll-all',
						kind: 'array',
						facet: 'kind',
						values: ['group'],
						label: m.search_filter_all(),
						count: cnt
					},
					...gl
				]
			});
		}

		// Other long-tail types (star, barycenter) — kept reachable, hidden at 0.
		{
			const others = (['star', 'barycenter'] as const).filter(
				(t) => (typeDist[t] ?? 0) > 0 || (model.filters.type ?? []).includes(t)
			);
			if (others.length)
				children.push({
					id: 'other',
					label: m.search_facet_other(),
					leaves: others.map((t) => ({
						id: `other-${t}`,
						kind: 'array',
						facet: 'type',
						values: [t],
						label: typeLabelPlural(t),
						count: typeDist[t] ?? 0
					}))
				});
		}

		return { id: 'root', label: '', leaves: rootLeaves, children };
	});

	// Applied-range chip label, e.g. "Size: 10–100 km", "Date: ≥ 1990".
	function rangeTokenLabel(facet: RangeFacet, b: RangeBound, locale: string): string {
		const def = rangeDef(facet);
		const dim = messages[def.labelKey]?.() ?? facet;
		const unit = def.unit === 'km' ? ` ${m.unit_symbol_kilometre()}` : '';
		// Years render ungrouped (no "1,990"); sizes compact; magnitudes as-is.
		const fmt = (v: number) =>
			def.unit === 'km'
				? formatCompactNumber(v)
				: v.toLocaleString(locale, { useGrouping: def.unit !== 'year' });
		const val =
			b.min != null && b.max != null
				? `${fmt(b.min)}–${fmt(b.max)}`
				: b.min != null
					? `≥ ${fmt(b.min)}`
					: `≤ ${fmt(b.max as number)}`;
		// Isolate the value as an LTR run so the ≥/≤ sign and digits don't
		// bidi-mirror/reorder inside an RTL chip.
		return `${dim}: ${ltrIsolate(`${val}${unit}`)}`;
	}

	const tokens = $derived.by((): FilterToken[] => {
		const locale = getLocale();
		const out: FilterToken[] = [];
		for (const v of model.filters.kind ?? [])
			out.push({ key: 'kind', value: v, label: kindLabel(v) });
		for (const v of model.filters.type ?? [])
			out.push({ key: 'type', value: v, label: typeLabelPlural(v) });
		for (const slug of model.filters.groups ?? []) {
			const g = groupBySlug.get(slug);
			out.push({ key: 'groups', value: slug, label: g ? groupName(g, locale) : slug });
		}
		for (const code of model.filters.featureType ?? [])
			out.push({ key: 'featureType', value: code, label: featureTypeLabel(code) });
		for (const t of model.filters.groupType ?? [])
			out.push({ key: 'groupType', value: t, label: groupTypeLabelPlural(t as GroupType) });
		for (const facet of ['diameter', 'magnitude', 'inception'] as RangeFacet[]) {
			const b = model.filters.ranges?.[facet];
			if (hasBound(b))
				out.push({ key: 'ranges', value: facet, label: rangeTokenLabel(facet, b!, locale) });
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
		// Picking collapses the combobox and blurs the input (focus falls to
		// <body>); announce the choice so screen-reader users aren't left in
		// silence while the drawer opens without a focus move.
		announce(m.search_selected_announce({ name: rowName(hit) }));
	}

	// Keyboard highlight, tracked by hit id (not index): a new search or a
	// virtualization window shift just drops the stale id instead of landing the
	// highlight on an unrelated row. Hover writes the same state.
	let highlightedId = $state<string | null>(null);
	const highlightedIndex = $derived(model.hits.findIndex((h) => h.id === highlightedId));
	const activeDescendant = $derived(
		expanded && highlightedIndex >= 0 ? optionDomId(highlightedId!) : undefined
	);

	function moveHighlight(delta: 1 | -1) {
		const hits = model.hits;
		if (hits.length === 0) return;
		const cur = highlightedIndex;
		const next =
			cur === -1
				? delta === 1
					? 0
					: hits.length - 1
				: Math.min(Math.max(cur + delta, 0), hits.length - 1);
		highlightedId = hits[next].id;
		if (next >= hits.length - 3) model.ensureNext();
		document.getElementById(optionDomId(highlightedId))?.scrollIntoView({ block: 'nearest' });
	}

	function collapse() {
		expanded = false;
		filterOpen = false;
	}

	// Close the filter popover on an outside click. focusout can't be used: a
	// drill that swaps its list (root → leaves) unmounts the just-clicked button,
	// dropping focus to <body> and reading as "left the cluster".
	let filterWrapEl: HTMLElement | undefined = $state();
	let filterTriggerEl: HTMLButtonElement | undefined = $state();
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
		if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
			e.preventDefault();
			moveHighlight(e.key === 'ArrowDown' ? 1 : -1);
		} else if (e.key === 'Enter') {
			const hit = highlightedIndex >= 0 ? model.hits[highlightedIndex] : undefined;
			if (hit) {
				e.preventDefault();
				pick(hit);
			}
		} else if (e.key === 'Escape') {
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
			? 'fixed inset-0 z-50 flex flex-col rounded-none border-0 bg-popover pt-[var(--safe-top)] pb-[var(--safe-bottom)] ps-[var(--safe-start)] pe-[var(--safe-end)] md:absolute md:inset-auto md:start-0 md:top-0 md:w-[min(400px,calc(100vw-7rem))] md:rounded-2xl md:border md:border-border md:shadow-xl md:p-0 ' +
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
					onfocus={() => {
						expanded = true;
						// Retry if the index was last seen unavailable.
						if (catalogTotal === null) loadCatalogCount();
					}}
					onkeydown={onInputKeyDown}
					type="text"
					role="combobox"
					aria-expanded={expanded && model.hasResults}
					aria-controls="search-results-listbox"
					aria-autocomplete="list"
					aria-activedescendant={activeDescendant}
					class="min-w-0 flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
					placeholder={m.search_placeholder()}
					aria-label={m.search_placeholder()}
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
						aria-label={m.search_clear_search()}
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
						{#if model.loading && model.hits.length === 0}
							<!-- searching: stand in for the count while the new query's first page loads -->
							<span class="inline-flex items-center gap-1.5 align-middle">
								<Skeleton class="h-3 w-10 rounded" />
								<Skeleton class="h-3 w-16 rounded opacity-70" />
							</span>
						{:else if model.hasResults}
							<span class="font-medium text-foreground"
								>{formatCompactNumber(model.total)}{model.total >= MAX_TOTAL_HITS ? '+' : ''}</span
							>
							{m.search_results_label()}
						{:else if catalogTotal === null}
							{m.search_catalog_unavailable()}
						{:else if catalogTotal !== undefined}
							{m.search_catalog_count({ count: catalogTotal.toLocaleString(getLocale()) })}
						{/if}
					</span>
					{#if model.hasResults}
						<SortMenu {model} />
					{/if}
					<div class="relative shrink-0" bind:this={filterWrapEl}>
						<button
							type="button"
							bind:this={filterTriggerEl}
							aria-haspopup="dialog"
							aria-expanded={filterOpen}
							class="inline-flex h-[30px] items-center gap-1.5 rounded-lg border px-2.5 text-xs whitespace-nowrap text-foreground transition-colors hover:bg-accent {model.activeCount ||
							filterOpen
								? 'border-foreground bg-accent'
								: 'border-border'}"
							onclick={() => {
								filterOpenTo = undefined;
								filterOpen = !filterOpen;
							}}
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
							<FilterDrill
								{model}
								root={tree}
								openTo={filterOpenTo}
								onClose={() => {
									filterOpen = false;
									filterTriggerEl?.focus();
								}}
							/>
						{/if}
					</div>
				</div>

				{#if tokens.length > 0}
					<div class="flex flex-wrap gap-1.5 px-3 pb-2.5">
						{#each tokens as t (t.key + (t.value ?? ''))}
							<span
								class="inline-flex h-[26px] items-center gap-1 rounded-full border border-primary/30 bg-primary/10 pe-1.5 ps-0.5 text-xs whitespace-nowrap text-foreground"
							>
								<button
									type="button"
									class="rounded-full px-2 py-0.5 transition-colors hover:bg-primary/15"
									title={m.search_filter()}
									onclick={() => editToken(t)}
								>
									{capitalize(t.label)}
								</button>
								<button
									type="button"
									class="grid size-[17px] place-items-center rounded-full bg-foreground/10 hover:bg-foreground/20"
									aria-label={m.search_remove_filter({ label: capitalize(t.label) })}
									onclick={() => model.removeToken(t)}
								>
									<XIcon class="size-2.5" />
								</button>
							</span>
						{/each}
						<button
							type="button"
							class="h-[26px] px-2 text-xs text-muted-foreground hover:text-foreground"
							onclick={() => model.clearFilters()}>{m.search_clear_all()}</button
						>
					</div>
				{/if}
			{/if}
		</div>

		<!-- results -->
		{#if expanded && model.hasResults}
			<SearchResults
				{model}
				name={rowName}
				secondary={secondaryText}
				onselect={pick}
				{highlightedId}
				onhighlight={(id) => (highlightedId = id)}
			/>
		{/if}
	</div>
{/if}
