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
	buildConstantThrustRoute,
	buildRoute,
	canDepartFrom,
	checkFeasibility,
	checkManifest,
	constantThrustAccelMs2,
	TravelSolver,
	type ArrivalMode,
	type DepartureMode,
	type Feasibility,
	type Manifest,
	type ManifestFit,
	type PorkchopGrid,
	type Route,
	type RouteChoice,
	type RouteOptions,
	type TravelBody,
	type Vehicle
} from '$lib/math/travel';
import { ensureVehicles, vehicleCatalogue } from './vehicles';
import { searchWindow } from './search-window';
import {
	DEFAULT_TRIP,
	type EndpointMode,
	type RouteOption,
	type TimeMode,
	type TripPick,
	type TripState
} from './trip';
import type { TransferFrame } from './travel-body';

export type TravelStatus = 'idle' | 'solving' | 'ready' | 'empty' | 'blocked';

export interface OfferedRoute {
	profile: RouteOption;
	route: Route;
}

/** Why no trip can be offered at all, as opposed to no route being found. */
export type BlockReason = 'unknown-primary' | 'unknown-orbit' | 'no-target' | 'no-origin';

export class TravelPanelState {
	originMode = $state<EndpointMode>(DEFAULT_TRIP.originMode);
	targetMode = $state<EndpointMode>(DEFAULT_TRIP.targetMode);
	/** Set when an end is a named place on a surface — there is only one way to
	 *  arrive at one, so the mode is fixed and its picker is skipped. Comes from
	 *  the path rather than the trip's terms, so it is not part of `trip`. */
	originIsFeature = $state(false);
	targetIsFeature = $state(false);
	timeMode = $state<TimeMode>(DEFAULT_TRIP.timeMode);
	/** Departure or arrival date behind the non-'now' time modes, as a JD. */
	pickedJd = $state<number | null>(DEFAULT_TRIP.pickedJd);
	vehicleId = $state<string | null>(DEFAULT_TRIP.vehicleId);
	/** The fetched catalogue; empty until `loadVehicles` lands. */
	vehicles = $state<readonly Vehicle[]>([]);
	/** What the trip carries. Costs no solve — mass moves no trajectory — so
	 *  these sit outside the effect that re-solves. */
	passengers = $state(DEFAULT_TRIP.passengers);
	payloadKg = $state(DEFAULT_TRIP.payloadKg);
	/** Null until a solve lands, then whichever route the user last chose. */
	selectedProfile = $state<RouteOption | null>(DEFAULT_TRIP.profile);

	routes = $state<RouteChoice[]>([]);
	/** A point picked off the porkchop, priced like any solved route. */
	custom = $state<Route | null>(null);
	/**
	 * The constant-thrust arc, when the chosen craft has an acceleration to hold.
	 *
	 * Comes out of the craft rather than out of the search, and costs one
	 * bisection rather than a grid, so it never goes near the worker.
	 */
	torch = $state<Route | null>(null);
	grid = $state<PorkchopGrid | null>(null);
	status = $state<TravelStatus>('idle');
	blocked = $state<BlockReason | null>(null);

	#solver = new TravelSolver();
	/** Guards against an older solve landing after a newer one. */
	#token = 0;
	/** Which craft the standing arc was built for, so choosing a new one selects
	 *  its arc and everything else leaves the selection alone. */
	#torchFor: string | null = null;
	/** The last solve's inputs, so a hand-picked point is priced the same way the
	 *  grid it was read off was. */
	#pricing: { origin: TravelBody; target: TravelBody; options: RouteOptions } | null = null;
	/** A pick that arrived before there was a grid to price it against — off a
	 *  shared link — held until the first solve lands. */
	#pendingPick = $state<TripPick | null>(null);

	/** Seeded from the URL, which is where a trip's terms live. */
	constructor(initial: TripState = DEFAULT_TRIP) {
		this.applyTrip(initial);
	}

	get vehicle(): Vehicle | null {
		return this.vehicles.find((v) => v.id === this.vehicleId) ?? null;
	}

	/** The trip as the URL carries it. The hand pick is reported whether or not a
	 *  solve has priced it, or a link would drop its own pick on the way in. */
	get trip(): TripState {
		return {
			originMode: this.originMode,
			targetMode: this.targetMode,
			timeMode: this.timeMode,
			pickedJd: this.pickedJd,
			vehicleId: this.vehicleId,
			passengers: this.passengers,
			payloadKg: this.payloadKg,
			profile: this.selectedProfile,
			pick: this.custom
				? { departJd: this.custom.departJd, tofDays: this.custom.tofDays }
				: this.#pendingPick
		};
	}

