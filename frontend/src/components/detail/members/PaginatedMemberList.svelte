<script lang="ts">
	import { getContext, untrack } from 'svelte';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import { Skeleton } from '$lib/components/ui/skeleton/index.js';
	import { memberEntryKey, type NotableMemberEntry } from '$lib/fetch/objects/object-data';
	import { pickedThumbnailUrl, type PickedThumbnail } from '$lib/fetch/objects/images';
	import {
		isSearchEnabled,
		localizedName,
		searchChildMembers,
		searchGroupMembers,
		type GroupMemberPage,
		type MemberHit
	} from '$lib/search/client';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusFeature, FocusObject } from '$lib/state/focusable';
	import {
		applyFeature,
		applyFocus,
		applyGroup,
		serializeUrl,
		urlTypeFromId
	} from '$lib/state/url';
	import { formatQuantity } from '$lib/format/quantities';

	/** A group's members (by slug) or a body's moons (by host id). */
	type MemberSource = { kind: 'group'; slug: string } | { kind: 'parent'; parentId: string };

	interface Props {
		source: MemberSource;
		totalCount: number;
		localizedNames?: Record<string, string>;
		/** Baked top members shown instantly, before/without the search backend. */
		fallback: NotableMemberEntry[];
	}
	let { source, totalCount, localizedNames, fallback }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');
	const focusFeature = getContext<FocusFeature | undefined>('focusFeature');

	const PAGE_SIZE = 30;
	// Meili caps results at maxTotalHits (1000); never page past it.
	const HARD_CAP = 1000;

	// Varied bar widths so the load-more placeholder reads as rows, not a grid.
	const SKELETON_ROWS = [70, 55, 64];

	interface Row {
		/** Object id (focus a mesh) — or `group` instead for a constellation row.
		 *  On a feature row it holds the host body. */
		id?: string;
		/** Group slug; set → the row routes to /g/<slug> instead of focusing. */
		group?: string;
		/** IAU feature id; set → the row opens that feature on its host body. */
		featureId?: number;
		name: string;
		thumbnail?: PickedThumbnail;
		diameter_km?: number;
		year?: string;
	}

	// Primitive identity of the source, so the load effect tracks only a change
	// of group/body — not the fresh object literal the parent passes each render.
	let sourceKey = $derived(source.kind === 'group' ? `g:${source.slug}` : `p:${source.parentId}`);

	function fetchPage(
		src: MemberSource,
		offset: number,
		limit: number,
		locale: string
	): Promise<GroupMemberPage> {
		return src.kind === 'group'
			? searchGroupMembers(src.slug, offset, limit, locale)
			: searchChildMembers(src.parentId, offset, limit, locale);
	}

	function yearOf(s?: string): string | undefined {
		const y = s?.slice(0, 4);
		return y && Number.isFinite(parseInt(y, 10)) ? y : undefined;
	}

	function fallbackRows(): Row[] {
		return fallback
			.filter((e) => e.id || e.group)
			.map((e) => {
				const key = memberEntryKey(e);
				return {
					id: e.id,
					group: e.group,
					featureId: e.feature_id,
					name: localizedNames?.[key] ?? e.name,
					thumbnail: e.thumbnail,
					diameter_km: e.diameter_km,
					year: yearOf(e.first_obs)
				};
			});
	}

	function hitRow(hit: MemberHit, locale: string): Row {
		const key = hit.id;
		const name = localizedNames?.[key] ?? localizedName(hit, locale);
		// A constellation member routes to its group page; an object focuses its mesh.
		if (hit.kind === 'group') return { group: hit.slug, name, thumbnail: hit.thumbnail };
		// A feature member opens on its host body.
		if (hit.kind === 'feature') {
			return {
				id: hit.body_id,
				featureId: hit.feature_id,
				name,
				thumbnail: hit.thumbnail,
				diameter_km: hit.diameter_km
			};
		}
		return {
			id: hit.id,
			name,
			thumbnail: hit.thumbnail,
			diameter_km: hit.diameter_km,
			year: hit.inception ? String(Math.trunc(hit.inception / 10000)) : undefined
		};
	}

	let rows = $state<Row[]>([]);
	// Refined by estimatedTotalHits once a search page lands; the $effect seeds it.
	let total = $state(0);
	let loading = $state(false);
	let searchBacked = $state(false);

	// (Re)seed from the baked list and pull the first search page on source change.
	// The reset + load run untracked so writes to loading/rows/searchBacked don't
	// re-trigger this effect (which would loop, hammering Meili) — `sourceKey` is
	// the only intended trigger.
	$effect(() => {
		const key = sourceKey;
		const seed = fallbackRows();
		const seedTotal = totalCount;
		untrack(() => {
			rows = seed;
			total = seedTotal;
			searchBacked = false;
			// Restore deep-linked depth (?mp=N); untracked so our setMemberPage
			// writes don't re-trigger this reload.
			const targetPages = Math.max(1, appState?.view.memberPage ?? 1);
			// A fully-baked list (small group exported whole) needs no search backend.
			if (seed.length < seedTotal && isSearchEnabled()) void loadInitial(key, targetPages);
		});
	});

	async function loadInitial(key: string, targetPages: number) {
		const src = untrack(() => source);
		loading = true;
		const locale = getLocale();
		// One request, not N round-trips.
		const limit = Math.min(targetPages * PAGE_SIZE, HARD_CAP);
		let page: GroupMemberPage;
		try {
			page = await fetchPage(src, 0, limit, locale);
		} catch {
			loading = false;
			return;
		}
		// A newer source may have superseded this request; empty page → nothing in
		// the index, so keep the baked fallback.
		if (key === sourceKey && page.hits.length > 0) {
			rows = page.hits.map((h) => hitRow(h, locale));
			total = page.estimatedTotalHits;
			searchBacked = true;
		}
		loading = false;
	}

	async function loadMore() {
		if (loading) return;
		const key = sourceKey;
		const src = source;
		loading = true;
		const locale = getLocale();
		let page: GroupMemberPage;
		try {
			page = await fetchPage(src, rows.length, PAGE_SIZE, locale);
		} catch {
			loading = false;
			return;
		}
		if (key === sourceKey) {
			rows = [...rows, ...page.hits.map((h) => hitRow(h, locale))];
			total = page.estimatedTotalHits;
			// Mirror depth into the URL so a share/reload lands here.
			appState?.setMemberPage(Math.ceil(rows.length / PAGE_SIZE));
		}
		loading = false;
	}

	let hasMore = $derived(searchBacked && rows.length < Math.min(total, HARD_CAP));

	// Auto-load the next page when the bottom sentinel nears the viewport — clipped
	// against whatever scroll container (drawer / ScrollArea) wraps the list. Reading
	// `rows.length` re-observes after each append, so a sentinel that stays in view
	// keeps pulling pages instead of firing only on the first intersection.
	let sentinel = $state<HTMLElement>();
	$effect(() => {
		const el = sentinel;
		if (!el || rows.length === 0) return;
		const io = new IntersectionObserver(
			(entries) => {
				if (entries[0].isIntersecting && hasMore && !loading) loadMore();
			},
			{ rootMargin: '400px' }
		);
		io.observe(el);
		return () => io.disconnect();
	});

	function rowKey(row: Row): string {
		return memberEntryKey({
			name: row.name,
			id: row.id,
			group: row.group,
			feature_id: row.featureId
		});
	}

	function rowHref(row: Row): string | undefined {
		if (!appState) return undefined;
		if (row.group) return serializeUrl(applyGroup(appState.view, row.group, row.name));
		if (!row.id) return undefined;
		if (row.featureId != null) {
			return serializeUrl(
				applyFeature(appState.view, {
					bodyId: row.id,
					featureId: row.featureId,
					featureName: row.name
				})
			);
		}
		return serializeUrl(
			applyFocus(appState.view, { type: urlTypeFromId(row.id), id: row.id, name: row.name })
		);
	}

	function focusRow(e: MouseEvent, row: Row) {
		if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
		// A constellation row opens its group page; an object focuses its mesh.
		if (row.group) {
			if (!appState) return;
			e.preventDefault();
			appState.setGroup(row.group, row.name);
			return;
		}
		// A feature row hands off to the map, which streams in the host body and
		// frames the feature on it.
		if (row.featureId != null && row.id) {
			if (!focusFeature) return;
			e.preventDefault();
			focusFeature(row.id, row.featureId, row.name);
			return;
		}
		if (!focusObject || !row.id) return;
		e.preventDefault();
		focusObject(row.id, row.name, { moveCamera: true });
	}
