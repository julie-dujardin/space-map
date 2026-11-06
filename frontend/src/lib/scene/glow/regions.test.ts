import { describe, expect, it } from 'vitest';
import {
	Matrix3,
	Matrix4,
	PerspectiveCamera,
	Scene,
	Texture,
	Vector3,
	type Mesh,
	type ShaderMaterial
} from 'three';
import type { EmissionRegions, GlowEmission } from './emission';
import { ViewRays } from './composite';
import { GlowRegions } from './regions';
import { glslFloat } from '$lib/scene/dust/glsl';

const EMISSION = {
	lines: { colour: [0.793347, 0.071671, 0.134982], k_rgb: [0.7954, 1.2237, 1.2237] }
} as GlowEmission;

const ROWS: EmissionRegions = {
	x: new Float32Array([3000, -2000]),
	y: new Float32Array([0, 500]),
	z: new Float32Array([0, -40]),
	sigma: new Float32Array([5, 20]),
	light: new Float32Array([1e3, 4e3])
};

function make() {
	const scene = new Scene();
	const rays = new ViewRays(new Matrix3());
	const regions = new GlowRegions(scene, ROWS, EMISSION, rays);
	const mesh = scene.getObjectByName('glow-regions') as Mesh<never, ShaderMaterial>;
	return { scene, regions, mesh, rays };
}

describe('the far H II regions', () => {
	it('draw one sprite a row, after the glow and before every opaque object', () => {
		const { mesh } = make();
		expect((mesh.geometry as { instanceCount: number }).instanceCount).toBe(2);
		expect(mesh.renderOrder).toBe(-1e6 + 1);
		expect(mesh.material.depthTest).toBe(false);
		expect(mesh.material.depthWrite).toBe(false);
		expect(mesh.visible).toBe(false);
	});

	it('turn nest axes into the view’s, so a region the camera looks at is ahead of it', () => {
		const { regions, mesh, rays } = make();
		const camera = new PerspectiveCamera(60, 16 / 9, 0.1, 10);
		camera.lookAt(1, 0, 0);
		camera.updateMatrixWorld();
		rays.set(camera, new Matrix4());
		const columns = { map: new Texture(), origin: [0, 0, 0] as [number, number, number] };
		regions.show([0, 0, 0], columns, 1, 1, 1e-3);
		const toView = mesh.material.uniforms.uNestToView.value as Matrix3;
		const ahead = new Vector3(3000, 0, 0).applyMatrix3(toView);
		expect(ahead.z).toBeCloseTo(-3000, 6);
		expect(Math.hypot(ahead.x, ahead.y)).toBeLessThan(1e-6);
		expect(mesh.visible).toBe(true);
	});

	it('put a region where the camera’s projection puts it, through the rays’ lens', () => {
		const { regions, mesh, rays } = make();
		const camera = new PerspectiveCamera(50, 16 / 9, 0.1, 1e5);
		camera.setViewOffset(1600, 900, 120, -40, 1600, 900);
		camera.position.set(0, 0, 0);
		camera.lookAt(1, 0.2, -0.1);
		camera.updateMatrixWorld();
		rays.set(camera, new Matrix4());
		regions.show([0, 0, 0], { map: new Texture(), origin: [0, 0, 0] }, 1, 1, 1e-3);
		const u = mesh.material.uniforms;
		const region = new Vector3(3000, 400, -200);
		const v = region.clone().applyMatrix3(u.uNestToView.value as Matrix3);
		const lens = u.uLens.value as { x: number; y: number; z: number; w: number };
		// As the vertex shader: (v.xy / -v.z) / uLens.xy - uLens.zw.
		const at = [v.x / -v.z / lens.x - lens.z, v.y / -v.z / lens.y - lens.w];
		const seen = region.clone().project(camera);
		expect(at[0]).toBeCloseTo(seen.x, 9);
		expect(at[1]).toBeCloseTo(seen.y, 9);
		expect(mesh.material.vertexShader).toContain('(v.xy / -v.z) / uLens.xy - uLens.zw');
	});

	it('take the dust’s column map and its origin, and hide with no share', () => {
		const { regions, mesh } = make();
		const map = new Texture();
		regions.show([1, 2, 3], { map, origin: [4, 5, 6] }, 2, 0.5, 1e-3);
		const u = mesh.material.uniforms;
		expect(u.uColumns.value).toBe(map);
		expect((u.uColumnOrigin.value as Vector3).toArray()).toEqual([4, 5, 6]);
		expect((u.uCamera.value as Vector3).toArray()).toEqual([1, 2, 3]);
		expect(u.uShare.value).toBe(0.5);
		regions.show([1, 2, 3], { map, origin: [4, 5, 6] }, 2, 0, 1e-3);
		expect(mesh.visible).toBe(false);
	});

	it('dim each at the lines’ K and keep its light whatever its size on screen', () => {
		const { mesh } = make();
		const text = mesh.material.vertexShader;
		expect(text).toContain(glslFloat(0.4 * Math.LN10 * 0.7954));
		expect(text).toContain('max(sigma / d, uPixel)');
		expect(text).toContain('smoothstep(1.0, 3.0, d / sigma)');
	});

	it('leave the scene when disposed', () => {
		const { scene, regions } = make();
		regions.dispose();
		expect(scene.getObjectByName('glow-regions')).toBeUndefined();
	});
});
