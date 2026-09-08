import type { ClientInit, HandleClientError } from '@sveltejs/kit';
import { getLocale, overwriteGetLocale } from '$lib/paraglide/runtime.js';
import { configureHost } from '$lib/host';
import { KIT_HOST } from '$lib/state/kit-host';
import { setSceneSettings } from '$lib/scene/settings.svelte';
import { getSettings } from '$lib/state/settings.svelte';
import { bodyHref } from '$lib/state/url';

// The core's view of the app: data origins, language, label links, and the
// persisted display settings. What the map reports back arrives as events.
export const init: ClientInit = () => {
	configureHost({ ...KIT_HOST, bodyHref });
	setSceneSettings(getSettings());
};

// SvelteKit-caught errors; the returned shape becomes `page.error` for +error.svelte.
export const handleError: HandleClientError = ({ error, message }) => {
	console.error('[sveltekit]', error);
	return { message: message || 'Something went wrong.' };
};

// Paraglide re-reads document.cookie on every getLocale() call, and the time
// bar and number formatters call it many times per frame. Locale changes
// reload the page (setLocale defaults to reload), so one value per page load is
// exact.
{
	const resolve = getLocale;
	let cached: ReturnType<typeof getLocale> | undefined;
	overwriteGetLocale(() => (cached ??= resolve()));
}
