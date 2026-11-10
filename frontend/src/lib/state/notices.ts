import { toast } from 'svelte-sonner';
import * as m from '$lib/paraglide/messages.js';
import { formatJulianDate } from '$lib/format/date';
import type { ArtistImpressionNotice, Notice, OutOfRangeNotice } from '$lib/scene/notice';

function outOfRangeLines(notice: OutOfRangeNotice): string[] {
	const lines: string[] = [];
	if (notice.focusedOutOfRange) lines.push(m.out_of_range_selected());
	const sat = notice.satellites;
	if (sat?.side === 'after') {
		lines.push(m.out_of_range_satellites_after({ date: formatJulianDate(sat.jd) }));
	} else if (sat?.side === 'gap') {
		lines.push(m.out_of_range_satellites_outside());
	}
	const major = notice.majorBodies;
	if (major?.side === 'after') {
		lines.push(m.out_of_range_major_bodies_after({ date: formatJulianDate(major.jd) }));
	} else if (major?.side === 'before') {
		lines.push(m.out_of_range_major_bodies_before({ date: formatJulianDate(major.jd) }));
	} else if (major?.side === 'outside') {
		lines.push(m.out_of_range_major_bodies_outside());
	}
	return lines;
}

/** The page's arrival toast for an object with no place at this date, which a
 *  later date can make false. */
export const UNPLACED_TOAST = 'object-unplaced';

/** The notices shown as toasts. The page shows an artist's impression in a box. */
type ToastNotice = Exclude<Notice, ArtistImpressionNotice>;
type ToastTopic = ToastNotice['topic'];

/** Core notices as sticky toasts, keyed by topic so a repeat updates in place. */
export function showNotice(notice: ToastNotice): void {
	switch (notice.topic) {
		case 'out-of-range':
			if (!notice.focusedOutOfRange) toast.dismiss(UNPLACED_TOAST);
			toast.warning(m.out_of_range_title(), {
				id: notice.topic,
				description: outOfRangeLines(notice).join('\n'),
				duration: Number.POSITIVE_INFINITY,
				closeButton: true
			});
			return;
		case 'coverage-pause': {
			const { name } = notice;
			const date = formatJulianDate(notice.jd);
			toast.info(m.coverage_pause_title(), {
				id: notice.topic,
				description:
					notice.direction === 'forward'
						? m.coverage_pause_forward({ name, date })
						: m.coverage_pause_backward({ name, date }),
				duration: Number.POSITIVE_INFINITY
			});
		}
	}
}

export function dismissNotice(topic: ToastTopic): void {
	if (topic === 'out-of-range') toast.dismiss(UNPLACED_TOAST);
	toast.dismiss(topic);
}
