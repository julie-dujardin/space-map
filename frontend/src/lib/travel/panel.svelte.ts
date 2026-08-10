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
	buildLowThrustRoute,
	buildRoute,
	canDepartFrom,
	checkFeasibility,
	checkManifest,
	constantThrustAccelMs2,
	lowThrustDrive,
	TravelSolver,
	type AeroAssist,
	type ArrivalMode,
	type DepartureMode,
	type EndOrbit,
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

/** What a body's atmosphere is worth to a price, as a key fragment. */
function air(body: TravelBody): string {
	return `${body.hasAtmosphere === true ? 1 : 0}/${body.surfacePressureBar ?? ''}`;
}

/**
 * How much cheaper a swing-by has to be before it is offered, km/s.
 *
 * Roughly what a Mars capture costs, and comfortably above the tens of metres
 * per second the two searches differ by on a route that is really the same one.
 */
const ASSIST_MIN_SAVING_KMS = 0.3;

export interface OfferedRoute {
	profile: RouteOption;
	route: Route;
}

/** Why no trip can be offered at all, as opposed to no route being found. */
export type BlockReason = 'unknown-primary' | 'unknown-orbit' | 'no-target' | 'no-origin';

export class TravelPanelState {
	originMode = $state<EndpointMode>(DEFAULT_TRIP.originMode);
	targetMode = $state<EndpointMode>(DEFAULT_TRIP.targetMode);
	originAltKm = $state(DEFAULT_TRIP.originAltKm);
	targetAltKm = $state(DEFAULT_TRIP.targetAltKm);
	/**
	 * The orbit each end is met in, km from the centre.
	 *
	 * Set by the component, because which orbits a body can hold takes the body's
	 * spin and its Hill radius — neither of which the kernel's `TravelBody`
	 * carries. Absent means the mode names no orbit, and the kernel falls back to
	 * the parking orbit it always used.
	 *
	 * Raw, and load-bearing: these ride into the solver worker inside the route
	 * options, and a deep `$state` proxy cannot be structured-cloned — the whole
	 * solve fails with a `DataCloneError`. They are replaced wholesale rather than
	 * written into, so there is nothing for the proxy to have earned.
	 */
	originOrbit = $state.raw<EndOrbit | undefined>(undefined);
	targetOrbit = $state.raw<EndOrbit | undefined>(undefined);
	/** What to ask of the destination's atmosphere. Held whatever the destination
	 *  is — the kernel ignores it where there is no atmosphere — so that moving
	 *  the trip to an airless body and back does not lose the choice. */
	aero = $state<AeroAssist>(DEFAULT_TRIP.aero);
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
	/**
	 * Whether the catalogue has settled, successfully or not.
	 *
	 * Empty means two different things before and after the fetch — "nothing
	 * loaded yet" and "nothing to load" — and every inference about the chosen
	 * craft is wrong in the first case. This is what tells them apart.
	 */
	vehiclesReady = $state(false);
	/** What the trip carries. Costs no solve — mass moves no trajectory — so
	 *  these sit outside the effect that re-solves. */
	passengers = $state(DEFAULT_TRIP.passengers);
	payloadKg = $state(DEFAULT_TRIP.payloadKg);
	/**
	 * The trajectory being read, or null while they are still being chosen between.
	 *
	 * This is the panel's two steps: nothing selected is the list of what is on
	 * offer, and a selection is that one trajectory in detail. So nothing here ever
	 * selects on the reader's behalf — a choice they did not make would put them in
	 * front of an answer to a question they had not finished asking.
	 */
	selectedProfile = $state<RouteOption | null>(DEFAULT_TRIP.profile);
	/** How much of the coast on offer the constant-thrust arc takes, 0 to 1. Kept
	 *  whatever the trip is, like the aero assist: a reader who chose to cross
	 *  gently has not changed their mind by changing destination. */
	coastFraction = $state(DEFAULT_TRIP.coastFraction);

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
	/** Set when there is an arc and it lands after the deadline. The arc is not
	 *  offered, but the coast is the one term that can cause this and the reader
	 *  needs it back to undo. */
	torchMissedDeadline = $state(false);
	/**
	 * The spiral, when the chosen craft is one that cannot burn.
	 *
	 * Comes off the craft the way the arc above does, and for the same reason:
	 * the trajectory an ion drive flies is a fact about the drive, not an option
	 * the porkchop offers. Unlike the arc it does have a departure date to find —
	 * the phase still has to close — but that is a bisection rather than a grid.
	 */
	spiral = $state<Route | null>(null);
	/**
	 * The cheapest route that swings past a third body, when one was found.
	 *
	 * Held raw rather than filtered: whether it is worth offering is a comparison
	 * against the direct routes, and those land on their own schedule. `offered`
	 * makes that call at read time so neither answer has to wait for the other.
	 */
	assist = $state<Route | null>(null);
	/** Whether a hunt is running. It takes about a second — long enough that
	 *  without saying so, "still looking" and "there isn't one" are the same
	 *  silence. */
	assistSearching = $state(false);
	grid = $state<PorkchopGrid | null>(null);
	status = $state<TravelStatus>('idle');
	blocked = $state<BlockReason | null>(null);

