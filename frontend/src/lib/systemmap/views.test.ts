import { describe, expect, it } from 'vitest';
import type { PlanetarySystemsMapFile } from '$lib/fetch/groups/planetary-systems-map';
import type { SolarSystemMapFile, SolarSystemMapObject } from '$lib/fetch/groups/solar-system-map';
import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
import {
	buildSolarView,
	buildSystemView,
	buildZoneView,
	extraFromBundle,
	extraFromPlace,
	unplacedIds,
	zoneOf,
	type ExtraBody,
	type SystemMapTarget,
	type ViewData,
	type ViewOptions,
	type ViewText
} from './views';

const object = (
	id: string,
	name: string,
	kind: SolarSystemMapObject['kind'],
	a: number,
	more: Partial<SolarSystemMapObject> = {}
): SolarSystemMapObject => ({
	id,
	qid: null,
	name,
	kind,
	a,
	i: 0,
	diameter_km: 100,
	color: null,
	...more
});

const SOLAR: SolarSystemMapFile = {
	objects: [
		object('naif-10', 'Sun', 'star', 0, { diameter_km: 1_392_000 }),
		object('naif-199', 'Mercury', 'planet', 0.39),
		object('naif-299', 'Venus', 'planet', 0.72),
		object('naif-399', 'Earth', 'planet', 1, { moon_count: 1 }),
		object('naif-599', 'Jupiter', 'planet', 5.2, { moon_count: 95 }),
		object('naif-699', 'Saturn', 'planet', 9.56, { moon_count: 292 }),
		object('naif-999', 'Pluto', 'dwarf', 39.6),
		object('naif-2000001', 'Ceres', 'dwarf', 2.77),
		object('spkid-20000004', '4 Vesta', 'asteroid', 2.36),
		object('naif-301', 'Moon', 'moon', 1, { parent: 'naif-399', link_parent: false }),
		object('naif-606', 'Titan', 'moon', 9.56, { parent: 'naif-699', link_parent: true })
	],
	belts: [
		{ slug: 'class-MBA', label: 'Main belt', kind: 'asteroid_belt', inner_au: 2.2, outer_au: 3.2 },
		{ slug: 'class-TNO', label: 'Kuiper belt', kind: 'kuiper_belt', inner_au: 37, outer_au: 45 }
	]
};

const moon = (id: string, a_rp: number, radius_km: number) => ({
	id,
	a_rp,
	tilt_deg: 0,
	radius_km
});

const SYSTEMS: PlanetarySystemsMapFile = {
	'naif-3': {
		primary: { id: 'naif-399', radius_km: 6378 },
		moons: [moon('naif-301', 60, 1737)],
		rings: null,
		moon_count: 1
	},
	'naif-6': {
		primary: { id: 'naif-699', radius_km: 60268 },
		moons: [
			moon('naif-601', 3, 198),
			moon('naif-602', 4, 252),
			moon('naif-605', 9, 764),
			moon('naif-606', 20, 2575),
			moon('naif-608', 59, 735),
			moon('naif-653', 4, 0)
		],
		rings: { inner_rp: 1.1, outer_rp: 8 },
		moon_count: 292
	},
	'naif-9': {
		primary: { id: 'naif-999', radius_km: 1188 },
		moons: [moon('naif-901', 16, 606)],
		rings: null,
		moon_count: 5
	}
};

const TEXT: ViewText = {
	primary: 'primary',
	retrograde: 'retrograde',
	moons: (count) => `${count} moons`,
	distance: (km) => `${km} km`,
	axisAu: 'AU · log',
	solarSystem: 'Solar System',
	rings: 'Rings',
	axisRadii: 'radii',
	zoneInner: 'Inner',
	zoneOuter: 'Outer'
};

const extra = (id: string, aAu: number, more: Partial<ExtraBody> = {}): ExtraBody =>
	extraFromPlace({ id, name: id, aAu, ...more });

const data = (extras: ExtraBody[] = []): ViewData => ({ solar: SOLAR, systems: SYSTEMS, extras });

