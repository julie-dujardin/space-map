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
		/** Set so the drawer/aside can name itself via aria-labelledby. */
		id?: string;
	}
	let { crumb, title, id }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');

	function crumbHref(c: Crumb): string | undefined {
		if (!appState) return undefined;
		const next =
			c.target.kind === 'focus'
				? applyFocus(appState.view, {
						type: urlTypeFromId(c.target.id),
						id: c.target.id,
						name: c.target.name,
						tab: c.target.tab
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
			focusObject(c.target.id, c.target.name, {
				moveCamera: c.target.moveCamera,
				tab: c.target.tab
			});
		} else {
			e.preventDefault();
			appState.setGroup(c.target.slug, c.target.name);
		}
	}

	// Show the breadcrumb label only when the pill plus a readable slice of the
	// title fit; otherwise collapse to the chevron. The probe is an always-full
	// offscreen copy, so the pill's real width is known regardless of what the
	// visible pill currently shows (no oscillation). The reserved title width is
	// capped at what the title actually needs, so short titles never force a
	// collapse — only a narrow row with both long does.
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
	<h2 {id} bind:this={titleEl} class="min-w-0 flex-1 truncate text-sm font-semibold">{title}</h2>
</div>
