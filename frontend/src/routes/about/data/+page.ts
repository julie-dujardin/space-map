/**
 * Loader of the data page. The page is static: it imports nothing of the 3D
 * map.
 */

import { dataBase } from '$lib/fetch/data-base';
import { fetchLabels, type LabelMap } from '$lib/fetch/position/labels';
import type { AboutData, DataPage } from '$lib/about/data-payload';

// On the server, a fetch of `/data` collides with the [type]/[id] route.
export const ssr = false;

// The payload is not awaited: the frame of the page draws before it lands.
export const load = ({
	fetch
}: {
	fetch: typeof globalThis.fetch;
}): { report: Promise<DataPage> } => {
	const data = (async () => {
		const res = await fetch(`${dataBase()}/v1/about-data.json`);
		if (!res.ok) throw new Error(`Failed to load about-data.json: ${res.status}`);
		return (await res.json()) as AboutData;
	})();
	// Without the labels the page shows the English names of the report.
	const labels = fetchLabels().catch((): LabelMap => new Map());
	const report = Promise.all([data, labels]).then(([data, labels]) => ({ data, labels }));
	return { report };
};