	/** Take a trip's terms as given — a fresh load, or browser-back onto one.
	 *  Which end is a named place is not among them: that comes from the path. */
	applyTrip(trip: TripState): void {
		this.originMode = trip.originMode;
		this.targetMode = trip.targetMode;
		this.timeMode = trip.timeMode;
		this.pickedJd = trip.pickedJd;
		this.vehicleId = trip.vehicleId;
		this.passengers = trip.passengers;
		this.payloadKg = trip.payloadKg;
		this.selectedProfile = trip.profile;
		this.custom = trip.pick ? this.#priceInGrid(trip.pick.departJd, trip.pick.tofDays) : null;
		this.#pendingPick = this.custom ? null : trip.pick;
		// A link naming both a craft and a trajectory has already made the choice
		// `updateTorch` makes on the reader's behalf, so the arc has had its turn
		// at the selection: arriving with a torch ship is not the same as picking
		// one, and a shared "fast" is a comparison someone meant to send.
		this.#torchFor = trip.profile !== null ? trip.vehicleId : null;
	}

	/**
	 * Pull the catalogue in. Called when the picker opens, and on load when a
	 * link already names a craft. The routes solve without it, so nothing waits
	 * on the fetch.
	 *
	 * The catalogue is held here rather than read from the module on demand: it
	 * lands after first paint, and a plain array is nothing a rune watches — a
	 * `vehicle` read off one would keep answering null long after the fetch.
	 */
	async loadVehicles(): Promise<void> {
		await ensureVehicles();
		this.vehicles = vehicleCatalogue();
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

	/**
	 * Everything on offer.
	 *
	 * The hand-picked route goes last: it is an addition to the solver's answer
	 * rather than one of them. The constant-thrust arc goes first, because the
	 * only craft it is ever offered for is one that can fly nothing else, and
	 * listing it under three trajectories that craft cannot fly would bury the
	 * only answer.
	 */
	get offered(): OfferedRoute[] {
		const offered: OfferedRoute[] = this.torch
			? [{ profile: 'constant-thrust', route: this.torch }, ...this.routes]
			: [...this.routes];
		if (this.custom) offered.push({ profile: 'custom', route: this.custom });
		return offered;
	}

	get selectedRoute(): Route | null {
		const offered = this.offered;
		if (offered.length === 0) return null;
		const chosen = offered.find((r) => r.profile === this.selectedProfile);
		return (chosen ?? offered[0]).route;
	}

	/**
	 * Take a point read off the porkchop as the route to fly.
	 *
	 * A point with no arc through it leaves the previous pick standing: the field
	 * has unsolved cells in it, and clearing the choice because a drag crossed one
	 * would make the picker fight the user.
	 */
	pickCustom(departJd: number, tofDays: number): void {
		const route = this.#price(departJd, tofDays);
		if (!route) return;
		this.custom = route;
		this.#pendingPick = null;
		this.selectedProfile = 'custom';
	}

	#price(departJd: number, tofDays: number): Route | null {
		if (!this.#pricing) return null;
		const { origin, target, options } = this.#pricing;
		return buildRoute(origin, target, departJd, tofDays, options);
	}

	/** Price a point only where the chart can still place it. */
	#priceInGrid(departJd: number, tofDays: number): Route | null {
		const grid = this.grid;
		if (!grid) return null;
		const inGrid =
			departJd >= grid.departJds[0] &&
			departJd <= grid.departJds[grid.departSteps - 1] &&
			tofDays >= grid.tofDays[0] &&
			tofDays <= grid.tofDays[grid.tofSteps - 1];
		return inGrid ? this.#price(departJd, tofDays) : null;
	}

	/**
	 * Carry a hand-picked point across a re-solve, re-priced.
	 *
	 * Changing a mode or a date is a change to what the same trip costs, so the
	 * point survives it. Changing an end is a different trip, and a point outside
	 * the new grid is one the chart can no longer place.
	 */
	#repriceCustom(): Route | null {
		const previous = this.custom;
		if (!previous || !this.#pricing) return null;
		const { origin, target } = this.#pricing;
		if (previous.departureId !== origin.id || previous.targetId !== target.id) return null;
		return this.#priceInGrid(previous.departJd, previous.tofDays);
	}

