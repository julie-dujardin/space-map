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
	status: 'active' | 'retired' | 'planned' | 'concept' | 'fictional';
	// Wikidata item, which supplies the display name in all twelve locales the
	// same way bodies get theirs.
	qid?: string;
	// English name, present only when there is no Wikidata item (two of the
	// fictional ships). Those carry hand-authored message keys instead.
	name?: string;
	// A solar-only craft past the asteroid belt is a real constraint.
	power?: 'solar' | 'rtg' | 'nuclear' | 'battery' | 'fictional';

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

## Gaps are deliberate

The catalogue omits rather than estimates, and the omissions carry
information:

- Four launchers ship no `c3_curve`. Falcon 9, Saturn V, New Glenn and Long
  March 5 publish payload to LEO and to GTO and answer escape questions
  privately; interpolating a curve from a mass-to-Mars headline would be an
  invention.
- Several spacecraft ship no `delta_v_kms`. Rosetta's masses are published and
  its engine's specific impulse is not; the Apollo service module's dry mass
  is in neither cited document, so its propellant load cannot be separated
  from its structure.
- Starship ships no performance figures at all. Every mass in circulation for
  it traces to a slide or a remark rather than a document.

The export logs each of these at INFO on every run, so a gap that gets filled
is noticed.
