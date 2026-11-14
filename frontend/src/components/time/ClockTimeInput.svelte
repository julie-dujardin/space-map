<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import type { SimClock } from '$lib/scene/state/clock.svelte';
	import { getSettings } from '$lib/state/settings.svelte';
	import { cn } from '$lib/utils.js';
	import {
		applyDayFractionToClock,
		applyTimeToClock,
		clockTimeValue,
		decimalTimeValue,
		parseDecimalTime
	} from './clock-pickers';

	/** The time of day under the date picker: the browser's own time field, or
	 *  under the Republican calendar a decimal one, ten hours to the day. No
	 *  browser draws a decimal clock, so that one is typed. */
	interface Props {
		clock: SimClock;
		class?: string;
	}

	let { clock, class: className }: Props = $props();

	const decimal = $derived(getSettings().resolvedDecimalTime);
	// Minutes are what both fields show; quantise so they don't re-render per frame.
	const shownJd = $derived(Math.floor(clock.jd * 86400) / 86400);
	const live = $derived(decimal ? decimalTimeValue(shownJd) : clockTimeValue(shownJd));
	// While the reader is in the field, it holds what they are typing: a running
	// clock moves a decimal minute every 1.4 s at 60×, and would write over it.
	let editing = $state(false);
	let draft = $state('');
	const value = $derived(editing ? draft : live);

	function onfocus(e: FocusEvent): void {
		draft = (e.currentTarget as HTMLInputElement).value;
		editing = true;
	}
	function oninput(e: Event): void {
		draft = (e.currentTarget as HTMLInputElement).value;
	}
	function onblur(): void {
		editing = false;
	}

	function onDecimalChange(e: Event): void {
		const input = e.currentTarget as HTMLInputElement;
		const fraction = parseDecimalTime(input.value);
		if (fraction === null) {
			draft = input.value = live;
			return;
		}
		applyDayFractionToClock(clock, fraction);
	}

	const base =
		'w-full rounded-md border bg-transparent px-2 font-mono tabular-nums scheme-light-dark focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring';
</script>

{#if decimal}
	<input
		type="text"
		inputmode="decimal"
		autocomplete="off"
		spellcheck="false"
		{value}
		{onfocus}
		{oninput}
		{onblur}
		onchange={onDecimalChange}
		aria-label={m.time_pick_time()}
		placeholder="0:00"
		class={cn(base, className)}
	/>
{:else}
	<input
		type="time"
		{value}
		{onfocus}
		{oninput}
		{onblur}
		onchange={(e) => applyTimeToClock(clock, e)}
		aria-label={m.time_pick_time()}
		class={cn(base, className)}
	/>
{/if}
