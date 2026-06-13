<script lang="ts">
	import { getContext, untrack } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import LoaderIcon from '@lucide/svelte/icons/loader-circle';
	import type { NotableMemberEntry } from '$lib/fetch/groups/details';
	import { pickedThumbnailUrl, type PickedThumbnail } from '$lib/fetch/objects/images';
	import {
		isSearchEnabled,
		localizedName,
		searchChildMembers,
		searchGroupMembers,
		type GroupMemberPage,
		type ObjectHit
	} from '$lib/search/client';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import { applyFocus, serializeUrl, urlTypeFromId } from '$lib/state/url';
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

	const PAGE_SIZE = 30;
	// Meili caps results at maxTotalHits (1000); never page past it.
	const HARD_CAP = 1000;

	interface Row {
		id: string;
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
			.filter((e) => e.id)
			.map((e) => ({
				id: e.id!,
				name: localizedNames?.[e.id!] ?? e.name,
				thumbnail: e.thumbnail,
				diameter_km: e.diameter_km,
				year: yearOf(e.first_obs)
			}));
	}

	function hitRow(hit: ObjectHit, locale: string): Row {
		return {
			id: hit.id,
			name: localizedNames?.[hit.id] ?? localizedName(hit, locale),
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
			if (isSearchEnabled()) void loadFirst(key);
		});
	});

	async function loadFirst(key: string) {
		const src = untrack(() => source);
		loading = true;
		const locale = getLocale();
		let page: GroupMemberPage;
		try {
			page = await fetchPage(src, 0, PAGE_SIZE, locale);
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
		}
		loading = false;
	}

	let hasMore = $derived(searchBacked && rows.length < Math.min(total, HARD_CAP));

	function rowHref(row: Row): string | undefined {
		if (!appState) return undefined;
		return serializeUrl(
			applyFocus(appState.view, { type: urlTypeFromId(row.id), id: row.id, name: row.name })
		);
	}

	function focusRow(e: MouseEvent, row: Row) {
		if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
		if (!focusObject) return;
		e.preventDefault();
		focusObject(row.id, row.name, { moveCamera: true });
	}
</script>

<div class="flex flex-col gap-1">
	<ul class="flex flex-col">
		{#each rows as row (row.id)}
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
		<button
			type="button"
			onclick={loadMore}
			disabled={loading}
			class="pointer-events-auto text-muted-foreground hover:text-foreground mt-1 inline-flex items-center justify-center gap-1.5 rounded-md py-2 text-xs disabled:opacity-60"
		>
			{#if loading}
				<LoaderIcon class="size-3 animate-spin" />
			{/if}
			{m.members_load_more()}
		</button>
	{/if}
</div>
