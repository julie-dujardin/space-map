/**
 * State behind the travel panel: the trip you are describing, and the routes
 * that come back.
 *
 * Solving is an explicit method rather than an effect inside the class — the
 * component owns the effect, so the reads that should trigger a re-solve stay
 * visible in one place instead of hidden behind a self-feeding async write.
 * Superseded solves are dropped by token, so a fast destination change can't
 * be overwritten by the answer to the previous one.
 */

import {
	arrivalCampaignDays,
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
	routeEndJd,
	type Route,
	type RouteChoice,
	type RouteOptions,
	type TravelBody,
	type Vehicle
} from '$lib/math/travel';
import { ensureVehicles, vehicleCatalogue } from './vehicles';
import { searchWindow } from './search-window';
import { listedTorchArcs, TORCH_PRESETS, type TorchArc } from './torch-arcs';
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
	return `${body.aeroPressurePa ?? ''}/${body.aeroScaleHeightKm ?? ''}/${body.surfacePressureBar ?? ''}`;
}

/** How much cheaper a swing-by has to be before it's offered, km/s. Roughly
 *  what a Mars capture costs, comfortably above the tens of m/s two searches
 *  differ by on a route that's really the same one. */
const ASSIST_MIN_SAVING_KMS = 0.3;

export interface OfferedRoute {
	profile: RouteOption;
	route: Route;
}

/** Why no trip can be offered at all, as opposed to no route being found. */
export type BlockReason = 'unknown-primary' | 'unknown-orbit' | 'no-target' | 'no-origin';

/**
 * A better description of one end at a date the search has landed on, or null
 * when the one in hand is already good for it.
 *
 * Planets keep the same ellipse for centuries; a probe doesn't. What describes
 * one is a fit over a window of weeks, and a transfer takes years — so a trip
 * planned against today's fit aims at where a long-expired ellipse says the
 * probe will be, nowhere near where it will. This is how the search asks
 * again at the dates its own answer names.
 */
export type RefineEnd = (role: 'origin' | 'target', jd: number) => Promise<TravelBody | null>;

/** How many times a search may be re-run against elements read at its own
 *  answer's dates. A pass is a whole porkchop, the ceiling on what a
 *  correction may cost. Two converge a crossing inside one fit; the third is
 *  for an answer moving far enough to land in a different one. */
const MAX_REFINE_PASSES = 3;

/** How little the dates have to move for a further pass to be answering the
 *  same question. Well under the day a porkchop cell spans. */
const REFINE_SETTLED_DAYS = 0.5;

/** When a trip leaves and when it arrives, as the search has it. */
interface TripDates {
	departJd: number;
	arriveJd: number;
}

/** The dates of the cheapest route on offer, or null when none came back. */
function cheapestDates(routes: readonly RouteChoice[]): TripDates | null {
	let best: RouteChoice | null = null;
	for (const choice of routes) {
		if (!best || choice.route.totalDvKms < best.route.totalDvKms) best = choice;
	}
	return best ? { departJd: best.route.departJd, arriveJd: best.route.arriveJd } : null;
}

/** The furthest either date moved between two passes, in days. */
function moved(a: TripDates, b: TripDates): number {
	return Math.max(Math.abs(a.departJd - b.departJd), Math.abs(a.arriveJd - b.arriveJd));
}

