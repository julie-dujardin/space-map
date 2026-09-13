import { toast } from 'svelte-sonner';
import * as m from '$lib/paraglide/messages.js';

/** Hand the page's URL to the native share sheet, or to the clipboard where
 *  there is none. */
export async function shareUrl(title: string): Promise<void> {
	const url = window.location.href;
	if (navigator.share) {
		try {
			await navigator.share({ url, title });
			return;
		} catch (err) {
			// The reader closed the sheet.
			if ((err as DOMException).name === 'AbortError') return;
		}
	}
	try {
		await navigator.clipboard.writeText(url);
		toast.success(m.link_copied());
	} catch (err) {
		console.warn('Share failed:', err);
	}
}
