# Spacecraft

`v1/spacecraft.json` (not gzipped) — the vehicle catalogue the travel panel
ranks routes against. Always-loaded like `atmospheres.json`: the panel needs
every vehicle at once to answer "what could fly this", so the file is fetched
once and kept. ~16 kB.

Written by `data/src/space_map_data/export/spacecraft.py` from the constants in
`data/src/space_map_data/constants/spacecraft/`. Two kinds of entry are judged
two different ways:

- **Launchers** are judged on whether they can reach the departure energy at
  all, which is one curve of payload against C3. Everything after injection is
  the spacecraft's problem.
- **Everything else** is judged on the Δv it carries once it is up there. The
  file ships the rocket equation's three inputs *and* the Δv derived from
  them, so a panel can show the working; `delta_v_kms` is absent whenever any
  input is, rather than being rounded from somewhere else.

Every numeric field carries its own `source`, keyed into the file's own
`sources` table. A mass and a C3 curve almost never come from the same
document.

```typescript
interface SpacecraftFile {
	vehicles: Vehicle[];
	// Source key → citation, for every key any `source` field uses. The same
	// works appear on /credits under `spacecraft_references`.
	sources: Record<string, { title: string; url: string; note: string }>;
}

// One number and the work it comes from.
interface Measured {
	value: number;
	source: string;
}

interface Vehicle {
	// Stable slug, and one entry per *configuration*: `falcon-heavy-reusable`
	// and `falcon-heavy-expendable` are separate vehicles because they are
	// separate curves.
	id: string;
	// Which feasibility path applies.
	kind: 'launcher' | 'probe' | 'crewed' | 'lander' | 'fictional';
	propulsion: 'chemical' | 'electric' | 'nuclear' | 'solar_sail' | 'fictional';
	// `cancelled` is not `retired`: one stopped flying, the other never
	// started. Both keep whatever performance was published for them.
	status: 'active' | 'retired' | 'planned' | 'cancelled' | 'concept' | 'fictional';
	// Wikidata item, which supplies the display name in all twelve locales the
	// same way bodies get theirs.
	qid?: string;
	// English name, present only when there is no Wikidata item: two of the
	// ships out of novels, and the three archetypes, which are a propulsion
	// type rather than a craft anyone named. Those carry hand-authored message
	// keys instead. Every other name comes from `spacecraft/{lang}.json`.
	name?: string;
	// Which configuration this entry is, where the name cannot say: the three
	// Falcon Heavy entries are three curves under one Wikidata item, so the
	// label alone would print the same row three times. Slugs, not words —
	// each is a message key the frontend renders beside the localized name,
	// and they stay separate so "expendable" can be translated without
	// dragging the "Star 48" part number through twelve locales.
	// Currently `expendable`, `reusable`, `star-48`.
	variant?: string[];
	// A solar-only craft past the asteroid belt is a real constraint.
	power?: 'solar' | 'rtg' | 'nuclear' | 'battery' | 'fictional';
	// Where a trip flown with this vehicle can start, so nothing offers to
	// lift an SLS out of low orbit. Always present, empty included: `[]` says
	// the thing is cargo — a rover starts no trip, it is delivered. Both
	// entries belong to the four vehicles that land and lift off again
	// (Apollo LM, Starship, and two of the fictional ships).
	departs_from: ('surface' | 'orbit')[];

	// --- in-space performance -------------------------------------------
	// `propellant_mass_kg` is the load spent through the engine whose Isp is
	// quoted, and nothing else: an ion craft's attitude-control hydrazine is
	// counted as dry mass, because spending it at 3,100 s would inflate the
	// answer by kilometres a second.
	dry_mass_kg?: Measured;
	propellant_mass_kg?: Measured;
	isp_s?: Measured;
	// Total thrust of that propulsion. Over wet mass it gives the
	// acceleration, which is what decides whether an impulsive burn is a fair
	// model at all — Dawn's 92 mN on 1.2 t is not.
	thrust_n?: Measured;
	// Isp·g₀·ln(m₀/m_f), km/s. Ideal: no gravity or finite-burn losses, whole
	// load through one engine. Present only when all three inputs are.
	delta_v_kms?: number;

	// --- launch performance (launchers only) ------------------------------
	c3_curve?: C3Curve;

	// --- what the trip does to the crew and the hull ----------------------
	// Everyone aboard: crew plus passengers. The two are the same set on
	// every spacecraft ever flown, which is what the name is from; they
	// stop being the same the moment something carries people who are not
	// operating it.
	crew?: Measured;
	// Consumables, days. The constraint a Δv budget never shows: a transfer a
	// capsule can afford may still be four times its life support.
	endurance_days?: Measured;
	// What the heat shield is rated for. Apollo's 11.03 km/s is a
	// lunar-return shield; a Mars return arrives faster.
	max_entry_speed_kms?: Measured;
	// What the vehicle can do on arrival, which gates the arrival modes worth
	// offering.
	capabilities?: (
		| 'aerocapture'
		| 'aerobraking'
		| 'entry'
		| 'landing'
		| 'sample_return'
		| 'crew_return'
	)[];
	capability_source?: string;

	// --- constant-acceleration drives -------------------------------------
	// A torch drive has no Δv budget worth stating; it has an acceleration it
	// holds until it arrives. Where this is set the route is a
	// brachistochrone, not a transfer orbit.
	accel_m_s2?: Measured;

	cost?: Cost;

	// --- links into the rest of the map -----------------------------------
	// Probe object ids whose hardware this entry describes. Voyager is one
	// design and two spacecraft.
	object_ids?: string[];
	// An existing group page: `lv-<slug>` for a launch-vehicle family,
	// `const-<slug>` for a capsule class.
	group_slug?: string;
}

interface C3Curve {
	// Ascending [C3 km²/s², payload kg]. Interpolate linearly. Thinned from
	// the source until every dropped point is predicted to within 0.5% of the
	// payload there, which is below the precision anyone publishes.
	points: [number, number][];
	source: string;
	// False: the curve ends where the vehicle does, and past the end means
	// *cannot fly this*. True: the published range stops earlier, and past the
	// end means *nobody has said* — a different sentence and a different UI.
	truncated: boolean;
	// A second work the curve was checked against, where one exists. The
	// digitised Vulcan curve reads 7,578 kg at C3 = 20 against the 7,600 kg
	// ULA's own user's guide states.
	cross_check?: string;
}

interface Cost {
	usd_millions: number;
	// Not inflation-adjusted anywhere. The year is shipped so the UI can say
	// "2021 dollars" rather than imply a comparison the data does not support.
	year: number;
	// What was actually bought: a ride, one more vehicle, or the whole
	// mission from proposal to end of operations.
	kind: 'launch_service' | 'unit' | 'mission_lifecycle';
	source: string;
}
```

