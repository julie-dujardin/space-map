import { afterEach, describe, expect, it, vi } from 'vitest';
import { CubeTexture } from 'three';
import { StarlessSky } from './starless';

afterEach(() => {
	vi.restoreAllMocks();
});

describe('StarlessSky', () => {
	it('loads once, on the first call, and tells when it lands', async () => {
		const cube = new CubeTexture();
		const load = vi.fn(async () => cube);
		const changed = vi.fn();
		const sky = new StarlessSky(load, changed);
		expect(load).not.toHaveBeenCalled();
		expect(sky.get()).toBeNull();
		expect(sky.loading).toBe(true);
		await Promise.resolve();
		expect(sky.get()).toBe(cube);
		expect(sky.loading).toBe(false);
		expect(load).toHaveBeenCalledTimes(1);
		expect(changed).toHaveBeenCalledTimes(1);
	});

	it('gives null for good after a failed load', async () => {
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
		const load = vi.fn(async () => {
			throw new Error('404');
		});
		const sky = new StarlessSky(load, () => {});
		sky.get();
		await Promise.resolve();
		await Promise.resolve();
		expect(sky.get()).toBeNull();
		expect(sky.loading).toBe(false);
		expect(load).toHaveBeenCalledTimes(1);
		expect(warn).toHaveBeenCalledTimes(1);
	});

	it('frees a cube that lands after it is disposed', async () => {
		const cube = new CubeTexture();
		const dispose = vi.spyOn(cube, 'dispose');
		let resolve: (cube: CubeTexture | null) => void = () => {};
		const sky = new StarlessSky(
			() => new Promise((r) => (resolve = r)),
			() => {}
		);
		sky.get();
		sky.dispose();
		resolve(cube);
		await Promise.resolve();
		expect(dispose).toHaveBeenCalledTimes(1);
		expect(sky.get()).toBeNull();
	});
});
