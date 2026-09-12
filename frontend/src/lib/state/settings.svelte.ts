import type { Locale } from '$lib/paraglide/runtime.js';
import { getLocale } from '$lib/host';
import type { SceneSettings } from '$lib/scene/settings.svelte';
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

/** Every display setting, and what its value is. */
interface SettingValues {
	theme: Theme;
	clock: Clock;
	reducedMotion: ReducedMotion;
	dateFormat: DateFormatChoice;
	language: LanguageChoice;
	showDebugInfo: boolean;
	showSkyboxAlign: boolean;
	showHaloDebug: boolean;
	showLightingTuner: boolean;
	showClouds: boolean;
	showAtmospheres: boolean;
	atmosphereQuality: AtmosphereQualityTier;
	atmosphereAutoTier: ResolvedAtmosphereTier | null;
	atmosphereCalibration: AtmosphereCalibration | null;
	atmoQualityOverrides: Partial<AtmosphereQualityConfig>;
	highAmbient: boolean;
	realisticLighting: boolean;
	overexposeRings: boolean;
	showShapeMesh: boolean;
	showSurfaceTexture: boolean;
	showDisplacement: boolean;
	showSelfShadow: boolean;
	viewMode: ViewMode;
	maxPartsPerZone: number;
}

export type SettingKey = keyof SettingValues;

interface SettingSpec<K extends SettingKey> {
	default: SettingValues[K];
	/** False for a session-only knob — it never reaches localStorage. */
	persist: boolean;
}

/**
 * The one place a setting is declared: its default and whether it survives a
 * reload. The $state fields, hydration and `persist()` all read this table, so
 * adding a setting is one row plus its field.
 */
const SETTING_SPEC = {
	theme: { default: 'auto', persist: true },
	clock: { default: 'auto', persist: true },
	reducedMotion: { default: 'auto', persist: true },
	dateFormat: { default: 'auto', persist: true },
	language: { default: 'auto', persist: true },
	showDebugInfo: { default: false, persist: true },
	showSkyboxAlign: { default: false, persist: true },
	showHaloDebug: { default: false, persist: true },
	showLightingTuner: { default: false, persist: true },
	showClouds: { default: true, persist: true },
	showAtmospheres: { default: true, persist: true },
	atmosphereQuality: { default: 'auto', persist: true },
	atmosphereAutoTier: { default: null, persist: true },
	atmosphereCalibration: { default: null, persist: true },
	// A debug layer on top of the tier preset: the map opens on the preset.
	atmoQualityOverrides: { default: {}, persist: false },
	highAmbient: { default: false, persist: true },
	realisticLighting: { default: false, persist: true },
	// The physical picture is the one the map opens on.
	overexposeRings: { default: false, persist: false },
	showShapeMesh: { default: true, persist: true },
	showSurfaceTexture: { default: true, persist: true },
	showDisplacement: { default: true, persist: true },
	showSelfShadow: { default: true, persist: true },
	viewMode: { default: 'map', persist: true },
	maxPartsPerZone: { default: 0, persist: true }
} as const satisfies { [K in SettingKey]: SettingSpec<K> };

type PersistedKey = {
	[K in SettingKey]: (typeof SETTING_SPEC)[K]['persist'] extends true ? K : never;
}[SettingKey];

/** What localStorage holds. A setting sitting at null is simply absent. */
type Persisted = { [K in PersistedKey]?: NonNullable<SettingValues[K]> };

function readPersisted(): Persisted {
	if (typeof localStorage === 'undefined') return {};
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		return raw ? (JSON.parse(raw) as Persisted) : {};
	} catch {
		return {};
	}
}

/** Per-locale cache: the time bar asks every frame. */
const hour12ByLocale = new Map<string, boolean>();
function localeUses12h(locale: string): boolean {
	let uses12h = hour12ByLocale.get(locale);
	if (uses12h === undefined) {
		const opts = new Intl.DateTimeFormat(locale, { hour: 'numeric' }).resolvedOptions();
		uses12h = opts.hour12 === true || opts.hourCycle === 'h11' || opts.hourCycle === 'h12';
		hour12ByLocale.set(locale, uses12h);
	}
	return uses12h;
}

