<script lang="ts">
	import type { ChildGroupEntry } from '$lib/fetch/groups/details';
	import { fetchGroupDetail } from '$lib/fetch/groups/details';
	import {
		categoryLabel,
		CATEGORY_SLUG_PREFIX,
		CAT_STRUCTURE_ACTIVITY,
		CAT_VOLCANISM
	} from '$lib/fetch/groups/registry';
	import { classNameFromSlug, orbitClassLabel } from '$lib/charts/orbit-zones';
	import { BODY_COLORS, DEFAULT_BODY_COLOR } from '$lib/constants';
	import { formatCompactNumber } from '$lib/format/quantities';
	import * as m from '$lib/paraglide/messages.js';
	import BodyCutaway from '../../charts/BodyCutaway.svelte';
	import GroupTile from './GroupTile.svelte';

	interface Props {
		childGroups: ChildGroupEntry[];
	}
	let { childGroups }: Props = $props();

	/**
	 * Two worlds cut open behind Structure & Activity — the one tile here whose
	 * subject is what a body is made of rather than which bodies there are, and
	 * no photograph says that. No accented shell: the meta node is about the
	 * whole stack rather than any one layer of it.
	 *
	 * Mars and Enceladus because between them they are the node: Mars is the
	 * rock stack, crust down through a magma layer to an inner core, and
	 * Enceladus is the other kind of world entirely — an ice shell over an ocean
	 * over a core, and the one still visibly venting its heat.
	 *
	 * Read off `cat-volcanism`, the one child carrying both. Costs no extra
	 * network: there is one global group bucket, so this is the bundle the page
	 * has already fetched, and `fetchGroupDetail` memoizes by URL.
	 */
	const STRUCTURE_TILE_BODIES = ['naif-499', 'naif-602'];

	let structureBodies = $derived.by(async () => {
		const detail = await fetchGroupDetail(CAT_VOLCANISM);
		const members = detail.global?.notable_members ?? [];
		return STRUCTURE_TILE_BODIES.flatMap((id) => {
			const member = members.find((e) => e.id === id);
			return member?.cutaway?.length ? [member] : [];
		});
	});

	// Category / orbit-class names come from i18n keys (the export name is
	// English-only there); other groups keep the export name. Mirrors ChildGroups.
	function childName(c: ChildGroupEntry): string {
		const slug = c.primary_id ?? '';
		if (slug.startsWith(CATEGORY_SLUG_PREFIX)) return categoryLabel(slug);
		const className = classNameFromSlug(slug);
		return className != null ? orbitClassLabel(className) : c.name;
	}

	let tiles = $derived(childGroups.filter((c) => c.primary_id));
</script>

{#snippet structureDrawings()}
	{#await structureBodies then bodies}
		{#if bodies.length > 0}
			<!-- Kept to the right: the name sits bottom-left over the same tile. -->
			<div class="flex size-full items-center justify-end gap-1.5 bg-[#05070e] pe-3">
				{#each bodies as body (body.id)}
					<BodyCutaway
						layers={body.cutaway ?? []}
						color={(body.id ? BODY_COLORS[body.id] : undefined) ?? body.color ?? DEFAULT_BODY_COLOR}
						id="tile-structure-activity-{body.id}"
						class="size-12 shrink-0"
					/>
				{/each}
			</div>
		{/if}
	{/await}
{/snippet}

{#if tiles.length > 0}
	<div class="grid grid-cols-2 gap-2">
		{#each tiles as c, i (c.primary_id)}
			{@const slug = c.primary_id ?? ''}
			<GroupTile
				{slug}
				name={childName(c)}
				label="{formatCompactNumber(c.n)} {m.group_stat_members()}"
				background={slug === CAT_STRUCTURE_ACTIVITY ? structureDrawings : undefined}
				class={i === tiles.length - 1 && tiles.length % 2 === 1 ? 'col-span-2' : ''}
			/>
		{/each}
	</div>
{/if}
