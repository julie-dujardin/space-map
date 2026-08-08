<script lang="ts">
	/**
	 * How much air each body holds, at the level its source quotes.
	 *
	 * Log bars because the answer spans sixteen decades — Venus's 92 bar against
	 * Mercury's 5×10⁻¹⁰ Pa — so a share of the largest would leave nineteen of
	 * the twenty at zero width. The level rides in the row's figure rather than
	 * the bar, because it is what stops the four giants' identical 0.1 bar from
	 * reading as a surface.
	 */
	import type { NotableMemberEntry } from '$lib/fetch/objects/object-data';
	import { formatPressure, pressureLevelLabel } from '$lib/format/pressure';
	import * as m from '$lib/paraglide/messages.js';
	import CountPerBodyChart, { type CountPerBodyEntry } from './CountPerBodyChart.svelte';

	interface Props {
		members: NotableMemberEntry[];
		localizedNames?: Record<string, string>;
	}
	let { members, localizedNames }: Props = $props();

	function name(entry: NotableMemberEntry): string {
		return localizedNames?.[entry.id ?? ''] ?? entry.name;
	}

	let readings = $derived(
		new Map(
			members
				.filter((entry) => entry.id && entry.atmosphere_pressure)
				.map((entry) => [entry.id as string, entry.atmosphere_pressure!])
		)
	);

	let entries = $derived.by<CountPerBodyEntry[]>(() =>
		members
			.filter((entry) => entry.id && readings.has(entry.id))
			.map((entry) => ({
				name: name(entry),
				primary_type: 'object' as const,
				primary_id: entry.id as string,
				color: entry.color,
				n: readings.get(entry.id as string)!.pa
			}))
			.sort((a, b) => b.n - a.n)
	);

	/** Members the page lists but nobody has put a number on — the four
	 *  exospheres whose density is known only as "there is some". */
	let unmeasured = $derived(
		members.filter((entry) => entry.id && !readings.has(entry.id)).map(name)
	);

	let scale = $derived.by(() => {
		if (!entries.length) return null;
		const low = Math.floor(Math.log10(Math.min(...entries.map((e) => e.n)))) - 1;
		const high = Math.ceil(Math.log10(Math.max(...entries.map((e) => e.n))));
		return { low, span: high - low };
	});

	function fraction(entry: CountPerBodyEntry): number {
		if (!scale) return 0;
		return Math.min(1, Math.max(0, (Math.log10(entry.n) - scale.low) / scale.span));
	}

	function text(entry: CountPerBodyEntry): string {
		const reading = readings.get(entry.primary_id ?? '');
		return reading ? formatPressure(reading.pa) : '';
	}

	/** The levels in play, so the chart says once what its figures are quoted
	 *  at instead of repeating "cloud top" on four rows. */
	let levels = $derived([...new Set([...readings.values()].map((r) => r.level))]);
</script>

{#if entries.length > 0}
	<div class="flex flex-col gap-1">
		<CountPerBodyChart
			{entries}
			{fraction}
			{text}
			title={m.group_atmosphere_pressure_title()}
			hint={m.chart_log_scale()}
			tab="structure"
		/>
		<p class="text-muted-foreground text-xs">
			{m.group_atmosphere_pressure_levels({
				levels: levels.map((level) => pressureLevelLabel(level)).join(', ')
			})}
			{#if unmeasured.length > 0}
				{m.group_atmosphere_pressure_unknown({ names: unmeasured.join(', ') })}
			{/if}
		</p>
	</div>
{/if}
