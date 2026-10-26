import { describe, expect, it, vi } from 'vitest';
import {
	Group,
	Line,
	Mesh,
	Object3D,
	PerspectiveCamera,
	Points,
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
		labelHalo: { style: {} },
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
			starShare: 1,
			systemShares: new Map(),
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
		fades,
		frame(radiusPx: number, dtMs: number) {
			bo.body.position![2] = -500 / radiusPx;
			fades.beginFrame(dtMs);
			updateBodyVisibility(
				new Map([['body', bo]]),
				camera,
				ctx,
				[0, 0, 0],
				'body',
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