export class TravelPanelState {
	originMode = $state<EndpointMode>(DEFAULT_TRIP.originMode);
	targetMode = $state<EndpointMode>(DEFAULT_TRIP.targetMode);
	originAltKm = $state(DEFAULT_TRIP.originAltKm);
	targetAltKm = $state(DEFAULT_TRIP.targetAltKm);
	/**
	 * The orbit each end is met in, km from the centre.
	 *
	 * Set by the component: which orbits a body can hold takes its spin and Hill
	 * radius, neither of which the kernel's `TravelBody` carries. Absent means
	 * the mode names no orbit, and the kernel falls back to the parking orbit.
	 *
	 * Raw, and load-bearing: these ride into the solver worker inside the route
	 * options, and a deep `$state` proxy can't be structured-cloned — the solve
	 * would fail with a `DataCloneError`. Replaced wholesale rather than written
	 * into, so there's nothing for the proxy to have earned.
	 */
	originOrbit = $state.raw<EndOrbit | undefined>(undefined);
	targetOrbit = $state.raw<EndOrbit | undefined>(undefined);
	/** What to ask of the destination's atmosphere. Held whatever the destination
	 *  is — the kernel ignores it where there is no atmosphere — so that moving
	 *  the trip to an airless body and back does not lose the choice. Pricing
	 *  reads `effectiveAero`, which is this choice as the arrival can honour it. */
	aero = $state<AeroAssist>(DEFAULT_TRIP.aero);
	/** Set when an end is a place on a surface — a named feature, or a probe
	 *  parked on one. There is only one way to arrive at a place, so the mode is
	 *  fixed and its picker is skipped. Comes from what the end resolves to
	 *  rather than from the trip's terms, so it is not part of `trip`. */
	originAtSite = $state(false);
	targetAtSite = $state(false);
	/** Latitude of that place, degrees, once it has been looked up — what the
	 *  ascent or the descent is charged against. Null while it is still coming,
	 *  which prices the end as the equatorial launch the estimates are fitted on. */
	originSiteLatDeg = $state<number | null>(null);
	targetSiteLatDeg = $state<number | null>(null);
	timeMode = $state<TimeMode>(DEFAULT_TRIP.timeMode);
	/** Departure or arrival date behind the non-'now' time modes, as a JD. */
	pickedJd = $state<number | null>(DEFAULT_TRIP.pickedJd);
	vehicleId = $state<string | null>(DEFAULT_TRIP.vehicleId);
	/** The fetched catalogue; empty until `loadVehicles` lands. */
	vehicles = $state<readonly Vehicle[]>([]);
	/** Whether the catalogue has settled, successfully or not. Empty means two
	 *  different things before and after the fetch — "nothing loaded yet" and
	 *  "nothing to load" — and this is what tells them apart. */
	vehiclesReady = $state(false);
	/** What the trip carries. Costs no solve — mass moves no trajectory — so
	 *  these sit outside the effect that re-solves. */
	passengers = $state(DEFAULT_TRIP.passengers);
	payloadKg = $state(DEFAULT_TRIP.payloadKg);
	/** The trajectory being read, or null while they're still being chosen
	 *  between — the panel's two steps. Nothing here ever selects on the
	 *  reader's behalf: a choice they didn't make would put them in front of an
	 *  answer to a question they hadn't finished asking. */
	selectedProfile = $state<RouteOption | null>(DEFAULT_TRIP.profile);
	/** How much of the coast on offer the constant-thrust arc takes, 0 to 1. Kept
	 *  whatever the trip is, like the aero assist: a reader who chose to cross
	 *  gently has not changed their mind by changing destination. */
	coastFraction = $state(DEFAULT_TRIP.coastFraction);

	routes = $state<RouteChoice[]>([]);
	/** A point picked off the porkchop, priced like any solved route. */
	custom = $state<Route | null>(null);
	/** The preset constant-thrust arcs, flat out first. From the craft, not the
	 *  search, and cost one shooting solve each. */
	torchPresets = $state<TorchArc[]>([]);
	/** The arc the cruise slider asks for. Kept apart from the presets because it
	 *  is solved on its own. A drag must not cost four solves a frame. */
	torchCustom = $state<TorchArc | null>(null);
	/** Set when arcs exist and all of them land after the deadline. None is
	 *  offered. The reader still needs the slider to undo the coast. */
	torchMissedDeadline = $state(false);
	/** The spiral, when the chosen craft can't burn. Comes off the craft like
	 *  the arc above, and for the same reason: the trajectory an ion drive flies
	 *  is a fact about the drive, not an option the porkchop offers. Unlike the
	 *  arc it does have a departure date to find — the phase has to close — but
	 *  that's a bisection rather than a grid. */
	spiral = $state<Route | null>(null);
	/** The cheapest route that swings past a third body, when one was found.
	 *  Held raw rather than filtered: whether it's worth offering is a
	 *  comparison against the direct routes, which land on their own schedule.
	 *  `offered` makes that call at read time so neither has to wait. */
	assist = $state<Route | null>(null);
	/** Whether a hunt is running. Takes about a second — long enough that
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
	 *  stops the last, so this is what makes asking the same question twice free. */
	#assistFor: string | null = null;
	/** The last solve's inputs, so a hand-picked point is priced the same way
	 *  the grid it was read off was. Reactive because the ends in it are also
	 *  what the trajectory is drawn from — see {@link pricedEnds}. */
	#pricing = $state<{ origin: TravelBody; target: TravelBody; options: RouteOptions } | null>(null);
	/** A pick that arrived before there was a grid to price it against — off a
	 *  shared link — held until the first solve lands. */
	#pendingPick = $state<TripPick | null>(null);
	/** A trajectory a link named that nothing offers yet. Only the swing-by
	 *  needs this: it arrives a second after the routes it's listed beside, so
	 *  the usual "drop a selection nothing offers" rule would throw it away
	 *  before the hunt that would have justified it came back. */
	#pendingProfile = $state<RouteOption | null>(null);

