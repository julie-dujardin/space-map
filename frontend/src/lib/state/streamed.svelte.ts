/** Page payloads a loader hands over unresolved, so a click on the site row
 *  switches page at once and the content lands behind it. */

/** Follows the promise a loader put in `data`, holding the last value it
 *  settled on. A navigation within the page — a query-string control editing
 *  what it draws — keeps that value on screen until the next one arrives,
 *  rather than dropping the page back to its pending state. */
export function streamed<T>(source: () => Promise<T>): {
	readonly value: T | undefined;
	readonly error: unknown;
} {
	let value = $state<T | undefined>(undefined);
	let error = $state<unknown>(undefined);

	$effect(() => {
		const pending = source();
		// A payload superseded while it was in flight is dropped: the page is
		// already following a newer one.
		void pending.then(
			(next) => {
				if (pending !== source()) return;
				value = next;
				error = undefined;
			},
			(reason) => {
				if (pending !== source()) return;
				error = reason;
			}
		);
	});

	return {
		get value() {
			return value;
		},
		get error() {
			return error;
		}
	};
}
