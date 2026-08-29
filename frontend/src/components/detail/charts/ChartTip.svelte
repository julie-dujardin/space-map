<script lang="ts">
	/** Hover readout for the map charts: a one-line box centred on `cx` and
	 *  seated above `cy` (both px in the chart box), clamped by its measured
	 *  width so a long readout is never clipped by the chart's overflow. */
	const TIP_H = 28;
	const MARGIN = 6;

	let {
		cx,
		cy,
		containerW,
		title,
		sub
	}: { cx: number; cy: number; containerW: number; title: string; sub?: string } = $props();

	let width = $state(0);
	let half = $derived(width / 2);
	let left = $derived(
		Math.min(Math.max(cx, half + MARGIN), Math.max(half, containerW - half - MARGIN))
	);
	let top = $derived(Math.max(4, cy - TIP_H));
</script>

<!-- `w-max` + `max-width` sizes the box to its content; auto width would
     shrink-to-fit the space right of `left`. -->
<div
	bind:clientWidth={width}
	class="bg-background/90 text-foreground pointer-events-none absolute z-10 w-max -translate-x-1/2 rounded px-2 py-1 text-xs whitespace-nowrap shadow-sm backdrop-blur-sm"
	style="left: {left}px; top: {top}px; max-width: {Math.max(
		0,
		containerW - 2 * MARGIN
	)}px; visibility: {width === 0 ? 'hidden' : 'visible'}"
>
	<span class="font-medium">{title}</span>
	{#if sub}<span class="text-muted-foreground">· {sub}</span>{/if}
</div>
