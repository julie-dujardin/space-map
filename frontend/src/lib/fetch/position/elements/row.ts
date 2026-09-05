/**
 * Per-row builders for the elements payload, two output shapes from the same
 * source columns: {@link materializeBodyData} (a full `BodyData` object) and
 * {@link fillOrbitColumnRow} (writes straight into the worker SoA, no object).
 * Both apply the same PLANET-scale conversions, so the worker-solved dot and
 * the materialized-on-click body trace the identical orbit.
 */

import type { LabelMap } from '$lib/fetch/position/labels';
import { buildSatrec, type SGP4Inputs } from '$lib/math/orbit/sgp4';
import type { SatRec } from 'satellite.js';
import { AU_KM } from '$lib/math/units';
import { Scale } from '$lib/fetch/position/format';
import { ObjectType, type BodyData } from '$lib/types/objects';
import type { ObjectKey } from '$lib/fetch/position/object-key';
import {
	rowId,
	type ElementColumns,
	type KeplerianColumns,
	type ParabolicColumns,
	type SGP4Columns
} from '$lib/fetch/position/elements/parse';
import {
	KIND_KEPLER,
	KIND_PARABOLIC,
	KIND_SGP4,
	KIND_SKIP,
	type OrbitColumns
} from '$lib/math/orbit/soa';

/**
 * Resolve a label to a non-empty name or null. The labels file ships
 * `{id}\x1f\x1f` for promoted bodies with no Wikidata/DB name (the id still
 * needs to be a key so the renderer auto-promotes it); coalescing `''` to null
 * keeps `body.data.name` truthy-or-null for downstream `?? fallback` chains.
 */
export function pickLabel(labels: LabelMap, id: string): string | null {
	return labels.get(id)?.name || null;
}

export function pickIsMinor(labels: LabelMap, id: string): boolean {
	return labels.get(id)?.isMinor ?? false;
}

/** Single-lookup variant of pickLabel + pickIsMinor for per-row hot loops —
 *  two string-keyed gets per row measured ~10% of the asteroid-load window. */
export function pickLabelEntry(
	labels: LabelMap,
	id: string
): { name: string | null; isMinor: boolean } {
	const entry = labels.get(id);
	return { name: entry?.name || null, isMinor: entry?.isMinor ?? false };
}

export function keplerianToBody(
	cols: KeplerianColumns,
	idx: number,
	labels: LabelMap,
	parentIdType: string
): BodyData | null {
	const isPlanetScale = cols.scale[idx] === Scale.PLANET;
	const omDot = cols.omDot[idx];
	const wDot = cols.wDot[idx];
	const id = rowId(cols, idx);
	if (id === null) return null;
	const { name, isMinor } = pickLabelEntry(labels, id);
	return {
		id,
		name,
		isMinor,
		hasLocalized: cols.hasLocalized[idx] === 1,
		flags: cols.flags[idx],
		objectType: cols.objectType[idx] as ObjectType,
		parentId: `${parentIdType}-${cols.parentId[idx]}`,
		radiusKm: cols.radiusKm[idx],
		// Planet-scale: a is in km, n is in rev/day → convert to AU and deg/day
		a: isPlanetScale ? cols.a[idx] / AU_KM : cols.a[idx],
		e: cols.e[idx],
		i: cols.i[idx],
		om: cols.om[idx],
		w: cols.w[idx],
		ma: cols.ma[idx],
		n: isPlanetScale ? cols.n[idx] * 360 : cols.n[idx],
		epoch: cols.epochJd[idx],
		omDot: omDot !== 0 ? omDot : undefined,
		wDot: wDot !== 0 ? wDot : undefined,
		// Planet-scale entries come from CelesTrak TLEs (Earth-equatorial TEME);
		// system-scale entries are ecliptic J2000.
		equatorial: isPlanetScale,
		validityStart: cols.validityStart,
		validityEnd: cols.validityEnd,
		orbitalSource: cols.source,
		visibleFromDays: cols.visibleFromDays[idx]
	};
}

