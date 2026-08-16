/**
 * Debug overlay: well-known sky positions as always-visible labels at a large
 * radius, for visually cross-checking skybox rotation. Uses the same
 * equatorial→scene transform as every body's IAU pole, so a marker lining up
 * with its cubemap feature confirms the rotation matches the ecliptic frame.
 */
import {
	BufferGeometry,
	Float32BufferAttribute,
	Group,
	LineBasicMaterial,
	LineLoop,
	Object3D,
	Vector3
} from 'three';
import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';

import { EARTH_OBLIQUITY_DEG } from '$lib/math/units';

const DEG2RAD = Math.PI / 180;
const OBL_RAD = EARTH_OBLIQUITY_DEG * DEG2RAD;
const COS_OBL = Math.cos(OBL_RAD);
const SIN_OBL = Math.sin(OBL_RAD);

/** Radius at which we plant the markers — far enough that they ride visually with the skybox. */
const SKY_MARKER_RADIUS = 5000;

interface SkyLandmark {
	id: string;
	label: string;
	/** Right Ascension, degrees (J2000). */
	raDeg: number;
	/** Declination, degrees (J2000). */
	decDeg: number;
	/** CSS color for the dot + label outline. */
	color: string;
}

/** Hand-picked landmarks (galactic anchors, celestial poles, equinoxes), J2000. */
const LANDMARKS: SkyLandmark[] = [
	{
		id: 'galactic-center',
		label: 'Galactic Center',
		raDeg: 266.41683,
		decDeg: -29.00781,
		color: '#ff6b35'
	},
	{
		id: 'galactic-anticenter',
		label: 'Galactic Anticenter',
		raDeg: 86.4,
		decDeg: 28.93785,
		color: '#ff6b35'
	},
	{ id: 'galactic-np', label: 'Galactic NP', raDeg: 192.85948, decDeg: 27.12825, color: '#ffb84d' },
	{ id: 'galactic-sp', label: 'Galactic SP', raDeg: 12.85948, decDeg: -27.12825, color: '#ffb84d' },
	{ id: 'ncp', label: 'NCP (Polaris ≈)', raDeg: 37.9542, decDeg: 89.2641, color: '#4dd0ff' },
	{ id: 'scp', label: 'SCP', raDeg: 0, decDeg: -90, color: '#4dd0ff' },
	{ id: 'vernal', label: 'Vernal Equinox (γ)', raDeg: 0, decDeg: 0, color: '#9d8cff' },
	{ id: 'autumnal', label: 'Autumnal Equinox', raDeg: 180, decDeg: 0, color: '#9d8cff' },
	{ id: 'm31', label: 'M31 (Andromeda)', raDeg: 10.6847, decDeg: 41.2692, color: '#ffffff' },
	{
		id: 'lmc',
		label: 'LMC (Large Magellanic Cloud)',
		raDeg: 80.8942,
		decDeg: -69.7561,
		color: '#ffffff'
	},
	{
		id: 'smc',
		label: 'SMC (Small Magellanic Cloud)',
		raDeg: 13.1583,
		decDeg: -72.8003,
		color: '#ffffff'
	},
	{ id: 'sirius', label: 'Sirius', raDeg: 101.2872, decDeg: -16.7161, color: '#ffffff' }
];

/**
 * (RA, Dec) J2000 equatorial → Three.js scene frame. Identical to
 * `equatorialToThreeJS` in `lib/math/orientation.ts`, inlined here to avoid
 * leaking a private helper.
 */
function eqToScene(raDeg: number, decDeg: number, out: Vector3): Vector3 {
	const ra = raDeg * DEG2RAD;
	const dec = decDeg * DEG2RAD;
	const cd = Math.cos(dec);
	const xEq = cd * Math.cos(ra);
	const yEq = cd * Math.sin(ra);
	const zEq = Math.sin(dec);
	const xEcl = xEq;
	const yEcl = yEq * COS_OBL + zEq * SIN_OBL;
	const zEcl = -yEq * SIN_OBL + zEq * COS_OBL;
	return out.set(xEcl, zEcl, -yEcl);
}

/**
 * A "+" reticle (SVG) plus a label, as the CSS2D element for each landmark.
 * The reticle centers on the projected point; the label sits to the right so
 * it doesn't occlude the aim point.
 */
function buildLabelElement(landmark: SkyLandmark): HTMLDivElement {
	const wrap = document.createElement('div');
	wrap.className = 'sky-debug-marker';
	wrap.style.cssText = [
		'display:flex',
		'align-items:center',
		'gap:4px',
		'font:11px/1 monospace',
		'text-shadow:0 0 3px #000, 0 0 3px #000',
		'pointer-events:none',
		'white-space:nowrap'
	].join(';');

	const reticle = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
	const size = 48;
	const half = size / 2;
	reticle.setAttribute('width', String(size));
	reticle.setAttribute('height', String(size));
	reticle.setAttribute('viewBox', `${-half} ${-half} ${size} ${size}`);
	// Shift left by half width so the CSS2DObject anchor (center.x = 0) lands
	// on the reticle's center, not its left edge.
	reticle.style.cssText = `flex:0 0 auto;filter:drop-shadow(0 0 2px #000);margin-inline-start:-${half}px`;
	const c = landmark.color;
	reticle.innerHTML = `
		<circle cx="0" cy="0" r="14" fill="none" stroke="${c}" stroke-width="1.6"/>
		<line x1="-${half - 1}" y1="0" x2="-10" y2="0" stroke="${c}" stroke-width="1.6"/>
		<line x1="10" y1="0" x2="${half - 1}" y2="0" stroke="${c}" stroke-width="1.6"/>
		<line x1="0" y1="-${half - 1}" x2="0" y2="-10" stroke="${c}" stroke-width="1.6"/>
		<line x1="0" y1="10" x2="0" y2="${half - 1}" stroke="${c}" stroke-width="1.6"/>
	`;

	const text = document.createElement('span');
	text.textContent = landmark.label;
	text.style.color = landmark.color;
	text.style.marginInlineStart = '2px';

	wrap.appendChild(reticle);
	wrap.appendChild(text);
	return wrap;
}

