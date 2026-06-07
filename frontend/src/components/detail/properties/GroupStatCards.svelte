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
		value: number;
		dot: string;
	}

	let stats = $derived.by<Stat[]>(() => {
		if (!global) return [];
		const out: Stat[] = [
			{ label: m.group_stat_members(), value: global.member_count, dot: 'bg-sky-400' }
		];
		if (global.active_count != null && global.active_count > 0)
			out.push({ label: m.group_stat_active(), value: global.active_count, dot: 'bg-emerald-400' });
		if (global.decayed_count != null && global.decayed_count > 0)
			out.push({ label: m.group_stat_decayed(), value: global.decayed_count, dot: 'bg-zinc-500' });
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
				<div class="text-lg font-semibold tabular-nums">{formatNumber(s.value)}</div>
			</div>
		{/each}
	</div>
{/if}
