import { toast } from 'svelte-sonner';
import * as m from '$lib/paraglide/messages.js';
import { formatJulianDate } from '$lib/format/date';
import type { Notice, NoticeTopic, OutOfRangeNotice } from '$lib/scene/notice';

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

/** Core notices as sticky toasts, keyed by topic so a repeat updates in place. */
export function showNotice(notice: Notice): void {
	switch (notice.topic) {
		case 'out-of-range':
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

export function dismissNotice(topic: NoticeTopic): void {
	toast.dismiss(topic);
}
