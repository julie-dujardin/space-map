<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalGroupData } from '$lib/fetch/groups/details';
	import { formatNumber } from '$lib/format/quantities';

	interface Props {
		global: GlobalGroupData | null;
	}
	let { global }: Props = $props();

	interface Stat {
		label: string;
		value: string;
		dot: string;
	}

	let firstLaunchYear = $derived.by(() => {
		const h = global?.launch_histogram;
		if (!h) return null;
		let best: number | null = null;
		for (const [y, n] of Object.entries(h)) {
			if (n <= 0) continue;
			const year = parseInt(y, 10);
			if (!Number.isFinite(year)) continue;
			if (best == null || year < best) best = year;
		}
		return best;
	});

	let stats = $derived.by<Stat[]>(() => {
		if (!global) return [];
		const out: Stat[] = [
			{
				label: m.group_stat_members(),
				value: formatNumber(global.member_count),
				dot: 'bg-sky-400'
			}
		];
		if (global.active_count != null && global.active_count > 0)
			out.push({
				label: m.group_stat_active(),
				value: formatNumber(global.active_count),
				dot: 'bg-emerald-400'
			});
		if (firstLaunchYear != null)
			out.push({
				label: m.group_stat_first_launch(),
				value: String(firstLaunchYear),
				dot: 'bg-zinc-500'
			});
		return out;
	});
</script>

{#if stats.length > 0}
	<div class="grid auto-cols-fr grid-flow-col gap-2">
		{#each stats as s (s.label)}
			<div class="border-border/60 bg-muted/40 flex flex-col gap-1 rounded-md border p-2.5">
				<div class="text-muted-foreground flex items-center gap-1.5 text-[10px] uppercase">
					<span class="inline-block size-1.5 rounded-full {s.dot}"></span>
					{s.label}
				</div>
				<div class="text-lg font-semibold tabular-nums">{s.value}</div>
			</div>
		{/each}
	</div>
{/if}
