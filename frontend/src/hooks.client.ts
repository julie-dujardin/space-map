import type { HandleClientError } from '@sveltejs/kit';
import { getLocale, overwriteGetLocale } from '$lib/paraglide/runtime.js';

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