## Names: `v1/spacecraft/{lang}.json`

One bundle per locale, keyed by vehicle id. Split out of `spacecraft.json`
because the name is the only part of a vehicle that differs per reader —
twelve locales inside the always-loaded file would cost more than the physics
in it does.

```typescript
type SpacecraftNames = Record<
	string, // vehicle id
	{
		// Wikidata's label in this locale, falling back to English where it has
		// none. Never the slug: a row labelled `atlas-v-551-star-48` is worse
		// than one labelled in the wrong language.
		name: string;
		// Wikidata's one-liner ("heavy-lift orbital launch vehicle made by
		// SpaceX"). Absent for about a third of entries in most locales.
		description?: string;
	}
>;
```

Nothing here is hand-translated: the labels are Wikidata's, keyed by the `qid`
each entry carries. Two entries are absent from every bundle — the Hail Mary
and the Hermes have no Wikidata item, and the frontend names them from its own
message keys. Entries sharing an item (Falcon Heavy's three configurations)
share a name, and are told apart by `variant`.

## Gaps are deliberate

The catalogue omits rather than estimates, and it goes one step further: a
vehicle the solver could never judge — a launcher without a curve, a craft
without Δv, an acceleration or an unlimited drive — is **not exported at
all**. Every route against such an entry would answer "no published figure",
and a row of shrugs tells the reader nothing a missing row does not. The
constants keep those entries with whatever *is* published, so the figure has
somewhere to land when one turns up, and the export logs each drop. Not
exported today:

- **New Glenn and Long March 5** publish payload to LEO and to GTO and
  nothing above them. Those are points on the curve — LEO is C3 = -61, GTO is
  C3 = -16 — but fitting a stage to them and extrapolating overshoots the
  launchers that *do* publish escape performance by 9% at C3 = 0 and by up to
  90% at C3 = 40, always high. What is missing is one published point past
  escape, not the curve. Falcon 9 escaped this gap because its website
  advertises a Mars payload — one point past escape — and a stage anchored
  there reproduces the site's GTO figure to 1.4%, so its (truncated) curve is
  that fit. It is the vendor's advertised accounting: the same page's Falcon
  Heavy figures run about a third above the NASA-certified curve, and the
  source entry says so.
- **Crew Dragon**: both masses are published and no specific impulse for the
  Draco thruster is, in any document or engine catalogue, so no Δv can be
  derived.
- **Starship** has no performance figures at all. Every mass in circulation
  for it traces to a slide or a remark rather than a document.

Gaps that do ship, because the entry is judgeable without the figure:

- The two rovers carry no propulsion and no Δv, which is a statement rather
  than a gap: a rover is delivered, and `departs_from: []` says the same
  thing.

Two classes of entry do carry figures nobody published, and both are
`kind: 'fictional'` and cited to `space_map_fitted` rather than to any work, so
a reader can tell a chosen number from a quoted one:

- **Ships out of novels** whose work describes a drive without numbering it.
  Faster-than-light ships get nothing — a jump is not a trajectory.
- **Archetypes** — an ion tug, a solar sail, a nuclear thermal stage — which
  come from no work at all. A propulsion type sized into a plausible vehicle,
  so a trip can be costed against what a *kind* of ship could do rather than
  only against the ones that happen to have flown. They carry
  `status: 'concept'`, since nothing here has flown and nothing here is
  impossible either.

The export logs each of these at INFO on every run, so a gap that gets filled
is noticed.
