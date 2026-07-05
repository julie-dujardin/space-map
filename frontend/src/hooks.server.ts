import type { Handle } from '@sveltejs/kit';

// Cloudflare Pages applies _headers only to static assets, so worker-rendered
// HTML needs its security headers set here. frame-ancestors ships via kit.csp.
export const handle: Handle = async ({ event, resolve }) => {
	const response = await resolve(event);
	response.headers.set('X-Frame-Options', 'DENY');
	response.headers.set('X-Content-Type-Options', 'nosniff');
	response.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin');
	response.headers.set(
		'Permissions-Policy',
		'geolocation=(self), camera=(), microphone=(), payment=(), usb=()'
	);
	return response;
};
