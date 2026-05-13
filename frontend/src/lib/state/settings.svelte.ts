import { cookieName, getLocale, locales, setLocale, type Locale } from '$lib/paraglide/runtime.js';

/**
 * User-tunable display settings, persisted to localStorage. A module-level
 * singleton because formatters (date, etc.) read these from non-component
 * code and the choices apply globally.
 *
 * Each setting can be 'auto' — meaning derived from the environment (browser
 * language, prefers-color-scheme, locale hour cycle). The UI surfaces *which*
 * environment input the auto resolved to so the user knows what's in effect.
 */

const STORAGE_KEY = 'space-map-settings';

export type Theme = 'auto' | 'light' | 'dark';
export type Clock = 'auto' | '12h' | '24h';
export type DateFormatChoice = 'auto' | 'iso';
export type LanguageChoice = 'auto' | Locale;

interface Persisted {
	theme?: Theme;
	clock?: Clock;
	dateFormat?: DateFormatChoice;
	language?: LanguageChoice;
}

function readPersisted(): Persisted {
	if (typeof localStorage === 'undefined') return {};
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		return raw ? (JSON.parse(raw) as Persisted) : {};
	} catch {
		return {};
	}
}

function localeUses12h(locale: string): boolean {
	const opts = new Intl.DateTimeFormat(locale, { hour: 'numeric' }).resolvedOptions();
	return opts.hour12 === true || opts.hourCycle === 'h11' || opts.hourCycle === 'h12';
}

class SettingsState {
	theme = $state<Theme>('auto');
	clock = $state<Clock>('auto');
	dateFormat = $state<DateFormatChoice>('auto');
	language = $state<LanguageChoice>('auto');
	#systemDark = $state(false);

	constructor() {
		const stored = readPersisted();
		this.theme = stored.theme ?? 'auto';
		this.clock = stored.clock ?? 'auto';
		this.dateFormat = stored.dateFormat ?? 'auto';
		this.language = stored.language ?? 'auto';

		if (typeof window !== 'undefined' && window.matchMedia) {
			const mq = window.matchMedia('(prefers-color-scheme: dark)');
			this.#systemDark = mq.matches;
			mq.addEventListener('change', (e) => (this.#systemDark = e.matches));
		}
	}

	setTheme(v: Theme) {
		this.theme = v;
		this.persist();
	}

	setClock(v: Clock) {
		this.clock = v;
		this.persist();
	}

	setDateFormat(v: DateFormatChoice) {
		this.dateFormat = v;
		this.persist();
	}

	/**
	 * Switching language triggers a paraglide reload. 'auto' deletes the cookie
	 * so preferredLanguage takes over again on next load.
	 */
	setLanguage(v: LanguageChoice) {
		this.language = v;
		this.persist();
		if (v === 'auto') {
			document.cookie = `${cookieName}=; path=/; max-age=0`;
			window.location.reload();
		} else {
			setLocale(v);
		}
	}

	/** Resolved theme — never 'auto'. */
	get resolvedTheme(): 'light' | 'dark' {
		if (this.theme === 'auto') return this.#systemDark ? 'dark' : 'light';
		return this.theme;
	}

	/** Resolved hour-cycle preference: true for 12h, false for 24h. */
	get resolvedHour12(): boolean {
		if (this.clock === '12h') return true;
		if (this.clock === '24h') return false;
		return localeUses12h(getLocale());
	}

	/** Resolved date format. */
	get resolvedDateFormat(): 'locale' | 'iso' {
		return this.dateFormat === 'iso' ? 'iso' : 'locale';
	}

	/** Browser language tag, used to label the "auto" language source. */
	get browserLanguage(): string {
		if (typeof navigator === 'undefined') return 'en';
		return navigator.language || 'en';
	}

	/** Locale list for the language picker (excludes 'auto'). */
	get availableLocales(): readonly Locale[] {
		return locales;
	}

	private persist() {
		if (typeof localStorage === 'undefined') return;
		try {
			const data: Persisted = {
				theme: this.theme,
				clock: this.clock,
				dateFormat: this.dateFormat,
				language: this.language
			};
			localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
		} catch {
			// localStorage can throw in private-mode Safari — drop silently.
		}
	}
}

let instance: SettingsState | undefined;

/** Lazily construct on first access; SSR is disabled so this only runs client-side. */
export function getSettings(): SettingsState {
	if (!instance) instance = new SettingsState();
	return instance;
}
