import { cookieName, getLocale, setLocale, type Locale } from '$lib/paraglide/runtime.js';
import type {
	AtmosphereCalibration,
	AtmosphereQualityConfig,
	AtmosphereQualityTier,
	ResolvedAtmosphereTier
} from '$lib/scene/objects/surface/atmosphere-quality';

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
export type ReducedMotion = 'auto' | 'on' | 'off';
export type DateFormatChoice = 'auto' | 'iso';
export type LanguageChoice = 'auto' | Locale;
export type ViewMode = 'map' | 'immersive';

interface Persisted {
	theme?: Theme;
	clock?: Clock;
	reducedMotion?: ReducedMotion;
	dateFormat?: DateFormatChoice;
	language?: LanguageChoice;
	showDebugInfo?: boolean;
	showSkyboxAlign?: boolean;
	showHaloDebug?: boolean;
	showLightingTuner?: boolean;
	showClouds?: boolean;
	showAtmospheres?: boolean;
	atmosphereQuality?: AtmosphereQualityTier;
	atmosphereAutoTier?: ResolvedAtmosphereTier;
	atmosphereCalibration?: AtmosphereCalibration;
	highAmbient?: boolean;
	realisticLighting?: boolean;
	showShapeMesh?: boolean;
	showSurfaceTexture?: boolean;
	showDisplacement?: boolean;
	showSelfShadow?: boolean;
	viewMode?: ViewMode;
	maxPartsPerZone?: number;
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
	reducedMotion = $state<ReducedMotion>('auto');
	dateFormat = $state<DateFormatChoice>('auto');
	language = $state<LanguageChoice>('auto');
	showDebugInfo = $state(false);
	showSkyboxAlign = $state(false);
	showHaloDebug = $state(false);
	showLightingTuner = $state(false);
	showClouds = $state(true);
	/** Per-body atmospheric-scattering shells (sky glow, sunset limb). */
	showAtmospheres = $state(true);
	/** Shell quality tier; 'auto' resolves from device capability. */
	atmosphereQuality = $state<AtmosphereQualityTier>('auto');
	/** Tier the perf governor settled on for this device (auto mode only);
	 *  null until a downgrade has ever triggered. */
	atmosphereAutoTier = $state<ResolvedAtmosphereTier | null>(null);
	/** Boot benchmark result; null until the first calibration completes. */
	atmosphereCalibration = $state<AtmosphereCalibration | null>(null);
	/** Session-only debug knob overrides on top of the tier preset — not
	 *  persisted, and cleared when the tier is changed. */
	atmoQualityOverrides = $state<Partial<AtmosphereQualityConfig>>({});
	/** Flood the scene with flat ambient fill so night sides are fully lit. */
	highAmbient = $state(false);
	/** Scale sunlight with the true inverse-square distance from the Sun instead
	 *  of lighting every body as if it sat at 1 AU. */
	realisticLighting = $state(false);
	/** Debug body-layer toggles: peel back the focused body's render stack to
	 *  isolate a layer (e.g. shape mesh off → textured triaxial sphere). */
	showShapeMesh = $state(true);
	showSurfaceTexture = $state(true);
	showDisplacement = $state(true);
	showSelfShadow = $state(true);
	viewMode = $state<ViewMode>('map');
	/** Debug cap on parts loaded per zone. 0 = unlimited. Only takes effect on
	 *  the next page load — already-resident chunks aren't unloaded. */
	maxPartsPerZone = $state(0);
	#systemDark = $state(false);
	#systemReducedMotion = $state(false);

