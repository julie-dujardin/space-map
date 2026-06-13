<script lang="ts">
	import { getContext } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import type { GlobalGroupData } from '$lib/fetch/groups/details';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import { applyFocus, applyGroup, serializeUrl } from '$lib/state/url';
	import { UrlType } from '$lib/state/view';
	import { formatIsoDate } from '$lib/format/date';
	import { formatNumber, formatQuantity } from '$lib/format/quantities';

	interface Props {
		global: GlobalGroupData | null;
		/** Whether the members tab (with its count badge) is shown — if so the
		 * Members card is redundant and dropped in favour of the Named card. */
		showMembersTab?: boolean;
	}
	let { global, showMembersTab = false }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');

	interface Stat {
		label: string;
		value: string;
		tooltip?: string;
		dot: string;
		href?: string;
		onClick?: (e: MouseEvent) => void;
	}

	function focusBody(id: string, name: string, e: MouseEvent) {
		if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
		// No focusObject in context — let the href do a full-page navigation.
		if (!focusObject) return;
		e.preventDefault();
		focusObject(id, name);
	}

	function focusGroup(slug: string, name: string, e: MouseEvent) {
		if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
		if (!appState) return;
		e.preventDefault();
		appState.setGroup(slug, name);
	}

	function formatPercent(n: number, total: number): string {
		if (!total) return '';
		return `${formatNumber((n / total) * 100)}%`;
	}

	let firstLaunch = $derived.by<{ year: string; full?: string } | null>(() => {
		const iso = global?.first_launch_date;
		if (iso) {
			const year = iso.slice(0, 4);
			if (!Number.isFinite(parseInt(year, 10))) return null;
			return { year, full: formatIsoDate(iso) };
		}
		const h = global?.launch_histogram;
		if (!h) return null;
		let best: number | null = null;
		for (const [y, n] of Object.entries(h)) {
			if (n <= 0) continue;
			const year = parseInt(y, 10);
			if (!Number.isFinite(year)) continue;
			if (best == null || year < best) best = year;
		}
		return best == null ? null : { year: String(best) };
	});

	let stats = $derived.by<Stat[]>(() => {
		if (!global) return [];
		const out: Stat[] = [];
		// The members tab already shows the count in its badge; only carry the
		// Members card when there's no tab (sat groups, categories without one).
		if (!showMembersTab)
			out.push({
				label: m.group_stat_members(),
				value: formatNumber(global.member_count),
				dot: 'bg-sky-400'
			});
		if (global.named_count != null)
			out.push({
				label: m.group_stat_named(),
				value: formatNumber(global.named_count),
				tooltip: formatPercent(global.named_count, global.member_count),
				dot: 'bg-teal-400'
			});
		if (global.active_count != null && global.active_count > 0)
			out.push({
				label: m.group_stat_active(),
				value: formatNumber(global.active_count),
				dot: 'bg-emerald-400'
			});
		if (firstLaunch != null)
			out.push({
				label: m.group_stat_first_launch(),
				value: firstLaunch.year,
				tooltip: firstLaunch.full,
				dot: 'bg-zinc-500'
			});
		const largest = global.largest_body;
		if (largest && appState) {
			const bodyId = `${largest.primary_type}-${largest.primary_id}`;
			out.push({
				label: m.group_stat_largest(),
				value: formatQuantity({ value: largest.diameter_km, unit: 'kilometre' }, true),
				tooltip: largest.name,
				dot: 'bg-amber-400',
				href: serializeUrl(
					applyFocus(appState.view, { type: UrlType.SmallBody, id: bodyId, name: largest.name })
				),
				onClick: (e) => focusBody(bodyId, largest.name, e)
			});
		}
		if (global.pha && appState) {
			const pha = global.pha;
			const label = m.group_stat_pha();
			out.push({
				label,
				value: formatPercent(pha.n, global.member_count),
				tooltip: formatNumber(pha.n),
				dot: 'bg-rose-400',
				href: serializeUrl(applyGroup(appState.view, pha.primary_id, label)),
				onClick: (e) => focusGroup(pha.primary_id, label, e)
			});
		}
		return out;
	});
</script>

{#snippet valueNode(s: Stat)}
	{#if s.href}
		<a
			href={s.href}
			onclick={s.onClick}
			class="pointer-events-auto hover:text-foreground text-lg font-semibold tabular-nums underline decoration-dotted underline-offset-2"
		>
			{s.value}
		</a>
	{:else}
		<div class="text-lg font-semibold tabular-nums">{s.value}</div>
	{/if}
{/snippet}

{#if stats.length > 0}
	<div class="grid auto-cols-fr grid-flow-col gap-2">
		{#each stats as s (s.label)}
			<div class="border-border/60 bg-muted/40 flex flex-col gap-1 rounded-md border p-2.5">
				<div class="text-muted-foreground flex items-center gap-1.5 text-[10px] uppercase">
					<span class="inline-block size-1.5 rounded-full {s.dot}"></span>
					{s.label}
				</div>
				{#if s.tooltip}
					<Tooltip.Root>
						<Tooltip.Trigger>
							{#snippet child({ props })}
								<div class="cursor-help" {...props}>
									{@render valueNode(s)}
								</div>
							{/snippet}
						</Tooltip.Trigger>
						<Tooltip.Content>{s.tooltip}</Tooltip.Content>
					</Tooltip.Root>
				{:else}
					{@render valueNode(s)}
				{/if}
			</div>
		{/each}
	</div>
{/if}