const options = (more: Partial<ViewOptions> & { ids?: string[] } = {}): ViewOptions => ({
	bodies: more.ids ? new Set(more.ids) : null,
	names: {},
	grouping: 'bodies',
	zones: 'belts',
	...more
});

const keys = (targets: SystemMapTarget[]) =>
	targets.map((t) => (t.kind === 'zone' ? `zone:${t.zone}` : `${t.kind}:${t.id}`));

const click = {} as MouseEvent;

describe('zoneOf', () => {
	it("splits at Jupiter's orbit, the trojans falling outside", () => {
		expect(zoneOf(3.4, 5.2)).toBe('inner');
		// The Hildas stay in, and a trojan inside Jupiter's own distance is out.
		expect(zoneOf(3.97, 5.2)).toBe('inner');
		expect(zoneOf(5.13, 5.2)).toBe('outer');
		expect(zoneOf(5.2, 5.2)).toBe('outer');
		expect(zoneOf(17.8, 5.2)).toBe('outer');
	});
});

describe('unplacedIds', () => {
	it('is what neither file nor the host places', () => {
		const ids = new Set(['naif-699', 'naif-602', 'spkid-20101955', 'spkid-20000433']);
		expect(unplacedIds(SOLAR, SYSTEMS, ids, ['spkid-20000433'])).toEqual(['spkid-20101955']);
		expect(unplacedIds(SOLAR, SYSTEMS, null)).toEqual([]);
	});
});

describe('extraFromBundle', () => {
	const bundle = (more: Partial<GlobalObjectData>) => ({
		id: 'x',
		type: 'asteroid_inner',
		...more
	});

	it('reads a small body off its orbit and its measured shape', () => {
		const body = extraFromBundle(
			bundle({
				name: '101955 Bennu',
				orbit: { a: 1.13, i: 6 } as GlobalObjectData['orbit'],
				radii: { a: 0.28, b: 0.27, c: 0.25 },
				sbdb: { diameter: 0.48, color: '#445566' }
			})
		);
		expect(body).toMatchObject({
			name: 'Bennu',
			moon: false,
			aAu: 1.13,
			tiltDeg: 6,
			color: '#445566'
		});
		expect(body?.radiusKm).toBeCloseTo(0.267, 3);
	});

	it('has no place for a body that orbits something other than the Sun', () => {
		const orbit = { a: 0.00004, i: 51, parent_id: 'naif-399' } as GlobalObjectData['orbit'];
		expect(extraFromBundle(bundle({ type: 'spacecraft', orbit }))).toBeNull();
	});

	it('places a parabolic comet at its perihelion', () => {
		const comet = bundle({ orbit: { q: 0.9, i: 12 } as GlobalObjectData['orbit'] });
		expect(extraFromBundle(comet)?.aAu).toBe(0.9);
	});

	it('takes a moon with no semi-major axis, and nothing else without one', () => {
		const orbit = { i: 160, parent_id: 'spkid-20065803' } as GlobalObjectData['orbit'];
		expect(extraFromBundle(bundle({ type: 'moon', orbit }))).toMatchObject({
			moon: true,
			parent: 'spkid-20065803'
		});
		expect(extraFromBundle(bundle({ orbit }))).toBeNull();
	});
});

