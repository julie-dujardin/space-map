<script lang="ts">
	/**
	 * The members of a Structure & Activity collection, each drawn as the thing
	 * the page is about rather than photographed.
	 *
	 * A photograph of Ganymede and a photograph of Callisto are two grey discs;
	 * their cutaways are a 375 km ocean and a 132 km one. So the tile is the
	 * body's own cross-section or its air seen edge-on — the same drawings the
	 * Structure tab makes, at tile size — and the row carries the one figure the
	 * page ranks by.
	 */
	import * as m from '$lib/paraglide/messages.js';
	import { getContext } from 'svelte';
	import type { NotableMemberEntry } from '$lib/fetch/objects/object-data';
	import { BODY_COLORS, DEFAULT_BODY_COLOR } from '$lib/constants';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import { focusClick, focusHref } from '$lib/state/focus-link';
	import AtmosphereBandBar from '../charts/AtmosphereBandBar.svelte';
	import BodyCutaway from '../charts/BodyCutaway.svelte';

	interface Props {
		members: NotableMemberEntry[];
		/** Body id → localized label, when the bundle ships one. */
		names?: Record<string, string>;
		/** Interior roles this page is about; a thin one gets a drawn floor. */
		accent?: ReadonlySet<string>;
		/** The reading under the name — whatever the page ranks by. */
		figure: (member: NotableMemberEntry) => string | undefined;
	}
	let { members, names, accent, figure }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');

	let rows = $derived(members.filter((entry) => entry.id));

	function label(e: NotableMemberEntry): string {
		return (e.id ? names?.[e.id] : undefined) ?? e.name;
	}
	function tint(e: NotableMemberEntry): string {
		return (e.id ? BODY_COLORS[e.id] : undefined) ?? e.color ?? DEFAULT_BODY_COLOR;
	}
</script>

{#if rows.length}
	<ul class="grid grid-cols-2 gap-2">
		{#each rows as member (member.id)}
			{@const name = label(member)}
			{@const reading = figure(member)}
			<li>
				<a
					href={focusHref(appState, member.id ?? '', name, 'structure')}
					onclick={focusClick(focusObject, member.id ?? '', name, { tab: 'structure' })}
					class="border-border/60 hover:bg-muted/40 flex items-center gap-2 rounded-lg border p-2
					       transition-colors"
				>
					<div class="size-11 shrink-0 overflow-hidden rounded-full">
						{#if member.cutaway?.length}
							<BodyCutaway
								layers={member.cutaway}
								color={tint(member)}
								{accent}
								id="cut-{member.id}"
								class="size-full"
							/>
						{:else if member.limb}
							<AtmosphereBandBar structure={member.limb.structure} species={member.limb.species} />
						{/if}
					</div>
					<div class="min-w-0">
						<div class="truncate text-sm leading-tight">{name}</div>
						{#if reading}
							<div class="text-muted-foreground text-xs tabular-nums">{reading}</div>
						{:else}
							<div class="text-muted-foreground/70 text-xs">{m.unknown()}</div>
						{/if}
					</div>
				</a>
			</li>
		{/each}
	</ul>
{/if}
