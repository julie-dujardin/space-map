import { describe, expect, it, vi } from 'vitest';
import {
	BufferGeometry,
	Group,
	Line,
	Mesh,
	Object3D,
	PerspectiveCamera,
	Points,
	PointsMaterial,
	ShaderMaterial,
	Vector2,
	Vector3,
	type WebGLRenderer
} from 'three';
import { ObjectType } from '$lib/types/objects';
import type { BodyObjects } from '../types';
import type { ContextManager } from '../state/context-manager.svelte';
import { VisibilityThresholdFades } from './threshold-fade';
import { VISIBILITY } from './thresholds';
import { updateBodyVisibility } from './update';

vi.mock('../objects/surface/nomenclature', () => ({
	updateNomenclatureVisibility: vi.fn(),
	cullOverlappingNomenclatureLabels: vi.fn(),
	nomenclatureBodyId: () => undefined
}));
vi.mock('../objects/body/model', () => ({ modelUnitScene: () => 1 }));

function scene(objectType: ObjectType, starPoint = false) {
	const label = Object.assign(new Object3D(), {
		center: new Vector2(0.5, 0.5),
		element: { style: { opacity: '' }, remove() {} }
	});
	const group = new Group();
	group.add(label);
	const bo = {
		body: {
			data: { id: 'body', objectType, radiusKm: 1 },
			position: [0, 0, -100],
			orbitCenter: 'sun'
		},
		root: new Group(),
		group,
		label,
		labelHalo: { style: {}, dataset: {} },
		radiusScene: 1,
		mesh: new Mesh(undefined, new ShaderMaterial({ uniforms: { uFade: { value: 1 } } })),
		starPoint: starPoint
			? new Points(
					undefined,
					new ShaderMaterial({ uniforms: { uFade: { value: 1 }, uDistancePc: { value: 0 } } })
				)
			: null,
		trail: new Line(
			undefined,
			new ShaderMaterial({
				uniforms: {
					uCenterOffset: { value: new Vector3() },
					uAlphaMultiplier: { value: 1 },
					uAlphaMin: { value: 0 },
					uShowFull: { value: 0 }
				}
			})
		)
	} as unknown as BodyObjects;
	const fades = new VisibilityThresholdFades();
	const ctx = {
		layers: { isVisible: () => true },
		visibility: {
			systemShare: 1,
			systemShareOf: () => 1,
			starShareOf: () => 1,
			systemShares: new Map(),
			systemCentres: new Map(),
			isPinned: () => false,
			planetarySystemShare: () => 0,
			focusedSystemId: null,
			getPlanetVisibility: () => VISIBILITY.FULL,
			getMoonVisibility: () => VISIBILITY.FULL,
			fullRenderingShare: () => 1,
			haloThresholdShare: (id: string, shown: boolean) => fades.haloShare(id, shown)
		},
		getBody: () => bo.body
	} as unknown as ContextManager;
	const camera = new PerspectiveCamera(90, 1, 0.1, 1000);
	camera.updateMatrixWorld();
	const renderer = { domElement: { clientWidth: 1000, clientHeight: 1000 } } as WebGLRenderer;
	return {
		bo,
		ctx,
		fades,
		/** `offset` moves the body off the axis of the view, in scene units. */
		frame(radiusPx: number, dtMs: number, focusedId = 'body', offset = [0, 0, 0]) {
			const pos = bo.body.position!;
			pos[0] = offset[0];
			pos[1] = offset[1];
			pos[2] = -500 / radiusPx + offset[2];
			fades.beginFrame(dtMs);
			updateBodyVisibility(
				new Map([['body', bo]]),
				camera,
				ctx,
				[0, 0, 0],
				focusedId,
				false,
				new Set(),
				0,
				renderer,
				new Vector3(),
				false,
				false
			);
		}
	};
}

