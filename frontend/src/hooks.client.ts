import type { HandleClientError } from '@sveltejs/kit';
import { reportClientError } from '$lib/telemetry/report';

// SvelteKit-caught errors; the returned shape becomes `page.error` for +error.svelte.
export const handleError: HandleClientError = ({ error, message }) => {
	reportClientError('sveltekit', error);
	return { message: message || 'Something went wrong.' };
};

// Errors that bypass SvelteKit: uncaught throws (rAF/timeouts/listeners) and
// rejected promises with no handler — else a WebGL boot throw just vanishes.
if (typeof window !== 'undefined') {
	window.addEventListener('error', (e) => reportClientError('error', e.error ?? e.message));
	window.addEventListener('unhandledrejection', (e) =>
		reportClientError('unhandledrejection', e.reason)
	);
}