	#solver = new TravelSolver();
	/** Guards against an older solve landing after a newer one. */
	#token = 0;
	/** The same guard for the swing-by hunt, which runs on its own schedule and
	 *  takes about a second — long enough for two trips to have gone by. */
	#assistToken = 0;
	/** What the standing hunt was asked. A hunt costs a second and starting one
	 *  stops the last, so a caller that asks the same question twice would never
	 *  get an answer; this is what makes asking again free. */
	#assistFor: string | null = null;
	/** The last solve's inputs, so a hand-picked point is priced the same way the
	 *  grid it was read off was. */
	#pricing: { origin: TravelBody; target: TravelBody; options: RouteOptions } | null = null;
	/** A pick that arrived before there was a grid to price it against — off a
	 *  shared link — held until the first solve lands. */
	#pendingPick = $state<TripPick | null>(null);
	/** A trajectory a link named that nothing offers yet. Only the swing-by needs
	 *  this: it is the one option that arrives a second after the routes it is
	 *  listed beside, so the usual "drop a selection nothing offers" rule would
	 *  throw it away before the hunt that would have justified it came back. */
	#pendingProfile = $state<RouteOption | null>(null);

	/** Seeded from the URL, which is where a trip's terms live. */
	constructor(initial: TripState = DEFAULT_TRIP) {
		this.applyTrip(initial);
	}

	get vehicle(): Vehicle | null {
		return this.vehicles.find((v) => v.id === this.vehicleId) ?? null;
	}

	/**
	 * Whether the chosen craft is settled enough to reason about.
	 *
	 * A trip naming no craft is settled the moment it loads. One that names a
	 * craft is not settled until the catalogue is in, and anything concluding
	 * "this craft cannot do X" before then is answering about a craft it has not
	 * seen. Every such inference is gated on this.
	 */
	get craftKnown(): boolean {
		return this.vehicleId === null || this.vehiclesReady;
	}

	/** The trip as the URL carries it. The hand pick is reported whether or not a
	 *  solve has priced it, or a link would drop its own pick on the way in. */
	get trip(): TripState {
		return {
			originMode: this.originMode,
			targetMode: this.targetMode,
			originAltKm: this.originAltKm,
			targetAltKm: this.targetAltKm,
			aero: this.aero,
			timeMode: this.timeMode,
			pickedJd: this.pickedJd,
			vehicleId: this.vehicleId,
			passengers: this.passengers,
			payloadKg: this.payloadKg,
			// The link's own choice outranks the fallback taken while it is still
			// being looked for, or the URL loses what it was sent with.
			profile: this.#pendingProfile ?? this.selectedProfile,
			pick: this.custom
				? { departJd: this.custom.departJd, tofDays: this.custom.tofDays }
				: this.#pendingPick,
			coastFraction: this.coastFraction
		};
	}

	/** Take a trip's terms as given — a fresh load, or browser-back onto one.
	 *  Which end is a named place is not among them: that comes from the path. */
	applyTrip(trip: TripState): void {
		this.originMode = trip.originMode;
		this.targetMode = trip.targetMode;
		this.originAltKm = trip.originAltKm;
		this.targetAltKm = trip.targetAltKm;
		this.aero = trip.aero;
		this.timeMode = trip.timeMode;
		this.pickedJd = trip.pickedJd;
		this.vehicleId = trip.vehicleId;
		this.passengers = trip.passengers;
		this.payloadKg = trip.payloadKg;
		this.selectedProfile = trip.profile;
		this.#pendingProfile = trip.profile === 'gravity-assist' ? trip.profile : null;
		this.coastFraction = trip.coastFraction;
		this.custom = trip.pick ? this.#priceInGrid(trip.pick.departJd, trip.pick.tofDays) : null;
		this.#pendingPick = this.custom ? null : trip.pick;
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
		try {
			await ensureVehicles();
			this.acceptVehicles(vehicleCatalogue());
		} catch (e) {
			// A catalogue that will never arrive is still an answer. Leaving it
			// unsettled would hold every craft-dependent decision open for the rest
			// of the session, waiting for something that is not coming.
			console.warn('[travel] no spacecraft catalogue, judging no craft:', e);
			this.acceptVehicles([]);
		}
	}

