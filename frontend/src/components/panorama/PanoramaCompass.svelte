<!--
  Heading dial for the panorama viewer: the card turns under a fixed view
  wedge, the observed sweep is drawn on the rim, and each neighbour gets a
  tick at its bearing.
-->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import { formatDegrees } from '$lib/format/quantities';

	interface Props {
		heading: number;
		fov: number;
		/** Observed sweep, degrees clockwise from north; null when unknown. */
		sweep: { startDeg: number; widthDeg: number } | null;
		ticks: Array<{ bearingDeg: number; label: string }>;
	}

	let { heading, fov, sweep, ticks }: Props = $props();

	const R = 26;
	const DEG = Math.PI / 180;

	function polar(deg: number, r: number): [number, number] {
		return [r * Math.sin(deg * DEG), -r * Math.cos(deg * DEG)];
	}

	function arc(startDeg: number, widthDeg: number, r: number): string {
		const w = Math.min(widthDeg, 359.99);
		const [x0, y0] = polar(startDeg, r);
		const [x1, y1] = polar(startDeg + w, r);
		return `M ${x0} ${y0} A ${r} ${r} 0 ${w > 180 ? 1 : 0} 1 ${x1} ${y1}`;
	}

	const wedge = $derived.by(() => {
		const half = fov / 2;
		const [x0, y0] = polar(-half, R);
		const [x1, y1] = polar(half, R);
		return `M 0 0 L ${x0} ${y0} A ${R} ${R} 0 0 1 ${x1} ${y1} Z`;
	});
</script>

<svg
	viewBox="-32 -32 64 64"
	class="size-16 rounded-full bg-black/40 text-white backdrop-blur-sm"
	role="img"
	aria-label={m.panorama_heading({ heading: formatDegrees(Math.round(heading)) })}
>
	<path d={wedge} fill="currentColor" opacity="0.18" />
	<g transform="rotate({-heading})">
		<circle r={R} fill="none" stroke="currentColor" stroke-opacity="0.25" />
		{#if sweep}
			<path
				d={arc(sweep.startDeg, sweep.widthDeg, R)}
				fill="none"
				stroke="currentColor"
				stroke-opacity="0.8"
				stroke-width="2.5"
			/>
		{/if}
		{#each [0, 90, 180, 270] as deg (deg)}
			{@const [x, y] = polar(deg, R - 5)}
			<text
				{x}
				{y}
				text-anchor="middle"
				dominant-baseline="central"
				font-size={deg === 0 ? 9 : 7}
				font-weight={deg === 0 ? 700 : 400}
				fill={deg === 0 ? '#f87171' : 'currentColor'}
				transform="rotate({heading} {x} {y})"
			>
				{['N', 'E', 'S', 'W'][deg / 90]}
			</text>
		{/each}
		{#each ticks as tick (tick.label)}
			{@const [x, y] = polar(tick.bearingDeg, R)}
			<circle cx={x} cy={y} r="3" fill="#facc15" stroke="#000" stroke-opacity="0.6">
				<title>{tick.label}</title>
			</circle>
		{/each}
	</g>
	<circle r="1.5" fill="currentColor" />
</svg>
