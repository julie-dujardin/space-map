/**
 * `/random` — a shareable link to nowhere in particular. Resolves a random
 * destination and redirects to it.
 *
 * Client-rendered: the walk reads the data tree through the client fetch layer,
 * whose `/data` path collides with the `[type]/[id]` route under SSR (same
 * reason as the credits page).
 */

import { redirect } from '@sveltejs/kit';
import { randomTarget, randomTargetPath } from '$lib/state/random-target';

export const ssr = false;

export const load = async () => {
	const target = await randomTarget();
	// Nothing drawn means the data tree never answered; the default view is
	// where a reader with no destination belongs.
	redirect(307, target ? randomTargetPath(target) : '/');
};