describe('close-range halos and labels', () => {
	it.each([
		['Sun', ObjectType.STAR, true],
		['extrasolar star', ObjectType.EXTRASOLAR, false],
		['planet', ObjectType.PLANET, false],
		['moon', ObjectType.MOON, false],
		['spacecraft', ObjectType.SPACECRAFT, false]
	] as const)(
		'keeps the %s name while its halo fades in 100 ms with a stationary camera',
		(_, type, point) => {
			const { bo, fades, frame } = scene(type, point);
			frame(5, 16);
			expect(bo.label!.element.style.opacity).toBe('');
			expect(bo.haloShare).toBe(1);
			frame(20, 50);
			expect(bo.haloShare).toBeCloseTo(0.5);
			expect(bo.label!.visible).toBe(true);
			expect(bo.label!.element.style.opacity).toBe('');
			expect(fades.fading).toBe(true);
			frame(20, 50);
			expect(bo.haloShare).toBe(0);
			expect(bo.labelHalo!.style.visibility).toBe('hidden');
			expect(bo.label!.visible).toBe(true);
			expect(bo.label!.element.style.opacity).toBe('');
			expect(fades.fading).toBe(false);
			frame(5, 100);
			expect(bo.haloShare).toBe(1);
			expect(bo.labelHalo!.style.visibility).toBe('');
		}
	);

	it('fades a trail with its halo and restores both when zooming out', () => {
		const { bo, frame } = scene(ObjectType.PLANET);
		bo.trail!.userData.isOpenCurve = false;
		const { uAlphaMultiplier: alpha, uAlphaMin: floor } = (bo.trail!.material as ShaderMaterial)
			.uniforms;
		frame(5, 16);
		const fullAlpha = alpha.value;
		frame(20, 50);
		expect(bo.trail!.visible).toBe(true);
		expect(alpha.value).toBeCloseTo(fullAlpha / 2);
		expect(floor.value).toBeCloseTo(0.075);
		frame(20, 50);
		expect(bo.trail!.visible).toBe(false);
		frame(5, 50);
		expect(bo.trail!.visible).toBe(true);
		expect(alpha.value).toBeCloseTo(fullAlpha / 2);
		expect(floor.value).toBeCloseTo(0.075);
		frame(5, 50);
		expect(alpha.value).toBe(fullAlpha);
		expect(floor.value).toBe(0.15);
	});

	it('keeps the halo for a body without a physical disc', () => {
		const { bo, frame } = scene(ObjectType.SPACECRAFT);
		bo.noPhysical = 'model';
		frame(20, 100);
		expect(bo.haloShare).toBe(1);
		expect(bo.label!.visible).toBe(true);
	});
});

describe('the artist-impression box', () => {
	function mappedPlanet() {
		const s = scene(ObjectType.EXOPLANET);
		Object.assign(s.bo, { artistImpression: true, textureTier: 'low' });
		return s;
	}

	it('names a mapped planet whose disc is in view', () => {
		const { ctx, frame } = mappedPlanet();
		frame(40, 16, 'other');
		frame(40, 200, 'other');
		expect(ctx.visibility.impressionInView).toBe('body');
	});

	it('names no planet behind the camera or past the side of the view', () => {
		const { ctx, frame } = mappedPlanet();
		frame(40, 16, 'other', [0, 0, 25]);
		frame(40, 200, 'other', [0, 0, 25]);
		expect(ctx.visibility.impressionInView).toBeNull();
		frame(40, 200, 'other', [12.5, 0, 11.5]);
		expect(ctx.visibility.impressionInView).toBeNull();
	});
});

describe('a moon at the CLOSE tier', () => {
	function closeMoon() {
		const s = scene(ObjectType.MOON);
		Object.assign(s.ctx.visibility, {
			focusedSystemId: 'system',
			isBodyInSystem: () => true,
			getMoonVisibility: () => VISIBILITY.CLOSE,
			labelThresholdShare: (id: string, shown: boolean) => s.fades.labelShare(id, shown),
			orbitThresholdShare: (id: string, shown: boolean) => s.fades.orbitShare(id, shown)
		});
		return s;
	}

	it('keeps the halo and name of a focused moon with no known size', () => {
		const { bo, frame } = closeMoon();
		bo.mesh = null;
		bo.noPhysical = 'radius';
		frame(400, 16);
		frame(400, 100);
		expect(bo.group.visible).toBe(true);
		expect(bo.label!.visible).toBe(true);
		expect(bo.label!.element.style.opacity).toBe('');
		expect(bo.haloShare).toBe(1);
	});

	it('keeps the name of a focused moon until its disc fills the view', () => {
		const { bo, frame } = closeMoon();
		frame(100, 16);
		frame(100, 100);
		expect(bo.label!.visible).toBe(true);
		expect(bo.label!.element.style.opacity).toBe('');
		frame(400, 100);
		frame(400, 16);
		expect(bo.label!.visible).toBe(false);
	});

	it('keeps the name of another moon of a pixel or more', () => {
		const { bo, frame } = closeMoon();
		frame(2, 16, 'other');
		frame(2, 100, 'other');
		expect(bo.label!.visible).toBe(true);
		expect(bo.label!.element.style.opacity).toBe('');
	});

	it('drops the name of another moon under a pixel', () => {
		const { bo, frame } = closeMoon();
		frame(0.5, 16, 'other');
		frame(0.5, 100, 'other');
		expect(bo.label!.visible).toBe(false);
	});
});