</script>

<div class="flex flex-col gap-1">
	<ul class="flex flex-col">
		{#each rows as row (rowKey(row))}
			<li>
				<a
					href={rowHref(row)}
					onclick={(e) => focusRow(e, row)}
					class="pointer-events-auto hover:bg-muted/40 -mx-1 flex items-center gap-3 rounded-md px-1 py-2"
				>
					{#if row.thumbnail}
						<img
							src={pickedThumbnailUrl(row.thumbnail)}
							alt=""
							loading="lazy"
							decoding="async"
							class="bg-muted size-10 shrink-0 rounded-md object-cover"
						/>
					{:else}
						<div
							class="bg-muted text-muted-foreground flex size-10 shrink-0 items-center justify-center rounded-md text-sm font-medium"
						>
							{row.name.charAt(0)}
						</div>
					{/if}
					<span class="min-w-0 flex-1 truncate text-sm font-medium">{row.name}</span>
					<span class="flex shrink-0 flex-col items-end text-xs tabular-nums">
						{#if row.diameter_km != null}
							<span>{formatQuantity({ value: row.diameter_km, unit: 'kilometre' }, true)}</span>
						{/if}
						{#if row.year}
							<span class="text-muted-foreground">{row.year}</span>
						{/if}
						{#if row.diameter_km == null && !row.year}
							<span class="text-muted-foreground">–</span>
						{/if}
					</span>
				</a>
			</li>
		{/each}
	</ul>
	{#if hasMore}
		<!-- bottom sentinel: scrolling near it pulls the next page -->
		<div bind:this={sentinel}>
			{#if loading}
				<ul class="flex flex-col" aria-hidden="true">
					{#each SKELETON_ROWS as w, i (i)}
						<li class="flex items-center gap-3 px-1 py-2">
							<Skeleton class="size-10 shrink-0 rounded-md" style="animation-delay: {i * 80}ms" />
							<Skeleton
								class="h-4 min-w-0 flex-1 rounded"
								style="max-width: {w}%; animation-delay: {i * 80}ms"
							/>
							<Skeleton
								class="h-3 w-8 shrink-0 rounded opacity-70"
								style="animation-delay: {i * 80}ms"
							/>
						</li>
					{/each}
				</ul>
			{/if}
		</div>
	{/if}
</div>
