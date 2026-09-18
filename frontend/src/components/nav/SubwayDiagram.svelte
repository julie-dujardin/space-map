<!--
  One drawing of the Δv map as SVG. Lines and stops are what the drawing
  says; type, theme colours and the trunk's colour come from the page, since
  the drawing writes `currentColor` for anything that is not a body.
-->
<script lang="ts">
	import type { Drawing } from '$lib/travel/subway-draw';

	interface Props {
		drawing: Drawing;
		/** Fixed pixel size (the strip) rather than the width of the column. */
		fixed?: boolean;
		class?: string;
	}

	let { drawing, fixed = false, class: className }: Props = $props();
</script>

<svg
	viewBox="0 0 {drawing.width} {drawing.height}"
	width={fixed ? drawing.width : undefined}
	height={fixed ? drawing.height : undefined}
	class="block text-foreground {fixed ? '' : 'h-auto w-full'} {className ?? ''}"
	role="img"
>
	{#each drawing.lines as line, i (i)}
		<polyline
			points={line.points}
			fill="none"
			stroke={line.color}
			stroke-width={line.width}
			stroke-linejoin="round"
			stroke-linecap="round"
			opacity={line.opacity}
		/>
	{/each}
	{#each drawing.aeros as a, i (i)}
		<path
			d="M{a.x - 6},{a.y} a6,6 0 0 1 12,0"
			fill="none"
			stroke-width="2"
			stroke-linecap="round"
			class="stroke-sky-500"
		/>
	{/each}
	{#each drawing.stops as s, i (i)}
		{#if s.href}
			<a href={s.href} class="group">
				<title>{s.label}</title>
				<!-- A wider invisible ring keeps the stop easy to hit. -->
				<circle cx={s.x} cy={s.y} r={s.r + 8} fill="transparent" />
				<circle
					cx={s.x}
					cy={s.y}
					r={s.r}
					stroke={s.color}
					stroke-width="3"
					class="transition-[r] group-hover:[r:9px] {s.filled ? '' : 'fill-background'}"
					fill={s.filled ? s.color : undefined}
				/>
			</a>
		{:else}
			<circle
				cx={s.x}
				cy={s.y}
				r={s.r}
				stroke={s.color}
				stroke-width="3"
				class={s.filled ? '' : 'fill-background'}
				fill={s.filled ? s.color : undefined}
			/>
		{/if}
	{/each}
	{#each drawing.labels as t, i (i)}
		{#if t.href}
			<a href={t.href} class="hover:underline">
				<text
					x={t.x}
					y={t.y}
					font-size={t.size}
					font-weight={t.weight}
					text-anchor={t.anchor}
					dominant-baseline="central"
					transform={t.rotate ? `rotate(${t.rotate} ${t.x} ${t.y})` : undefined}
					class={t.muted ? 'fill-muted-foreground' : 'fill-foreground'}>{t.text}</text
				>
			</a>
		{:else}
			<text
				x={t.x}
				y={t.y}
				font-size={t.size}
				font-weight={t.weight}
				text-anchor={t.anchor}
				dominant-baseline="central"
				transform={t.rotate ? `rotate(${t.rotate} ${t.x} ${t.y})` : undefined}
				class={t.muted ? 'fill-muted-foreground' : 'fill-foreground'}>{t.text}</text
			>
		{/if}
	{/each}
</svg>