describe('buildSolarView', () => {
	it('makes a dot and a stack two targets when grouping by bodies', () => {
		const picked: SystemMapTarget[] = [];
		const view = buildSolarView(data(), options(), TEXT, (t) => picked.push(t));
		expect(keys(view.targets)).toEqual([
			'body:naif-10',
			'body:naif-199',
			'body:naif-299',
			'body:naif-399',
			'body:naif-301',
			'body:naif-599',
			'body:naif-699',
			'system:naif-699',
			'body:naif-999',
			'system:naif-999',
			'body:naif-2000001',
			'body:spkid-20000004'
		]);
		const saturn = view.model.bodies.find((b) => b.id === 'naif-699');
		saturn?.link?.onclick?.(click);
		saturn?.satellitesLink?.onclick?.(click);
		expect(keys(picked)).toEqual(['body:naif-699', 'system:naif-699']);
		expect(view.model.bands.every((band) => !band.onclick)).toBe(true);
	});

	it('makes a primary and its stack one system target when grouping by systems', () => {
		const view = buildSolarView(data(), options({ grouping: 'systems' }), TEXT, () => {});
		expect(keys(view.targets)).toContain('system:naif-699');
		expect(keys(view.targets)).not.toContain('body:naif-699');
		// No moons, so nothing to open.
		expect(keys(view.targets)).toContain('body:naif-199');
		const saturn = view.model.bodies.find((b) => b.id === 'naif-699');
		expect(saturn).toMatchObject({ grouped: true });
		expect(saturn?.satellitesLink).toBeUndefined();
	});

	it('draws what `bodies` names, and a primary out of scope for the moon that is in', () => {
		const ids = [
			'naif-199',
			'naif-301',
			'naif-699',
			'naif-601',
			'naif-602',
			'naif-605',
			'naif-606',
			'naif-608'
		];
		const view = buildSolarView(data(), options({ ids, grouping: 'systems' }), TEXT, () => {});
		expect(view.model.bodies.map((b) => b.id)).toEqual(['naif-199', 'naif-399', 'naif-699']);
		expect(keys(view.targets)).toEqual(['body:naif-199', 'system:naif-399', 'system:naif-699']);
		const saturn = view.model.bodies.find((b) => b.id === 'naif-699');
		// The four largest are drawn; all five count.
		expect(saturn?.satellites?.map((s) => s.id)).toEqual([
			'naif-606',
			'naif-605',
			'naif-608',
			'naif-602'
		]);
		expect(saturn?.satelliteCount).toBe(5);
	});

	it('leaves a primary whose moons are all out of scope a plain body', () => {
		const view = buildSolarView(
			data(),
			options({ ids: ['naif-699'], grouping: 'systems' }),
			TEXT,
			() => {}
		);
		expect(keys(view.targets)).toEqual(['body:naif-699']);
	});

	it('turns the belts into the doors of the two zones', () => {
		const picked: SystemMapTarget[] = [];
		const view = buildSolarView(data(), options({ zones: 'inner-outer' }), TEXT, (t) =>
			picked.push(t)
		);
		expect(view.model.bands.map((band) => band.label)).toEqual(['Inner', 'Outer']);
		for (const band of view.model.bands) band.onclick?.(click);
		expect(picked).toEqual([
			{ kind: 'zone', zone: 'inner', name: 'Inner' },
			{ kind: 'zone', zone: 'outer', name: 'Outer' }
		]);
	});

	it("names from the host's list first, the export's tidied otherwise", () => {
		const view = buildSolarView(
			data(),
			options({ names: { 'naif-699': 'Saturne' } }),
			TEXT,
			() => {}
		);
		const names = Object.fromEntries(view.targets.map((t) => ['id' in t ? t.id : t.zone, t.name]));
		expect(names['naif-699']).toBe('Saturne');
		expect(names['spkid-20000004']).toBe('Vesta');
	});
});

describe('buildSystemView', () => {
	it('offers the primary and every moon in scope as bodies', () => {
		const view = buildSystemView(
			data(),
			'naif-699',
			{ 'naif-699': 'Saturn', 'naif-606': 'Titan' },
			options({ ids: ['naif-606', 'naif-602'], names: { 'naif-602': 'Encelade' } }),
			TEXT,
			() => {}
		);
		expect(view.label).toBe('Saturn');
		expect(view.targets).toEqual([
			{ kind: 'body', id: 'naif-602', name: 'Encelade' },
			{ kind: 'body', id: 'naif-606', name: 'Titan' }
		]);
		expect(view.model.primary.link).toBeUndefined();
		expect(view.model.bands.map((band) => [band.key, !!band.onclick])).toEqual([['rings', false]]);
	});

	it('survives a scope that leaves it no moon', () => {
		const view = buildSystemView(
			data(),
			'naif-999',
			{},
			options({ ids: ['naif-999'] }),
			TEXT,
			() => {}
		);
		expect(keys(view.targets)).toEqual(['body:naif-999']);
		expect(view.model.domain.every(Number.isFinite)).toBe(true);
	});

	it('has no map of a body with no moons', () => {
		expect(() => buildSystemView(data(), 'naif-299', {}, options(), TEXT, () => {})).toThrow(
			/no planetary system/
		);
	});
});