describe('a star of another system', () => {
	it('keeps its name in the sky of a system only while it is focused or pinned', () => {
		const { bo, ctx, frame } = scene(ObjectType.EXTRASOLAR);
		const vis = ctx.visibility as unknown as {
			isPinned: () => boolean;
			planetarySystemShare: () => number;
		};
		vis.planetarySystemShare = () => 1;
		frame(5, 16, 'other');
		expect(bo.group.visible).toBe(false);
		vis.isPinned = () => true;
		frame(5, 16, 'other');
		expect(bo.group.visible).toBe(true);
		expect(bo.label!.element.style.opacity).toBe('');
		vis.isPinned = () => false;
		frame(5, 16);
		expect(bo.group.visible).toBe(true);
	});
});

describe('the centre of a star system', () => {
	it('keeps its halo and name in the sky of its system with the focus on a star', () => {
		const { bo, ctx, frame } = scene(ObjectType.EXTRASOLAR);
		bo.mesh = null;
		bo.trail = null;
		const vis = ctx.visibility as unknown as {
			planetarySystemShare: () => number;
			systemCentres: Map<string, number>;
		};
		vis.planetarySystemShare = () => 1;
		frame(5, 16, 'other');
		expect(bo.group.visible).toBe(false);
		vis.systemCentres.set('body', 1);
		frame(5, 16, 'other');
		expect(bo.group.visible).toBe(true);
		expect(bo.label!.element.style.opacity).toBe('');
	});

	it('hides while the focused body sits on it', () => {
		const { bo, ctx, frame } = scene(ObjectType.EXTRASOLAR);
		bo.mesh = null;
		bo.trail = null;
		const vis = ctx.visibility as unknown as { systemCentres: Map<string, number> };
		vis.systemCentres.set('body', 0);
		frame(5, 16, 'other');
		expect(bo.group.visible).toBe(false);
	});

	it('draws no halo or name of a focused node that a star takes over', () => {
		const { bo, ctx, frame } = scene(ObjectType.EXTRASOLAR);
		bo.mesh = null;
		bo.trail = null;
		frame(5, 16, 'body');
		expect(bo.group.visible).toBe(true);
		const vis = ctx.visibility as unknown as { systemCentres: Map<string, number> };
		vis.systemCentres.set('body', 0);
		frame(5, 16, 'body');
		expect(bo.group.visible).toBe(false);
		expect(bo.label!.visible).toBe(false);
	});
});

describe('a star on a drawn orbit', () => {
	/** `id` is the focus. A focused star takes the tiers too. */
	function onOrbit() {
		const s = scene(ObjectType.EXTRASOLAR);
		s.bo.mesh = null;
		s.bo.radiusScene = 0;
		s.bo.body.orbitElements = s.bo.body.data;
		return {
			...s,
			vis: s.ctx.visibility as unknown as {
				getPlanetVisibility: () => VISIBILITY;
				systemShareOf: () => number;
				planetarySystemShare: () => number;
			}
		};
	}

	it('drops its halo, name and line at the tiers of a planet, focused or not', () => {
		for (const focusedId of ['body', 'other']) {
			const { bo, frame, vis } = onOrbit();
			frame(5, 16, focusedId);
			expect(bo.group.visible).toBe(true);
			expect(bo.trail!.visible).toBe(true);
			vis.getPlanetVisibility = () => VISIBILITY.FAR;
			frame(5, 16, focusedId);
			expect(bo.group.visible).toBe(false);
			expect(bo.trail!.visible).toBe(false);
		}
	});

	it('fades its name and line with the share of its orbit', () => {
		const { bo, frame, vis } = onOrbit();
		vis.systemShareOf = () => 0.5;
		frame(5, 16, 'other');
		expect(bo.label!.element.style.opacity).toBe('0.5');
		expect(bo.trail!.userData.zoneShare).toBe(1);
	});

	it('shows in the sky of its own system', () => {
		const { bo, frame, vis } = onOrbit();
		vis.planetarySystemShare = () => 1;
		frame(5, 16, 'other');
		expect(bo.group.visible).toBe(true);
	});
});

describe('a planet of another star', () => {
	it('takes the distance tiers and the system share of a planet of the Sun', () => {
		const { bo, ctx, frame } = scene(ObjectType.EXOPLANET);
		bo.mesh = null;
		bo.radiusScene = 0;
		const dot = new Points(new BufferGeometry(), new PointsMaterial({ transparent: true }));
		bo.planetDot = dot;
		bo.group.add(dot);
		const vis = ctx.visibility as unknown as {
			getPlanetVisibility: () => VISIBILITY;
			systemShareOf: () => number;
		};
		vis.systemShareOf = () => 0.5;
		frame(5, 16);
		expect(bo.group.visible).toBe(true);
		expect(bo.trail!.visible).toBe(true);
		expect(bo.label!.element.style.opacity).toBe('0.5');
		expect((dot.material as PointsMaterial).opacity).toBe(0.5);
		vis.getPlanetVisibility = () => VISIBILITY.FAR;
		frame(5, 16);
		expect(bo.group.visible).toBe(false);
		expect(bo.trail!.visible).toBe(false);
	});
});