const SPEC_ENTRIES = Object.entries(SETTING_SPEC) as [
	SettingKey,
	{ default: unknown; persist: boolean }
][];

// `implements SettingValues` ties the fields to the table: a key the spec
// declares and the class misses (or types differently) fails to compile.
class SettingsState implements SceneSettings, SettingValues {
	// Declared one by one: a $state field cannot be generated in a loop. Only the
	// metadata behind them comes from the table.
	theme = $state<Theme>(SETTING_SPEC.theme.default);
	clock = $state<Clock>(SETTING_SPEC.clock.default);
	reducedMotion = $state<ReducedMotion>(SETTING_SPEC.reducedMotion.default);
	dateFormat = $state<DateFormatChoice>(SETTING_SPEC.dateFormat.default);
	language = $state<LanguageChoice>(SETTING_SPEC.language.default);
	showDebugInfo = $state<boolean>(SETTING_SPEC.showDebugInfo.default);
	showSkyboxAlign = $state<boolean>(SETTING_SPEC.showSkyboxAlign.default);
	showHaloDebug = $state<boolean>(SETTING_SPEC.showHaloDebug.default);
	showLightingTuner = $state<boolean>(SETTING_SPEC.showLightingTuner.default);
	showClouds = $state<boolean>(SETTING_SPEC.showClouds.default);
	/** Per-body atmospheric-scattering shells (sky glow, sunset limb). */
	showAtmospheres = $state<boolean>(SETTING_SPEC.showAtmospheres.default);
	/** Shell quality tier; 'auto' resolves from device capability. */
	atmosphereQuality = $state<AtmosphereQualityTier>(SETTING_SPEC.atmosphereQuality.default);
	/** Tier the perf governor settled on for this device (auto mode only);
	 *  null until a downgrade has ever triggered. */
	atmosphereAutoTier = $state<ResolvedAtmosphereTier | null>(
		SETTING_SPEC.atmosphereAutoTier.default
	);
	/** Boot benchmark result; null until the first calibration completes. */
	atmosphereCalibration = $state<AtmosphereCalibration | null>(
		SETTING_SPEC.atmosphereCalibration.default
	);
	/** Debug knob overrides on top of the tier preset, cleared when the tier
	 *  changes. */
	atmoQualityOverrides = $state<Partial<AtmosphereQualityConfig>>(
		SETTING_SPEC.atmoQualityOverrides.default
	);
	/** Flood the scene with flat ambient fill so night sides are fully lit. */
	highAmbient = $state<boolean>(SETTING_SPEC.highAmbient.default);
	/** Scale sunlight with the true inverse-square distance from the Sun instead
	 *  of lighting every body as if it sat at 1 AU. Debug menu only. */
	realisticLighting = $state<boolean>(SETTING_SPEC.realisticLighting.default);
	/** Render ring systems at their full stored dynamic range instead of the
	 *  physical intensity scale — Jupiter/Uranus/Neptune's rings are otherwise
	 *  (correctly) near-invisible. */
	overexposeRings = $state<boolean>(SETTING_SPEC.overexposeRings.default);
	/** Debug body-layer toggles: peel back the focused body's render stack to
	 *  isolate a layer (e.g. shape mesh off → textured triaxial sphere). */
	showShapeMesh = $state<boolean>(SETTING_SPEC.showShapeMesh.default);
	showSurfaceTexture = $state<boolean>(SETTING_SPEC.showSurfaceTexture.default);
	showDisplacement = $state<boolean>(SETTING_SPEC.showDisplacement.default);
	showSelfShadow = $state<boolean>(SETTING_SPEC.showSelfShadow.default);
	viewMode = $state<ViewMode>(SETTING_SPEC.viewMode.default);
	/** Debug cap on parts loaded per zone. 0 = unlimited. Only takes effect on
	 *  the next page load — already-resident chunks aren't unloaded. */
	maxPartsPerZone = $state<number>(SETTING_SPEC.maxPartsPerZone.default);
	#systemDark = $state(false);
	#systemReducedMotion = $state(false);

