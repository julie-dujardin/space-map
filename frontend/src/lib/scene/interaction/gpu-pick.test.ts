import { describe, expect, it } from 'vitest';
import {
	BufferGeometry,
	Float32BufferAttribute,
	PerspectiveCamera,
	Points,
	PointsMaterial,
	type Scene,
	type WebGLRenderer
} from 'three';
import { GpuPickPass } from './gpu-pick';

/** A renderer that logs how many objects each render draws. */
function fakeRenderer(drawn: number[]): WebGLRenderer {
	return {
		autoClear: true,
		getRenderTarget: () => null,
		setRenderTarget: () => {},
		getClearColor: (c: unknown) => c,
		getClearAlpha: () => 1,
		setClearColor: () => {},
		clear: () => {},
		render: (scene: Scene) => drawn.push(scene.children.length),
		readRenderTargetPixels: () => {}
	} as unknown as WebGLRenderer;
}

describe('GpuPickPass', () => {
	it('keeps nothing of a pick after it', () => {
		const drawn: number[] = [];
		const camera = new PerspectiveCamera();
		const pass = new GpuPickPass(fakeRenderer(drawn), camera);
		const geometry = new BufferGeometry();
		geometry.setAttribute('position', new Float32BufferAttribute([0, 0, -1], 3));
		const material = new PointsMaterial();
		const points = new Points(geometry, material);
		const rect = { left: 0, top: 0, width: 100, height: 100 } as DOMRect;

		pass.pickDraws([{ points, material }], camera, 50, 50, rect, 24);

		// The second render, of the empty scene, makes the renderer drop its list.
		expect(drawn).toEqual([1, 0]);
		const { proxies } = pass as unknown as { proxies: Points[] };
		expect(proxies).toHaveLength(1);
		expect(proxies[0].geometry).not.toBe(geometry);
		expect(proxies[0].material).not.toBe(material);
	});
});
