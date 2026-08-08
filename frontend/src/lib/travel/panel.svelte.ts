/**
 * State behind the travel panel: the trip you are describing, and the routes
 * that come back.
 *
 * Solving is an explicit method rather than an effect inside the class — the
 * component owns the effect, so the reads that should trigger a re-solve are
 * visible in one place instead of hidden behind an async write that would feed
 * itself. Superseded solves are dropped by token, so a fast change of
 * destination cannot be overwritten by the answer to the previous one.
 */

import {
	canDepartFrom,
	checkFeasibility,
	checkManifest,
	TravelSolver,
	type ArrivalMode,
	type DepartureMode,
	type Feasibility,
	type Manifest,
	type ManifestFit,
	type PorkchopGrid,
	type Route,
	type RouteChoice,
	type RouteProfile,
	type TravelBody,
	type Vehicle
} from '$lib/math/travel';
import { ensureVehicles, findVehicle } from './vehicles';
import { searchWindow, type TimeMode } from './search-window';
import type { TransferFrame } from './travel-body';

/**
 * How a trip meets a body at one end. These are the kernel's own manoeuvre
 * cases, not named orbits — "low-orbit" is a circular parking orbit and
 * "elliptical" the loose capture ellipse a real orbiter enters first.
 */
export type EndpointMode = 'surface' | 'low-orbit' | 'elliptical' | 'flyby';

/** Modes each end can be in. Departure has no elliptical case — the injection
 *  burn is priced from a circular parking orbit — and only a destination can be
 *  flown past. */
export const ORIGIN_MODES: readonly EndpointMode[] = ['surface', 'low-orbit'];
export const TARGET_MODES: readonly EndpointMode[] = [
	'surface',
	'low-orbit',
	'elliptical',
	'flyby'
];

export type TravelStatus = 'idle' | 'solving' | 'ready' | 'empty' | 'blocked';

/** Why no trip can be offered at all, as opposed to no route being found. */
export type BlockReason = 'unknown-primary' | 'unknown-orbit' | 'no-target' | 'no-origin';

export class TravelPanelState {
	originMode = $state<EndpointMode>('surface');
	targetMode = $state<EndpointMode>('low-orbit');
	/** Set when an end is a named place on a surface — there is only one way to
	 *  arrive at one, so the mode is fixed and its picker is skipped. */
	originIsFeature = $state(false);
	targetIsFeature = $state(false);
	timeMode = $state<TimeMode>('now');
	/** Departure or arrival date behind the non-'now' time modes, as a JD. */
	pickedJd = $state<number | null>(null);
	vehicleId = $state<string | null>(null);
	/** What the trip carries. Costs no solve — mass moves no trajectory — so
	 *  these sit outside the effect that re-solves. */
	passengers = $state(0);
	payloadKg = $state(0);
	/** Null until a solve lands, then whichever profile the user last chose. */
	selectedProfile = $state<RouteProfile | null>(null);

	routes = $state<RouteChoice[]>([]);
	grid = $state<PorkchopGrid | null>(null);
	status = $state<TravelStatus>('idle');
	blocked = $state<BlockReason | null>(null);

	#solver = new TravelSolver();
	/** Guards against an older solve landing after a newer one. */
	#token = 0;

	get vehicle(): Vehicle | null {
		return findVehicle(this.vehicleId);
	}

	/** Pull the catalogue in. The panel calls this when it opens; the routes
	 *  solve without it, so nothing waits on the fetch. */
	loadVehicles(): Promise<void> {
		return ensureVehicles();
	}

	/** Arrival mode the kernel should price, from what the destination box says.
	 *  Landing somewhere named is still a landing, whatever the box last held. */
	get arrivalMode(): ArrivalMode {
		if (this.targetIsFeature) return 'landing';
		if (this.targetMode === 'flyby') return 'flyby';
		if (this.targetMode === 'surface') return 'landing';
		if (this.targetMode === 'elliptical') return 'capture';
		return 'low-orbit';
	}

	get departureMode(): DepartureMode {
		if (this.originIsFeature) return 'surface';
		return this.originMode === 'surface' ? 'surface' : 'orbit';
	}

