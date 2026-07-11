// App-wide screen-reader live regions (WCAG 4.1.3). One polite (role="status")
// and one assertive (role="alert") region are mounted once at the app root; a
// live region must already be in the DOM before its text changes to announce
// reliably, so feature code pushes text here rather than owning its own region.
//
// Setting the same string twice is a no-op (no DOM mutation, no re-announce) —
// which conveniently suppresses repeat announcements as a query is retyped.

let polite = $state('');
let assertive = $state('');

export function announce(message: string, opts?: { assertive?: boolean }): void {
	if (opts?.assertive) assertive = message;
	else polite = message;
}

export const announcements = {
	get polite() {
		return polite;
	},
	get assertive() {
		return assertive;
	}
};
