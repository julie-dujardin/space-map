import { describe, expect, it } from 'vitest';
import { Group, Object3D, PerspectiveCamera } from 'three';
import type { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { kmToScene } from '$lib/math/units';
import type { BodyObjects } from '$lib/scene/types';
import { updateNomenclatureVisibility } from './nomenclature';

const R_KM = 3389.5;
const W = 1920;
const H = 1080;
const PROJ = H / (2 * Math.tan(Math.PI / 6));

/** A Mars-sized body at the origin with one label per diameter, all at the
 *  sub-camera point, seen from `altitudeKm` above it. */
function scene(diamsM: number[], altitudeKm: number, activeIdx = -1) {
	const group = new Group();
	const mesh = new Object3D();
	group.add(mesh);
	const labels = diamsM.map(() => {
		const lbl = new Object3D();
		lbl.position.set(kmToScene(R_KM), 0, 0);
		mesh.add(lbl);
		return lbl as unknown as CSS2DObject;
	});
	const n = diamsM.length;
	const bo = {
		body: { data: { id: 'body', radiusKm: R_KM } },
		group,
		radiusScene: kmToScene(R_KM),
		nomenclatureLabels: labels,
		nomenclatureDiamsM: Float32Array.from(diamsM),
		nomenclatureMaxRadial: kmToScene(R_KM),
		nomenclatureSX: new Float32Array(n),
		nomenclatureSY: new Float32Array(n),
		nomenclatureActiveIndex: activeIdx
	} as unknown as BodyObjects;
	const camera = new PerspectiveCamera(60, W / H, kmToScene(0.001), 1);
	const dist = kmToScene(R_KM + altitudeKm);
	camera.position.set(dist, 0, 0);
	camera.lookAt(0, 0, 0);
	camera.updateMatrixWorld();
	const screenR = (bo.radiusScene / dist) * PROJ;
	updateNomenclatureVisibility(bo, true, screenR, PROJ, camera, W, H);
	return labels.map((l) => l.visible);
}

describe('updateNomenclatureVisibility', () => {
	it('sizes a feature by its distance from the camera, not the body centre', () => {
		// 10 km from 100 km up is ~94 px; from the centre it would be ~3 px.
		expect(scene([10_000], 100)).toEqual([true]);
	});

	it('hides features outside the on-screen size band', () => {
		expect(scene([1_000, 1_000_000], 100)).toEqual([false, false]);
	});

	it('lets a feature wider than the cap show while the body is small', () => {
		// The body is ~150 px in radius, the cap ~440 px; a 5000 km region is ~260 px.
		expect(scene([5_000_000], 17_740)).toEqual([true]);
		// Closer in, the cap is back to a fifth of the view.
		expect(scene([5_000_000], 3_000)).toEqual([false]);
	});

	it('shows a non-circular feature only when it is selected', () => {
		expect(scene([0], 100)).toEqual([false]);
		expect(scene([0], 100, 0)).toEqual([true]);
	});
});
