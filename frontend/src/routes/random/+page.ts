/**
 * `/random` — a shareable link to nowhere in particular. The page resolves a
 * random destination and replaces itself with it.
 *
 * Client-rendered: the walk reads the data tree through the client fetch layer,
 * whose `/data` path collides with the `[type]/[id]` route under SSR (same
 * reason as the credits page).
 */

export const ssr = false;
