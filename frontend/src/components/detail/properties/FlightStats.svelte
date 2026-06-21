<script lang="ts">
	import { getContext } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
	import { type OrbitalElements, type PositionedBody } from '$lib/types/objects';
	import { OrbitalSource } from '$lib/fetch/position/format';
	import { isLandedAt, probeStateKm } from '$lib/fetch/position/probes/propagate';
	import { resolvePrimaryOverride } from '$lib/fetch/position/probes/primary';
	import { getGmKm3s2 } from '$lib/fetch/systems-global';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import { currentStateFromElements } from '$lib/math/orbit/state';
	import { sgp4State } from '$lib/math/orbit/sgp4';
	import { AU_KM } from '$lib/math/units';
	import { SECONDS_PER_DAY } from '$lib/time/jd';
	import { formatDistance } from '$lib/format/distance';
	import { formatDuration } from '$lib/format/duration';
	import { formatQuantity } from '$lib/format/quantities';

	const ctx = getContext<ContextManager>('ctx');

	interface Props {
		global: GlobalObjectData | null;
		body?: PositionedBody;
		/** TLE-derived elements for earth sats; undefined for probes. */
		orbitElements?: OrbitalElements;
		/** Resolved scene body the orbiter circles (Earth for earth sats). */
		parentBody?: PositionedBody;
		jd: number;
	}
	let { global, body, orbitElements, parentBody, jd }: Props = $props();

	const TWO_PI = Math.PI * 2;

	interface FlightStats {
		altitudeKm: number | null;
		speedKms: number | null;
		periodDays: number | null;
	}

	let isProbe = $derived(body?.data.orbitalSource === OrbitalSource.SPICE_PROBE);
	// Earth satellites (SGP4 from TLE). These get the card set in place of the
	// altitude/speed/period rows the Orbital table would otherwise show.
	let isEarthSat = $derived(global?.celestrak?.orbit_center === 'earth');

	// Bound two-body period from an osculating state. Returns null for unbound
	// (hyperbolic/parabolic) trajectories — a flyby has no period.
	function periodDaysFromState(rKm: number, vKms: number, muKm3S2: number): number | null {
		if (!(muKm3S2 > 0) || !(rKm > 0)) return null;
		const energy = (vKms * vKms) / 2 - muKm3S2 / rKm; // km²/s²
		if (energy >= 0) return null;
		const aKm = -muKm3S2 / (2 * energy);
		if (!(aKm > 0)) return null;
		return (TWO_PI * Math.sqrt((aKm * aKm * aKm) / muKm3S2)) / SECONDS_PER_DAY;
	}

	// Probe path: mirror the renderer's parent resolution (probeWithCenter →
	// primary override) so the altitude reference matches the body the scene
	// fits the probe against — the Sun on heliocentric cruise, the captured
	// planet/moon otherwise. Position/velocity are parent-relative.
	let probeStats = $derived.by<FlightStats | null>(() => {
		if (!isProbe || !ctx?.probeStore || !body) return null;
		const located = ctx.probeStore.probeWithCenter(body.data.id, jd);
		if (!located) return null;
		// Landed probes get the surface-position section instead.
		if (located.probe.landed && isLandedAt(located.probe, jd)) return null;
		const zoneCenterKey = `naif-${located.fitCenterNaifId}`;
		const override = resolvePrimaryOverride(
			located.probe,
			jd,
			zoneCenterKey,
			ctx.chebStore ?? null
		);
		const primaryKey = override ? override.id : zoneCenterKey;
		const primaryNaif = override ? override.naifId : located.fitCenterNaifId;
		const mu = getGmKm3s2(primaryNaif) ?? 0;
		const state = probeStateKm(located.probe, jd, mu);
		if (!state) return null;
		const primary = ctx.bodies.bodiesById.get(primaryKey) ?? null;
		const rKm = Math.hypot(state.position[0], state.position[1], state.position[2]);
		// probeStateKm velocity is km/day; the cards report km/s.
		const speedKms =
			Math.hypot(state.velocity[0], state.velocity[1], state.velocity[2]) / SECONDS_PER_DAY;
		const radiusKm = primary?.data.radiusKm ?? 0;
		const altitudeKm = radiusKm > 0 && rKm > radiusKm ? rKm - radiusKm : null;
		return { altitudeKm, speedKms, periodDays: periodDaysFromState(rKm, speedKms, mu) };
	});

	let earthSatStats = $derived.by<FlightStats | null>(() => {
		if (isProbe || !isEarthSat || !body || !parentBody) return null;
		if (!(parentBody.data.radiusKm > 0)) return null;
		const state = body.data.satrec
			? sgp4State(body.data.satrec, jd)
			: orbitElements
				? currentStateFromElements(orbitElements, jd)
				: null;
		if (!state) return null;
		const altitudeKm = state.rKm - parentBody.data.radiusKm;
		const periodMin = global?.celestrak?.period;
		return {
			altitudeKm: altitudeKm > 0 ? altitudeKm : null,
			speedKms: state.vKms,
			periodDays: periodMin != null ? periodMin / 1440 : null
		};
	});

	let stats = $derived(probeStats ?? earthSatStats);

	interface Card {
		label: string;
		value: string;
		tooltip: string;
	}

	let cards = $derived.by<Card[]>(() => {
		const s = stats;
		if (!s) return [];
		const out: Card[] = [];
		if (s.altitudeKm != null)
			out.push({
				label: m.altitude(),
				value: formatDistance(s.altitudeKm / AU_KM),
				tooltip: m.tooltip_altitude()
			});
		if (s.speedKms != null)
			out.push({
				label: m.orbital_speed(),
				value: formatQuantity({ value: s.speedKms, unit: 'kilometre_per_second' }, true),
				tooltip: m.tooltip_orbital_speed()
			});
		if (s.periodDays != null)
			out.push({
				label: m.orbital_period(),
				value: formatDuration(s.periodDays),
				tooltip: m.tooltip_orbital_period()
			});
		return out;
	});
</script>

{#if cards.length > 0}
	<div class="grid auto-cols-fr grid-flow-col gap-2">
		{#each cards as c (c.label)}
			<Tooltip.Root>
				<Tooltip.Trigger>
					{#snippet child({ props })}
						<div
							class="border-border/60 bg-muted/40 pointer-events-auto flex cursor-help flex-col gap-1 rounded-md border p-2.5"
							{...props}
						>
							<div class="text-muted-foreground text-[10px] uppercase">{c.label}</div>
							<div class="text-sm font-semibold tabular-nums">{c.value}</div>
						</div>
					{/snippet}
				</Tooltip.Trigger>
				<Tooltip.Content>{c.tooltip}</Tooltip.Content>
			</Tooltip.Root>
		{/each}
	</div>
{/if}