	/**
	 * Take the catalogue and settle everything that was waiting on it.
	 *
	 * The terms of a trip cannot all be applied when the URL is read: two of them
	 * name things only this can resolve. So they are held as asked for, and
	 * answered here.
	 */
	acceptVehicles(list: readonly Vehicle[]): void {
		this.vehicles = list;
		this.vehiclesReady = true;
		this.#reconcileCraft();
	}

	/**
	 * Check what the URL asked for against the catalogue that has now landed.
	 *
	 * This is the whole reason the trip's terms cannot simply be applied once at
	 * load: two of them name things only the catalogue can resolve. A link is a
	 * request, and a request for a craft nobody ships, or for an arc that craft
	 * cannot fly, has to be answered rather than carried around.
	 */
	#reconcileCraft(): void {
		if (this.vehicleId !== null && this.vehicle === null) {
			console.debug(`[travel] no craft "${this.vehicleId}" in the catalogue — dropping it.`);
			this.vehicleId = null;
		}
		const vehicle = this.vehicle;
		// An arc held all the way is a claim about the drive, so a link naming one
		// for a craft that cannot hold it named a trip that does not exist.
		if (this.selectedProfile === 'constant-thrust') {
			if (!vehicle || constantThrustAccelMs2(vehicle) === undefined) {
				this.selectedProfile = null;
				this.torch = null;
			}
		}
		// And a spiral is a claim about a drive that cannot burn, so the same holds
		// for a link naming one beside a craft whose engine does.
		if (this.selectedProfile === 'low-thrust') {
			if (!vehicle || lowThrustDrive(vehicle, this.payloadKg) === undefined) {
				this.selectedProfile = null;
				this.spiral = null;
			}
		}
	}

	/** Arrival mode the kernel should price, from what the destination box says.
	 *  Landing somewhere named is still a landing, whatever the box last held. */
	get arrivalMode(): ArrivalMode {
		if (this.targetIsFeature) return 'landing';
		if (this.targetMode === 'flyby') return 'flyby';
		if (this.targetMode === 'surface') return 'landing';
		// Which of the two remaining cases is picked no longer sets the orbit —
		// `targetOrbit` does — but it still decides what an aerobraking campaign
		// starts from, and a loose ellipse has nothing to walk down.
		return this.targetMode === 'elliptical' ? 'capture' : 'low-orbit';
	}

	/** The orbits the kernel should price, as route options. A landing or a flyby
	 *  names none, and neither does an end whose body has not been measured yet. */
	get endOrbits(): Pick<RouteOptions, 'departureOrbit' | 'targetOrbit'> {
		return {
			departureOrbit: this.departureMode === 'surface' ? undefined : this.originOrbit,
			targetOrbit:
				this.arrivalMode === 'landing' || this.arrivalMode === 'flyby'
					? undefined
					: this.targetOrbit
		};
	}

	/** What the two orbits are worth to a cache key. */
	#orbitKey(): string {
		const { departureOrbit: d, targetOrbit: t } = this.endOrbits;
		const one = (o?: EndOrbit) => (o ? `${Math.round(o.rPeriKm)}/${Math.round(o.rApoKm)}` : '');
		return `${one(d)}|${one(t)}`;
	}

	get departureMode(): DepartureMode {
		if (this.originIsFeature) return 'surface';
		return this.originMode === 'surface' ? 'surface' : 'orbit';
	}

	/**
	 * Everything on offer.
	 *
	 * The hand-picked route goes last: it is an addition to the solver's answer
	 * rather than one of them. Whatever the craft's own drive flies goes first,
	 * because the craft it is offered for usually cannot fly the rest, and
	 * listing the one real answer under three trajectories that craft has to
	 * refuse would bury it.
	 */
	get offered(): OfferedRoute[] {
		const craftArc: OfferedRoute[] = [];
		if (this.torch) craftArc.push({ profile: 'constant-thrust', route: this.torch });
		if (this.spiral) craftArc.push({ profile: 'low-thrust', route: this.spiral });
		const offered: OfferedRoute[] = [...craftArc, ...this.routes];
		const assist = this.#assistWorthOffering();
		if (assist) offered.push({ profile: 'gravity-assist', route: assist });
		if (this.custom) offered.push({ profile: 'custom', route: this.custom });
		return offered;
	}

	/**
	 * The swing-by route, if it earns its place.
	 *
	 * It is only ever an alternative to going straight there, and it buys its Δv
	 * with years of extra travel and a departure date well outside the grid. So it
	 * is shown when it is genuinely cheaper than anything the direct search found
	 * and left out when it merely ties — an identical price for a decade more
	 * waiting is not a choice worth putting in front of anyone.
	 */
	#assistWorthOffering(): Route | null {
		const assist = this.assist;
		if (!assist || this.routes.length === 0) return null;
		const cheapest = Math.min(...this.routes.map((choice) => choice.route.totalDvKms));
		return assist.totalDvKms <= cheapest - ASSIST_MIN_SAVING_KMS ? assist : null;
	}

	/** The trajectory being read, with the name it is listed under. */
	get selected(): OfferedRoute | null {
		return this.offered.find((choice) => choice.profile === this.selectedProfile) ?? null;
	}

	get selectedRoute(): Route | null {
		return this.selected?.route ?? null;
	}

	/** Read one of the trajectories on offer. */
	choose(profile: RouteOption): void {
		this.selectedProfile = profile;
	}

	/** Go back to the ones on offer, reading none of them. */
	clearSelection(): void {
		this.selectedProfile = null;
	}

	/**
	 * Take a point read off the porkchop as a further trajectory on offer.
	 *
	 * It joins the list rather than being read straight away: picking is a drag,
	 * and every point crossed on the way would otherwise replace the list with the
	 * detail of a trajectory nobody stopped on.
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
		// The arc is entirely a fact about the craft, so there is nothing to say
		// about it until the catalogue naming that craft is in. A pass taken during
		// the wait would find no craft, conclude there is no arc, and take a shared
		// link's own trajectory away from it.
		if (!this.craftKnown) return;

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
					...this.endOrbits,
					aero: this.aero,
					centralMu: frame.centralMu,
					systemPrimary: frame.systemPrimary,
					coastFraction: this.coastFraction
				})
			: null;
		const missesDeadline =
			this.timeMode === 'arrive' && this.pickedJd != null && arc !== null
				? arc.arriveJd > this.pickedJd
				: false;

		const offer = missesDeadline ? null : arc;
		this.torch = offer;
		this.torchMissedDeadline = missesDeadline;
		// The arc leads the list when a craft can hold it, but is never selected on
		// the reader's behalf: a torch ship can fly the coasting routes too, and
		// choosing between them is the step this would skip.
		if (!offer && this.selectedProfile === 'constant-thrust') this.selectedProfile = null;
	}

	/**
	 * Recompute the spiral for the craft and the trip as they stand.
	 *
	 * A sibling of `updateTorch` in every structural way — it comes off the craft
	 * rather than the search, it costs a bisection rather than a grid, and it
	 * never reads its own answer back. What differs is the date: a spiral does
	 * have to wait for the phase to close, so the date asked for is the earliest
	 * it may leave rather than the date it leaves.
	 *
	 * The manifest is an input here and nowhere else. Cargo makes a spiral slower
	 * as well as shorter of Δv, because the drive is pushing it too.
	 */
	updateSpiral(
		origin: TravelBody,
		target: TravelBody,
		nowJd: number,
		frame: TransferFrame = { orbit: 'heliocentric' }
	): void {
		if (!this.craftKnown) return;

		const vehicle = this.vehicle;
		const drive = vehicle ? lowThrustDrive(vehicle, this.payloadKg) : undefined;
		const earliestJd =
			this.timeMode === 'depart' && this.pickedJd != null ? Math.max(nowJd, this.pickedJd) : nowJd;
		const route = drive
			? buildLowThrustRoute(origin, target, earliestJd, drive, {
					departureMode: this.departureMode,
					arrivalMode: this.arrivalMode,
					...this.endOrbits,
					aero: this.aero,
					centralMu: frame.centralMu,
					systemPrimary: frame.systemPrimary
				})
			: null;
		const missesDeadline =
			this.timeMode === 'arrive' && this.pickedJd != null && route !== null
				? route.arriveJd > this.pickedJd
				: false;

		const offer = missesDeadline ? null : route;
		this.spiral = offer;
		// Offered, never opened: an ion craft can be compared against the coasting
		// routes, and choosing between them is the step an auto-selection skips.
		if (!offer && this.selectedProfile === 'low-thrust') this.selectedProfile = null;
	}

	/**
	 * Look for a route that swings past one of `vias`, and hold whatever comes
	 * back.
	 *
	 * Its own method for the same reason `updateTorch` is: it answers to a
	 * different question than the porkchop and on a different timescale — a second
	 * or so in the worker, against a grid that lands immediately — so the panel
	 * shows the direct routes and lets this fill in behind them.
	 *
	 * It only ever adds a row to the list. A trajectory that appeared a second late
	 * and took the reader off the one they had opened would be reading their mind
	 * about a comparison they had already made.
	 */
	async updateAssist(
		origin: TravelBody,
		target: TravelBody,
		vias: TravelBody[],
		nowJd: number,
		options: RouteOptions = {}
	): Promise<void> {
		// Ids and modes rather than the bodies themselves: the elements behind them
		// are the scene's, and the scene rewrites them as its clock runs. The planner
		// already reasons from a snapshotted "now", so the same trip asked again is
		// the same question however far the planets have moved since.
		//
		// The exception is the air, which is why it is spelled out here: whether an
		// end has an atmosphere comes from a detail bundle that lands *after* the
		// first hunt, and it moves an arrival by ten kilometres per second. Keyed on
		// ids alone, the answer to "airless Saturn" would stand for the rest of the
		// session while the routes beside it were priced with the aerocapture.
		const key = [
			origin.id,
			target.id,
			air(origin),
			air(target),
			vias.map((via) => via.id).join(','),
			nowJd,
			this.departureMode,
			this.arrivalMode,
			this.#orbitKey(),
			this.aero,
			options.centralMu ?? ''
		].join('|');
		if (key === this.#assistFor) return;
		this.#assistFor = key;

		const token = ++this.#assistToken;
		this.assistSearching = true;
		const route = await this.#solver.findAssist(origin, target, vias, {
			...options,
			nowJd,
			departureMode: this.departureMode,
			arrivalMode: this.arrivalMode,
			...this.endOrbits,
			// Load-bearing: the hunt is only ever compared against the direct routes,
			// so an arrival priced on a different braking mode than theirs is not a
			// comparison at all — it reads as a swing-by that saves nothing.
			aero: this.aero
		});
		// A newer hunt has replaced this one; it owns the flag now.
		if (token !== this.#assistToken) return;
		this.assistSearching = false;
		this.assist = route;
		this.#settleSelection(true);
	}

	/** Drop the swing-by, and anything still looking for one. */
	clearAssist(): void {
		this.#assistToken++;
		this.#assistFor = null;
		this.assistSearching = false;
		this.assist = null;
		if (this.selectedProfile === 'gravity-assist') this.selectedProfile = null;
	}

	/**
	 * Settle which trajectory is being read, now that what is offered has changed.
	 *
	 * Only ever retires a selection — a trajectory that stopped being offered puts
	 * the reader back in front of the ones that are. Nothing is chosen in its place;
	 * that is theirs to do.
	 *
	 * Two things a link can name arrive later than the routes do — the swing-by,
	 * which is still being hunted, and the constant-thrust arc, which waits on the
	 * craft catalogue — and neither may be retired by a search that knows nothing
	 * about it. `huntSettled` is the hunt saying it has answered.
	 */
	#settleSelection(huntSettled = false): void {
		const wanted = this.#pendingProfile;
		if (wanted) {
			if (this.offered.some((choice) => choice.profile === wanted)) {
				this.selectedProfile = wanted;
				this.#pendingProfile = null;
			} else if (huntSettled) {
				// It has had its turn: the link named a trajectory this pair does not
				// have, and from here it falls back like any other.
				this.#pendingProfile = null;
			} else {
				return;
			}
		}
		// A search says nothing about the two trajectories that come off the craft
		// rather than the grid, so it cannot retire a selection whose craft has yet
		// to land.
		const fromCraft =
			this.selectedProfile === 'constant-thrust' || this.selectedProfile === 'low-thrust';
		if (fromCraft && !this.craftKnown) return;
		if (
			this.selectedProfile !== null &&
			!this.offered.some((choice) => choice.profile === this.selectedProfile)
		) {
			this.selectedProfile = null;
		}
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
		this.torchMissedDeadline = false;
		this.spiral = null;
		this.assist = null;
		this.assistSearching = false;
		this.#assistToken++;
		this.#assistFor = null;
		this.#pendingProfile = null;
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
			arrivalMode: this.arrivalMode,
			...this.endOrbits,
			aero: this.aero
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

		this.#settleSelection();
	}

	dispose(): void {
		this.#token++;
		this.#solver.dispose();
	}
}
