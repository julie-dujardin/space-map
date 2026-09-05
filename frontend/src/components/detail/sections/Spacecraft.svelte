<script lang="ts">
	/** The vehicle itself — what it weighs and how big it is. Kept apart from
	 *  Mission, which is who flew it and why.
	 *
	 *  Wikidata leads on the figures it has, since a claim is sourced and dated;
	 *  GCAT answers for the rest of the catalogue, which is most of it, and for
	 *  the readings Wikidata does not keep at all (dry mass, deployed span). */
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalObjectData, QuantityWithUnit } from '$lib/fetch/objects/object-data';
	import { formatQuantity } from '$lib/format/quantities';
	import { massKg } from '$lib/format/mass';
	import Section from './kit/Section.svelte';
	import Row from './kit/Row.svelte';

	interface Props {
		global: GlobalObjectData | null;
	}

	let { global }: Props = $props();

	let isSpacecraft = $derived(global?.type === 'spacecraft' || global?.type === 'debris');
	let wd = $derived(global?.wikidata);
	let ct = $derived(global?.celestrak);

	let mass = $derived(wd?.mass ?? ct?.mass);
	// The estimate mark belongs to GCAT's figure, not to a Wikidata claim that
	// happens to sit beside one.
	let massEstimated = $derived(!wd?.mass && ct?.mass_estimated === true);
	// A catalogue row can describe a different thing than the Wikidata entity:
	// the ISS is filed under Zarya's NORAD number, whose 20 t and 24 m are one
	// module's. When the two masses disagree by more than half, GCAT's hardware
	// figures are not this object's and stay off the page.
	let gcatDescribesThis = $derived.by(() => {
		if (!wd?.mass || !ct?.mass) return true;
		const a = massKg(wd.mass);
		const b = massKg(ct.mass);
		return a === null || b === null || Math.abs(a - b) <= 0.5 * Math.max(a, b);
	});
	let hardware = $derived(gcatDescribesThis ? ct : undefined);
	// GCAT carries a dry mass for everything, equal to the launch mass wherever
	// it knows of no propellant; saying the same number twice reads as an error.
	let dryMass = $derived(
		hardware?.dry_mass && hardware.dry_mass.value !== mass?.value ? hardware.dry_mass : undefined
	);

	interface Size {
		label: string;
		quantity: QuantityWithUnit;
		tooltip?: string;
		estimated?: boolean;
	}

	// One reading, not three near-duplicates. The deployed span is what says how
	// big a spacecraft is — a satellite is mostly solar array — and a body
	// dimension only stands in where there is no span to give.
	let size = $derived<Size | null>(
		hardware?.span
			? {
					label: m.span(),
					quantity: hardware.span,
					tooltip: m.tooltip_span(),
					estimated: hardware.span_estimated === true
				}
			: (wd?.length ?? hardware?.length)
				? { label: m.property_name_length(), quantity: (wd?.length ?? hardware?.length)! }
				: wd?.width
					? { label: m.property_name_width(), quantity: wd.width }
					: hardware?.diameter
						? { label: m.diameter(), quantity: hardware.diameter }
						: null
	);

	let hasContent = $derived(isSpacecraft && !!(mass || dryMass || size));
</script>

{#if hasContent}
	<Section title={m.spacecraft_properties()}>
		{#if mass}
			<Row
				label={m.property_name_mass()}
				value={massEstimated ? `≈ ${formatQuantity(mass)}` : formatQuantity(mass)}
				valueTooltip={massEstimated ? m.tooltip_size_estimated() : undefined}
			/>
		{/if}
		{#if dryMass}
			<Row label={m.dry_mass()} value={formatQuantity(dryMass)} tooltip={m.tooltip_dry_mass()} />
		{/if}
		{#if size}
			<Row
				label={size.label}
				value={size.estimated
					? `≈ ${formatQuantity(size.quantity)}`
					: formatQuantity(size.quantity)}
				tooltip={size.tooltip}
				valueTooltip={size.estimated ? m.tooltip_size_estimated() : undefined}
			/>
		{/if}
	</Section>
{/if}
