import { unixMsToJD } from '$lib/time/jd';
import type { CoverageEdge, NoticeSink, UncoveredBodies } from './notice';
import type { DateCoverage } from '$lib/fetch/metadata';

/** Where the date is against a body's spans: past the first or the last, or
 *  in a hole between two. */
export type EdgeSide = 'before' | 'after' | 'outside';

/**
 * The planets and moons one pass found past their kernels, in the order it
 * placed them. The arrays are reused from pass to pass: a frame with the same
 * answer as the last allocates nothing.
 */
export class UncoveredPass {
	readonly ids: string[] = [];
	readonly names: string[] = [];
	readonly sides: EdgeSide[] = [];
	/** The edge crossed, UTC JD. NaN for `outside`. */
	readonly edges: number[] = [];
	/** The edge is where the whole ephemeris ends, not the body's own kernel. */
	readonly ephemerisEdges: boolean[] = [];
	count = 0;

	reset(): void {
		this.count = 0;
	}

	add(id: string, name: string, side: EdgeSide, edge: number, ephemerisEdge: boolean): void {
		const k = this.count++;
		this.ids[k] = id;
		this.names[k] = name;
		this.sides[k] = side;
		this.edges[k] = edge;
		this.ephemerisEdges[k] = ephemerisEdge;
	}

	/** Same bodies, names, sides and edges as `other`: a locale switch renames
	 *  the bodies under an unchanged date. */
	equals(other: UncoveredPass): boolean {
		if (this.count !== other.count) return false;
		for (let k = 0; k < this.count; k++) {
			if (
				this.ids[k] !== other.ids[k] ||
				this.names[k] !== other.names[k] ||
				this.sides[k] !== other.sides[k] ||
				!Object.is(this.edges[k], other.edges[k])
			) {
				return false;
			}
		}
		return true;
	}

	copyFrom(other: UncoveredPass): void {
		this.reset();
		for (let k = 0; k < other.count; k++) {
			this.add(
				other.ids[k],
				other.names[k],
				other.sides[k],
				other.edges[k],
				other.ephemerisEdges[k]
			);
		}
	}
}

export interface OutOfRangeState {
	jd: number;
	/** Zone-level coverage, not a loaded chunk's window — see {@link DateCoverage}. */
	satellites: DateCoverage;
	majorBodies: UncoveredPass;
	focusedOutOfRange: boolean;
}

/** The civil day of a JD: bodies whose edges print as one date share a line. */
function dayOf(jd: number): number {
	return Math.floor(jd + 0.5);
}

/** The ephemeris's own edge, and the bodies whose kernels end inside it,
 *  grouped by the edge they crossed. */
function groupUncovered(pass: UncoveredPass): {
	edge: CoverageEdge | null;
	bodies: UncoveredBodies[];
} {
	let edge: CoverageEdge | null = null;
	for (let k = 0; k < pass.count; k++) {
		const side = pass.sides[k];
		if (pass.ephemerisEdges[k] && side !== 'outside') {
			edge = { side, jd: pass.edges[k] };
			break;
		}
	}
	const groups = new Map<string, UncoveredBodies>();
	for (let k = 0; k < pass.count; k++) {
		const side = pass.sides[k];
		if (side === edge?.side) continue;
		const key = side === 'outside' ? side : `${side}:${dayOf(pass.edges[k])}`;
		let group = groups.get(key);
		if (!group) {
			group =
				side === 'outside'
					? { side, ids: [], names: [] }
					: { side, jd: pass.edges[k], ids: [], names: [] };
			groups.set(key, group);
		}
		group.ids.push(pass.ids[k]);
		group.names.push(pass.names[k]);
	}
	const order = (g: UncoveredBodies): number => (g.side === 'outside' ? Infinity : g.jd);
	return { edge, bodies: [...groups.values()].sort((a, b) => order(a) - order(b)) };
}

type SatSide = 'after' | 'gap' | null;

/** Sends the out-of-range notice for one map, and only when it changes: the
 *  state is recomputed every frame, so the last report is held as scalars and
 *  reused arrays, and nothing is allocated while it is stable. */
export class OutOfRangeNotifier {
	private focused = false;
	private satSide: SatSide = null;
	private satJd = NaN;
	private readonly uncovered = new UncoveredPass();

	constructor(private readonly notices: NoticeSink) {}

	update(state: OutOfRangeState): void {
		const { majorBodies: pass, satellites: cov } = state;
		// Pre-space-age is folded into `covered`, so only `after`/`gap` warn.
		const satSide: SatSide = cov.kind === 'covered' ? null : cov.kind;
		const satJd = cov.kind === 'after' ? unixMsToJD(cov.lastMs) : NaN;
		const focused = state.focusedOutOfRange;
		if (
			focused === this.focused &&
			satSide === this.satSide &&
			Object.is(satJd, this.satJd) &&
			pass.equals(this.uncovered)
		) {
			return;
		}
		this.focused = focused;
		this.satSide = satSide;
		this.satJd = satJd;
		this.uncovered.copyFrom(pass);

		if (!focused && satSide === null && pass.count === 0) {
			this.notices.dismiss('out-of-range');
			return;
		}
		const { edge, bodies } = groupUncovered(pass);
		this.notices.notify({
			topic: 'out-of-range',
			focusedOutOfRange: focused,
			satellites:
				satSide === 'after'
					? { side: 'after', jd: satJd }
					: satSide === 'gap'
						? { side: 'gap' }
						: null,
			majorBodies: edge,
			bodies
		});
	}
}
