import { env } from '$env/dynamic/public';
import * as m from '$lib/paraglide/messages.js';
import { getLocale } from '$lib/paraglide/runtime.js';
import type { HostOverrides } from '$lib/host';

// Images are their own export project, so they follow the data origin only
// when nothing names theirs; unset, the production origins in the host
// defaults stand. In dev both are proxy prefixes (`/data`, `/images`).
const IMAGES_URL = env.PUBLIC_IMAGES_URL || env.PUBLIC_DATA_URL;

/** The SvelteKit app's side of the core seam, for server and client alike;
 *  the client adds label links and notices on top. The app's bundle carries
 *  the wording the app itself shows; text only the SDK renders keeps the
 *  English the host defaults hold. */
export const KIT_HOST: HostOverrides = {
	...(env.PUBLIC_DATA_URL ? { dataUrl: env.PUBLIC_DATA_URL } : {}),
	...(IMAGES_URL ? { imagesUrl: IMAGES_URL } : {}),
	// Read through the live binding: the client swaps in a cached getLocale.
	locale: () => getLocale(),
	messages: m,
	// spacemap.co is the site the site-only maps are cleared for.
	textures: 'site-only'
};
