import type { Handle } from '@sveltejs/kit';

// Cloudflare Pages applies _headers only to static assets, so worker-rendered
// HTML needs its security headers set here. frame-ancestors ships via kit.csp.
export const handle: Handle = async ({ event, resolve }) => {
	const response = await resolve(event);
	response.headers.set('X-Frame-Options', 'DENY');
	response.headers.set('X-Content-Type-Options', 'nosniff');
	response.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin');
	response.headers.set('Strict-Transport-Security', 'max-age=31536000');
	response.headers.set(
		'Permissions-Policy',
		'geolocation=(self), camera=(), microphone=(), payment=(), usb=()'
	);
	// Without an explicit policy browsers heuristic-cache the shell, which can
	// outlive its hashed /_app/immutable/* chunks after a redeploy → white screen.
	const type = response.headers.get('Content-Type');
	if (type?.includes('text/html') && !response.headers.has('Cache-Control')) {
		response.headers.set('Cache-Control', 'no-cache');
	}
	return response;
};