	constructor() {
		const stored = readPersisted();
		this.theme = stored.theme ?? 'auto';
		this.clock = stored.clock ?? 'auto';
		this.reducedMotion = stored.reducedMotion ?? 'auto';
		this.dateFormat = stored.dateFormat ?? 'auto';
		this.language = stored.language ?? 'auto';
		this.showDebugInfo = stored.showDebugInfo ?? false;
		this.showSkyboxAlign = stored.showSkyboxAlign ?? false;
		this.showHaloDebug = stored.showHaloDebug ?? false;
		this.showLightingTuner = stored.showLightingTuner ?? false;
		this.showClouds = stored.showClouds ?? true;
		this.showAtmospheres = stored.showAtmospheres ?? true;
		this.atmosphereQuality = stored.atmosphereQuality ?? 'auto';
		this.atmosphereAutoTier = stored.atmosphereAutoTier ?? null;
		this.atmosphereCalibration = stored.atmosphereCalibration ?? null;
		this.highAmbient = stored.highAmbient ?? false;
		this.realisticLighting = stored.realisticLighting ?? false;
		this.showShapeMesh = stored.showShapeMesh ?? true;
		this.showSurfaceTexture = stored.showSurfaceTexture ?? true;
		this.showDisplacement = stored.showDisplacement ?? true;
		this.showSelfShadow = stored.showSelfShadow ?? true;
		this.viewMode = stored.viewMode ?? 'map';
		this.maxPartsPerZone = stored.maxPartsPerZone ?? 0;

		if (typeof window !== 'undefined' && window.matchMedia) {
			const mq = window.matchMedia('(prefers-color-scheme: dark)');
			this.#systemDark = mq.matches;
			mq.addEventListener('change', (e) => (this.#systemDark = e.matches));

			const rm = window.matchMedia('(prefers-reduced-motion: reduce)');
			this.#systemReducedMotion = rm.matches;
			rm.addEventListener('change', (e) => (this.#systemReducedMotion = e.matches));
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

	setReducedMotion(v: ReducedMotion) {
		this.reducedMotion = v;
		this.persist();
	}

	setDateFormat(v: DateFormatChoice) {
		this.dateFormat = v;
		this.persist();
	}

	setShowDebugInfo(v: boolean) {
		this.showDebugInfo = v;
		this.persist();
	}

	setShowSkyboxAlign(v: boolean) {
		this.showSkyboxAlign = v;
		this.persist();
	}

	setShowHaloDebug(v: boolean) {
		this.showHaloDebug = v;
		this.persist();
	}

	setShowLightingTuner(v: boolean) {
		this.showLightingTuner = v;
		this.persist();
	}

	setShowClouds(v: boolean) {
		this.showClouds = v;
		this.persist();
	}

	setShowAtmospheres(v: boolean) {
		this.showAtmospheres = v;
		this.persist();
	}

	setAtmosphereQuality(v: AtmosphereQualityTier) {
		this.atmosphereQuality = v;
		this.atmoQualityOverrides = {};
		this.persist();
	}

	setAtmosphereAutoTier(v: ResolvedAtmosphereTier | null) {
		this.atmosphereAutoTier = v;
		this.persist();
	}

	setAtmosphereCalibration(v: AtmosphereCalibration | null) {
		this.atmosphereCalibration = v;
		this.persist();
	}

	/** Merge debug knob overrides onto the current tier preset (session-only). */
	setAtmoQualityOverrides(patch: Partial<AtmosphereQualityConfig>) {
		this.atmoQualityOverrides = { ...this.atmoQualityOverrides, ...patch };
	}

	setHighAmbient(v: boolean) {
		this.highAmbient = v;
		this.persist();
	}

	setRealisticLighting(v: boolean) {
		this.realisticLighting = v;
		this.persist();
	}

	setShowShapeMesh(v: boolean) {
		this.showShapeMesh = v;
		this.persist();
	}

	setShowSurfaceTexture(v: boolean) {
		this.showSurfaceTexture = v;
		this.persist();
	}

	setShowDisplacement(v: boolean) {
		this.showDisplacement = v;
		this.persist();
	}

	setShowSelfShadow(v: boolean) {
		this.showSelfShadow = v;
		this.persist();
	}

	setViewMode(v: ViewMode) {
		this.viewMode = v;
		this.persist();
	}

	setMaxPartsPerZone(v: number) {
		this.maxPartsPerZone = Math.max(0, Math.floor(v));
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

	/** Whether to suppress motion: the OS preference under 'auto', else the explicit choice. */
	get resolvedReducedMotion(): boolean {
		if (this.reducedMotion === 'auto') return this.#systemReducedMotion;
		return this.reducedMotion === 'on';
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

	private persist() {
		if (typeof localStorage === 'undefined') return;
		try {
			const data: Persisted = {
				theme: this.theme,
				clock: this.clock,
				reducedMotion: this.reducedMotion,
				dateFormat: this.dateFormat,
				language: this.language,
				showDebugInfo: this.showDebugInfo,
				showSkyboxAlign: this.showSkyboxAlign,
				showHaloDebug: this.showHaloDebug,
				showLightingTuner: this.showLightingTuner,
				showClouds: this.showClouds,
				showAtmospheres: this.showAtmospheres,
				atmosphereQuality: this.atmosphereQuality,
				atmosphereAutoTier: this.atmosphereAutoTier ?? undefined,
				atmosphereCalibration: this.atmosphereCalibration ?? undefined,
				highAmbient: this.highAmbient,
				realisticLighting: this.realisticLighting,
				showShapeMesh: this.showShapeMesh,
				showSurfaceTexture: this.showSurfaceTexture,
				showDisplacement: this.showDisplacement,
				showSelfShadow: this.showSelfShadow,
				viewMode: this.viewMode,
				maxPartsPerZone: this.maxPartsPerZone
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
