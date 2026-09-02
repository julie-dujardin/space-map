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
	// GCAT carries a dry mass for everything, equal to the launch mass wherever
	// it knows of no propellant; saying the same number twice reads as an error.
	let dryMass = $derived(
		ct?.dry_mass && ct.dry_mass.value !== mass?.value ? ct.dry_mass : undefined
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
		ct?.span
			? {
					label: m.span(),
					quantity: ct.span,
					tooltip: m.tooltip_span(),
					estimated: ct.span_estimated === true
				}
			: (wd?.length ?? ct?.length)
				? { label: m.property_name_length(), quantity: (wd?.length ?? ct?.length)! }
				: wd?.width
					? { label: m.property_name_width(), quantity: wd.width }
					: ct?.diameter
						? { label: m.diameter(), quantity: ct.diameter }
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
