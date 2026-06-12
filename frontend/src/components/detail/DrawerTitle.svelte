<script lang="ts">
	import { getContext } from 'svelte';
	import ChevronLeftIcon from '@lucide/svelte/icons/chevron-left';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import type { Crumb } from '$lib/state/breadcrumb';
	import { applyFocus, applyGroup, serializeUrl, urlTypeFromId } from '$lib/state/url';

	interface Props {
		crumb: Crumb | null;
		title: string;
	}
	let { crumb, title }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');

	function crumbHref(c: Crumb): string | undefined {
		if (!appState) return undefined;
		const next =
			c.target.kind === 'focus'
				? applyFocus(appState.view, {
						type: urlTypeFromId(c.target.id),
						id: c.target.id,
						name: c.target.name
					})
				: applyGroup(appState.view, c.target.slug, c.target.name);
		return serializeUrl(next);
	}

	// Plain left-click navigates in-session; modifier-clicks fall through to the
	// href so "open in new tab" works. Mirrors MemberList / Orbital.
	function onCrumbClick(e: MouseEvent, c: Crumb) {
		if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
		if (!appState) return;
		if (c.target.kind === 'focus') {
			if (!focusObject) return; // no in-session nav available — let the href win
			e.preventDefault();
			focusObject(c.target.id, c.target.name);
		} else {
			e.preventDefault();
			appState.setGroup(c.target.slug, c.target.name);
		}
	}

	// The chevron is always visible; the label is added only once we've confirmed
	// it fits. The expanded width is read from an always-full, offscreen measurer
	// — so the decision is independent of the label's presence (no oscillation)
	// and the label never flashes in then collapses (it starts hidden and only
	// appears when measured to fit).
	let rowEl = $state<HTMLDivElement | null>(null);
	let titleEl = $state<HTMLSpanElement | null>(null);
	let measureEl = $state<HTMLSpanElement | null>(null);
	let fits = $state(false);
	let measured = $state(false);
	let showLabel = $derived(measured && fits);

	const GAP_PX = 8;

	function measure() {
		if (!rowEl || !titleEl) return;
		if (crumb && measureEl) {
			const full = measureEl.getBoundingClientRect().width;
			fits = full + GAP_PX + titleEl.scrollWidth <= rowEl.clientWidth;
		}
		measured = true;
	}

	$effect(() => {
		// Re-measure from scratch whenever the crumb or title changes; hide the
		// visible pill until the new measurement lands.
		void crumb?.label;
		void title;
		measured = false;
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
		<!-- Offscreen measurer: always the full pill, out of flow + invisible, so
		     we know the expanded width before the visible pill is rendered. -->
		<span
			bind:this={measureEl}
			aria-hidden="true"
			class="invisible pointer-events-none absolute flex w-max items-center gap-0.5 rounded-md py-0.5 pe-2 ps-1 text-xs whitespace-nowrap"
		>
			<ChevronLeftIcon class="size-3.5 shrink-0" />
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
			<ChevronLeftIcon class="size-3.5 shrink-0" />
			{#if showLabel}
				<span class="max-w-[14ch] truncate">{c.label}</span>
			{/if}
		</a>
	{/if}
	<span bind:this={titleEl} class="min-w-0 flex-1 truncate text-sm font-semibold">{title}</span>
</div>