	/** Price the pick a shared link arrived with, now that there is a grid. It
	 *  gets the one attempt: if the trip it named is not in this grid, the link
	 *  described a window this pair no longer has. */
	#pricePendingPick(): Route | null {
		const pending = this.#pendingPick;
		if (!pending) return null;
		this.#pendingPick = null;
		return this.#priceInGrid(pending.departJd, pending.tofDays);
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

	/**
	 * Recompute the constant-thrust arc for the craft and the trip as they stand.
	 *
	 * Called on its own rather than from `solve`, because the two answer to
	 * different things: choosing a craft is not a new search, and a new search
	 * does not change how hard that craft's drive pushes.
	 *
	 * Nothing below reads `this.torch` back. This runs inside an effect, and the
	 * arc is a fresh object every time, so reading it here would make the effect
	 * depend on a value it had just replaced with an unequal one — which is not a
	 * slow solve but an endless one.
	 */
	updateTorch(
		origin: TravelBody,
		target: TravelBody,
		nowJd: number,
		frame: TransferFrame = { orbit: 'heliocentric' }
	): void {
		const vehicle = this.vehicle;
		const accelMs2 = vehicle ? constantThrustAccelMs2(vehicle) : undefined;
		// Every departure date flies the same arc, so the only thing a date says is
		// when to start counting. A deadline says nothing at all until it is met.
		const departJd =
			this.timeMode === 'depart' && this.pickedJd != null ? Math.max(nowJd, this.pickedJd) : nowJd;
		const arc = accelMs2
			? buildConstantThrustRoute(origin, target, departJd, accelMs2, {
					departureMode: this.departureMode,
					arrivalMode: this.arrivalMode,
					centralMu: frame.centralMu,
					systemPrimary: frame.systemPrimary
				})
			: null;
		const missesDeadline =
			this.timeMode === 'arrive' && this.pickedJd != null && arc !== null
				? arc.arriveJd > this.pickedJd
				: false;

		const offer = missesDeadline ? null : arc;
		this.torch = offer;
		if (offer && this.#torchFor !== this.vehicleId) {
			// The arc is the answer a torch ship is chosen for, so it is selected the
			// moment one is — but only then. These craft can fly the coasting routes
			// too, and re-selecting the arc under a reader comparing it against them
			// would take the comparison away.
			this.selectedProfile = 'constant-thrust';
		} else if (!offer && this.#craftKnown && this.selectedProfile === 'constant-thrust') {
			this.selectedProfile = this.#fallbackProfile();
		}
		if (this.#craftKnown) this.#torchFor = offer ? this.vehicleId : null;
	}

	/**
	 * Whether the chosen craft is settled — nothing chosen, the entry in hand, or
	 * a catalogue that has landed without it.
	 *
	 * The catalogue is fetched, so a link naming a craft is read before it lands,
	 * and everything about that craft is unanswerable until it does. The arc it
	 * would fly is the one trajectory that comes off the craft rather than out of
	 * the search, so a pass taken during the wait must not conclude there is no
	 * such trajectory: the whole point of the wait is that nobody knows yet.
	 */
	get #craftKnown(): boolean {
		return this.vehicleId === null || this.vehicle !== null || this.vehicles.length > 0;
	}

	/** The trajectory to fall back on when the selected one stops being offered. */
	#fallbackProfile(): RouteOption | null {
		const balanced = this.routes.find((r) => r.profile === 'balanced');
		return (balanced ?? this.routes[0])?.profile ?? null;
	}

	/** Mark a trip impossible before any solve is attempted. */
	block(reason: BlockReason): void {
		this.#token++;
		this.blocked = reason;
		this.status = 'blocked';
		this.routes = [];
		this.grid = null;
		this.custom = null;
		this.torch = null;
		this.#pricing = null;
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

		const solveOptions = {
			...options,
			departureMode: this.departureMode,
			arrivalMode: this.arrivalMode
		};
		const result = await this.#solver.solve(origin, target, solveOptions);

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
		this.#pricing = { origin, target, options: solveOptions };
		this.custom = this.#repriceCustom() ?? this.#pricePendingPick();
		this.status = this.offered.length > 0 ? 'ready' : 'empty';

		// A search says nothing about the constant-thrust arc — that comes off the
		// craft — so it cannot retire a selection whose craft has yet to land.
		const awaitingTorch = this.selectedProfile === 'constant-thrust' && !this.#craftKnown;
		if (!awaitingTorch && !this.offered.some((r) => r.profile === this.selectedProfile)) {
			this.selectedProfile = this.#fallbackProfile();
		}
	}

	dispose(): void {
		this.#token++;
		this.#solver.dispose();
	}
}
