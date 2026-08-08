<script lang="ts">
	/**
	 * The Structure & Activity children, each tiled behind a few of its own
	 * members drawn as the property it collects.
	 *
	 * The same rule the gallery shelves settled on: a tile is backed by what its
	 * destination draws, never by a photograph. A photograph of Ganymede says
	 * nothing about oceans; a cutaway with the ocean lit says the whole page.
	 *
	 * Costs no extra network. There is one global group bucket, so the child's
	 * bundle is the one this page already fetched and `fetchGzipBundle`
	 * memoizes by URL.
	 */
	import type { ChildGroupEntry } from '$lib/fetch/groups/details';
	import { fetchGroupDetail } from '$lib/fetch/groups/details';
	import { categoryLabel } from '$lib/fetch/groups/registry';
	import { BODY_COLORS, DEFAULT_BODY_COLOR } from '$lib/constants';
	import { formatCompactNumber } from '$lib/format/quantities';
	import type { NotableMemberEntry } from '$lib/fetch/objects/object-data';
	import { PROPERTY_ACCENT, type PropertyKind } from '$lib/state/category-config';
	import * as m from '$lib/paraglide/messages.js';
	import AtmosphereBandBar from '../../charts/AtmosphereBandBar.svelte';
	import BodyCutaway from '../../charts/BodyCutaway.svelte';
	import GroupTile from './GroupTile.svelte';

	interface Props {
		childGroups: ChildGroupEntry[];
		/** Which property each child slug collects, for the accented shell. */
		kinds: Record<string, PropertyKind>;
	}
	let { childGroups, kinds }: Props = $props();

	/** How many members fit in the tile's right half before they are grit. */
	const SHOWN = 4;

	let tiles = $derived(childGroups.filter((c) => c.primary_id));

	function members(slug: string): Promise<NotableMemberEntry[]> {
		return fetchGroupDetail(slug).then((detail) =>
			(detail.global?.notable_members ?? [])
				.filter((entry) => entry.id && (entry.cutaway?.length || entry.limb))
				.slice(0, SHOWN)
		);
	}

	function tint(e: NotableMemberEntry): string {
		return (e.id ? BODY_COLORS[e.id] : undefined) ?? e.color ?? DEFAULT_BODY_COLOR;
	}
</script>

{#snippet drawings(slug: string, kind: PropertyKind)}
	{#await members(slug) then shown}
		<!-- The drawings keep to the right half: the name sits bottom-left over
		     the same tile, and a full-width row would be read through it. -->
		<div class="flex size-full items-center bg-[#05070e]">
			<div class="ms-auto flex w-3/5 items-center justify-end gap-1.5 overflow-hidden pe-3">
				{#each shown as member (member.id)}
					<div class="size-11 shrink-0 overflow-hidden rounded-full">
						{#if member.cutaway?.length}
							<BodyCutaway
								layers={member.cutaway}
								color={tint(member)}
								accent={PROPERTY_ACCENT[kind]}
								id="tile-{slug}-{member.id}"
								class="size-full"
							/>
						{:else if member.limb}
							<AtmosphereBandBar structure={member.limb.structure} species={member.limb.species} />
						{/if}
					</div>
				{/each}
			</div>
		</div>
	{/await}
{/snippet}

{#if tiles.length > 0}
	<div class="grid gap-2">
		{#each tiles as c (c.primary_id)}
			{@const slug = c.primary_id ?? ''}
			{@const kind = kinds[slug]}
			<!-- Declared in the loop so it closes over this child's slug and kind:
			     `background` takes a snippet with no arguments. -->
			{#snippet backdrop()}
				{@render drawings(slug, kind)}
			{/snippet}
			<GroupTile
				{slug}
				name={categoryLabel(slug)}
				label="{formatCompactNumber(c.n)} {m.group_stat_members()}"
				background={kind ? backdrop : undefined}
			/>
		{/each}
	</div>
{/if}
