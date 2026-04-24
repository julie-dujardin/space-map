import { env } from '$env/dynamic/public';

/**
 * Base URL for the data API. In dev, defaults to `/data` which Vite proxies
 * to `DATA_SERVER_URL` (see vite.config.ts). In prod, set `PUBLIC_DATA_URL`
 * to the absolute origin of the data host.
 */
export const DATA_BASE = env.PUBLIC_DATA_URL || '/data';