	get selectedRoute(): Route | null {
		if (this.routes.length === 0) return null;
		const chosen = this.routes.find((r) => r.profile === this.selectedProfile);
		return (chosen ?? this.routes[0]).route;
	}

	/**
	 * Choose a craft, or clear it by choosing it again, and move the departure
	 * to one the craft can actually make.
	 *
	 * Picking an SLS while the origin box says "low orbit" means the box is
	 * wrong, not the choice: a launcher is the one thing that cannot already be
	 * up there. Left alone when the origin is a named place on a surface (there
	 * is only one way to leave one) or when the craft departs from nowhere.
	 */
	selectVehicle(id: string | null): void {
		this.vehicleId = this.vehicleId === id ? null : id;
		const vehicle = this.vehicle;
		if (!vehicle || this.originIsFeature) return;
		if (canDepartFrom(vehicle, this.departureMode)) return;
		if (canDepartFrom(vehicle, 'surface')) this.originMode = 'surface';
		else if (canDepartFrom(vehicle, 'orbit')) this.originMode = 'low-orbit';
	}

	get manifest(): Manifest {
		return { passengers: this.passengers, payloadKg: this.payloadKg };
	}

	/** Whether the chosen craft can fly a route loaded as described; null when
	 *  no craft is chosen. */
	feasibility(route: Route): Feasibility | null {
		const vehicle = this.vehicle;
		return vehicle ? checkFeasibility(vehicle, route, this.manifest) : null;
	}

	/** Whether the chosen craft has room for the manifest at all. Route-blind,
	 *  so it is reported beside the craft rather than on every trajectory. */
	get manifestFit(): ManifestFit | null {
		const vehicle = this.vehicle;
		return vehicle ? checkManifest(vehicle, this.manifest) : null;
	}

	/** Mark a trip impossible before any solve is attempted. */
	block(reason: BlockReason): void {
		this.#token++;
		this.blocked = reason;
		this.status = 'blocked';
		this.routes = [];
		this.grid = null;
	}

	/**
	 * Solve the current trip. Safe to call on every input change — the newest
	 * call wins and the rest are discarded when they land.
	 *
	 * `frame` says what the transfer goes round: nothing for an arc about the Sun,
	 * an end for a trip to that body's own moon, a μ for two moons of one planet.
	 */
	async solve(
		origin: TravelBody,
		target: TravelBody,
		nowJd: number,
		frame: TransferFrame = { orbit: 'heliocentric' }
	): Promise<void> {
		const options = searchWindow({
			origin,
			target,
			nowJd,
			timeMode: this.timeMode,
			pickedJd: this.pickedJd,
			systemPrimary: frame.systemPrimary,
			centralMu: frame.centralMu
		});
		if (!options) {
			console.debug(
				`[travel] no search window for ${origin.id} → ${target.id}: ` +
					`a=${origin.elements.a}/${target.elements.a}, e=${origin.elements.e}/${target.elements.e}`
			);
			this.block('unknown-orbit');
			return;
		}

		const token = ++this.#token;
		this.blocked = null;
		this.status = 'solving';

		const result = await this.#solver.solve(origin, target, {
			...options,
			departureMode: this.departureMode,
			arrivalMode: this.arrivalMode
		});

		// A newer solve has already started, or already answered.
		if (token !== this.#token) return;

		if (!result) {
			this.status = 'empty';
			return;
		}

		let routes = result.routes;
		// An arrival deadline is a filter on the answer, not on the search: the
		// grid still has to cover the departures that could meet it.
		if (this.timeMode === 'arrive' && this.pickedJd != null) {
			const deadline = this.pickedJd;
			routes = routes.filter((choice) => choice.route.arriveJd <= deadline);
		}

		this.routes = routes;
		this.grid = result.grid;
		this.status = routes.length > 0 ? 'ready' : 'empty';

		const stillOffered = routes.some((r) => r.profile === this.selectedProfile);
		if (!stillOffered) {
			const balanced = routes.find((r) => r.profile === 'balanced');
			this.selectedProfile = (balanced ?? routes[0])?.profile ?? null;
		}
	}

	dispose(): void {
		this.#token++;
		this.#solver.dispose();
	}
}