	/** Seeded from the URL, which is where a trip's terms live. */
	constructor(initial: TripState = DEFAULT_TRIP) {
		this.applyTrip(initial);
	}

	get vehicle(): Vehicle | null {
		return this.vehicles.find((v) => v.id === this.vehicleId) ?? null;
	}

	/** Whether the chosen craft is settled enough to reason about. A trip naming
	 *  no craft is settled the moment it loads; one that does isn't settled
	 *  until the catalogue is in, and anything concluding "this craft can't do
	 *  X" before then is answering about a craft it hasn't seen. Every such
	 *  inference is gated on this. */
	get craftKnown(): boolean {
		return this.vehicleId === null || this.vehiclesReady;
	}

	/** The two ends the standing routes were priced against, which for anything
	 *  that doesn't keep still aren't the ends the caller handed in: a refined
	 *  pass describes each at the trip's own dates. Null until a solve lands.
	 *  Everything drawn from a route has to come off these — geometry rebuilt
	 *  from another description of the same body is a picture of a different
	 *  trip. */
	get pricedEnds(): { origin: TravelBody; target: TravelBody } | null {
		const pricing = this.#pricing;
		return pricing ? { origin: pricing.origin, target: pricing.target } : null;
	}

	/** How many times {@link pricedEnds} has been replaced. A refined pass can
	 *  re-describe an end without moving a single date, so a caller keyed on
	 *  what a route says has no other way to notice. */
	pricedRevision = $state(0);

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
	 *  Which end is a named place isn't among them: that comes from the path. */
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
	 * Held here rather than read from the module on demand: it lands after
	 * first paint, and a plain array is nothing a rune watches — a `vehicle`
	 * read off one would keep answering null long after the fetch.
	 */
	async loadVehicles(): Promise<void> {
		try {
			await ensureVehicles();
			this.acceptVehicles(vehicleCatalogue());
		} catch (e) {
			// A catalogue that will never arrive is still an answer. Leaving it
			// unsettled would hold every craft-dependent decision open for the
			// rest of the session, waiting for something that isn't coming.
			console.warn('[travel] no spacecraft catalogue, judging no craft:', e);
			this.acceptVehicles([]);
		}
	}

	/** Take the catalogue and settle everything that was waiting on it. Two of a
	 *  trip's terms can't be applied when the URL is read, since only the
	 *  catalogue can resolve them, so they're held as asked for and answered
	 *  here. */
	acceptVehicles(list: readonly Vehicle[]): void {
		this.vehicles = list;
		this.vehiclesReady = true;
		this.#reconcileCraft();
	}

