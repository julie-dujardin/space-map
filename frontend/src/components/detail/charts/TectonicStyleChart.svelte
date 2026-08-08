<script lang="ts">
	/**
	 * How many bodies behave each way, for the ten with a published tectonic
	 * style.
	 *
	 * A tally rather than a quantity because tectonics carries no number at all
	 * — a style and a status is the whole record. Counting by style rather than
	 * by status is what makes the page worth having: five of the ten are the
	 * same ice shell, and Earth is alone in plate tectonics, which is the one
	 * fact about crusts that nothing else in the app says.
	 *
	 * Rows carry no `primary_id`, so they render unlinked: a style is a set of
	 * bodies, not a body.
	 */
	import type { NotableMemberEntry } from '$lib/fetch/objects/object-data';
	import { tectonicStyleLabel } from '$lib/format/activity';
	import { ucfirst } from '$lib/format/quantities';
	import * as m from '$lib/paraglide/messages.js';
	import CountPerBodyChart, { type CountPerBodyEntry } from './CountPerBodyChart.svelte';

	interface Props {
		members: NotableMemberEntry[];
	}
	let { members }: Props = $props();

	let entries = $derived.by<CountPerBodyEntry[]>(() => {
		const tally = new Map<string, number>();
		for (const member of members) {
			const style = member.activity?.tectonics?.style;
			if (style) tally.set(style, (tally.get(style) ?? 0) + 1);
		}
		return (
			[...tally]
				// The vocabulary is authored lowercase so it can sit inside
				// "Ice-shell tectonics (probable)"; standing alone it takes a capital.
				.map(([style, n]) => ({ name: ucfirst(tectonicStyleLabel(style)), n }))
				.sort((a, b) => b.n - a.n || a.name.localeCompare(b.name))
		);
	});
</script>

{#if entries.length > 0}
	<CountPerBodyChart {entries} title={m.group_tectonics_style_title()} />
{/if}
