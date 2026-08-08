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
	import type { PropertyKind } from '$lib/state/category-config';
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

	/** How many members fit across a half-width tile before they are grit. */
	const SHOWN = 4;

	const ACCENT: Record<PropertyKind, ReadonlySet<string> | undefined> = {
		oceans: new Set(['ocean']),
		atmospheres: undefined
	};

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
		<div class="flex size-full items-center justify-center gap-1 bg-[#05070e] px-2">
			{#each shown as member (member.id)}
				<div class="size-9 shrink-0 overflow-hidden rounded-full">
					{#if member.cutaway?.length}
						<BodyCutaway
							layers={member.cutaway}
							color={tint(member)}
							accent={ACCENT[kind]}
							id="tile-{slug}-{member.id}"
							class="size-full"
						/>
					{:else if member.limb}
						<AtmosphereBandBar structure={member.limb.structure} species={member.limb.species} />
					{/if}
				</div>
			{/each}
		</div>
	{/await}
{/snippet}

{#if tiles.length > 0}
	<div class="grid grid-cols-2 gap-2">
		{#each tiles as c, i (c.primary_id)}
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
				class={i === tiles.length - 1 && tiles.length % 2 === 1 ? 'col-span-2' : ''}
			/>
		{/each}
	</div>
{/if}
