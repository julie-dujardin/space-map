/**
 * The sky of a chart from the skybox cube, for a page with no map to read it
 * from. It has a renderer of its own and loads the tiers itself: the smallest
 * first, and a larger one only for a chart that the smallest paints too
 * coarsely.
 */

import { WebGLRenderer, type CubeTexture } from 'three';
import { RetryBackoff } from '$lib/fetch/retry-backoff';
import type { SkyboxMetadata } from '$lib/fetch/metadata';
import { CubeSkySource, texelsPerPixel } from '$lib/star-chart/cube-sky';
import type { ChartFrame } from '$lib/star-chart/frame';
import type { Pixels, SkySource } from '$lib/star-chart/sky';
import { webgl2Canvas } from '$lib/star-chart/webgl';
import { loadSkyboxTier, skyboxTiers } from './skybox';

/** Under this many cube texels per painted pixel, the next tier is loaded. */
const MIN_TEXELS_PER_PIXEL = 0.5;

export class CubeTierSky implements SkySource {
	private readonly renderer: WebGLRenderer;
	private readonly source: CubeSkySource;
	private readonly tiers: string[];
	private cube: CubeTexture | null = null;
	private face = 0;
	private readonly loads = new Map<string, Promise<void>>();
	/** A tier that failed is asked for again after a wait. */
	private readonly retry = new RetryBackoff<string>((tier) => {
		this.loads.delete(tier);
		this.load(tier).catch(() => {});
	});
	/** A paint ended with no cube, so the charts hear of the first one. */
	private blank = false;
	private disposed = false;

	/** Throws on a device with no WebGL 2. */
	constructor(private readonly meta: SkyboxMetadata) {
		const held = webgl2Canvas({ alpha: true, antialias: false, depth: false, stencil: false });
		if (!held) throw new Error('star map needs WebGL 2');
		this.renderer = new WebGLRenderer({
			canvas: held.canvas,
			context: held.gl,
			antialias: false,
			depth: false,
			stencil: false
		});
		this.tiers = skyboxTiers(meta, this.renderer.capabilities.maxTextureSize);
		this.source = new CubeSkySource(this.renderer, () => this.cube);
	}

	async paint(
		frame: ChartFrame,
		width: number,
		height: number,
		signal?: AbortSignal
	): Promise<Pixels | null> {
		const smallest = this.tiers[0];
		if (!smallest) return null;
		const first = this.load(smallest);
		const wanted =
			this.tiers.find(
				(tier) => texelsPerPixel(frame, width, this.faceOf(tier)) >= MIN_TEXELS_PER_PIXEL
			) ?? this.tiers[this.tiers.length - 1];
		if (!this.cube) await first.catch(() => {});
		// The larger tier waits for the first picture, so the two do not share the line.
		if (wanted !== smallest) void first.then(() => this.load(wanted)).catch(() => {});
		if (this.disposed || signal?.aborted) return null;
		if (!this.cube) this.blank = true;
		return this.source.paint(frame, width, height);
	}

	finest(): number | null {
		return this.source.finest();
	}

	onChange(listener: () => void): () => void {
		return this.source.onChange(listener);
	}

	/** Frees the cube and the renderer's context. */
	dispose(): void {
		this.disposed = true;
		for (const tier of this.tiers) this.retry.clear(tier);
		this.cube?.dispose();
		this.cube = null;
		this.source.dispose();
		this.renderer.dispose();
		this.renderer.forceContextLoss();
	}

	private faceOf(tier: string): number {
		return this.meta.tier_face_size[tier] ?? 0;
	}

	/** A failed tier stays failed until its wait ends. */
	private load(tier: string): Promise<void> {
		let held = this.loads.get(tier);
		if (held) return held;
		held = loadSkyboxTier(this.renderer, this.meta, tier).then((cube) => {
			this.retry.clear(tier);
			if (this.disposed || this.faceOf(tier) <= this.face) {
				cube.dispose();
				return;
			}
			const shown = this.cube !== null;
			this.cube?.dispose();
			this.cube = cube;
			this.face = this.faceOf(tier);
			// A paint that waits for this cube paints it: only charts that show
			// another cube, or none, repaint.
			if (shown || this.blank) {
				this.blank = false;
				this.source.changed();
			}
		});
		held.catch((e: unknown) => {
			if (this.disposed) return;
			console.warn(`[star-chart] no skybox tier ${tier}:`, e);
			this.retry.fail(tier);
		});
		this.loads.set(tier, held);
		return held;
	}
}
