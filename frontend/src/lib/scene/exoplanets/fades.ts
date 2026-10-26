/**
 * The share of each planetary system that may draw. A system shows while its
 * host's outer orbit is a few pixels across, by the switch of the solar
 * system (`system-fade.ts`), and fades in and out over the same time. A host
 * whose planets have no orbit counts as {@link NO_ORBIT_AU} across.
 */

import type { PlanetIndex } from '$lib/fetch/extrasolar/planets';
import { treeToScene, type Vec3 } from '$lib/scene/starfield/tree';
import { SwitchFade } from '$lib/scene/visibility/switch-fade';
import { systemShown } from '$lib/scene/visibility/system-fade';
import { NO_ORBIT_AU } from './bodies';

export interface SystemStep {
	/** Scene position of the camera, barycentre origin. */
	camera: Readonly<Vec3>;
	viewportPx: number;
	fovDeg: number;
	dtMs: number;
	/** 0 to 1: the share of the view outside the solar system. Systems draw only there. */
	outside: number;
	/** The hosts that may draw. Others fade out. */
	hosts: readonly number[];
	/** Whether a host's bodies are in and placed, so it can show. */
	ready: (host: number) => boolean;
}

interface Host {
	/** Scene position, barycentre origin. */
	at: Vec3;
	/** Outer orbit, AU. */
	radius: number;
}

interface HostState {
	shown: boolean;
	fade: SwitchFade;
}

export class SystemFades {
	private readonly hosts = new Map<number, Host>();
	private readonly state = new Map<number, HostState>();

	constructor(index: PlanetIndex) {
		for (const h of index.file.hosts) {
			if (!h.position) continue;
			const at = treeToScene(h.position[0], h.position[1], h.position[2], { x: 0, y: 0, z: 0 });
			this.hosts.set(h.id, { at: [at.x, at.y, at.z], radius: h.outer_orbit ?? NO_ORBIT_AU });
		}
	}

	/** The share above 0 of each host that draws. */
	step(s: SystemStep): Map<number, number> {
		const [cx, cy, cz] = s.camera;
		const seen = new Set<number>();
		for (const id of s.hosts) {
			const host = this.hosts.get(id);
			// A host with no place draws nothing.
			if (!host) continue;
			seen.add(id);
			const d = Math.hypot(host.at[0] - cx, host.at[1] - cy, host.at[2] - cz);
			let state = this.state.get(id);
			const shown = systemShown(d, s.viewportPx, s.fovDeg, state?.shown ?? false, host.radius);
			const on = shown && s.outside > 0 && s.ready(id);
			if (!state) {
				if (!on) continue;
				state = { shown, fade: new SwitchFade(false) };
				this.state.set(id, state);
			}
			state.shown = shown;
			state.fade.step(on, s.dtMs);
		}
		for (const [id, state] of this.state) {
			if (seen.has(id)) continue;
			state.shown = false;
			state.fade.step(false, s.dtMs);
		}
		const shares = new Map<number, number>();
		for (const [id, state] of this.state) {
			if (state.fade.share === 0 && !state.fade.fading) {
				this.state.delete(id);
				continue;
			}
			const share = state.fade.share * s.outside;
			if (share > 0) shares.set(id, share);
		}
		return shares;
	}

	/** True while a system fades in or out. */
	get fading(): boolean {
		for (const state of this.state.values()) if (state.fade.fading) return true;
		return false;
	}
}
