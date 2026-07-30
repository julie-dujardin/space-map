<script lang="ts">
	/** The Surface Features page's 57 type chips, grouped into the eight
	 *  landform families the export curates (see constants/nomenclature/
	 *  families.py). Family rows don't link anywhere — there are no family
	 *  pages yet; the chips are the navigation. */

	import * as m from '$lib/paraglide/messages.js';
	import type { ChildGroupEntry, FeatureFamily } from '$lib/fetch/groups/details';
	import { formatCompactNumber } from '$lib/format/quantities';
	import { groupTypeLabelPlural } from '$lib/format/group';
	import ZoneChip from './kit/ZoneChip.svelte';

	interface Props {
		families: FeatureFamily[];
		/** Localized type chips, keyed on by slug for names + counts. */
		childGroups: ChildGroupEntry[];
	}
	let { families, childGroups }: Props = $props();

	/** Chips shown per family before the overflow toggle. Enough for the shape
	 *  of a family at a glance; the rest are one click away. */
	const COLLAPSED = 3;

	// Warm for endogenic/impact, cool for the water/wind/ice terms, neutral for
	// terrain, violet for the human-named odd one out — the ramp groups the groups.
	const FAMILY_DOT: Record<string, string> = {
		impact: 'bg-amber-400',
		volcanic: 'bg-orange-500',
		tectonic: 'bg-rose-500',
		erosional: 'bg-sky-400',
		liquid: 'bg-blue-500',
		relief: 'bg-stone-400',
		albedo: 'bg-zinc-300',
		human: 'bg-violet-400'
	};

	const FAMILY_NAME: Record<string, () => string> = {
		impact: m.feature_family_impact,
		volcanic: m.feature_family_volcanic,
		tectonic: m.feature_family_tectonic,
		erosional: m.feature_family_erosional,
		liquid: m.feature_family_liquid,
		relief: m.feature_family_relief,
		albedo: m.feature_family_albedo,
		human: m.feature_family_human
	};

	let bySlug = $derived(new Map(childGroups.map((c) => [c.primary_id ?? '', c])));
	// Drop types the localized bundle has no chip for, so a family can't render
	// a nameless gap; a family emptied that way disappears with them.
	let rows = $derived(
		families
			.map((f) => ({ ...f, chips: f.types.map((s) => bySlug.get(s)).filter((c) => c != null) }))
			.filter((f) => f.chips.length > 0)
	);
	let expanded = $state(new Set<string>());
	function toggle(key: string) {
		// Reassign — a mutated Set isn't a new value, so `$derived` wouldn't fire.
		const next = new Set(expanded);
		if (!next.delete(key)) next.add(key);
		expanded = next;
	}
</script>

{#if rows.length > 0}
	<div class="flex flex-col gap-1">
		<h3 class="text-sm font-medium">{groupTypeLabelPlural('feature_type')}</h3>
		<div class="border-border/60 border-t"></div>
		<div class="flex flex-col gap-2.5 pt-1.5">
			{#each rows as family (family.key)}
				{@const open = expanded.has(family.key)}
				{@const hidden = family.chips.length - COLLAPSED}
				{@const chips = open ? family.chips : family.chips.slice(0, COLLAPSED)}
				<div class="flex flex-col gap-1.5">
					<div class="flex items-baseline gap-1.5">
						<span
							class="inline-block size-1.5 rounded-full {FAMILY_DOT[family.key] ?? 'bg-zinc-400'}"
						></span>
						<h4 class="text-xs font-medium">
							{FAMILY_NAME[family.key]?.() ?? family.key}
						</h4>
						<span class="text-muted-foreground text-[10px] tabular-nums">
							{formatCompactNumber(family.n)}
						</span>
					</div>
					<div class="flex flex-wrap gap-1.5">
						{#each chips as c (c.primary_id)}
							<ZoneChip slug={c.primary_id ?? ''} name={c.name} n={c.n} />
						{/each}
						{#if hidden > 0}
							<button
								type="button"
								onclick={() => toggle(family.key)}
								aria-expanded={open}
								class="border-border/60 hover:bg-muted/60 text-muted-foreground pointer-events-auto rounded-md border px-2 py-1 text-xs transition-colors"
							>
								{open ? m.group_family_collapse() : `+${hidden}`}
							</button>
						{/if}
					</div>
				</div>
			{/each}
		</div>
	</div>
{/if}