/** Galactic North Pole (RA, Dec, J2000) — defines galactic↔equatorial rotation. */
const GAL_NP_RA = 192.85948;
const GAL_NP_DEC = 27.12825;
/** RA, Dec of the galactic center (l=0, b=0) — Sgr A* region. */
const GAL_CENTER_RA = 266.40499;
const GAL_CENTER_DEC = -28.93617;

/**
 * A `LineLoop` tracing one great circle, given the "0°" longitude-origin axis
 * and the pole axis in scene coordinates.
 */
function buildGreatCircle(
	zeroAxis: Vector3,
	poleAxis: Vector3,
	radius: number,
	color: number,
	segments: number
): LineLoop {
	const quadAxis = new Vector3().crossVectors(poleAxis, zeroAxis).normalize();
	const positions = new Float32Array(segments * 3);
	const p = new Vector3();
	for (let i = 0; i < segments; i++) {
		const theta = (i / segments) * Math.PI * 2;
		const c = Math.cos(theta);
		const s = Math.sin(theta);
		p.copy(zeroAxis).multiplyScalar(c).addScaledVector(quadAxis, s).multiplyScalar(radius);
		positions[i * 3] = p.x;
		positions[i * 3 + 1] = p.y;
		positions[i * 3 + 2] = p.z;
	}
	const geom = new BufferGeometry();
	geom.setAttribute('position', new Float32BufferAttribute(positions, 3));
	const mat = new LineBasicMaterial({ color, transparent: true, opacity: 0.55 });
	const loop = new LineLoop(geom, mat);
	loop.frustumCulled = false;
	return loop;
}

/**
 * Galactic plane (b=0) great circle at the marker radius. Inset slightly so
 * it doesn't z-fight with the marker dots.
 */
function buildGalacticPlane(): LineLoop {
	const zero = new Vector3();
	eqToScene(GAL_CENTER_RA, GAL_CENTER_DEC, zero).normalize();
	const pole = new Vector3();
	eqToScene(GAL_NP_RA, GAL_NP_DEC, pole).normalize();
	const loop = buildGreatCircle(zero, pole, SKY_MARKER_RADIUS * 0.999, 0xff6b35, 256);
	loop.name = 'galactic-plane';
	return loop;
}

/** Ecliptic plane (b=0) — by construction sits on the scene XZ plane. */
function buildEclipticPlane(): LineLoop {
	const zero = new Vector3(1, 0, 0);
	const pole = new Vector3(0, 1, 0);
	const loop = buildGreatCircle(zero, pole, SKY_MARKER_RADIUS * 0.999, 0x4dd0ff, 256);
	loop.name = 'ecliptic-plane';
	return loop;
}

/** Celestial equator (declination 0) — same as RA=anything, dec=0 transformed. */
function buildCelestialEquator(): LineLoop {
	const zero = new Vector3();
	eqToScene(0, 0, zero).normalize();
	const pole = new Vector3();
	eqToScene(0, 90, pole).normalize();
	const loop = buildGreatCircle(zero, pole, SKY_MARKER_RADIUS * 0.999, 0x9d8cff, 256);
	loop.name = 'celestial-equator';
	return loop;
}

/**
 * A Group of CSS2D landmark markers + great-circle reference lines (galactic,
 * ecliptic, celestial-equator), all at `SKY_MARKER_RADIUS`. Starts hidden;
 * caller toggles `group.visible` behind the debug flag.
 */
export function createSkyDebugMarkers(): Group {
	const group = new Group();
	group.name = 'sky-debug-markers';
	group.visible = false;
	const dir = new Vector3();
	for (const landmark of LANDMARKS) {
		eqToScene(landmark.raDeg, landmark.decDeg, dir).multiplyScalar(SKY_MARKER_RADIUS);
		const css = new CSS2DObject(buildLabelElement(landmark));
		css.center.set(0, 0.5); // anchor on the reticle's center
		css.position.copy(dir);
		group.add(css);
	}
	group.add(buildGalacticPlane());
	group.add(buildEclipticPlane());
	group.add(buildCelestialEquator());
	return group;
}

/** Remove every CSS2D label from the DOM, free geometry/material, and detach the group. */
export function disposeSkyDebugMarkers(group: Group): void {
	group.traverse((obj: Object3D) => {
		if (obj instanceof CSS2DObject) obj.element.remove();
		if (obj instanceof LineLoop) {
			obj.geometry.dispose();
			(obj.material as LineBasicMaterial).dispose();
		}
	});
	group.parent?.remove(group);
}
