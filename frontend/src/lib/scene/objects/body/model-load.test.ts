/**
 * A model mounts after its body is placed, and the position pass that turns a
 * body runs again only when the date or the scene changes. A map whose clock
 * stands still, or whose date is held, can go the whole view without one.
 * Mimas's mesh came in after its spin in a spaceguesser round and was drawn
 * unturned, about 70° off the globe its camera was placed on.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Group, Mesh, MeshStandardMaterial, Quaternion, Scene, SphereGeometry } from 'three';
import { bodyQuaternion } from '$lib/math/orientation';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { ObjectType, type PositionedBody } from '$lib/types/objects';
import type { BodyObjects } from '../../types';
import { loadBodyModel, modelLoader, unloadBodyModel } from './model';

const detail = vi.hoisted(() => ({ global: null as Record<string, unknown> | null }));

vi.mock('$lib/fetch/objects/object-data', () => ({
	fetchObjectDetail: () => Promise.resolve({ global: detail.global, localized: null })
}));

vi.mock('$lib/fetch/data-base', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/fetch/data-base')>()),
	versionedUrl: (path: string) => path
}));

const MIMAS_SPIN = {
	pole_ra_0: 40.66,
	pole_ra_1: -0.036,
	pole_dec_0: 83.52,
	pole_dec_1: -0.004,
	w0: 333.46,
	w1: 381.994555,
	w2: 0
};

/** The tutorial's date, 2026-10-27 15:30 UTC. */
const JD = 2461341.1458333335;

const credit = { name: 'NASA', url: 'https://pds.nasa.gov' };

function bodyObjects(id: string, objectType: ObjectType): BodyObjects {
	const body = {
		data: { id, name: id, objectType, radiusKm: 198.2 },
		position: [0, 0, 0],
		orientation: objectType === ObjectType.MOON ? MIMAS_SPIN : undefined
	} as unknown as PositionedBody;
	const mesh = new Mesh(new SphereGeometry(1), new MeshStandardMaterial());
	// As the last position pass left it.
	if (body.orientation) mesh.quaternion.copy(bodyQuaternion(body.orientation, JD));
	return { body, group: new Group(), mesh, radiusScene: 1e-6 } as unknown as BodyObjects;
}

function context(): ContextManager {
	return {
		bodies: { dataVersion: 0 },
		credits: { registerModel: () => {} }
	} as unknown as ContextManager;
}

/** A metadata.json and a GLB, each answered when the test says so. */
function serve(meta: Record<string, unknown>) {
	let sendMeta!: () => void;
	let sendMesh!: () => void;
	const metaSent = new Promise<void>((resolve) => (sendMeta = resolve));
	const meshSent = new Promise<void>((resolve) => (sendMesh = resolve));
	vi.stubGlobal(
		'fetch',
		vi.fn(async () => {
			await metaSent;
			return { json: async () => meta };
		})
	);
	vi.spyOn(modelLoader, 'loadAsync').mockImplementation(async () => {
		await meshSent;
		const scene = new Group();
		scene.add(new Mesh(new SphereGeometry(1, 8, 6), new MeshStandardMaterial()));
		return { scene } as unknown as Awaited<ReturnType<typeof modelLoader.loadAsync>>;
	});
	return { sendMeta, sendMesh };
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

let mounted: BodyObjects | null = null;

beforeEach(() => {
	// The craft's loading spinner is a DOM element.
	vi.stubGlobal('document', {
		createElement: () => ({ style: {}, remove: () => {} }),
		body: { appendChild: () => {} }
	});
});

afterEach(() => {
	// Out of the module's mount registry, so no test sees another's model.
	if (mounted) unloadBodyModel(mounted);
	mounted = null;
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

// Each test names its own bundle: the module keeps a metadata.json per slug.
describe('loadBodyModel', () => {
	it('mounts a shape model turned as the sphere it replaces', async () => {
		detail.global = { id: 'naif-601', model_name: 'mimas-turned', render_quality: 'high' };
		const { sendMeta, sendMesh } = serve({ kind: 'shape_model', exports: { high: { credit } } });
		sendMeta();
		sendMesh();
		const bo = (mounted = bodyObjects('naif-601', ObjectType.MOON));
		await loadBodyModel(bo, new Scene(), context());
		expect(bo.model).toBeTruthy();
		expect(bo.mesh!.quaternion.equals(new Quaternion())).toBe(false);
		expect(bo.model!.quaternion.angleTo(bo.mesh!.quaternion)).toBeLessThan(1e-9);
	});

	it('mounts nothing for a load given up while its mesh was on the way', async () => {
		detail.global = { id: 'naif-601', model_name: 'mimas-mesh-late', render_quality: 'high' };
		const { sendMeta, sendMesh } = serve({ kind: 'shape_model', exports: { high: { credit } } });
		sendMeta();
		const bo = (mounted = bodyObjects('naif-601', ObjectType.MOON));
		const load = loadBodyModel(bo, new Scene(), context());
		await flush();
		unloadBodyModel(bo);
		sendMesh();
		await load;
		expect(bo.model).toBeFalsy();
		expect(bo.mesh!.visible).toBe(true);
	});

	it('mounts nothing for a load given up while its metadata was on the way', async () => {
		detail.global = { id: 'naif-601', model_name: 'mimas-meta-late', render_quality: 'high' };
		const { sendMeta, sendMesh } = serve({ kind: 'shape_model', exports: { high: { credit } } });
		sendMesh();
		const bo = (mounted = bodyObjects('naif-601', ObjectType.MOON));
		const load = loadBodyModel(bo, new Scene(), context());
		await flush();
		unloadBodyModel(bo);
		sendMeta();
		await load;
		expect(bo.model).toBeFalsy();
		expect(bo.mesh!.visible).toBe(true);
	});

	it('runs the position pass again once a craft model mounts', async () => {
		detail.global = { id: 'probe-88592384', model_name: 'cassini-pass' };
		const { sendMeta, sendMesh } = serve({ exports: { high: { credit } } });
		sendMeta();
		sendMesh();
		const bo = (mounted = bodyObjects('probe-88592384', ObjectType.SPACECRAFT));
		const ctx = context();
		await loadBodyModel(bo, new Scene(), ctx);
		expect(bo.model).toBeTruthy();
		expect(ctx.bodies.dataVersion).toBe(1);
	});

	it('leaves the pass alone when there is no model to mount', async () => {
		detail.global = { id: 'probe-88592384' };
		const bo = (mounted = bodyObjects('probe-88592384', ObjectType.SPACECRAFT));
		const ctx = context();
		await loadBodyModel(bo, new Scene(), ctx);
		expect(bo.model).toBeFalsy();
		expect(ctx.bodies.dataVersion).toBe(0);
	});
});