export function parabolicToBody(
	cols: ParabolicColumns,
	idx: number,
	labels: LabelMap,
	parentIdType: string
): BodyData | null {
	const id = rowId(cols, idx);
	if (id === null) return null;
	const { name, isMinor } = pickLabelEntry(labels, id);
	return {
		id,
		name,
		isMinor,
		hasLocalized: cols.hasLocalized[idx] === 1,
		flags: cols.flags[idx],
		objectType: cols.objectType[idx] as ObjectType,
		parentId: `${parentIdType}-${cols.parentId[idx]}`,
		radiusKm: cols.radiusKm[idx],
		a: 0,
		e: cols.e[idx],
		i: cols.i[idx],
		om: cols.om[idx],
		w: cols.w[idx],
		ma: 0,
		n: 0,
		epoch: cols.epochJd[idx],
		q: cols.q[idx],
		tp: cols.tp[idx],
		validityStart: cols.validityStart,
		validityEnd: cols.validityEnd,
		orbitalSource: cols.source,
		visibleFromDays: cols.visibleFromDays[idx]
	};
}

/**
 * Build an SGP4-backed BodyData for one earth satellite. Returns null when
 * satrec init fails — earth sats must use SGP4, so we drop the row rather than
 * silently falling back to Kepler (which diverges from the SGP4 curve by km and
 * breaks trail construction).
 */
/** Records built on first read, keyed by body: only promoted satellites and
 *  trails ever need one. */
const satrecs = new WeakMap<BodyData, SatRec | null>();
/** Chunk row behind each SGP4 body, so its OMM inputs can be read back on
 *  demand instead of held as a second object per satellite. */
const sgp4Rows = new WeakMap<BodyData, [cols: SGP4Columns, idx: number]>();

function ommOf(cols: SGP4Columns, idx: number): SGP4Inputs {
	return {
		noradCatId: cols.id[idx],
		epochJd: cols.epochJd[idx],
		meanMotion: cols.n[idx],
		eccentricity: cols.e[idx],
		inclination: cols.i[idx],
		raOfAscNode: cols.om[idx],
		argOfPericenter: cols.w[idx],
		meanAnomaly: cols.ma[idx],
		bstar: cols.bstar[idx],
		meanMotionDot: cols.meanMotionDot[idx],
		meanMotionDdot: cols.meanMotionDdot[idx],
		elementSetNo: cols.elementSetNo[idx],
		revAtEpoch: cols.revAtEpoch[idx]
	};
}

/** Shared prototype for SGP4 rows. A per-instance `satrec` accessor put every
 *  satellite in dictionary mode at ~2 KB each; one getter on a shared
 *  prototype keeps the objects small and in fast mode. An init failure (a
 *  decayed satellite) marks the row unplaceable instead of letting the Kepler
 *  fallback draw a wrong orbit. */
const SGP4_BODY_PROTO = {
	get omm(): SGP4Inputs | undefined {
		const row = sgp4Rows.get(this as unknown as BodyData);
		return row && ommOf(row[0], row[1]);
	},
	get satrec(): SatRec | undefined {
		const body = this as unknown as BodyData;
		let satrec = satrecs.get(body);
		if (satrec === undefined) {
			satrec = buildSatrec(body.omm!, body.name ?? undefined);
			satrecs.set(body, satrec);
			if (!satrec) body.unplaceable = true;
		}
		return satrec ?? undefined;
	}
};

export function sgp4ToBody(
	cols: SGP4Columns,
	idx: number,
	labels: LabelMap,
	parentIdType: string
): BodyData | null {
	const id = rowId(cols, idx);
	if (id === null) return null;
	const { name, isMinor } = pickLabelEntry(labels, id);
	const data = Object.assign(Object.create(SGP4_BODY_PROTO) as BodyData, {
		id,
		name,
		isMinor,
		hasLocalized: cols.hasLocalized[idx] === 1,
		flags: cols.flags[idx],
		objectType: cols.objectType[idx] as ObjectType,
		parentId: `${parentIdType}-${cols.parentId[idx]}`,
		radiusKm: cols.radiusKm[idx],
		// Kepler mean elements in canonical (AU, deg/day) units for the
		// orbit-period estimate used by sgp4Curve — not used to propagate.
		a: cols.a[idx] / AU_KM,
		e: cols.e[idx],
		i: cols.i[idx],
		om: cols.om[idx],
		w: cols.w[idx],
		ma: cols.ma[idx],
		n: cols.n[idx] * 360,
		epoch: cols.epochJd[idx],
		equatorial: true,
		validityStart: cols.validityStart,
		validityEnd: cols.validityEnd,
		orbitalSource: cols.source,
		visibleFromDays: cols.visibleFromDays[idx]
	});
	sgp4Rows.set(data, [cols, idx]);
	return data;
}

