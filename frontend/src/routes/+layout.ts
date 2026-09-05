import type { LayoutLoad } from './$types';
import { browser } from '$app/environment';
import { getLocale } from '$lib/paraglide/runtime';
import { loadLocaleMessages } from '$lib/i18n/locale-messages';

// SSR is on so crawlers get real <head> meta; the WebGL app itself still mounts
// client-only (pages gate it behind `browser`). Prerendering stays off — pages
// are data-driven per request.
export const prerender = false;
export const ssr = true;

// The client ships the base locale's messages only; the active locale's
// module must be in before hydration renders in it.
export const load: LayoutLoad = async () => {
	if (browser) await loadLocaleMessages(getLocale());
};
