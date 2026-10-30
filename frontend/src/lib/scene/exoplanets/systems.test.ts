import { describe, expect, it } from 'vitest';
import type { PromotionRegistry } from '$lib/scene/focus/promotion';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { ObjectType, type PositionedBody, type StarAnchor } from '$lib/types/objects';
import { ExoplanetSystems } from './systems';

function star(id: number): PositionedBody {
	const anchor = { id, scene: [id, 0, 0], tree: [id, 0, 0] } as unknown as StarAnchor;
	return {
		data: { id: `x-${id}`, objectType: ObjectType.EXTRASOLAR, parentId: '' },
		position: null,
		extrasolar: anchor
	} as unknown as PositionedBody;
}

function planetOf(host: PositionedBody): PositionedBody {
	return {
		data: { id: `${host.data.id}-b-1`, objectType: ObjectType.EXOPLANET, parentId: host.data.id },
		position: null
	} as unknown as PositionedBody;
}

/** Systems over a scene that holds `bodies`, as they are at each lookup. */
function systemsWith(bodies: PositionedBody[]): ExoplanetSystems {
	const ctx = {
		getBody: (id: string) => bodies.find((body) => body.data.id === id)
	} as unknown as ContextManager;
	return new ExoplanetSystems(ctx, {} as PromotionRegistry, () => {});
}

describe('ExoplanetSystems.exactStars', () => {
	it('draws the stars of a trip exactly, after the focused one', () => {
		const sirius = star(1);
		const proxima = star(2);
		const proximaB = planetOf(proxima);
		const tauCeti = star(3);
		const systems = systemsWith([sirius, proxima, proximaB, tauCeti]);
		const ids = systems
			.exactStars(sirius, [proximaB.data.id, tauCeti.data.id, 'x-404'])
			.map((anchor) => anchor.id);
		expect(ids).toEqual([1, 2, 3]);
	});

	it('names a star once, and the solar system not at all', () => {
		const proxima = star(2);
		const earth = {
			data: { id: 'naif-399', objectType: ObjectType.PLANET, parentId: 'naif-3' },
			position: null
		} as unknown as PositionedBody;
		const systems = systemsWith([proxima, earth]);
		const ids = systems.exactStars(proxima, [earth.data.id, proxima.data.id]);
		expect(ids.map((anchor) => anchor.id)).toEqual([2]);
	});

	it('draws the star of an end that streams in after the trip is drawn', () => {
		const scene: PositionedBody[] = [];
		const systems = systemsWith(scene);
		const proxima = star(2);
		expect(systems.exactStars(undefined, [proxima.data.id])).toEqual([]);
		scene.push(proxima);
		expect(systems.exactStars(undefined, [proxima.data.id]).map((anchor) => anchor.id)).toEqual([
			2
		]);
	});
});
