<!--
  What the trip is carrying: people and cargo.

  Neither changes the trajectory — they only decide what the chosen craft can
  do with the route already offered, checked against the room `fit` reports.

  Stepped rather than typed: both start at nothing and most trips move them a
  step or two, which a pair of buttons does in one press each. The figure
  itself stays typeable for the trips that don't.
-->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import UsersIcon from '@lucide/svelte/icons/users';
	import PackageIcon from '@lucide/svelte/icons/package';
	import MinusIcon from '@lucide/svelte/icons/minus';
	import PlusIcon from '@lucide/svelte/icons/plus';
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

	/** A crate at a time: the hold figures craft are rated by run to tonnes, so a
	 *  single kilogram would be a step nobody could reach the top of. */
	const CARGO_STEP_KG = 100;

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
		'border-border/60 bg-background flex min-w-0 flex-1 items-center gap-1.5 rounded-md border ps-2 pe-1 py-1';
	const INPUT =
		'text-foreground w-0 min-w-0 flex-1 bg-transparent text-end text-sm tabular-nums outline-none';
	const STEP =
		'border-border/60 bg-muted/40 hover:bg-muted disabled:text-muted-foreground/50 disabled:hover:bg-muted/40 flex size-5 shrink-0 items-center justify-center rounded border transition-colors';
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
			<button
				type="button"
				class={STEP}
				disabled={passengers <= 0}
				aria-label={m.travel_manifest_fewer({ what: m.travel_people() })}
				onclick={() => onPassengersChange(Math.max(0, passengers - 1))}
			>
				<MinusIcon class="size-3" aria-hidden="true" />
			</button>
			<button
				type="button"
				class={STEP}
				aria-label={m.travel_manifest_more({ what: m.travel_people() })}
				onclick={() => onPassengersChange(passengers + 1)}
			>
				<PlusIcon class="size-3" aria-hidden="true" />
			</button>
		</label>

		<label class={FIELD}>
			<PackageIcon class="text-muted-foreground size-3.5 shrink-0" />
			<span class="text-muted-foreground shrink-0 text-xs">{m.travel_cargo()}</span>
			<input
				type="number"
				min="0"
				step={CARGO_STEP_KG}
				inputmode="numeric"
				value={payloadKg}
				class={INPUT}
				oninput={(e) => onPayloadChange(parseAmount(e.currentTarget.value))}
			/>
			<span class="text-muted-foreground shrink-0 text-[11px]">{formatUnit('kilogram', true)}</span>
			<button
				type="button"
				class={STEP}
				disabled={payloadKg <= 0}
				aria-label={m.travel_manifest_fewer({ what: m.travel_cargo() })}
				onclick={() => onPayloadChange(Math.max(0, payloadKg - CARGO_STEP_KG))}
			>
				<MinusIcon class="size-3" aria-hidden="true" />
			</button>
			<button
				type="button"
				class={STEP}
				aria-label={m.travel_manifest_more({ what: m.travel_cargo() })}
				onclick={() => onPayloadChange(payloadKg + CARGO_STEP_KG)}
			>
				<PlusIcon class="size-3" aria-hidden="true" />
			</button>
		</label>
	</div>

	{#if note}
		<p class="{note.warn ? 'text-amber-500' : 'text-muted-foreground'} text-[11px]">{note.text}</p>
	{/if}
</div>

<style>
	/* The type stays `number` for the keypad it brings up on a phone; the native
	   spinners go, because the buttons beside the figure are already the steppers
	   and two sets of arrows on one field read as two different controls. */
	input[type='number'] {
		appearance: textfield;
	}
	input[type='number']::-webkit-inner-spin-button,
	input[type='number']::-webkit-outer-spin-button {
		appearance: none;
		margin: 0;
	}
</style>
