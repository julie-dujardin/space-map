<script lang="ts">
	import { getContext } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import type { GlobalGroupData } from '$lib/fetch/groups/details';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusFeature, FocusObject } from '$lib/state/focusable';
	import { applyFeature, applyFocus, applyGroup, serializeUrl } from '$lib/state/url';
	import { UrlType } from '$lib/state/view';
	import { formatIsoDate } from '$lib/format/date';
	import { formatNumber, formatQuantity } from '$lib/format/quantities';

	interface Props {
		global: GlobalGroupData | null;
	}
	let { global }: Props = $props();

	// Three across is what the row fits; a fourth squeezes every value.
	const MAX_CARDS = 3;

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');
	const focusFeature = getContext<FocusFeature | undefined>('focusFeature');

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

	function openFeature(bodyId: string, featureId: number, name: string, e: MouseEvent) {
		if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
		if (!focusFeature) return;
		e.preventDefault();
		focusFeature(bodyId, featureId, name);
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

	// Feature types: when the IAU first approved a name of this kind.
	let firstApproval = $derived.by<{ year: string; full?: string } | null>(() => {
		const iso = global?.first_approval_date;
		if (!iso) return null;
		const year = iso.slice(0, 4);
		if (!Number.isFinite(parseInt(year, 10))) return null;
		return { year, full: formatIsoDate(iso) };
	});

	let stats = $derived.by<Stat[]>(() => {
		if (!global) return [];
		const out: Stat[] = [];
		// No members card: the count rides the members tab's badge, and a strip
		// short enough to have no tab is short enough to count by eye.
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
		if (global.launch_count != null && global.launch_count > 0) {
			out.push({
				label: m.group_stat_launches(),
				value: formatNumber(global.launch_count),
				dot: 'bg-indigo-400'
			});
			if (global.success_count != null)
				out.push({
					label: m.group_stat_success(),
					value: formatPercent(global.success_count, global.launch_count),
					tooltip: m.group_stat_failures({ count: global.failure_count ?? 0 }),
					dot: 'bg-emerald-400'
				});
		}
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
		// Surface Features meta page: its members are features, not objects, so
		// the count that has nowhere else to go (no members strip) rides a card.
		if (global.feature_type_count != null) {
			out.push({
				label: m.group_stat_types(),
				value: formatNumber(global.feature_type_count),
				dot: 'bg-sky-400'
			});
			out.push({
				label: m.group_stat_features(),
				value: formatNumber(global.member_count),
				dot: 'bg-teal-400'
			});
		}
		if (global.body_count != null && global.body_count > 0)
			out.push({
				label: m.group_stat_bodies(),
				value: formatNumber(global.body_count),
				dot: 'bg-violet-400'
			});
		const largestFeature = global.largest_feature;
		if (largestFeature && appState) {
			const bodyId = `${largestFeature.primary_type}-${largestFeature.primary_id}`;
			const featureId = parseInt(largestFeature.secondary_id, 10);
			out.push({
				label: m.group_stat_largest(),
				value: formatQuantity({ value: largestFeature.diameter_km, unit: 'kilometre' }, true),
				tooltip: largestFeature.name,
				dot: 'bg-amber-400',
				href: serializeUrl(
					applyFeature(appState.view, { bodyId, featureId, featureName: largestFeature.name })
				),
				onClick: (e) => openFeature(bodyId, featureId, largestFeature.name, e)
			});
		}
		if (firstApproval != null)
			out.push({
				label: m.group_stat_first_named(),
				value: firstApproval.year,
				tooltip: firstApproval.full,
				dot: 'bg-zinc-500'
			});
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
		if (out.length > MAX_CARDS) {
			console.warn(
				`[group] ${global.slug} produced ${out.length} stat cards; showing the first ${MAX_CARDS}: ` +
					out.map((s) => s.label).join(', ')
			);
		}
		return out.slice(0, MAX_CARDS);
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
