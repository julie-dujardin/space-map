// SSR is on so crawlers get real <head> meta; the WebGL app itself still mounts
// client-only (pages gate it behind `browser`). Prerendering stays off — pages
// are data-driven per request.
export const prerender = false;
export const ssr = true;
