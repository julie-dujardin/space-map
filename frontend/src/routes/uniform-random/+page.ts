/**
 * `/uniform-random` — the same link as `/random`, drawn without the tree. One
 * ticket per catalogued thing, so it nearly always lands on a Main Belt rock.
 *
 * Client-rendered for the same reason as `/random`: the draw reads the data
 * tree through the client fetch layer, whose `/data` path collides with the
 * `[type]/[id]` route under SSR.
 */

import { redirect } from '@sveltejs/kit';
import { randomTargetPath } from '$lib/state/random-target';
import { uniformRandomTarget } from '$lib/state/uniform-random-target';

export const ssr = false;

export const load = async () => {
	const target = await uniformRandomTarget();
	redirect(307, target ? randomTargetPath(target) : '/');
};