	/** Check what the URL asked for against the catalogue that has now landed.
	 *  A link is a request, and a request for a craft nobody ships, or for an
	 *  arc that craft can't fly, has to be answered rather than carried around. */
	#reconcileCraft(): void {
		if (this.vehicleId !== null && this.vehicle === null) {
			console.debug(`[travel] no craft "${this.vehicleId}" in the catalogue — dropping it.`);
			this.vehicleId = null;
		}
		const vehicle = this.vehicle;
		// An arc held all the way is a claim about the drive, so a link naming
		// one for a craft that can't hold it named a trip that doesn't exist.
		if (this.selectedProfile?.startsWith('constant-thrust')) {
			if (!vehicle || constantThrustAccelMs2(vehicle) === undefined) {
				this.selectedProfile = null;
				this.torchPresets = [];
				this.torchCustom = null;
			}
		}
		// And a spiral is a claim about a drive that can't burn, so the same
		// holds for a link naming one beside a craft whose engine does.
		if (this.selectedProfile === 'low-thrust') {
			if (!vehicle || lowThrustDrive(vehicle, this.payloadKg) === undefined) {
				this.selectedProfile = null;
				this.spiral = null;
			}
		}
	}

	/** Whether aerobraking is an arrival this trip can fly: it walks a loose
	 *  orbit into a tight one, so only a low-orbit arrival has one to walk. A
	 *  site is a landing whatever the picker last held. */
	get aerobrakingApplies(): boolean {
		return this.targetMode === 'low-orbit' && !this.targetAtSite;
	}

	/** The braking the trip is actually priced with. `aero` is the choice as
	 *  made, held across destination changes so it isn't lost to a detour; this
	 *  is what that choice means for the arrival at hand. A trip that was
	 *  aerobraking and is now landing isn't braking at all until it says so
	 *  again — pricing the raw value would grow a landing a months-long
	 *  campaign the control says isn't there. */
	get effectiveAero(): AeroAssist {
		return this.aero === 'aerobraking' && !this.aerobrakingApplies ? 'none' : this.aero;
	}

	/** Arrival mode the kernel should price, from what the destination box says.
	 *  Landing on a site is still a landing, whatever the box last held. */
	get arrivalMode(): ArrivalMode {
		if (this.targetAtSite) return 'landing';
		if (this.targetMode === 'flyby') return 'flyby';
		if (this.targetMode === 'surface') return 'landing';
		// The remaining case no longer sets the orbit — `targetOrbit` does — but
		// still decides what an aerobraking campaign starts from, and a loose
		// ellipse has nothing to walk down.
		return this.targetMode === 'elliptical' ? 'capture' : 'low-orbit';
	}

	/** What each end of the trip is, as route options: the orbit it's met in,
	 *  and the latitude it stands at where it stands on a surface. A landing or
	 *  flyby names no orbit, nor does an end whose body hasn't been measured
	 *  yet. A latitude is only worth quoting where the trip actually touches
	 *  the ground — anywhere else the ascent it would price never happens. */
	get endTerms(): Pick<
		RouteOptions,
		'departureOrbit' | 'targetOrbit' | 'departureSiteLatDeg' | 'targetSiteLatDeg'
	> {
		return {
			departureOrbit: this.departureMode === 'surface' ? undefined : this.originOrbit,
			targetOrbit:
				this.arrivalMode === 'landing' || this.arrivalMode === 'flyby'
					? undefined
					: this.targetOrbit,
			departureSiteLatDeg:
				this.departureMode === 'surface' ? (this.originSiteLatDeg ?? undefined) : undefined,
			targetSiteLatDeg:
				this.arrivalMode === 'landing' ? (this.targetSiteLatDeg ?? undefined) : undefined
		};
	}

	/** What the ends' orbits and sites are worth to a cache key. */
	#orbitKey(): string {
		const {
			departureOrbit: d,
			targetOrbit: t,
			departureSiteLatDeg,
			targetSiteLatDeg
		} = this.endTerms;
		const one = (o?: EndOrbit) => (o ? `${Math.round(o.rPeriKm)}/${Math.round(o.rApoKm)}` : '');
		const lat = (v?: number) => (v === undefined ? '' : v.toFixed(2));
		return `${one(d)}|${one(t)}|${lat(departureSiteLatDeg)}|${lat(targetSiteLatDeg)}`;
	}

	get departureMode(): DepartureMode {
		if (this.originAtSite) return 'surface';
		return this.originMode === 'surface' ? 'surface' : 'orbit';
	}

	/**
	 * Everything on offer.
	 *
	 * The hand-picked route goes last: it's an addition to the solver's answer
	 * rather than one of them. Whatever the craft's own drive flies goes first,
	 * because that craft usually can't fly the rest, and listing the one real
	 * answer under three trajectories it has to refuse would bury it.
	 */
	get offered(): OfferedRoute[] {
		const craftArc: OfferedRoute[] = [...this.torchPresets];
		// Last among the arcs, like the hand-picked window among the transfers.
		if (this.torchCustom) craftArc.push(this.torchCustom);
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
	 * Only ever an alternative to going straight there, buying its Δv with
	 * years of extra travel and a departure date well outside the grid. Shown
	 * when genuinely cheaper than the direct search's best, left out when it
	 * merely ties — an identical price for a decade more waiting isn't a
	 * choice worth putting in front of anyone.
	 */
	#assistWorthOffering(): Route | null {
		const assist = this.assist;
		if (!assist || this.routes.length === 0) return null;
		const cheapest = Math.min(...this.routes.map((choice) => choice.route.totalDvKms));
		return assist.totalDvKms <= cheapest - ASSIST_MIN_SAVING_KMS ? assist : null;
	}

	/** Set when transfers exist but none arrive by the date asked for. Worth
	 *  telling apart from finding nothing at all: one says the pair can't be
	 *  flown as described, the other only that the deadline is too soon — and
	 *  a date is the one term of a trip the reader can move. */
	get missedDeadline(): boolean {
		return (
			this.timeMode === 'arrive' &&
			this.pickedJd != null &&
			this.routes.length === 0 &&
			(this.grid?.solvedCount ?? 0) > 0
		);
	}

	/** The trajectory being read, with the name it is listed under. */
	get selected(): OfferedRoute | null {
		return this.offered.find((choice) => choice.profile === this.selectedProfile) ?? null;
	}

	get selectedRoute(): Route | null {
		return this.selected?.route ?? null;
	}

	/** Read one of the trajectories on offer. A choice made by hand outranks
	 *  whatever a link is still waiting on — the hunt landing later must not
	 *  move the reader off it. */
	choose(profile: RouteOption): void {
		this.selectedProfile = profile;
		this.#pendingProfile = null;
	}

	/** Go back to the ones on offer, reading none of them. Stepping back is as
	 *  much a choice as opening one, so it settles a link's wait too. */
	clearSelection(): void {
		this.selectedProfile = null;
		this.#pendingProfile = null;
	}

	/**
	 * Take a point read off the porkchop as a further trajectory on offer.
	 *
	 * It joins the list rather than being read straight away: picking is a
	 * drag, and every point crossed on the way would otherwise replace the
	 * list with the detail of a trajectory nobody stopped on.
	 *
	 * A point with no arc through it leaves the previous pick standing: the
	 * field has unsolved cells, and clearing the choice because a drag crossed
	 * one would make the picker fight the user.
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

	/** Carry a hand-picked point across a re-solve, re-priced. Changing a mode
	 *  or date changes what the same trip costs, so the point survives it.
	 *  Changing an end is a different trip, and a point outside the new grid is
	 *  one the chart can no longer place. */
	#repriceCustom(): Route | null {
		const previous = this.custom;
		if (!previous || !this.#pricing) return null;
		const { origin, target } = this.#pricing;
		if (previous.departureId !== origin.id || previous.targetId !== target.id) return null;
		return this.#priceInGrid(previous.departJd, previous.tofDays);
	}

	/** Price the pick a shared link arrived with, now that there is a grid. It
	 *  gets one attempt: if the trip it named isn't in this grid, the link
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
	 * wrong, not the choice: a launcher is the one thing that can't already be
	 * up there. Left alone when the origin is a place on a surface (only one
	 * way to leave one) or when the craft departs from nowhere.
	 */
	selectVehicle(id: string | null): void {
		this.vehicleId = this.vehicleId === id ? null : id;
		const vehicle = this.vehicle;
		if (!vehicle || this.originAtSite) return;
		if (canDepartFrom(vehicle, this.departureMode)) return;
		if (canDepartFrom(vehicle, 'surface')) this.originMode = 'surface';
		else if (canDepartFrom(vehicle, 'orbit')) this.originMode = 'low-orbit';
	}

	get manifest(): Manifest {
		return { passengers: this.passengers, payloadKg: this.payloadKg };
	}

	/** Whether the chosen craft can fly a route loaded as described. Null when
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

	/** The date the trip has to be over by, or nothing when it sets no deadline.
	 *  Over rather than landed at — see `DeadlineOptions`. */
	get deadlineJd(): number | undefined {
		return this.timeMode === 'arrive' && this.pickedJd != null ? this.pickedJd : undefined;
	}

	/** Whether `route` is finished by the deadline, campaign and all. True when
	 *  the trip sets none. */
	#meetsDeadline(route: Route): boolean {
		const deadlineJd = this.deadlineJd;
		return deadlineJd == null || routeEndJd(route) <= deadlineJd;
	}

	/** Days this trip's arrival still owes once the crossing is over. Read off
	 *  the same orbit the routes are priced against, or it would answer about
	 *  another trip. */
	#arrivalCampaignDays(target: TravelBody): number {
		return arrivalCampaignDays(
			target,
			this.arrivalMode,
			this.effectiveAero,
			this.endTerms.targetOrbit
		);
	}

	/** The earliest the trip may leave — now, unless a later departure was
	 *  asked for. A deadline says nothing here: it's a date to be met, not
	 *  waited for. */
	#earliestDepartJd(nowJd: number): number {
		return this.timeMode === 'depart' && this.pickedJd != null
			? Math.max(nowJd, this.pickedJd)
			: nowJd;
	}

	/** One held arc at one point on the coast span. Null when the drive can't
	 *  fly that crossing. */
	#buildTorch(
		origin: TravelBody,
		target: TravelBody,
		accelMs2: number,
		nowJd: number,
		frame: TransferFrame,
		coastFraction: number
	): Route | null {
		// Every departure date flies the same arc, so a date only says when to
		// start counting. A deadline says nothing at all until it is met.
		return buildConstantThrustRoute(origin, target, this.#earliestDepartJd(nowJd), accelMs2, {
			departureMode: this.departureMode,
			arrivalMode: this.arrivalMode,
			...this.endTerms,
			aero: this.effectiveAero,
			centralMu: frame.centralMu,
			systemPrimary: frame.systemPrimary,
			coastFraction
		});
	}

	/** The acceleration the craft holds. Zero when there's no arc to be had.
	 *  Null while the catalogue is still coming: an answer given then would
	 *  drop the trajectory a shared link named. */
	#torchAccelMs2(): number | null {
		if (!this.craftKnown) return null;
		const vehicle = this.vehicle;
		return (vehicle ? constantThrustAccelMs2(vehicle) : undefined) ?? 0;
	}

	/**
	 * Recompute the preset arcs for the craft and the trip as they stand.
	 *
	 * Called on its own, not from `solve`: a new craft isn't a new search, and
	 * a new search doesn't change how hard the drive pushes.
	 *
	 * Nothing below reads `this.torchPresets` back. This runs inside an effect
	 * and builds fresh objects, so a read would make the effect depend on a
	 * value it just replaced — looping forever.
	 */
	updateTorch(
		origin: TravelBody,
		target: TravelBody,
		nowJd: number,
		frame: TransferFrame = { orbit: 'heliocentric' }
	): void {
		const accelMs2 = this.#torchAccelMs2();
		if (accelMs2 === null) return;

		const found: TorchArc[] = [];
		if (accelMs2 > 0) {
			for (const preset of TORCH_PRESETS) {
				const route = this.#buildTorch(
					origin,
					target,
					accelMs2,
					nowJd,
					frame,
					preset.coastFraction
				);
				if (route) found.push({ profile: preset.profile, route });
			}
		}
		const listed = listedTorchArcs(found);
		const offered = listed.filter((arc) => this.#meetsDeadline(arc.route));

		this.torchPresets = offered;
		// Only the coast can put a crossing past a deadline.
		this.torchMissedDeadline = listed.length > 0 && offered.length === 0;
		// Never selected for the reader: a torch ship can fly the coasting
		// routes too. But an arc no longer offered must release the panel.
		const reading = this.selectedProfile;
		if (
			reading !== null &&
			reading !== 'constant-thrust-custom' &&
			reading.startsWith('constant-thrust') &&
			!offered.some((arc) => arc.profile === reading)
		) {
			this.selectedProfile = null;
		}
	}

	/** Recompute the arc the cruise slider asks for. Its own method and effect
	 *  because a drag must not re-solve the presets on every frame. */
	updateTorchCustom(
		origin: TravelBody,
		target: TravelBody,
		nowJd: number,
		frame: TransferFrame = { orbit: 'heliocentric' }
	): void {
		const accelMs2 = this.#torchAccelMs2();
		if (accelMs2 === null) return;

		// Built wherever the slider is, presets included: a box that goes blank
		// at both ends of its own travel looks broken.
		const route =
			accelMs2 > 0
				? this.#buildTorch(origin, target, accelMs2, nowJd, frame, this.coastFraction)
				: null;
		const offered = route && this.#meetsDeadline(route);

		this.torchCustom = offered ? { profile: 'constant-thrust-custom', route } : null;
		// A coast past the deadline would leave the reader on a trajectory
		// nothing offers. The presets drop their own.
		if (!offered && this.selectedProfile === 'constant-thrust-custom') this.selectedProfile = null;
	}

	/**
	 * Recompute the spiral for the craft and the trip as they stand.
	 *
	 * A sibling of `updateTorch` in every structural way — off the craft rather
	 * than the search, a bisection rather than a grid, never reading its own
	 * answer back. What differs is the date: a spiral has to wait for the phase
	 * to close, so it's asked for the earliest it may leave rather than the
	 * date it leaves.
	 *
	 * The manifest is an input here and nowhere else: cargo makes a spiral
	 * slower as well as shorter of Δv, since the drive is pushing it too.
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
		const earliestJd = this.#earliestDepartJd(nowJd);
		const route = drive
			? buildLowThrustRoute(origin, target, earliestJd, drive, {
					departureMode: this.departureMode,
					arrivalMode: this.arrivalMode,
					...this.endTerms,
					aero: this.effectiveAero,
					centralMu: frame.centralMu,
					systemPrimary: frame.systemPrimary
				})
			: null;
		const offer = route !== null && this.#meetsDeadline(route) ? route : null;
		this.spiral = offer;
		// Offered, never opened: an ion craft can be compared against the
		// coasting routes, and choosing between them is a step no auto-selection
		// should skip.
		if (!offer && this.selectedProfile === 'low-thrust') this.selectedProfile = null;
	}

	/**
	 * Look for a route that swings past one of `vias`, and hold whatever comes
	 * back.
	 *
	 * Its own method for the same reason `updateTorch` is: it answers a
	 * different question than the porkchop, on a different timescale — a
	 * second or so in the worker, against a grid that lands immediately — so
	 * the panel shows the direct routes and lets this fill in behind them.
	 *
	 * It only ever adds a row to the list. A trajectory appearing a second late
	 * and taking the reader off the one they'd opened would be reading their
	 * mind about a comparison they'd already made.
	 */
	async updateAssist(
		origin: TravelBody,
		target: TravelBody,
		vias: TravelBody[],
		nowJd: number,
		options: RouteOptions = {}
	): Promise<void> {
		// Ids and modes rather than the bodies themselves: their elements belong
		// to the scene, which rewrites them as its clock runs, while the planner
		// reasons from a snapshotted "now" — the same trip asked again is the
		// same question however far the planets have moved since.
		//
		// The exception is the air: whether an end has an atmosphere comes from
		// a detail bundle that lands *after* the first hunt, and it moves an
		// arrival by ten km/s. Keyed on ids alone, "airless Saturn" would stand
		// for the rest of the session while the routes beside it priced the
		// aerocapture.
		//
		// The trip's dates are in here as the hunt reads them, not as the panel
		// holds them: a departure date floors the search and a deadline caps
		// it, and both change which swing-by comes back.
		const earliestJd = this.#earliestDepartJd(nowJd);
		const deadlineJd = this.deadlineJd;
		const key = [
			origin.id,
			target.id,
			air(origin),
			air(target),
			vias.map((via) => via.id).join(','),
			earliestJd,
			deadlineJd ?? '',
			this.departureMode,
			this.arrivalMode,
			this.#orbitKey(),
			this.effectiveAero,
			options.centralMu ?? ''
		].join('|');
		if (key === this.#assistFor) return;
		this.#assistFor = key;

		const token = ++this.#assistToken;
		this.assistSearching = true;
		const route = await this.#solver.findAssist(origin, target, vias, {
			...options,
			nowJd: earliestJd,
			deadlineJd,
			departureMode: this.departureMode,
			arrivalMode: this.arrivalMode,
			...this.endTerms,
			// Load-bearing: the hunt is only ever compared against the direct
			// routes, so an arrival priced on a different braking mode isn't a
			// comparison at all — it reads as a swing-by that saves nothing.
			aero: this.effectiveAero
		});
		// A newer hunt has replaced this one; it owns the flag now.
		if (token !== this.#assistToken) return;
		this.assistSearching = false;
		this.assist = route;
		this.#settleSelection(true);
	}

	/** Drop the swing-by, and anything still looking for one. No hunt is coming
	 *  after this, so a link still waiting on one has its answer: there is
	 *  none — holding on would report a trajectory this pair can never have. */
	clearAssist(): void {
		this.#assistToken++;
		this.#assistFor = null;
		this.assistSearching = false;
		this.assist = null;
		if (this.#pendingProfile === 'gravity-assist') this.#pendingProfile = null;
		if (this.selectedProfile === 'gravity-assist') this.selectedProfile = null;
	}

	/**
	 * Settle which trajectory is being read, now that what is offered has
	 * changed.
	 *
	 * Only ever retires a selection — a trajectory that stopped being offered
	 * puts the reader back in front of the ones that are. Nothing is chosen in
	 * its place; that's theirs to do.
	 *
	 * Two things a link can name arrive later than the routes do — the
	 * swing-by, still being hunted, and the constant-thrust arc, waiting on
	 * the craft catalogue — and neither may be retired by a search that knows
	 * nothing about it. `huntSettled` is the hunt saying it has answered.
	 */
	#settleSelection(huntSettled = false): void {
		const wanted = this.#pendingProfile;
		if (wanted) {
			if (this.offered.some((choice) => choice.profile === wanted)) {
				this.selectedProfile = wanted;
				this.#pendingProfile = null;
			} else if (huntSettled) {
				// It has had its turn: the link named a trajectory this pair
				// doesn't have, and from here it falls back like any other.
				this.#pendingProfile = null;
			} else {
				return;
			}
		}
		// A search says nothing about the two trajectories that come off the
		// craft rather than the grid, so it can't retire a selection whose craft
		// hasn't landed yet.
		const fromCraft =
			this.selectedProfile?.startsWith('constant-thrust') || this.selectedProfile === 'low-thrust';
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
		this.torchPresets = [];
		this.torchCustom = null;
		this.torchMissedDeadline = false;
		this.spiral = null;
		this.assist = null;
		this.assistSearching = false;
		this.#assistToken++;
		this.#assistFor = null;
		this.#pendingProfile = null;
		this.#pricing = null;
		this.pricedRevision++;
	}

	/**
	 * Solve the current trip. Safe to call on every input change — the newest
	 * call wins and the rest are discarded when they land.
	 *
	 * `frame` says what the transfer goes round: nothing for an arc about the
	 * Sun, an end for a trip to that body's own moon, a μ for two moons of one
	 * planet.
	 *
	 * `refine` is how an end that doesn't keep still gets answered honestly —
	 * see {@link RefineEnd}. Each pass is a whole search, so the first answer
	 * is on screen at the usual speed and the corrections land behind it.
	 */
	async solve(
		origin: TravelBody,
		target: TravelBody,
		nowJd: number,
		frame: TransferFrame = { orbit: 'heliocentric' },
		refine?: RefineEnd
	): Promise<void> {
		const token = ++this.#token;
		let from = origin;
		let to = target;
		let previous: TripDates | null = null;
		for (let pass = 0; ; pass++) {
			if (!(await this.#solvePass(from, to, nowJd, frame, token))) return;

			// Where this pass says the craft leaves and arrives. Read off the
			// cheapest route rather than each of them: the families share a
			// window, and one set of elements per pass is what keeps this a
			// search rather than a search per trajectory.
			const dates = cheapestDates(this.routes);
			if (!dates) return;
			// How far a pass moves the dates is how wrong its given elements
			// were. Once that's under a day, another pass answers the same thing.
			if (previous) {
				const movedDays = moved(previous, dates);
				console.debug(
					`[travel] ${from.id} → ${to.id} re-solved at its own dates: they moved ` +
						`${movedDays.toFixed(1)} d.`
				);
				if (movedDays < REFINE_SETTLED_DAYS) return;
			}
			previous = dates;
			if (!refine || pass >= MAX_REFINE_PASSES) return;

			const [nextFrom, nextTo] = await Promise.all([
				refine('origin', dates.departJd),
				refine('target', dates.arriveJd)
			]);
			if (token !== this.#token) return;
			// Neither end has anything better to say about those dates.
			if (!nextFrom && !nextTo) return;
			from = nextFrom ?? from;
			to = nextTo ?? to;
		}
	}

	/** One search against the ends as given. False when it didn't land — the
	 *  trip was blocked, the search was superseded, or nothing came back. */
	async #solvePass(
		origin: TravelBody,
		target: TravelBody,
		nowJd: number,
		frame: TransferFrame,
		token: number
	): Promise<boolean> {
		const options = searchWindow({
			origin,
			target,
			nowJd,
			timeMode: this.timeMode,
			pickedJd: this.pickedJd,
			systemPrimary: frame.systemPrimary,
			centralMu: frame.centralMu,
			arrivalDays: this.#arrivalCampaignDays(target)
		});
		if (!options) {
			console.debug(
				`[travel] no search window for ${origin.id} → ${target.id}: ` +
					`a=${origin.elements.a}/${target.elements.a}, e=${origin.elements.e}/${target.elements.e}`
			);
			this.block('unknown-orbit');
			return false;
		}

		this.blocked = null;
		this.status = 'solving';

		const solveOptions = {
			...options,
			departureMode: this.departureMode,
			arrivalMode: this.arrivalMode,
			...this.endTerms,
			aero: this.effectiveAero
		};
		const result = await this.#solver.solve(origin, target, solveOptions);

		// A newer solve has already started, or already answered.
		if (token !== this.#token) return false;

		if (!result) {
			this.status = 'empty';
			return false;
		}

		this.routes = result.routes;
		this.grid = result.grid;
		this.#pricing = { origin, target, options: solveOptions };
		this.pricedRevision++;
		this.custom = this.#repriceCustom() ?? this.#pricePendingPick();
		this.status = this.offered.length > 0 ? 'ready' : 'empty';

		this.#settleSelection();
		return true;
	}

	dispose(): void {
		this.#token++;
		this.#solver.dispose();
	}
}
