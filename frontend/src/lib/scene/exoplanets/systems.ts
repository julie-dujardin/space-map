/**
 * The planetary system the renderer draws, set once per frame: the system
 * of the focused star or planet. Each of its hosts draws by the pixel rule of
 * the solar system, with the halo, name and orbit line of each planet, and
 * the starfield draws the host at its exact place.
 */

import { ExtrasolarStaleError } from '$lib/fetch/extrasolar/files';
import { extrasolarObjectId } from '$lib/fetch/extrasolar/ids';
import { RetryBackoff } from '$lib/fetch/retry-backoff';
import type { Vec3 } from '$lib/scene/animation/math';
import type { PromotionRegistry } from '$lib/scene/focus/promotion';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import {
	isExoplanet,
	isExtrasolar,
	type PositionedBody,
	type StarAnchor
} from '$lib/types/objects';
import { SystemFades } from './fades';

/** Stars the starfield draws at their exact place at once. */
export const EXACT_STARS = 4;
/** The key of the index among the loads, which no host ID is. */
const INDEX = 0;

export interface SystemsFrame {
	/** Scene position of the camera, barycentre origin. */
	camera: Readonly<Vec3>;
	viewportPx: number;
	fovDeg: number;
	dtMs: number;
	/** 0 to 1: the share of the view outside the solar system. */
	outside: number;
	focused: PositionedBody | undefined;
}

export class ExoplanetSystems {
	private fades: SystemFades | null = null;
	/** Hosts whose system and body are on their way, and the index. */
	private readonly asked = new Set<number>();
	/** Failed loads wait before they are asked for again. */
	private readonly retries: RetryBackoff<number>;
	/** Drawn hosts by camera distance, nearest first. */
	private drawn: number[] = [];
	private drawnKey = '';

	constructor(
		private readonly ctx: ContextManager,
		private readonly promotion: PromotionRegistry,
		/** Called when a load lands that the next frame should draw. */
		private readonly onChange: () => void
	) {
		this.retries = new RetryBackoff(onChange);
	}

	/** True while a system fades in or out. */
	get fading(): boolean {
		return this.fades?.fading ?? false;
	}

	update(frame: SystemsFrame): void {
		const store = this.ctx.exoplanets;
		const star = this.starOf(frame.focused);
		if (!store.index) {
			if (star !== null) this.askIndex();
			return;
		}
		this.fades ??= new SystemFades(store.index);
		const key = star === null ? undefined : store.index.host(star)?.system;
		const hosts = key === undefined ? [] : store.index.hostsOf(key);
		for (const host of hosts) if (!this.loaded(host)) this.ask(host);
		const shares = this.fades.step({ ...frame, hosts, ready: (host) => this.ready(host) });

		const [cx, cy, cz] = frame.camera;
		const distance = (host: number): number => {
			const at = this.ctx.getBody(extrasolarObjectId(host))?.extrasolar?.scene;
			return at ? Math.hypot(at[0] - cx, at[1] - cy, at[2] - cz) : Infinity;
		};
		this.drawn = [...shares.keys()].sort((a, b) => distance(a) - distance(b));
		const byId = new Map<string, number>();
		for (const [host, share] of shares) byId.set(extrasolarObjectId(host), share);
		this.ctx.visibility.systemShares = byId;

		store.use(new Set(key === undefined ? [] : [key]));
		this.ctx.bodies.pinExtrasolar(new Set([...hosts, ...this.drawn].map(extrasolarObjectId)));
		this.syncBodies(frame.focused);
	}

	/** The stars to draw at their exact place: the focused one, then the
	 *  hosts of the drawn systems, nearest first. */
	exactStars(focused: PositionedBody | undefined): StarAnchor[] {
		const out: StarAnchor[] = [];
		const add = (star: StarAnchor | undefined) => {
			if (star && out.length < EXACT_STARS && !out.some((s) => s.id === star.id)) out.push(star);
		};
		if (focused && isExtrasolar(focused)) add(focused.extrasolar);
		if (focused && isExoplanet(focused)) {
			add(this.ctx.getBody(focused.data.parentId)?.extrasolar);
		}
		for (const host of this.drawn) add(this.ctx.getBody(extrasolarObjectId(host))?.extrasolar);
		return out;
	}

	/** The star that a focused star or planet belongs to. */
	private starOf(body: PositionedBody | undefined): number | null {
		if (!body) return null;
		return body.exoplanet?.host ?? (isExtrasolar(body) ? (body.extrasolar?.id ?? null) : null);
	}

	private askIndex(): void {
		if (this.asked.has(INDEX) || this.retries.waiting(INDEX)) return;
		this.asked.add(INDEX);
		this.ctx.exoplanets.loadIndex().then(
			() => {
				this.retries.clear(INDEX);
				this.onChange();
			},
			(e) => {
				console.warn('[planets] the index did not load:', e);
				// Files from a newer export: the reload prompt is up, and nothing more loads.
				if (e instanceof ExtrasolarStaleError) return;
				this.asked.delete(INDEX);
				this.retries.fail(INDEX);
			}
		);
	}

	/** Hold a host's system and its body. */
	private ask(host: number): void {
		if (this.asked.has(host) || this.retries.waiting(host)) return;
		this.asked.add(host);
		this.ctx.exoplanets.ensureHost(host).then(
			() => {
				this.asked.delete(host);
				this.retries.clear(host);
				this.onChange();
			},
			(e) => {
				console.warn(`[planets] the system of ${host} did not load:`, e);
				if (e instanceof ExtrasolarStaleError) return;
				// Asked for again after a wait, if it is still wanted.
				this.asked.delete(host);
				this.retries.fail(host);
			}
		);
	}

	/** Whether a host's system and its body are held, and the body has the
	 *  place that the index gives a host with none of its own. */
	private loaded(host: number): boolean {
		const star = this.ctx.getBody(extrasolarObjectId(host))?.extrasolar;
		const placed = !!star?.scene || !this.ctx.exoplanets.index?.host(host)?.position;
		return this.ctx.exoplanets.held(host) !== null && !!star && placed;
	}

	/** A host shows once its planets are in and it has a place. */
	private ready(host: number): boolean {
		const star = this.ctx.getBody(extrasolarObjectId(host));
		return this.ctx.exoplanets.held(host) !== null && !!star?.extrasolar?.scene;
	}

	/** Give the drawn planets and their hosts a halo and a name, and take them
	 *  from the ones that left. */
	private syncBodies(focused: PositionedBody | undefined): void {
		const bodies: PositionedBody[] = [];
		for (const host of this.drawn) {
			const star = this.ctx.getBody(extrasolarObjectId(host));
			if (star) bodies.push(star);
			bodies.push(...(this.ctx.exoplanets.held(host)?.planets.get(host) ?? []));
		}
		const key = `${bodies.map((b) => b.data.id).join(',')}|${focused?.data.id ?? ''}`;
		if (key === this.drawnKey) return;
		this.drawnKey = key;
		this.promotion.syncSystemBodies(bodies);
	}
}
