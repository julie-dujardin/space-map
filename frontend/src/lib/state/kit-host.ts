import { env } from '$env/dynamic/public';
import * as m from '$lib/paraglide/messages.js';
import { getLocale } from '$lib/paraglide/runtime.js';
import type { Host } from '$lib/host';

/** The SvelteKit app's side of the core seam, for server and client alike;
 *  the client adds label links and notices on top. */
export const KIT_HOST: Partial<Host> = {
	// An explicit data origin serves images too (dev's `/data` proxy does);
	// unset, the production origins in the host defaults stand.
	...(env.PUBLIC_DATA_URL ? { dataUrl: env.PUBLIC_DATA_URL, imagesUrl: env.PUBLIC_DATA_URL } : {}),
	// Read through the live binding: the client swaps in a cached getLocale.
	locale: () => getLocale(),
	messages: m
};
