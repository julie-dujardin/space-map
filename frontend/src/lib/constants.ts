/** Colors keyed by prefixed body ID */
export const BODY_COLORS: Record<string, string> = {
	'naif-10': '#ffdd44', // Sun
	'naif-199': '#b5b5b5', // Mercury
	'naif-299': '#e8cda0', // Venus
	'naif-399': '#4da6ff', // Earth
	'naif-301': '#888888', // Moon
	'naif-499': '#c1440e', // Mars
	'naif-401': '#aa9988', // Phobos
	'naif-402': '#aa9988', // Deimos
	'naif-599': '#d4a66a', // Jupiter
	'naif-501': '#8a762e', // Io
	'naif-502': '#7c7f6c', // Europa
	'naif-503': '#7e6c5e', // Ganymede
	'naif-504': '#6c6453', // Callisto
	'naif-699': '#e8d8a0', // Saturn
	'naif-601': '#aba890', // Mimas
	'naif-602': '#71a29f', // Enceladus
	'naif-603': '#6c6645', // Tethys
	'naif-604': '#494a2a', // Dione
	'naif-605': '#5c5a3c', // Rhea
	'naif-606': '#835422', // Titan
	'naif-608': '#776b60', // Iapetus
	'naif-799': '#87ceeb', // Uranus
	'naif-701': '#b0b0b0', // Ariel
	'naif-702': '#a8a8a8', // Umbriel
	'naif-703': '#62534c', // Titania
	'naif-704': '#626a62', // Oberon
	'naif-705': '#625252', // Miranda
	'naif-899': '#3f54ba', // Neptune
	'naif-801': '#7c757c', // Triton
	'naif-999': '#b48977' // Pluto
};

export const DEFAULT_BODY_COLOR = '#cccccc';

/** Fallback colors by broad category, used when a body isn't in BODY_COLORS. */
export const TYPE_COLOR_PLANET = '#fcb493';
export const TYPE_COLOR_MOON = '#c7ccda';
export const TYPE_COLOR_STAR = '#ffe89e';
export const TYPE_COLOR_ASTEROID = '#ccb49a';
export const TYPE_COLOR_COMET = '#d8ffe8';
export const TYPE_COLOR_DEBRIS = '#e8a85c';
export const TYPE_COLOR_MANNED = '#6ED66B';
/** SPACECRAFT orbiting Earth. */
export const TYPE_COLOR_SATELLITE = '#bed4ec';
/** SPACECRAFT orbiting the Sun. */
export const TYPE_COLOR_PROBE = '#d5cfe7';

export const GITHUB_REPO_URL = 'https://github.com/julie-dujardin/space-map';

/**
 * Bodies rendered as halos but with no label or trail by default — label
 * appears on hover (alongside the existing halo scale), trail draws as usual
 * when the body is selected (focused). Curated to keep the inner system from
 * getting too busy while still surfacing main-belt giants and notable Trojans,
 * plus the few barycenters that visibly differ from their primary at close
 * zoom (the Sun wobbles around the SSB; Pluto-Charon's barycenter sits between
 * the two). Those barycenters stay hidden at wide zoom — see
 * {@link BARYCENTER_PRIMARY}.
 */
export const MINOR_PROMOTED_IDS: ReadonlySet<string> = new Set([
	'naif-0', // Solar System Barycenter
	'naif-9', // Pluto-Charon Barycenter
	'spkid-20000002', // 2 Pallas
	'spkid-20000003', // 3 Juno
	'spkid-20000007', // 7 Iris
	'spkid-20000010', // 10 Hygiea
	'spkid-20000015', // 15 Eunomia
	'spkid-20000031', // 31 Euphrosyne
	'spkid-20000052', // 52 Europa
	'spkid-20000065', // 65 Cybele
	'spkid-20000088', // 88 Thisbe
	'spkid-20000107', // 107 Camilla
	'spkid-20000511', // 511 Davida
	'spkid-20000588', // 588 Achilles
	'spkid-20000704', // 704 Interamnia
	'spkid-20001862' // 1862 Apollo
]);

/**
 * Barycenters whose halo overlaps a single dominant body when zoomed out, and
 * should only render once the camera is close enough to see the offset.
 * Maps barycenter id → primary body id; the visibility update hides the
 * barycenter until the projected pixel separation exceeds one halo diameter.
 */
export const BARYCENTER_PRIMARY: ReadonlyMap<string, string> = new Map([
	['naif-0', 'naif-10'], // Solar System Barycenter ↔ Sun
	['naif-9', 'naif-999'] // Pluto-Charon Barycenter ↔ Pluto
]);
