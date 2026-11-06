import type { NoticeSink } from './notice';

/** Sends the artist-impression notice for the body a sphere in view wears one
 *  on, again when that body changes, and dismisses it once none does. */
export class ImpressionNotifier {
	private shown: string | null = null;

	constructor(private readonly notices: NoticeSink) {}

	update(id: string | null): void {
		if (id === this.shown) return;
		this.shown = id;
		if (id !== null) this.notices.notify({ topic: 'artist-impression', id });
		else this.notices.dismiss('artist-impression');
	}
}
