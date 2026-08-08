<script lang="ts">
	/**
	 * One Structure & Activity page as a tile, backed by a few of its own
	 * members drawn as the property it collects.
	 *
	 * The rule the gallery shelves settled on: a tile is backed by what its
	 * destination draws, never by a photograph. A photograph of Ganymede says
	 * nothing about oceans; a cutaway with the ocean lit says the whole page.
	 *
	 * Costs no extra network. There is one global group bucket, so the child's
	 * bundle is the one the page already fetched and `fetchGroupDetail`
	 * memoizes by URL.
	 */
	import { fetchGroupDetail } from '$lib/fetch/groups/details';
	import { categoryLabel, CAT_STRUCTURE_ACTIVITY, CAT_VOLCANISM } from '$lib/fetch/groups/registry';
	import { BODY_COLORS, DEFAULT_BODY_COLOR } from '$lib/constants';
	import { formatCompactNumber } from '$lib/format/quantities';
	import type { NotableMemberEntry } from '$lib/fetch/objects/object-data';
	import { categoryConfig, PROPERTY_ACCENT } from '$lib/state/category-config';
	import * as m from '$lib/paraglide/messages.js';
	import AtmosphereBandBar from '../../charts/AtmosphereBandBar.svelte';
	import BodyCutaway from '../../charts/BodyCutaway.svelte';
	import GroupTile from './GroupTile.svelte';

	interface Props {
		slug: string;
		/** How many members fit before they are grit — four across a full-width
		 *  tile, two across a half-width one. */
		shown?: number;
		/** Member count, where the caller already has it and a flash of an empty
		 *  label would be visible. */
		n?: number;
		/** Overrides the category label — the Solar System page's child list also
		 *  carries orbit classes, which name themselves differently. */
		name?: string;
		class?: string;
	}
	let { slug, shown = 4, n, name, class: className }: Props = $props();

	/** The shell this page is about, or undefined for a slug that collects no
	 *  property — then the tile keeps its lead image. */
	let kind = $derived(categoryConfig({ kind: 'group', slug }).property);

	/**
	 * The meta node collects no single property, so it draws the two worlds that
	 * between them are the whole node: Mars is the rock stack, crust down
	 * through a magma layer to an inner core, and Enceladus the other kind of
	 * world entirely — an ice shell over an ocean over a core, still venting.
	 * No accented shell, because the node is the whole stack.
	 *
	 * Read off `cat-volcanism`, the one child carrying both.
	 */
	const META_BODIES = ['naif-499', 'naif-602'];
	let isMeta = $derived(slug === CAT_STRUCTURE_ACTIVITY);
	/** Drawn whenever this page collects a property, and for the meta node. */
	let drawn = $derived(!!kind || isMeta);

	let detail = $derived(fetchGroupDetail(slug));
	let source = $derived(fetchGroupDetail(isMeta ? CAT_VOLCANISM : slug));

	let members = $derived(
		source.then((d) => {
			const all = (d.global?.notable_members ?? []).filter(
				(entry) => entry.id && (entry.cutaway?.length || entry.limb)
			);
			if (!isMeta) return all.slice(0, shown);
			return META_BODIES.flatMap((id) => all.find((e) => e.id === id) ?? []).slice(0, shown);
		})
	);
	let count = $derived(n != null ? Promise.resolve(n) : detail.then((d) => d.global?.member_count));

	function tint(e: NotableMemberEntry): string {
		return (e.id ? BODY_COLORS[e.id] : undefined) ?? e.color ?? DEFAULT_BODY_COLOR;
	}
</script>

{#snippet drawings()}
	{#await members then list}
		<!-- The drawings keep to the right: the name sits bottom-left over the
		     same tile, and a full-width row would be read through it. -->
		<div class="flex size-full items-center bg-[#05070e]">
			<div class="ms-auto flex w-3/5 items-center justify-end gap-1.5 overflow-hidden pe-3">
				{#each list as member (member.id)}
					<div class="size-11 shrink-0 overflow-hidden rounded-full">
						{#if member.cutaway?.length}
							<BodyCutaway
								layers={member.cutaway}
								color={tint(member)}
								accent={kind ? PROPERTY_ACCENT[kind] : undefined}
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

{#await count then total}
	<GroupTile
		{slug}
		name={name ?? categoryLabel(slug)}
		label={total != null ? `${formatCompactNumber(total)} ${m.group_stat_members()}` : ''}
		background={drawn ? drawings : undefined}
		class={className}
	/>
{/await}
