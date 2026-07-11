import { sequence } from '@sveltejs/kit/hooks';
import type { Handle } from '@sveltejs/kit';
import { paraglideMiddleware } from '$lib/paraglide/server';
import { getTextDirection } from '$lib/paraglide/runtime';

// Resolve the request locale (cookie → Accept-Language) and stamp it onto the
// shell so the server-rendered <html> ships the right lang/dir. Without this
// RTL users get an LTR first paint and crawlers see the wrong language.
const handleParaglide: Handle = ({ event, resolve }) =>
	paraglideMiddleware(event.request, ({ request, locale }) => {
		event.request = request;
		return resolve(event, {
			transformPageChunk: ({ html }) =>
				html
					.replace('%paraglide.lang%', locale)
					.replace('%paraglide.dir%', getTextDirection(locale))
		});
	});

// Cloudflare Pages applies _headers only to static assets, so worker-rendered
// HTML needs its security headers set here. frame-ancestors ships via kit.csp.
const handleHeaders: Handle = async ({ event, resolve }) => {
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

export const handle = sequence(handleParaglide, handleHeaders);
