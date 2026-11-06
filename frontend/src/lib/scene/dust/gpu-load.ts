/**
 * The load of an export that draws on the GPU: its metadata, then its data, an
 * upload over frames, then the build of what draws. `StarDust` and the glow both
 * go through it, so a load that fails, a lost context and a restore act the same
 * in both.
 */

import type { WebGLRenderer } from 'three';
import { ExtrasolarStaleError } from '$lib/fetch/extrasolar/files';
import { RetryBackoff } from '$lib/fetch/retry-backoff';
import { NestFormatError } from './nest';

export type LoadPhase = 'idle' | 'loading' | 'uploading' | 'ready' | 'none';

/** What the owner of a load does at its steps. */
export interface LoadSteps<M, D> {
	/** The metadata, or null where this host has none to draw. */
	metadata(): Promise<M | null>;
	/** The data of the load in hand is in: make what it uploads to. Returns
	 *  `uploading`, or `ready` where nothing goes to the GPU. */
	received(meta: M, data: D): LoadPhase;
	/** Free the GPU objects. With `live` false, a lost context took them. */
	release(live: boolean): void;
	/** Set the owner's own state back to that of a new load. */
	reset(): void;
}

/** What uploads over frames. */
export interface Upload {
	readonly uploaded: boolean;
	step(): void;
}

export class GpuLoad<M, D> {
	/** The owner moves it only from `ready`, to build again on what is uploaded. */
	phase: LoadPhase = 'idle';
	/** Kept across restarts: it is the same for every plan. */
	meta: M | null = null;
	private loads = 0;
	private readonly retries: RetryBackoff<string>;
	private readonly metaKey: string;
	private readonly dataKey: string;

	/** `tag` and `what` name the load in a warning: `[dust] the nest did not load`. */
	constructor(
		private readonly renderer: WebGLRenderer,
		private readonly tag: string,
		private readonly what: string,
		private readonly steps: LoadSteps<M, D>,
		private readonly onChange: () => void
	) {
		this.retries = new RetryBackoff<string>(() => onChange());
		this.metaKey = `${tag} metadata`;
		this.dataKey = `${tag} data`;
		renderer.domElement.addEventListener('webglcontextrestored', this.onRestored);
	}

	private get lost(): boolean {
		return this.renderer.getContext().isContextLost();
	}

	/** Load from `idle`, with `data` for the data of the plan in hand. Nothing
	 *  starts while a failure waits out its delay, or on a lost context. */
	start(data: (meta: M) => Promise<D>): void {
		if (this.lost || this.retries.waiting(this.metaKey) || this.retries.waiting(this.dataKey)) {
			return;
		}
		this.phase = 'loading';
		void this.load(data);
	}

	private async load(data: (meta: M) => Promise<D>): Promise<void> {
		const loadId = ++this.loads;
		let key = this.metaKey;
		try {
			const meta = this.meta ?? (await this.steps.metadata());
			if (loadId !== this.loads) return;
			this.retries.clear(this.metaKey);
			if (!meta) {
				this.phase = 'none';
				return;
			}
			this.meta = meta;
			key = this.dataKey;
			const value = await data(meta);
			if (loadId !== this.loads) return;
			this.retries.clear(this.dataKey);
			this.phase = this.steps.received(meta, value);
			this.onChange();
		} catch (err) {
			if (loadId !== this.loads) return;
			console.warn(`[${this.tag}] ${this.what} did not load:`, err);
			if (err instanceof ExtrasolarStaleError || err instanceof NestFormatError) {
				// The files are not the ones the metadata lists. A retry reads the same.
				this.phase = 'none';
				return;
			}
			this.phase = 'idle';
			this.retries.fail(key);
		}
	}

	/** One frame of the upload, then the build. A throw of the build goes to `fail`. */
	upload(upload: Upload, build: () => void, failed: (err: unknown) => LoadPhase): void {
		if (!upload.uploaded) {
			upload.step();
			return;
		}
		try {
			build();
			this.phase = 'ready';
		} catch (err) {
			this.fail(err, failed);
		}
	}

	/**
	 * Something the owner makes on the GPU threw. On a lost context it is no
	 * fault of the device: what was made goes, and the restore builds again. Any
	 * other throw would repeat on every frame, so `failed` gives the phase the
	 * session goes on in.
	 */
	fail(err: unknown, failed: (err: unknown) => LoadPhase): void {
		const lost = this.lost;
		this.steps.release(!lost);
		this.phase = lost ? 'idle' : failed(err);
	}

	/**
	 * Back to the start, for a plan change and a restored context. What the old
	 * plan built is of no use to the new one, and a load on its way is for the
	 * old one.
	 */
	restart(live: boolean): void {
		this.loads++;
		this.retries.clear(this.dataKey);
		this.steps.release(live);
		if (this.phase !== 'none') this.phase = 'idle';
		this.steps.reset();
		this.onChange();
	}

	private readonly onRestored = (): void => this.restart(false);

	dispose(): void {
		this.loads++;
		// A retry calls `onChange` at the end of its wait. Nothing may call it after this.
		this.retries.clear(this.metaKey);
		this.retries.clear(this.dataKey);
		this.renderer.domElement.removeEventListener('webglcontextrestored', this.onRestored);
		this.steps.release(true);
		this.phase = 'none';
	}
}
