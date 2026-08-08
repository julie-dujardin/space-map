<script lang="ts">
	/**
	 * How many bodies sit on each rung of the volcanic-status ladder.
	 *
	 * A count rather than a quantity, because the quantities are not there: two
	 * of the fifteen members have a heat output and three a vent count, so any
	 * numeric ranking would be four bodies followed by eleven blanks. What
	 * actually separates them is how well anyone has caught them at it, and the
	 * middle rungs are the whole reason that vocabulary is not a boolean —
	 * collapsing them would turn Venus's argument into Earth's fact.
	 *
	 * Rows carry no `primary_id`, so they render unlinked: a rung is a set of
	 * bodies, not a body.
	 */
	import type { NotableMemberEntry } from '$lib/fetch/objects/object-data';
	import { statusLabel } from '$lib/format/activity';
	import { ucfirst } from '$lib/format/quantities';
	import * as m from '$lib/paraglide/messages.js';
	import CountPerBodyChart, { type CountPerBodyEntry } from './CountPerBodyChart.svelte';

	interface Props {
		members: NotableMemberEntry[];
		localizedNames?: Record<string, string>;
	}
	let { members, localizedNames }: Props = $props();

	/** Best-evidenced first, which is also how the members are ordered. */
	const RUNGS = ['active', 'probable', 'suspected', 'dormant', 'extinct', 'none'];

	let entries = $derived.by<CountPerBodyEntry[]>(() => {
		const tally = new Map<string, string[]>();
		for (const member of members) {
			const status = member.activity?.volcanism?.status;
			if (!status) continue;
			const name = localizedNames?.[member.id ?? ''] ?? member.name;
			tally.set(status, [...(tally.get(status) ?? []), name]);
		}
		return RUNGS.filter((rung) => tally.has(rung)).map((rung) => ({
			// The vocabulary is authored lowercase so it can sit inside
			// "Volcanism (probable)"; standing alone as a row it takes a capital.
			name: ucfirst(statusLabel(rung)),
			n: tally.get(rung)!.length
		}));
	});
</script>

{#if entries.length > 0}
	<CountPerBodyChart {entries} title={m.group_volcanism_status_title()} />
{/if}
