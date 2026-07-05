import type { HandleClientError } from '@sveltejs/kit';

// SvelteKit-caught errors; the returned shape becomes `page.error` for +error.svelte.
export const handleError: HandleClientError = ({ error, message }) => {
	console.error('[sveltekit]', error);
	return { message: message || 'Something went wrong.' };
};