describe('buildZoneView', () => {
	const extras = [
		extra('spkid-20101955', 1.13),
		extra('spkid-20065803', 1.64),
		extra('spkid-120065803', 0, { moon: true, parent: 'spkid-20065803' }),
		extra('spkid-1000036', 17.8),
		extra('spkid-588', 5.2)
	];

	it("keeps each small body on its side of Jupiter's orbit", () => {
		const inner = buildZoneView(data(extras), 'inner', options(), TEXT, () => {});
		expect(keys(inner.targets)).toEqual([
			'body:naif-2000001',
			'body:spkid-20000004',
			'body:spkid-20101955',
			'body:spkid-120065803',
			'body:spkid-20065803'
		]);
		const outer = buildZoneView(data(extras), 'outer', options(), TEXT, () => {});
		expect(keys(outer.targets)).toEqual([
			'body:naif-999',
			'system:naif-999',
			'body:spkid-1000036',
			'body:spkid-588'
		]);
	});

	it('stacks a moon no system map places over its parent, a target of its own', () => {
		const view = buildZoneView(data(extras), 'inner', options(), TEXT, () => {});
		const didymos = view.model.bodies.find((b) => b.id === 'spkid-20065803');
		expect(didymos?.grouped).toBeUndefined();
		expect(didymos?.satellites?.map((s) => [s.id, !!s.link])).toEqual([['spkid-120065803', true]]);
	});

	it('draws a parent out of scope for its moon, and leaves the names of a page alone', () => {
		const named = [
			extra('spkid-20065803', 1.64, { name: '67P' }),
			extra('spkid-120065803', 0, { moon: true, parent: 'spkid-20065803', name: 'NEOWISE' })
		];
		const view = buildZoneView(
			data(named),
			'inner',
			options({ ids: ['spkid-120065803'] }),
			TEXT,
			() => {}
		);
		expect(keys(view.targets)).toEqual(['body:spkid-120065803']);
		const parent = view.model.bodies.find((b) => b.id === 'spkid-20065803');
		expect(parent?.name).toBe('67P');
		expect(parent?.link).toBeUndefined();
		expect(parent?.satellites?.map((s) => s.name)).toEqual(['NEOWISE']);
	});

	it('draws the planets in range as landmarks, not targets', () => {
		const view = buildZoneView(data(), 'inner', options(), TEXT, () => {});
		const landmarks = view.model.bodies.filter((b) => b.reference);
		expect(landmarks.map((b) => b.id)).toEqual(['naif-299', 'naif-399', 'naif-599']);
		expect(landmarks.every((b) => !b.link)).toBe(true);
	});

	it('filters by `bodies`, and groups a small body with its moons like a planet', () => {
		const view = buildZoneView(
			data(extras),
			'outer',
			options({ ids: ['naif-901', 'spkid-1000036'], grouping: 'systems' }),
			TEXT,
			() => {}
		);
		expect(keys(view.targets)).toEqual(['system:naif-999', 'body:spkid-1000036']);
	});

	it('widens the axis to a body beyond it', () => {
		const far = buildZoneView(
			data([extra('spkid-90377', 540)]),
			'outer',
			options(),
			TEXT,
			() => {}
		);
		expect(far.model.domain[1]).toBeGreaterThan(540);
	});

	it('leaves out a place with no orbit to put on the axis', () => {
		const view = buildZoneView(
			data([extra('nowhere', 0), extra('hyperbola', -3)]),
			'inner',
			options(),
			TEXT,
			() => {}
		);
		expect(view.model.domain[0]).toBeGreaterThan(0);
		expect(keys(view.targets)).not.toContain('body:nowhere');
		expect(keys(view.targets)).not.toContain('body:hyperbola');
	});
});
