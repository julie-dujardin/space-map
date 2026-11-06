/**
 * The sky from the Sun without its bright stars. Past the join the glow reads
 * it in place of the skybox: there the stars draw as points, so the skybox's
 * stars would count twice. It loads the first time the glow asks for it, so the
 * view from the Sun costs nothing.
 */

import type { CubeTexture } from 'three';

export class StarlessSky {
	private cube: CubeTexture | null = null;
	private state: 'idle' | 'loading' | 'done' = 'idle';

	/** `load` gives null where the export has none. */
	constructor(
		private readonly load: () => Promise<CubeTexture | null>,
		private readonly onChange: () => void
	) {}

	/** The cube once it is loaded. The first call starts the load. */
	get(): CubeTexture | null {
		if (this.state === 'idle') {
			this.state = 'loading';
			this.load().then(
				(cube) => this.loaded(cube),
				(err: unknown) => {
					console.warn('[glow] the starless sky did not load:', err);
					this.loaded(null);
				}
			);
		}
		return this.cube;
	}

	/** True while the load is under way: the sky changes when it ends. */
	get loading(): boolean {
		return this.state === 'loading';
	}

	dispose(): void {
		this.cube?.dispose();
		this.cube = null;
		this.state = 'done';
	}

	private loaded(cube: CubeTexture | null): void {
		// Disposed while it loaded.
		if (this.state !== 'loading') {
			cube?.dispose();
			return;
		}
		this.cube = cube;
		this.state = 'done';
		this.onChange();
	}
}