/** Materialize the full `BodyData` for one row, dispatching on sub-format.
 *  Returns null for SGP4 rows whose satrec init fails (same drop rule as the
 *  AoS path). Position is the caller's responsibility (the worker solves the
 *  bulk; pick/promotion call `refreshMinorBodyPosition`). */
export function materializeBodyData(
	cols: ElementColumns,
	idx: number,
	labels: LabelMap,
	parentIdType: string
): BodyData | null {
	if (cols.kind === 'parabolic') return parabolicToBody(cols, idx, labels, parentIdType);
	if (cols.kind === 'sgp4') return sgp4ToBody(cols, idx, labels, parentIdType);
	return keplerianToBody(cols, idx, labels, parentIdType);
}

/**
 * Write one source row into `out[outIdx]` of an `OrbitColumns` SoA — same
 * PLANET-scale conversions as the body builders, no `BodyData`. Returns false
 * (tags KIND_SKIP) for degenerate rows. `skip` drops promoted ids; pass `id`
 * only when a skip set is active (building it per row is the dominant cost).
 */
export function fillOrbitColumnRow(
	cols: ElementColumns,
	idx: number,
	out: OrbitColumns,
	outIdx: number,
	key?: ObjectKey,
	skip?: ReadonlySet<ObjectKey>
): boolean {
	if (skip && key !== undefined && skip.has(key)) {
		out.kind[outIdx] = KIND_SKIP;
		return false;
	}
	if (cols.kind === 'parabolic') {
		const q = cols.q[idx];
		const tp = cols.tp[idx];
		if (!(isFinite(q) && isFinite(tp))) {
			out.kind[outIdx] = KIND_SKIP;
			return false;
		}
		out.kind[outIdx] = KIND_PARABOLIC;
		out.q[outIdx] = q;
		out.tp[outIdx] = tp;
		out.a[outIdx] = 0;
		out.e[outIdx] = cols.e[idx];
		out.i[outIdx] = cols.i[idx];
		out.om[outIdx] = cols.om[idx];
		out.w[outIdx] = cols.w[idx];
		out.ma[outIdx] = 0;
		out.n[outIdx] = 0;
		out.epoch[outIdx] = cols.epochJd[idx];
		out.equatorial[outIdx] = 0;
		out.flags[outIdx] = cols.flags[idx];
		out.visibleFromDays[outIdx] = cols.visibleFromDays[idx];
		return true;
	}
	if (cols.kind === 'sgp4') {
		// The worker builds the SGP4 record from these on its first solve.
		out.kind[outIdx] = KIND_SGP4;
		out.satrec[outIdx] = null;
		out.satnum[outIdx] = cols.id[idx];
		out.bstar[outIdx] = cols.bstar[idx];
		out.ndot[outIdx] = cols.meanMotionDot[idx];
		out.nddot[outIdx] = cols.meanMotionDdot[idx];
		out.a[outIdx] = cols.a[idx] / AU_KM;
		out.e[outIdx] = cols.e[idx];
		out.i[outIdx] = cols.i[idx];
		out.om[outIdx] = cols.om[idx];
		out.w[outIdx] = cols.w[idx];
		out.ma[outIdx] = cols.ma[idx];
		out.n[outIdx] = cols.n[idx] * 360;
		out.epoch[outIdx] = cols.epochJd[idx];
		out.equatorial[outIdx] = 1;
		out.flags[outIdx] = cols.flags[idx];
		out.visibleFromDays[outIdx] = cols.visibleFromDays[idx];
		return true;
	}
	// keplerian
	const isPlanetScale = cols.scale[idx] === Scale.PLANET;
	const a = isPlanetScale ? cols.a[idx] / AU_KM : cols.a[idx];
	if (!(a !== 0 && isFinite(a))) {
		out.kind[outIdx] = KIND_SKIP;
		return false;
	}
	out.kind[outIdx] = KIND_KEPLER;
	out.a[outIdx] = a;
	out.e[outIdx] = cols.e[idx];
	out.i[outIdx] = cols.i[idx];
	out.om[outIdx] = cols.om[idx];
	out.w[outIdx] = cols.w[idx];
	out.ma[outIdx] = cols.ma[idx];
	out.n[outIdx] = isPlanetScale ? cols.n[idx] * 360 : cols.n[idx];
	out.epoch[outIdx] = cols.epochJd[idx];
	out.equatorial[outIdx] = isPlanetScale ? 1 : 0;
	out.flags[outIdx] = cols.flags[idx];
	out.visibleFromDays[outIdx] = cols.visibleFromDays[idx];
	return true;
}