	constructor() {
		const stored = readPersisted() as Record<string, unknown>;
		const fields = this as unknown as Record<string, unknown>;
		for (const [key, spec] of SPEC_ENTRIES) {
			if (spec.persist) fields[key] = stored[key] ?? spec.default;
		}

		if (typeof window !== 'undefined' && window.matchMedia) {
			const mq = window.matchMedia('(prefers-color-scheme: dark)');
			this.#systemDark = mq.matches;
			mq.addEventListener('change', (e) => (this.#systemDark = e.matches));

			const rm = window.matchMedia('(prefers-reduced-motion: reduce)');
			this.#systemReducedMotion = rm.matches;
			rm.addEventListener('change', (e) => (this.#systemReducedMotion = e.matches));
		}
	}

	/** Write one setting, persisting it when the spec says it survives a reload. */
	set<K extends SettingKey>(key: K, value: SettingValues[K]): void {
		(this as unknown as Record<string, unknown>)[key] = value;
		if (SETTING_SPEC[key].persist) this.persist();
	}

	// Named setters are the call surface the menus use; each is a thin wrapper
	// over `set`, bar the three that do something else besides.

	setTheme(v: Theme) {
		this.set('theme', v);
	}

	setClock(v: Clock) {
		this.set('clock', v);
	}

	setReducedMotion(v: ReducedMotion) {
		this.set('reducedMotion', v);
	}

	setDateFormat(v: DateFormatChoice) {
		this.set('dateFormat', v);
	}

	setShowDebugInfo(v: boolean) {
		this.set('showDebugInfo', v);
	}

	setShowSkyboxAlign(v: boolean) {
		this.set('showSkyboxAlign', v);
	}

	setShowHaloDebug(v: boolean) {
		this.set('showHaloDebug', v);
	}

	setShowLightingTuner(v: boolean) {
		this.set('showLightingTuner', v);
	}

	setShowClouds(v: boolean) {
		this.set('showClouds', v);
	}

	setShowAtmospheres(v: boolean) {
		this.set('showAtmospheres', v);
	}

	/** A new tier is a new preset, so the knobs layered on the old one drop. */
	setAtmosphereQuality(v: AtmosphereQualityTier) {
		this.atmoQualityOverrides = {};
		this.set('atmosphereQuality', v);
	}

	setAtmosphereAutoTier(v: ResolvedAtmosphereTier | null) {
		this.set('atmosphereAutoTier', v);
	}

	setAtmosphereCalibration(v: AtmosphereCalibration | null) {
		this.set('atmosphereCalibration', v);
	}

	/** Merge debug knob overrides onto the current tier preset. */
	setAtmoQualityOverrides(patch: Partial<AtmosphereQualityConfig>) {
		this.set('atmoQualityOverrides', { ...this.atmoQualityOverrides, ...patch });
	}

	setHighAmbient(v: boolean) {
		this.set('highAmbient', v);
	}

	setRealisticLighting(v: boolean) {
		this.set('realisticLighting', v);
	}

	setOverexposeRings(v: boolean) {
		this.set('overexposeRings', v);
	}

	setShowShapeMesh(v: boolean) {
		this.set('showShapeMesh', v);
	}

	setShowSurfaceTexture(v: boolean) {
		this.set('showSurfaceTexture', v);
	}

	setShowDisplacement(v: boolean) {
		this.set('showDisplacement', v);
	}

	setShowSelfShadow(v: boolean) {
		this.set('showSelfShadow', v);
	}

	setViewMode(v: ViewMode) {
		this.set('viewMode', v);
	}

	/** A cap, so a fractional or negative request lands on the nearest real one. */
	setMaxPartsPerZone(v: number) {
		this.set('maxPartsPerZone', Math.max(0, Math.floor(v)));
	}

	/** The stored choice only; `switchLanguage` reloads the page into it. */
	setLanguage(v: LanguageChoice) {
		this.set('language', v);
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
			const fields = this as unknown as Record<string, unknown>;
			const data: Record<string, unknown> = {};
			for (const [key, spec] of SPEC_ENTRIES) {
				if (spec.persist && fields[key] !== null) data[key] = fields[key];
			}
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
