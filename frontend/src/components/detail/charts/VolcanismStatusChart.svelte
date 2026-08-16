<script lang="ts">
	/**
	 * How many bodies sit on each rung of the volcanic-status ladder — a count,
	 * not a quantity, since only 2 of 15 members have a heat output and 3 a
	 * vent count. What separates them is how well anyone has caught them at it;
	 * the middle rungs matter because collapsing them turns Venus's argument
	 * into Earth's fact.
	 *
	 * Rows carry no `primary_id` and render unlinked: a rung is a set of
	 * bodies, not a body.
	 */
	import type { NotableMemberEntry } from '$lib/fetch/objects/object-data';
	import { statusLabel } from '$lib/format/activity';
	import { ucfirst } from '$lib/format/quantities';
	import * as m from '$lib/paraglide/messages.js';
	import CountPerBodyChart, { type CountPerBodyEntry } from './CountPerBodyChart.svelte';

	interface Props {
		members: NotableMemberEntry[];
	}
	let { members }: Props = $props();

	/** Best-evidenced first, which is also how the members are ordered. */
	const RUNGS = ['active', 'probable', 'suspected', 'dormant', 'extinct', 'none'];

	let entries = $derived.by<CountPerBodyEntry[]>(() => {
		const tally = new Map<string, number>();
		for (const member of members) {
			const status = member.activity?.volcanism?.status;
			if (status) tally.set(status, (tally.get(status) ?? 0) + 1);
		}
		return RUNGS.filter((rung) => tally.has(rung)).map((rung) => ({
			// The vocabulary is authored lowercase so it can sit inside
			// "Volcanism (probable)"; standing alone as a row it takes a capital.
			name: ucfirst(statusLabel(rung)),
			n: tally.get(rung)!
		}));
	});
</script>

{#if entries.length > 0}
	<CountPerBodyChart {entries} title={m.group_volcanism_status_title()} />
{/if}
