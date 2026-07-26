<script lang="ts">
	/** Feature-type chips over the Surface tab's list. A flat list, ordered by
	 *  how much of this body each type covers — the landform families the
	 *  Surface Features page groups by don't help when you're already looking at
	 *  one body's own handful of types. */

	import { untrack } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import { bodyFeatureTypeCounts } from '$lib/search/client';
	import { featureTypeSlug } from '$lib/fetch/groups/registry';
	import { featureTypeLabel } from '$lib/format/feature-type';
	import { formatCompactNumber } from '$lib/format/quantities';

	interface Props {
		bodyId: string;
		/** Counts follow the quadrangle selection, so a chip's tally always
		 *  matches what clicking it yields. */
		quad: string | null;
		selected: string | null;
		onselect: (code: string | null) => void;
	}
	let { bodyId, quad, selected, onselect }: Props = $props();

	/** Chips shown before the overflow toggle — Mars carries 29 types, most
	 *  bodies three. */
	const COLLAPSED = 8;

	let counts = $state<Record<string, number>>({});
	$effect(() => {
		const id = bodyId;
		const q = quad;
		let live = true;
		untrack(() => bodyFeatureTypeCounts(id, q ?? undefined)).then((c) => {
			if (live) counts = c;
		});
		return () => {
			live = false;
		};
	});

	// Type names live on each type's `ft-` slug, so codes resolve through the
	// group index (fetched once, cached).
	let slugByCode = $state<Record<string, string>>({});
	$effect(() => {
		const codes = Object.keys(counts);
		if (!codes.length) return;
		untrack(() =>
			Promise.all(codes.map((code) => featureTypeSlug(code).then((slug) => [code, slug] as const)))
		).then((pairs) => {
			slugByCode = Object.fromEntries(pairs.filter(([, slug]) => slug)) as Record<string, string>;
		});
	});

	let types = $derived.by(() => {
		void getLocale();
		return Object.entries(counts)
			.map(([code, n]) => ({ code, n, label: featureTypeLabel(slugByCode[code]) ?? code }))
			.sort((a, b) => b.n - a.n || a.label.localeCompare(b.label));
	});

	let expanded = $state(false);
	// A selected type must stay visible even when it sits in the tail.
	let visible = $derived.by(() => {
		if (expanded || types.length <= COLLAPSED) return types;
		const head = types.slice(0, COLLAPSED);
		const sel = types.find((t) => t.code === selected);
		return sel && !head.includes(sel) ? [...head, sel] : head;
	});
	let hidden = $derived(types.length - visible.length);

	const CHIP =
		'pointer-events-auto rounded-md border px-2 py-1 text-xs transition-colors whitespace-nowrap';
</script>

{#if types.length > 1}
	<div class="flex flex-wrap gap-1.5">
		<button
			type="button"
			aria-pressed={selected === null}
			onclick={() => onselect(null)}
			class="{CHIP} {selected === null
				? 'border-foreground bg-accent'
				: 'border-border/60 hover:bg-muted/60 text-muted-foreground'}"
		>
			{m.search_filter_all()}
		</button>
		{#each visible as t (t.code)}
			<button
				type="button"
				aria-pressed={selected === t.code}
				onclick={() => onselect(selected === t.code ? null : t.code)}
				class="{CHIP} {selected === t.code
					? 'border-foreground bg-accent'
					: 'border-border/60 hover:bg-muted/60 text-muted-foreground'}"
			>
				{t.label}
				<span class="tabular-nums opacity-60">{formatCompactNumber(t.n)}</span>
			</button>
		{/each}
		{#if hidden > 0 || expanded}
			<button
				type="button"
				aria-expanded={expanded}
				onclick={() => (expanded = !expanded)}
				class="{CHIP} border-border/60 hover:bg-muted/60 text-muted-foreground"
			>
				{expanded ? m.group_family_collapse() : `+${hidden}`}
			</button>
		{/if}
	</div>
{/if}
