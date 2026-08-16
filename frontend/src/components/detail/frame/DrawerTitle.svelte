<script lang="ts">
	import { getContext } from 'svelte';
	import ChevronLeftIcon from '@lucide/svelte/icons/chevron-left';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import type { Crumb } from '$lib/state/breadcrumb';
	import { applyFocus, applyGroup, applyTab, serializeUrl, urlTypeFromId } from '$lib/state/url';

	interface Props {
		crumb: Crumb | null;
		title: string;
		/** Overrides the accessible name when the visible title alone is too little
		 *  context — a promoted tab shows "Images" but must announce whose. */
		ariaLabel?: string;
		/** Set so the drawer/aside can name itself via aria-labelledby. */
		id?: string;
	}
	let { crumb, title, ariaLabel, id }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');

	function crumbHref(c: Crumb): string | undefined {
		if (!appState) return undefined;
		const t = c.target;
		const next =
			t.kind === 'focus'
				? applyFocus(appState.view, {
						type: urlTypeFromId(t.id),
						id: t.id,
						name: t.name,
						tab: t.tab
					})
				: t.kind === 'group'
					? applyGroup(appState.view, t.slug, t.name)
					: t.kind === 'trip'
						? { ...appState.view, trip: { ...appState.view.trip, profile: null } }
						: applyTab(appState.view, t.tab);
		return serializeUrl(next);
	}

	// Plain left-click navigates in-session; modifier-clicks fall through to the
	// href so "open in new tab" works. Mirrors MemberList / Orbital.
	function onCrumbClick(e: MouseEvent, c: Crumb) {
		if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
		if (!appState) return;
		const t = c.target;
		if (t.kind === 'focus') {
			if (!focusObject) return; // no in-session nav available — let the href win
			e.preventDefault();
			focusObject(t.id, t.name, { moveCamera: t.moveCamera, tab: t.tab });
		} else if (t.kind === 'group') {
			e.preventDefault();
			appState.setGroup(t.slug, t.name);
		} else if (t.kind === 'trip') {
			e.preventDefault();
			// The panel mirrors the trip's terms back out of the URL, so dropping the
			// trajectory here is what puts the list back up.
			appState.setTrip({ ...appState.view.trip, profile: null });
		} else {
			e.preventDefault();
			appState.setTab(t.tab);
		}
	}

	// Show the label only when it plus a readable slice of the title fit;
	// otherwise collapse to the chevron. The offscreen probe is always full
	// pill width, so measuring it can't oscillate with what's currently shown.
	let rowEl = $state<HTMLDivElement | null>(null);
	let titleEl = $state<HTMLHeadingElement | null>(null);
	let probeEl = $state<HTMLSpanElement | null>(null);
	let showLabel = $state(false);

	const GAP_PX = 8;
	const MIN_TITLE_PX = 72; // ~10 chars of the title kept readable beside the pill

	function measure() {
		if (!rowEl || !titleEl || !probeEl || !crumb) {
			showLabel = false;
			return;
		}
		const pill = probeEl.getBoundingClientRect().width;
		const titleNeed = Math.min(MIN_TITLE_PX, titleEl.scrollWidth);
		showLabel = pill + GAP_PX + titleNeed <= rowEl.clientWidth;
	}

	$effect(() => {
		void crumb?.label;
		void title;
		let raf = requestAnimationFrame(measure);
		const ro = new ResizeObserver(() => {
			cancelAnimationFrame(raf);
			raf = requestAnimationFrame(measure);
		});
		if (rowEl) ro.observe(rowEl);
		return () => {
			cancelAnimationFrame(raf);
			ro.disconnect();
		};
	});
</script>

<div bind:this={rowEl} class="flex min-w-0 flex-1 items-center gap-2">
	{#if crumb}
		{@const c = crumb}
		<!-- Offscreen probe: always the full pill, out of flow + invisible, so the
		     expanded width is known before deciding whether to show the label. -->
		<span
			bind:this={probeEl}
			aria-hidden="true"
			class="invisible pointer-events-none absolute flex w-max items-center gap-0.5 rounded-md py-0.5 pe-2 ps-1 text-xs whitespace-nowrap"
		>
			<ChevronLeftIcon class="size-3.5 shrink-0 rtl:rotate-180" />
			<span class="max-w-[14ch] truncate">{c.label}</span>
		</span>
		<a
			href={crumbHref(c)}
			onclick={(e) => onCrumbClick(e, c)}
			aria-label={c.label}
			title={c.label}
			class="text-muted-foreground hover:bg-muted hover:text-foreground bg-muted/50 flex shrink-0 items-center gap-0.5 rounded-md text-xs transition-colors {showLabel
				? 'py-0.5 pe-2 ps-1'
				: 'p-1'}"
		>
			<ChevronLeftIcon class="size-3.5 shrink-0 rtl:rotate-180" />
			{#if showLabel}
				<span class="max-w-[14ch] truncate">{c.label}</span>
			{/if}
		</a>
	{/if}
	<h2
		{id}
		aria-label={ariaLabel}
		bind:this={titleEl}
		class="min-w-0 flex-1 truncate text-sm font-semibold"
	>
		{title}
	</h2>
</div>
