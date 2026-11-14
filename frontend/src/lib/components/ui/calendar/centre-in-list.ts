/** Scrolls `list` so `item` sits mid-height. `scrollIntoView` would also
 *  scroll every clipping ancestor, and the picker with them. */
export function centreInList(list: HTMLElement, item: HTMLElement): void {
	const offset = item.getBoundingClientRect().top - list.getBoundingClientRect().top;
	list.scrollTop += offset - (list.clientHeight - item.offsetHeight) / 2;
}
