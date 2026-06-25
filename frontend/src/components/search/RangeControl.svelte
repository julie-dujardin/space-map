<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import { hasBound, type RangeBound } from '$lib/search/client';
	import { type RangeDef, toPos, fromPos } from '$lib/search/ranges';

	let {
		def,
		value,
		label,
		onchange
	}: {
		def: RangeDef;
		value: RangeBound;
		label: string;
		onchange: (b: RangeBound) => void;
	} = $props();

	let trackEl: HTMLDivElement | undefined = $state();

	// Unset edges sit at the track ends (0 / 1), imposing no bound.
	const posMin = $derived(value.min != null ? toPos(def, value.min) : 0);
	const posMax = $derived(value.max != null ? toPos(def, value.max) : 1);
	const active = $derived(hasBound(value));

	const stepAttr = $derived(def.unit === 'year' ? 1 : def.unit === 'mag' ? 0.1 : 'any');
	const unitSuffix = $derived(def.unit === 'km' ? m.unit_symbol_kilometre() : '');

	function setEdge(edge: 'min' | 'max', v: number | undefined): void {
		onchange({ ...value, [edge]: v });
	}

	function fracFromClientX(clientX: number): number {
		const el = trackEl;
		if (!el) return 0;
		const rect = el.getBoundingClientRect();
		let f = (clientX - rect.left) / rect.width;
		if (getComputedStyle(el).direction === 'rtl') f = 1 - f;
		return Math.min(1, Math.max(0, f));
	}

	// Fraction → bound value; the end stops (≈0 / ≈1) clear the edge (unbounded).
	function edgeValue(edge: 'min' | 'max', f: number): number | undefined {
		if (edge === 'min') return f <= 0.001 ? undefined : fromPos(def, Math.min(f, posMax));
		return f >= 0.999 ? undefined : fromPos(def, Math.max(f, posMin));
	}

	function startDrag(edge: 'min' | 'max', e: PointerEvent): void {
		e.preventDefault();
		const move = (ev: PointerEvent) => setEdge(edge, edgeValue(edge, fracFromClientX(ev.clientX)));
		const up = () => {
			window.removeEventListener('pointermove', move);
			window.removeEventListener('pointerup', up);
			window.removeEventListener('pointercancel', up);
		};
		window.addEventListener('pointermove', move);
		window.addEventListener('pointerup', up);
		window.addEventListener('pointercancel', up);
	}

	function nudge(edge: 'min' | 'max', delta: number): void {
		const cur = edge === 'min' ? posMin : posMax;
		setEdge(edge, edgeValue(edge, Math.min(1, Math.max(0, cur + delta))));
	}
	function onThumbKey(edge: 'min' | 'max', e: KeyboardEvent): void {
		if (e.key === 'ArrowRight' || e.key === 'ArrowUp') nudge(edge, 0.02);
		else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') nudge(edge, -0.02);
		else return;
		e.preventDefault();
	}

	function parseInput(raw: string): number | undefined {
		const s = raw.trim();
		if (s === '') return undefined;
		const v = Number(s);
		return Number.isNaN(v) ? undefined : v;
	}
</script>

<div class="px-2 py-2">
	<div class="mb-2.5 flex items-center justify-between">
		<span class="text-sm font-medium text-foreground">{label}</span>
		{#if active}
			<button
				type="button"
				class="text-xs text-primary hover:underline"
				onclick={() => onchange({})}>{m.search_clear()}</button
			>
		{/if}
	</div>

	<!-- dual-thumb slider -->
	<div class="relative mx-2 h-5">
		<div
			bind:this={trackEl}
			class="absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-muted"
		>
			<div
				class="absolute top-0 h-full rounded-full bg-primary"
				style="inset-inline-start: {posMin * 100}%; width: {(posMax - posMin) * 100}%"
			></div>
		</div>
		{#each [['min', posMin], ['max', posMax]] as const as [edge, pos] (edge)}
			<!-- Raise the thumb at the crowded end so it stays grabbable when the two overlap. -->
			{@const onTop = edge === 'min' ? pos > 0.5 : pos < 0.5}
			<button
				type="button"
				role="slider"
				tabindex="0"
				aria-label="{label} {edge === 'min' ? m.search_range_min() : m.search_range_max()}"
				aria-valuemin={def.lo}
				aria-valuemax={def.hi}
				aria-valuenow={fromPos(def, pos)}
				class="absolute top-1/2 size-4 -translate-y-1/2 rounded-full border-2 border-primary bg-popover shadow ring-ring/40 focus:ring-2 focus:outline-none"
				style="inset-inline-start: {pos * 100}%; margin-inline-start: -8px; z-index: {onTop
					? 20
					: 10}"
				onpointerdown={(e) => startDrag(edge, e)}
				onkeydown={(e) => onThumbKey(edge, e)}
			></button>
		{/each}
	</div>

	<!-- exact min/max entry -->
	<div class="mt-3 flex items-center gap-2">
		<input
			type="number"
			step={stepAttr}
			inputmode="decimal"
			value={value.min ?? ''}
			placeholder={m.search_range_min()}
			aria-label="{label} {m.search_range_min()}"
			class="w-0 min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1 text-sm text-foreground outline-none focus:border-foreground"
			oninput={(e) => setEdge('min', parseInput(e.currentTarget.value))}
		/>
		<span class="text-muted-foreground">–</span>
		<input
			type="number"
			step={stepAttr}
			inputmode="decimal"
			value={value.max ?? ''}
			placeholder={m.search_range_max()}
			aria-label="{label} {m.search_range_max()}"
			class="w-0 min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1 text-sm text-foreground outline-none focus:border-foreground"
			oninput={(e) => setEdge('max', parseInput(e.currentTarget.value))}
		/>
		{#if unitSuffix}
			<span class="shrink-0 text-xs text-muted-foreground">{unitSuffix}</span>
		{/if}
	</div>
</div>
