import { describe, expect, it } from 'vitest';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { ObjectType, type PositionedBody } from '$lib/types/objects';
import {
	PLANE_REF_PREFIX,
	defaultNorthChoice,
	getNorthChoices,
	northRefHolds,
	resolveNorthChoice
} from './north-reference';

function body(id: string, parentId: string, oriented: boolean, extra = {}): PositionedBody {
	return {
		data: { id, parentId, name: id, objectType: ObjectType.MOON },
		position: null,
		...(oriented ? { orientation: {} } : {}),
		...extra
	} as unknown as PositionedBody;
}

function scene(bodies: PositionedBody[], planes: Record<string, number[]> = {}): ContextManager {
	const byId = new Map(bodies.map((b) => [b.data.id, b]));
	return {
		getBody: (id: string) => byId.get(id),
		exoplanets: { planeNormal: (id: string) => planes[id] ?? null }
	} as unknown as ContextManager;
}

const earth = body('naif-399', 'naif-3', true);
const earthBary = body('naif-3', 'naif-0', false);
const moon = body('naif-301', 'naif-3', true);
const lander = body('probe-1', 'naif-301', false, {
	data: { id: 'probe-1', parentId: 'naif-301', name: 'Lander', objectType: ObjectType.SPACECRAFT }
});
const solar = scene([earth, earthBary, moon, lander]);

describe('getNorthChoices', () => {
	it('names the ancestors by their steps up from the focus', () => {
		const refs = getNorthChoices(lander, solar).map((c) => c.ref);
		expect(refs).toEqual(['galactic', null, 'parent-2', 'parent', 'body']);
	});

	it('gives the barycentre one step up to the planet in it', () => {
		const choices = getNorthChoices(moon, solar);
		expect(choices.find((c) => c.ref === 'parent')?.id).toBe('naif-399');
	});

	it('has the J2000 ecliptic as the system in the solar system', () => {
		expect(defaultNorthChoice(getNorthChoices(moon, solar)).id).toBeNull();
	});

	it('has the orbital plane as the system of another star, and no ecliptic', () => {
		const star = body('x-7', '', false);
		const planet = body('x-7-b-1', 'x-7', false, { exoplanet: {} });
		const ctx = scene([star, planet], { 'x-7-b-1': [0, 0, 1] });
		const choices = getNorthChoices(planet, ctx);
		expect(choices.map((c) => c.id)).toEqual(['galactic', `${PLANE_REF_PREFIX}x-7-b-1`]);
		expect(choices[1].name).toBe('x-7');
		expect(defaultNorthChoice(choices).plane).toBe(true);
	});

	it('defaults a star with no plane to galactic', () => {
		const star = body('x-8', '', false);
		const choices = getNorthChoices(star, scene([star]));
		expect(choices.map((c) => c.id)).toEqual(['galactic']);
		expect(defaultNorthChoice(choices).id).toBe('galactic');
	});
});

describe('resolveNorthChoice', () => {
	it('falls back to the default while the named north has not loaded', () => {
		const unspun = scene([body('naif-301', 'naif-3', false), earthBary]);
		const choices = getNorthChoices(unspun.getBody('naif-301'), unspun);
		expect(resolveNorthChoice(choices, 'body').id).toBeNull();
	});
});

describe('northRefHolds', () => {
	it('keeps a step the focus has, drops one past the root', () => {
		expect(northRefHolds('parent-2', lander, solar)).toBe(true);
		expect(northRefHolds('parent-2', moon, solar)).toBe(false);
		expect(northRefHolds('parent', moon, solar)).toBe(true);
	});

	it('gives Earth no parent: its barycentre stands for Earth itself', () => {
		expect(northRefHolds('parent', earth, solar)).toBe(false);
	});

	it('ends on a parent chain that loops, however far up the URL asks', () => {
		const a = body('s-1', 's-2', true);
		const looped = scene([a, body('s-2', 's-1', true)]);
		expect(northRefHolds('parent', a, looped)).toBe(true);
		expect(northRefHolds('parent-99999999999', a, looped)).toBe(false);
	});

	it('leaves a step open while an ancestor on the way is not loaded', () => {
		const partial = scene([moon]);
		expect(northRefHolds('parent', moon, partial)).toBeNull();
		expect(northRefHolds('parent-5', moon, partial)).toBeNull();
	});

	it('ends the chain at a star with no parent', () => {
		const star = body('x-7', '', false);
		expect(northRefHolds('parent', star, scene([star]))).toBe(false);
	});
});
