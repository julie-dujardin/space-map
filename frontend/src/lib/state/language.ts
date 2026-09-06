import { cookieName, setLocale } from '$lib/paraglide/runtime.js';
import { getSettings, type LanguageChoice } from '$lib/state/settings.svelte';

/** Store the choice, then let paraglide reload the page into it. 'auto' drops
 *  the cookie so preferredLanguage takes over again on the next load. */
export function switchLanguage(choice: LanguageChoice): void {
	getSettings().setLanguage(choice);
	if (choice === 'auto') {
		document.cookie = `${cookieName}=; path=/; max-age=0`;
		window.location.reload();
	} else {
		setLocale(choice);
	}
}
