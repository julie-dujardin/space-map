<!--
  What the trip is carrying: people and cargo.

  Neither changes the trajectory — they only decide what the chosen craft can
  do with the route already offered, checked against the room `fit` reports.
-->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import UsersIcon from '@lucide/svelte/icons/users';
	import PackageIcon from '@lucide/svelte/icons/package';
	import type { ManifestFit } from '$lib/math/travel';
	import { formatQuantity, formatUnit } from '$lib/format/quantities';

	interface Props {
		passengers: number;
		payloadKg: number;
		/** Whether the chosen craft has room; null when none is chosen. */
		fit: ManifestFit | null;
		onPassengersChange: (value: number) => void;
		onPayloadChange: (value: number) => void;
	}
	let { passengers, payloadKg, fit, onPassengersChange, onPayloadChange }: Props = $props();

	/** An emptied box means nothing aboard, not a broken figure. */
	function parseAmount(raw: string): number {
		const value = Number(raw);
		return Number.isFinite(value) && value > 0 ? value : 0;
	}

	// Over-capacity and over-payload mean the trip cannot be flown as loaded, so
	// they carry the panel's caution colour; the unpublished figure is only a
	// silence and stays muted.
	let note = $derived.by(() => {
		if (fit === null) return null;
		if (fit.status === 'over-capacity') {
			return { text: m.travel_over_capacity({ value: fit.seats }), warn: true };
		}
		if (fit.status === 'unknown-capacity') {
			return { text: m.travel_capacity_unpublished(), warn: false };
		}
		if (fit.status === 'over-payload') {
			return {
				text: m.travel_over_hold({
					value: formatQuantity({ value: fit.capacityKg, unit: 'kilogram' }, true)
				}),
				warn: true
			};
		}
		return null;
	});

	const FIELD =
		'border-border/60 bg-background flex min-w-0 flex-1 items-center gap-1.5 rounded-md border px-2 py-1';
	const INPUT =
		'text-foreground w-0 min-w-0 flex-1 bg-transparent text-end text-sm tabular-nums outline-none';
</script>

<div class="flex flex-col gap-1.5">
	<div class="flex items-center gap-2" role="group" aria-label={m.travel_manifest()}>
		<label class={FIELD}>
			<UsersIcon class="text-muted-foreground size-3.5 shrink-0" />
			<span class="text-muted-foreground shrink-0 text-xs">{m.travel_people()}</span>
			<input
				type="number"
				min="0"
				step="1"
				inputmode="numeric"
				value={passengers}
				class={INPUT}
				oninput={(e) => onPassengersChange(Math.floor(parseAmount(e.currentTarget.value)))}
			/>
		</label>

		<label class={FIELD}>
			<PackageIcon class="text-muted-foreground size-3.5 shrink-0" />
			<span class="text-muted-foreground shrink-0 text-xs">{m.travel_cargo()}</span>
			<input
				type="number"
				min="0"
				step="100"
				inputmode="numeric"
				value={payloadKg}
				class={INPUT}
				oninput={(e) => onPayloadChange(parseAmount(e.currentTarget.value))}
			/>
			<span class="text-muted-foreground shrink-0 text-[11px]">{formatUnit('kilogram', true)}</span>
		</label>
	</div>

	{#if note}
		<p class="{note.warn ? 'text-amber-500' : 'text-muted-foreground'} text-[11px]">{note.text}</p>
	{/if}
</div>
