<!--
  Dev tool: isolates one planet + its atmospheric-scattering shell in a bare
  scene (same ACES + bloom compositing as production) so every AtmosphereParams
  knob can be tuned live against a flyable camera and Sun.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import {
		ACESFilmicToneMapping,
		AmbientLight,
		BackSide,
		FrontSide,
		Mesh,
		MeshBasicMaterial,
		MeshStandardMaterial,
		PerspectiveCamera,
		PointLight,
		Scene,
		SphereGeometry,
		SRGBColorSpace,
		type Texture,
		TextureLoader,
		Vector2,
		Vector3,
		WebGLRenderer
	} from 'three';
	import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
	import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
	import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
	import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
	import {
		applyAtmosphereParams,
		applyAtmosphereQuality,
		type AtmosphereNode,
		type AtmosphereParams,
		buildAtmosphereNode,
		disposeAtmosphereNode,
		TERRAIN_DIP_KM
	} from '$lib/scene/objects/surface/atmosphere';
	import { getAtmosphereParams, loadAtmospheres } from '$lib/fetch/atmospheres';
	import {
		ATMOSPHERE_QUALITY_PRESETS,
		resolveAtmosphereTier,
		type AtmosphereQualityConfig,
		type ResolvedAtmosphereTier
	} from '$lib/scene/objects/surface/atmosphere-quality';
	import {
		marsSolarLongitudeDeg,
		seasonalAtmosphereParams
	} from '$lib/scene/objects/surface/atmosphere-season';
	import { getSettings } from '$lib/state/settings.svelte';
	import { replaceState } from '$app/navigation';
	import { fetchMetadata } from '$lib/fetch/metadata';
	import { versionedUrl } from '$lib/fetch/data-base';
	import { AU_KM } from '$lib/math/units';
	import { AMBIENT_INTENSITY, SUN_LIGHT_INTENSITY } from '$lib/scene/lighting';
	import { loadSkybox, SKYBOX_BASE_ROTATION } from '$lib/scene/objects/sky/skybox';
	import { refractionLiftRad, skyboxDimFactor } from '$lib/scene/shaders/atmosphere-uniforms';
	import {
		attachEclipseShadowToBody,
		getEclipseSceneUniforms
	} from '$lib/scene/objects/surface/eclipse-shadow';
	import {
		attachSunTransmittanceToBody,
		attachViewTintToMaterial,
		bindViewTint,
		setSunTransmittanceEnabled,
		sunPathTransmittance,
		syncSunTransmittanceUniforms,
		type SunTransmittanceUniforms,
		type ViewTintUniforms
	} from '$lib/scene/objects/surface/sun-transmittance';

	interface BodyDef {
		id: string;
		name: string;
		/** Equatorial radius, km — the shader normalises coefficients against it. */
		radiusKm: number;
		/** Mean heliocentric distance, AU — drives inverse-square sun scaling. */
		au: number;
	}

	// Only the bodies with a shipped atmosphere shell, sorted sunward-out.
	const BODIES: BodyDef[] = [
		{ id: 'naif-299', name: 'Venus', radiusKm: 6051.8, au: 0.723 },
		{ id: 'naif-399', name: 'Earth', radiusKm: 6371.0, au: 1.0 },
		{ id: 'naif-499', name: 'Mars', radiusKm: 3389.5, au: 1.524 },
		{ id: 'naif-599', name: 'Jupiter', radiusKm: 71492, au: 5.203 },
		{ id: 'naif-606', name: 'Titan', radiusKm: 2574.7, au: 9.537 },
		{ id: 'naif-699', name: 'Saturn', radiusKm: 60268, au: 9.537 },
		{ id: 'naif-799', name: 'Uranus', radiusKm: 25559, au: 19.19 },
		{ id: 'naif-801', name: 'Triton', radiusKm: 1353.4, au: 30.07 },
		{ id: 'naif-899', name: 'Neptune', radiusKm: 24764, au: 30.07 },
		{ id: 'naif-999', name: 'Pluto', radiusKm: 1188.3, au: 39.48 }
	];

	// The planet mesh sits at the origin with unit radius; altitude and shell
	// thickness are expressed relative to it, so absolute scale is irrelevant.
	const RADIUS_SCENE = 1;
	const DEG = Math.PI / 180;
	// Altitude is kept in body-radii (not km) so a body keeps the same apparent
	// size when you switch to another; the readout converts back to km.
	const ALT_MIN_RADII = 1e-4; // log-slider/wheel floor ("Ground" preset sets 0)
	const ALT_MAX_RADII = 30;
	const DEFAULT_ALT_RADII = 2.5;
	const DEFAULT_LAT = 12;
	const DEFAULT_LON = -28;
	const DEFAULT_SUN_AZ = 60;
	const DEFAULT_SUN_EL = 10;
	// HDR white so the Sun disc crosses the composer's bloom threshold, matching
	// the production Sun.
	const SUN_DISC_BRIGHTNESS = 4;
	// Sun disc placed far enough that altitude barely shifts its apparent size;
	// scaled to the Sun's true angular size for the focused body.
	const SUN_DIST = 800;
	const SUN_RADIUS_KM = 695_700;
	// Never let the disc fall below this on-screen diameter (px) — a sub-pixel
	// sphere rasterises to nothing, so far-out suns (Neptune, Pluto) would vanish.
	const SUN_MIN_PX = 2;

	// State captured from the URL at load; applied once the first body is built.
	const initialParams = new URLSearchParams(typeof location === 'undefined' ? '' : location.search);

	let bodyId = $state('naif-399');
	// Sun-distance blend: 0 = flat sun (Earth-equivalent, ×1), 1 = full
	// inverse-square at the body's AU; interpolates in log space between them.
	let sunDistT = $state(0);
	let sunScaleX = $state(0); // log2 global multiplier on shell + surface sunlight

	// The camera sits on the view sphere: altitude (body radii) plus a
	// longitude/latitude. Mouse drag and wheel drive the same sliders bind to.
	let altRadii = $state(DEFAULT_ALT_RADII);
	let camLon = $state(DEFAULT_LON);
	let camLat = $state(DEFAULT_LAT);
	// 'look' = free mouse-look (this tool's default); 'orbit' = the app's
	// familiar drag-to-rotate-the-body camera.
	let cameraMode = $state<'look' | 'orbit'>('look');
	// Collapse the controls to a bare header so the panel doesn't hog a phone
	// screen while you inspect the atmosphere.
	let collapsed = $state(false);
	// Gate the URL writer until the initial state has been applied.
	let ready = $state(false);

	let sunAz = $state(DEFAULT_SUN_AZ); // degrees, 0 = +X, sweeps in the equatorial plane
	let sunEl = $state(DEFAULT_SUN_EL); // degrees above the equator

	// Atmosphere knobs: coefficients are log2 multipliers over the shipped params
	// (one panel fits every body's magnitude), gains and comp are absolute.
	let comp = $state(1);
	let sunIntensity = $state(5);
	let multiScatter = $state(0.3);
	let topX = $state(0);
	let rayleighX = $state(0);
	let mieX = $state(0);
	let mieAbsX = $state(0);
	let absorberX = $state(0);
	let rayleighHX = $state(0);
	let mieHX = $state(0);
	let copied = $state(false);

	// Quality: page-local (never writes the app settings) so tiers can be A/B'd
	// freely, starting from what the app would resolve on this device.
	const QUALITY_TIERS: ResolvedAtmosphereTier[] = ['low', 'medium', 'high', 'ultra'];
	const initTier = resolveAtmosphereTier(getSettings().atmosphereQuality);
	let qTier = $state<ResolvedAtmosphereTier>(initTier);
	let qPrimarySteps = $state(ATMOSPHERE_QUALITY_PRESETS[initTier].primarySteps);
	let qLightSteps = $state(ATMOSPHERE_QUALITY_PRESETS[initTier].lightSteps);
	let qEclipse = $state(ATMOSPHERE_QUALITY_PRESETS[initTier].eclipseShadows);
	let qRings = $state(ATMOSPHERE_QUALITY_PRESETS[initTier].ringShadows);
	let qInside = $state(ATMOSPHERE_QUALITY_PRESETS[initTier].insideView);
	let qSunTint = $state(ATMOSPHERE_QUALITY_PRESETS[initTier].sunTint);
	let qLayered = $state(ATMOSPHERE_QUALITY_PRESETS[initTier].layeredDensity);
	let qGroundAlbedo = $state(ATMOSPHERE_QUALITY_PRESETS[initTier].groundAlbedo);
	let qSeasonal = $state(ATMOSPHERE_QUALITY_PRESETS[initTier].seasonal);
	let qRefraction = $state(ATMOSPHERE_QUALITY_PRESETS[initTier].refraction);
	// Mars solar longitude the seasonal toggle renders; starts at today's.
	let lsDeg = $state(
		Math.round(marsSolarLongitudeDeg(Date.now() / 86400000 + 2440587.5) * 10) / 10
	);

	function qualityConfig(): AtmosphereQualityConfig {
		return {
			primarySteps: qPrimarySteps,
			lightSteps: qLightSteps,
			eclipseShadows: qEclipse,
			ringShadows: qRings,
			insideView: qInside,
			sunTint: qSunTint,
			layeredDensity: qLayered,
			groundAlbedo: qGroundAlbedo,
			seasonal: qSeasonal,
			refraction: qRefraction
		};
	}

	function pushQuality(): void {
		if (atmoNode) applyAtmosphereQuality(atmoNode, qualityConfig());
	}

	function loadTierPreset(t: ResolvedAtmosphereTier): void {
		qTier = t;
		const p = ATMOSPHERE_QUALITY_PRESETS[t];
		qPrimarySteps = p.primarySteps;
		qLightSteps = p.lightSteps;
		qEclipse = p.eclipseShadows;
		qRings = p.ringShadows;
		qInside = p.insideView;
		qSunTint = p.sunTint;
		qLayered = p.layeredDensity;
		qGroundAlbedo = p.groundAlbedo;
		qSeasonal = p.seasonal;
		qRefraction = p.refraction;
	}

	function setTier(t: ResolvedAtmosphereTier): void {
		loadTierPreset(t);
		pushQuality();
	}

	const LOG_SLIDERS: { label: string; get: () => number; set: (v: number) => void }[] = [
		{ label: 'Top altitude', get: () => topX, set: (v) => (topX = v) },
		{ label: 'Rayleigh β', get: () => rayleighX, set: (v) => (rayleighX = v) },
		{ label: 'Mie β', get: () => mieX, set: (v) => (mieX = v) },
		{ label: 'Mie absorb', get: () => mieAbsX, set: (v) => (mieAbsX = v) },
		{ label: 'Absorber β', get: () => absorberX, set: (v) => (absorberX = v) },
		{ label: 'Rayleigh H', get: () => rayleighHX, set: (v) => (rayleighHX = v) },
		{ label: 'Mie H', get: () => mieHX, set: (v) => (mieHX = v) }
	];

	// Non-reactive scene handles.
	let canvas: HTMLCanvasElement;
	let renderer: WebGLRenderer;
	let scene: Scene;
	let camera: PerspectiveCamera;
	let composer: EffectComposer;
	let pointLight: PointLight;
	let textureLoader: TextureLoader;
	let planetMesh: Mesh | null = null;
	let atmoNode: AtmosphereNode | null = null;
	// Surface sun-transmittance patch handle — re-synced on every slider push.
	let sunTUniforms: SunTransmittanceUniforms | null = null;
	// Per-fragment disc chroma handle (attachViewTintToMaterial on the sun disc).
	let discTintUniforms: ViewTintUniforms | null = null;
	let sunMesh: Mesh;
	// Reactive: the altitude slider bounds and the realistic-sun label read it.
	let currentBody = $state<BodyDef>(BODIES[1]);
	let raf = 0;
	// First body frames itself; later switches keep the current camera + Sun.
	let firstBuild = true;
	const sunVec = new Vector3();
	const camDir = new Vector3();
	// Refraction-lift scratches (sun-disc direction, camera zenith, lift axis).
	const refrSd = new Vector3();
	const refrUp = new Vector3();
	const refrPerp = new Vector3();
	// Free-look orientation (mouse-driven, degrees) — $state so URL sync tracks
	// it. Not shown as sliders: the mouse owns aiming, the sliders own position.
	let lookYaw = $state(0);
	let lookPitch = $state(0);
	// FPS readout, refreshed in ~500 ms windows so the label is legible instead
	// of flickering every frame.
	let fps = $state(0);
	let fpsWindowMs = 0;
	let fpsFrames = 0;
	let lastFrameMs = 0;

	// Star-map dim for the tuned params at the current altitude and sun — the
	// same factor production feeds `scene.backgroundIntensity`.
	const skyDim = $derived.by(() => {
		const latR = camLat * DEG;
		const lonR = camLon * DEG;
		const elR = sunEl * DEG;
		const azR = sunAz * DEG;
		// up(camera) · sunDirection, both on the unit sphere.
		const sinSunElev =
			Math.cos(latR) * Math.cos(lonR) * Math.cos(elR) * Math.cos(azR) +
			Math.sin(latR) * Math.sin(elR) +
			Math.cos(latR) * Math.sin(lonR) * Math.cos(elR) * Math.sin(azR);
		return skyboxDimFactor(resolved(), altRadii * currentBody.radiusKm, sinSunElev);
	});

	const tintCam = new Vector3();
	const tintSunDir = new Vector3();
	const tintT = new Vector3();
	// Swatch readout: the production sunTint chroma (camera→sun-centre ray);
	// the disc itself shades per fragment.
	const sunTint = $derived.by(() => {
		if (!qSunTint) return [1, 1, 1];
		const latR = camLat * DEG;
		const lonR = camLon * DEG;
		tintCam
			.set(Math.cos(latR) * Math.cos(lonR), Math.sin(latR), Math.cos(latR) * Math.sin(lonR))
			.multiplyScalar(RADIUS_SCENE * (1 + Math.max(altRadii, 0)));
		const elR = sunEl * DEG;
		const azR = sunAz * DEG;
		tintSunDir.set(Math.cos(elR) * Math.cos(azR), Math.sin(elR), Math.cos(elR) * Math.sin(azR));
		const through = sunPathTransmittance(
			resolved(),
			tintCam,
			tintSunDir,
			RADIUS_SCENE,
			currentBody.radiusKm,
			tintT
		);
		if (!through) return [1, 1, 1];
		const lum = 0.2126 * tintT.x + 0.7152 * tintT.y + 0.0722 * tintT.z;
		if (lum < 1e-4) return [1, 1, 1];
		return [tintT.x / lum, tintT.y / lum, tintT.z / lum];
	});

	// Inert stand-in: template $deriveds evaluate before onMount's
	// loadAtmospheres() populates the registry; `ready` gates any visible use.
	const PENDING_PARAMS: AtmosphereParams = {
		topAltitudeKm: 1,
		rayleighScatterPerKm: [0, 0, 0],
		rayleighScaleHeightKm: 1,
		mieScatterPerKm: [0, 0, 0],
		mieAbsorptionPerKm: [0, 0, 0],
		mieScaleHeightKm: 1,
		miePhase: new Array(384).fill(0),
		absorptionPerKm: [0, 0, 0],
		absorptionCenterKm: 0,
		absorptionWidthKm: 1,
		bakedCompensation: 0,
		multiScatterGain: 0,
		sunIntensity: 0,
		sunColor: [1, 1, 1]
	};

	function shipped(): AtmosphereParams {
		return getAtmosphereParams(bodyId) ?? PENDING_PARAMS;
	}

	function resolved(): AtmosphereParams {
		// Season first (its factors are part of the baseline), sliders on top.
		const base = qSeasonal ? seasonalAtmosphereParams(shipped(), lsDeg) : shipped();
		const scale3 = (v: [number, number, number], f: number): [number, number, number] => [
			v[0] * f,
			v[1] * f,
			v[2] * f
		];
		return {
			...base,
			topAltitudeKm: base.topAltitudeKm * 2 ** topX,
			rayleighScatterPerKm: scale3(base.rayleighScatterPerKm, 2 ** rayleighX),
			mieScatterPerKm: scale3(base.mieScatterPerKm, 2 ** mieX),
			mieAbsorptionPerKm: scale3(base.mieAbsorptionPerKm, 2 ** mieAbsX),
			absorptionPerKm: scale3(base.absorptionPerKm, 2 ** absorberX),
			rayleighScaleHeightKm: base.rayleighScaleHeightKm * 2 ** rayleighHX,
			mieScaleHeightKm: base.mieScaleHeightKm * 2 ** mieHX,
			bakedCompensation: comp,
			multiScatterGain: multiScatter,
			sunIntensity,
			// The albedo toggle is uniform-level in production; here the zeroed
			// param flows through applyAtmosphereParams to the same uniform.
			groundAlbedo: qGroundAlbedo ? shipped().groundAlbedo : 0
		};
	}

	const PLANET_ORIGIN = new Vector3();

	function push(): void {
		if (atmoNode) applyAtmosphereParams(atmoNode, resolved());
		if (sunTUniforms) {
			syncSunTransmittanceUniforms(sunTUniforms, resolved(), RADIUS_SCENE, currentBody.radiusKm);
		}
		if (discTintUniforms) {
			bindViewTint(discTintUniforms, resolved(), PLANET_ORIGIN, RADIUS_SCENE, currentBody.radiusKm);
		}
	}

	// Reset every slider to the body's shipped baseline (all multipliers → ×1).
	function syncFromShipped(): void {
		const base = shipped();
		comp = base.bakedCompensation;
		sunIntensity = base.sunIntensity;
		multiScatter = base.multiScatterGain;
		topX = 0;
		rayleighX = 0;
		mieX = 0;
		mieAbsX = 0;
		absorberX = 0;
		rayleighHX = 0;
		mieHX = 0;
	}

	function resetShipped(): void {
		syncFromShipped();
		push();
	}

	async function copyJson(): Promise<void> {
		// miePhase is a 384-float offline table — pointless in a param dump.
		const rest = { ...resolved(), miePhase: undefined };
		await navigator.clipboard.writeText(JSON.stringify(rest, null, '\t'));
		copied = true;
		setTimeout(() => (copied = false), 1200);
	}

	function sunDirection(): Vector3 {
		const el = sunEl * DEG;
		const az = sunAz * DEG;
		return sunVec
			.set(Math.cos(el) * Math.cos(az), Math.sin(el), Math.cos(el) * Math.sin(az))
			.normalize();
	}

	// Altitude/longitude/latitude place the camera on the view sphere; aiming
	// is separate (free mouse-look), so repositioning keeps its current look.
	function setPosition(): void {
		const latR = camLat * DEG;
		const lonR = camLon * DEG;
		const dist = RADIUS_SCENE * (1 + Math.max(altRadii, 0));
		camDir.set(Math.cos(latR) * Math.cos(lonR), Math.sin(latR), Math.cos(latR) * Math.sin(lonR));
		camera.position.copy(camDir).multiplyScalar(dist);
		camera.near = Math.max(dist * 1e-4, RADIUS_SCENE * 1e-5);
		camera.updateProjectionMatrix();
	}

	// Free-look: the mouse aims the camera itself (yaw then pitch), not the
	// app's orbit-the-body drag — lets you sit on the ground and look up.
	function applyLook(): void {
		camera.rotation.set(lookPitch * DEG, lookYaw * DEG, 0);
	}

	function positionCamera(): void {
		setPosition();
		if (cameraMode === 'orbit') faceCenter();
		else applyLook();
	}

	function setCameraMode(m: 'look' | 'orbit'): void {
		cameraMode = m;
		positionCamera();
	}

	// Aim back at the body centre and capture that as the yaw/pitch the mouse
	// then nudges from.
	function faceCenter(): void {
		camera.lookAt(0, 0, 0);
		lookYaw = camera.rotation.y / DEG;
		lookPitch = camera.rotation.x / DEG;
	}

	// Current (tuned) top-of-atmosphere altitude in body radii — drives the
	// mid/top presets.
	function topAltitudeRadii(): number {
		return (shipped().topAltitudeKm * 2 ** topX) / currentBody.radiusKm;
	}

	// Absolute-km readout for the (radius-relative) altitude.
	function altitudeLabel(): string {
		const km = altRadii * currentBody.radiusKm;
		if (km < 1) return 'ground';
		if (km >= 1000) return `${(km / 1000).toFixed(1)}Mm`;
		return `${Math.round(km)}km`;
	}

	function setAltitude(radii: number): void {
		altRadii = radii;
		positionCamera();
	}

	function resetCamera(): void {
		camLat = DEFAULT_LAT;
		camLon = DEFAULT_LON;
		altRadii = DEFAULT_ALT_RADII;
		setPosition();
		faceCenter();
	}

	function resetSun(): void {
		sunAz = DEFAULT_SUN_AZ;
		sunEl = DEFAULT_SUN_EL;
		sunScaleX = 0;
		// Back to the body's shipped default, not flat — matches buildBody.
		sunDistT = shipped().realisticSunAlways ? 1 : 0;
	}

	// Drag orbits (longitude/latitude); wheel changes altitude.
	let dragging = false;
	let lastX = 0;
	let lastY = 0;

	function onPointerDown(e: PointerEvent): void {
		dragging = true;
		lastX = e.clientX;
		lastY = e.clientY;
		canvas.setPointerCapture(e.pointerId);
	}

	function onPointerMove(e: PointerEvent): void {
		if (!dragging) return;
		const dx = e.clientX - lastX;
		const dy = e.clientY - lastY;
		lastX = e.clientX;
		lastY = e.clientY;
		if (cameraMode === 'orbit') {
			// Match the app's OrbitControls "grab the globe" sense (drag right →
			// the body follows), which is the opposite sign of free-look.
			camLon = ((((camLon + dx * 0.25) % 360) + 540) % 360) - 180;
			camLat = Math.max(-89, Math.min(89, camLat + dy * 0.25));
			setPosition();
			faceCenter();
		} else {
			lookYaw -= dx * 0.15;
			lookPitch = Math.max(-89, Math.min(89, lookPitch - dy * 0.15));
			applyLook();
		}
	}

	function onPointerUp(e: PointerEvent): void {
		dragging = false;
		if (canvas.hasPointerCapture(e.pointerId)) canvas.releasePointerCapture(e.pointerId);
	}

	function onWheel(e: WheelEvent): void {
		e.preventDefault();
		const base = Math.max(altRadii, ALT_MIN_RADII);
		altRadii = Math.min(base * Math.exp(e.deltaY * 0.0015), ALT_MAX_RADII);
		positionCamera();
	}

	// Serialize the full tunable state into a query string. Multipliers are
	// per-body (relative to shipped), so they restore against whichever body `b` selects.
	function serializeSearch(): string {
		const r = (n: number) => String(Number(n.toFixed(4)));
		const p = new URLSearchParams();
		p.set('b', bodyId.replace('naif-', ''));
		p.set('cam', cameraMode === 'orbit' ? 'o' : 'l');
		p.set('alt', r(altRadii));
		p.set('lon', r(camLon));
		p.set('lat', r(camLat));
		p.set('yaw', r(lookYaw));
		p.set('pit', r(lookPitch));
		p.set('saz', r(sunAz));
		p.set('sel', r(sunEl));
		p.set('slit', r(sunScaleX));
		p.set('real', r(sunDistT));
		p.set('comp', r(comp));
		p.set('asun', r(sunIntensity));
		p.set('msc', r(multiScatter));
		p.set('top', r(topX));
		p.set('ray', r(rayleighX));
		p.set('mie', r(mieX));
		p.set('mieA', r(mieAbsX));
		p.set('abs', r(absorberX));
		p.set('rayH', r(rayleighHX));
		p.set('mieH', r(mieHX));
		p.set('q', qTier);
		p.set('qps', String(qPrimarySteps));
		p.set('qls', String(qLightSteps));
		p.set('qec', qEclipse ? '1' : '0');
		p.set('qrs', qRings ? '1' : '0');
		p.set('qiv', qInside ? '1' : '0');
		p.set('qst', qSunTint ? '1' : '0');
		p.set('qld', qLayered ? '1' : '0');
		p.set('qga', qGroundAlbedo ? '1' : '0');
		p.set('qss', qSeasonal ? '1' : '0');
		p.set('qrf', qRefraction ? '1' : '0');
		p.set('mls', r(lsDeg));
		return p.toString();
	}

	// Apply the URL-captured state after the first body has built, so it
	// overrides the shipped/reset defaults. `b` is applied earlier, pre-build.
	function applyInitialState(): void {
		const p = initialParams;
		const num = (k: string, cur: number) => (p.has(k) ? Number(p.get(k)) : cur);
		cameraMode = p.get('cam') === 'o' ? 'orbit' : cameraMode;
		altRadii = num('alt', altRadii);
		camLon = num('lon', camLon);
		camLat = num('lat', camLat);
		lookYaw = num('yaw', lookYaw);
		lookPitch = num('pit', lookPitch);
		sunAz = num('saz', sunAz);
		sunEl = num('sel', sunEl);
		sunScaleX = num('slit', sunScaleX);
		// Also parses the old boolean URLs ('0'/'1').
		sunDistT = num('real', sunDistT);
		comp = num('comp', comp);
		sunIntensity = num('asun', sunIntensity);
		multiScatter = num('msc', multiScatter);
		topX = num('top', topX);
		rayleighX = num('ray', rayleighX);
		mieX = num('mie', mieX);
		mieAbsX = num('mieA', mieAbsX);
		absorberX = num('abs', absorberX);
		rayleighHX = num('rayH', rayleighHX);
		mieHX = num('mieH', mieHX);
		const qt = p.get('q') as ResolvedAtmosphereTier | null;
		if (qt && QUALITY_TIERS.includes(qt)) loadTierPreset(qt);
		qPrimarySteps = num('qps', qPrimarySteps);
		qLightSteps = num('qls', qLightSteps);
		if (p.has('qec')) qEclipse = p.get('qec') === '1';
		if (p.has('qrs')) qRings = p.get('qrs') === '1';
		if (p.has('qiv')) qInside = p.get('qiv') === '1';
		if (p.has('qst')) qSunTint = p.get('qst') === '1';
		if (p.has('qld')) qLayered = p.get('qld') === '1';
		if (p.has('qga')) qGroundAlbedo = p.get('qga') === '1';
		if (p.has('qss')) qSeasonal = p.get('qss') === '1';
		if (p.has('qrf')) qRefraction = p.get('qrf') === '1';
		lsDeg = num('mls', lsDeg);
		positionCamera();
		push();
		pushQuality();
	}

	function loadOne(url: string): Promise<Texture> {
		return new Promise((resolve, reject) => textureLoader.load(url, resolve, undefined, reject));
	}

	async function loadTexture(id: string, mesh: Mesh): Promise<void> {
		// Most bodies ship a single `low.webp`; the monthly-mosaic ones (Earth)
		// only have per-frame `low_NN.webp`, so fall back to the first frame.
		const tex = await loadOne(versionedUrl(`/v1/textures/${id}/low.webp`, 'textures'))
			.catch(() => loadOne(versionedUrl(`/v1/textures/${id}/low_01.webp`, 'textures')))
			.catch((e) => {
				console.error(`atmosphere debug: texture load failed for ${id}`, e);
				return null;
			});
		if (!tex) return;
		// Bail if the body was swapped out while the texture was in flight.
		if (mesh !== planetMesh) {
			tex.dispose();
			return;
		}
		tex.colorSpace = SRGBColorSpace;
		tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
		const mat = mesh.material as MeshStandardMaterial;
		mat.map = tex;
		mat.color.setScalar(1);
		mat.needsUpdate = true;
	}

	function disposePlanet(): void {
		sunTUniforms = null;
		if (atmoNode) {
			scene.remove(atmoNode.mesh);
			disposeAtmosphereNode(atmoNode);
			atmoNode = null;
		}
		if (planetMesh) {
			scene.remove(planetMesh);
			planetMesh.geometry.dispose();
			const mat = planetMesh.material as MeshStandardMaterial;
			mat.map?.dispose();
			mat.dispose();
			planetMesh = null;
		}
	}

	function buildBody(): void {
		disposePlanet();
		currentBody = BODIES.find((b) => b.id === bodyId) ?? BODIES[1];
		// Always-realistic bodies start with inverse-square on; the URL's `real`
		// param can still override it, since applyInitialState runs after.
		sunDistT = shipped().realisticSunAlways ? 1 : 0;
		syncFromShipped();

		const geometry = new SphereGeometry(RADIUS_SCENE, 128, 128);
		// Untextured fallback stays visible until the CDN texture resolves.
		const material = new MeshStandardMaterial({ color: 0x777777, roughness: 1, metalness: 0 });
		// Eclipse patch only as scaffolding for the sun-transmittance patch —
		// the frame loop zeroes the occluder set, so its own factor is 1.
		const eclipseSelf = attachEclipseShadowToBody(material);
		sunTUniforms = attachSunTransmittanceToBody(
			material,
			resolved(),
			RADIUS_SCENE,
			currentBody.radiusKm,
			eclipseSelf
		);
		// Re-aim the disc's per-fragment chroma at the newly selected body.
		push();
		planetMesh = new Mesh(geometry, material);
		planetMesh.renderOrder = 1;
		scene.add(planetMesh);
		void loadTexture(bodyId, planetMesh);

		atmoNode = buildAtmosphereNode(resolved(), RADIUS_SCENE, currentBody.radiusKm);
		// The builder compiles against the app-wide config; re-apply the bench's
		// own quality state (no-op when they match).
		applyAtmosphereQuality(atmoNode, qualityConfig());
		scene.add(atmoNode.mesh);

		// First body frames itself; later switches keep the current camera and
		// Sun so the same viewpoint can be compared across bodies.
		if (firstBuild) {
			firstBuild = false;
			resetCamera();
		} else {
			positionCamera();
		}
	}

	function resize(): void {
		const w = canvas.clientWidth;
		const h = canvas.clientHeight;
		renderer.setSize(w, h, false);
		composer.setSize(w, h);
		camera.aspect = w / h;
		camera.updateProjectionMatrix();
	}

	function frame(): void {
		raf = requestAnimationFrame(frame);

		const now = performance.now();
		if (lastFrameMs) {
			fpsWindowMs += now - lastFrameMs;
			fpsFrames++;
			if (fpsWindowMs >= 500) {
				fps = (fpsFrames * 1000) / fpsWindowMs;
				fpsWindowMs = 0;
				fpsFrames = 0;
			}
		}
		lastFrameMs = now;

		const sd = sunDirection();
		const sunScale = 2 ** sunScaleX; // sun-light bar (log2)
		// Real-sun blend: au^(-2t) walks from flat (t=0) to inverse-square at the
		// body's AU (t=1), i.e. an effective distance of au^t.
		const invSq = currentBody.au ** (-2 * sunDistT);

		// Scene-shared eclipse refs + tint enables, per frame — SPA navigation
		// can leave the map page's last state in them.
		const eclipse = getEclipseSceneUniforms();
		eclipse.uSunDir.value.copy(sd);
		eclipse.uSunAngularRadius.value = 0;
		eclipse.uOccluderCount.value = 0;
		setSunTransmittanceEnabled(qSunTint);
		if (discTintUniforms) discTintUniforms.uAtmoTEnable.value = qSunTint ? 1 : 0;

		pointLight.position.copy(sd).multiplyScalar(50);
		pointLight.intensity = SUN_LIGHT_INTENSITY * sunScale;

		// Sun disc at true apparent size, floored to SUN_MIN_PX so far-out suns
		// don't vanish below the rasteriser. Direction carries the in-atmosphere
		// refraction lift (production: updateSunProxy).
		refrSd.copy(sd);
		if (qRefraction) {
			const p = resolved();
			const altKm = Math.max(altRadii, 0) * currentBody.radiusKm;
			if (p.refractivity && altKm < p.topAltitudeKm) {
				refrUp.copy(camera.position).normalize();
				const sinE = Math.min(1, Math.max(-1, refrUp.dot(sd)));
				const n1 = p.refractivity[1] * Math.exp(-altKm / p.rayleighScaleHeightKm);
				const lift = refractionLiftRad(
					n1,
					Math.asin(sinE),
					p.rayleighScaleHeightKm,
					currentBody.radiusKm
				);
				refrPerp.copy(refrUp).addScaledVector(refrSd, -refrUp.dot(refrSd));
				if (lift > 5e-6 && refrPerp.lengthSq() > 1e-12) {
					refrSd.addScaledVector(refrPerp.normalize(), lift).normalize();
				}
			}
		}
		sunMesh.position.copy(refrSd).multiplyScalar(SUN_DIST);
		const distToSun = camera.position.distanceTo(sunMesh.position);
		const realAngRadius = SUN_RADIUS_KM / (currentBody.au * AU_KM);
		const minAngRadius = (SUN_MIN_PX * ((camera.fov * DEG) / canvas.clientHeight)) / 2;
		sunMesh.scale.setScalar(Math.max(realAngRadius, minAngRadius) * distToSun);
		(sunMesh.material as MeshBasicMaterial).color.setScalar(SUN_DISC_BRIGHTNESS * sunScale * invSq);

		if (atmoNode && planetMesh) {
			const u = atmoNode.material.uniforms;
			(u.uSunDir.value as Vector3).copy(sd);
			// Unlike production, the slider alone decides inverse-square here, so
			// always-realistic bodies (Pluto/Triton) can still be inspected flat-sun.
			u.uSunIntensity.value = atmoNode.params.sunIntensity * sunScale * invSq;
			// Flip to BackSide once the camera enters the shell so the sky still
			// renders from inside; drop depth writes there too, mirroring production.
			const shellR = atmoNode.geometryRadiusScene * atmoNode.mesh.scale.x;
			const inside = qInside && camera.position.lengthSq() < shellR * shellR;
			atmoNode.material.side = inside ? BackSide : FrontSide;
			atmoNode.material.depthWrite = !inside;
			atmoNode.material.depthTest = !inside;
			// Sub-datum march floor is an inside-only allowance (see TERRAIN_DIP_KM).
			u.uSurfaceBlockR.value = inside ? 1 - TERRAIN_DIP_KM / atmoNode.planetRadiusKm : 1;
		}
		// Production dims the star map only via the inside-shell path; the
		// readout still shows the would-be factor when the toggle is off.
		scene.backgroundIntensity = qInside ? skyDim : 1;

		composer.render();
	}

	// Keep the URL in sync with the tunable state, debounced so a drag doesn't
	// spam history; gated by `ready` so it can't clobber the incoming URL.
	let urlTimer: ReturnType<typeof setTimeout> | undefined;
	$effect(() => {
		const search = serializeSearch();
		if (!ready) return;
		clearTimeout(urlTimer);
		urlTimer = setTimeout(() => replaceState(`?${search}`, {}), 120);
	});

	onMount(() => {
		renderer = new WebGLRenderer({ canvas, logarithmicDepthBuffer: true, antialias: true });
		renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
		renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);
		// The shell's HDR rolloff is tuned against ACES + bloom — match it exactly.
		renderer.toneMapping = ACESFilmicToneMapping;
		renderer.toneMappingExposure = 1.0;
		textureLoader = new TextureLoader();

		scene = new Scene();
		scene.backgroundRotation.setFromQuaternion(SKYBOX_BASE_ROTATION);
		void loadSkybox(scene, renderer);
		scene.add(new AmbientLight(0xffffff, AMBIENT_INTENSITY));
		pointLight = new PointLight(0xffffff, SUN_LIGHT_INTENSITY, 0, 0);
		scene.add(pointLight);
		sunMesh = new Mesh(new SphereGeometry(1, 32, 32), new MeshBasicMaterial({ color: 0xffffff }));
		// Per-fragment disc chroma, mirroring the production photosphere;
		// push() aims it at the current body's params.
		discTintUniforms = attachViewTintToMaterial(sunMesh.material as MeshBasicMaterial);
		scene.add(sunMesh);

		camera = new PerspectiveCamera(50, canvas.clientWidth / canvas.clientHeight, 1e-4, 1000);
		// Yaw-then-pitch so mouse-look never rolls the horizon.
		camera.rotation.order = 'YXZ';

		composer = new EffectComposer(renderer);
		composer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
		composer.setSize(canvas.clientWidth, canvas.clientHeight);
		composer.addPass(new RenderPass(scene, camera));
		composer.addPass(
			new UnrealBloomPass(new Vector2(canvas.clientWidth, canvas.clientHeight), 0.3, 0.5, 1.0)
		);
		composer.addPass(new OutputPass());

		Promise.allSettled([fetchMetadata(), loadAtmospheres()]).then(() => {
			if (!getAtmosphereParams(bodyId)) {
				console.error('atmosphere tuner: atmospheres.json failed to load — nothing to tune');
				return;
			}
			// Select the URL's body before building so it frames itself, then
			// overlay the rest of the saved state.
			const bid = initialParams.get('b');
			if (bid && getAtmosphereParams(`naif-${bid}`)) bodyId = `naif-${bid}`;
			buildBody();
			applyInitialState();
			ready = true;
		});

		canvas.addEventListener('pointerdown', onPointerDown);
		window.addEventListener('pointermove', onPointerMove);
		window.addEventListener('pointerup', onPointerUp);
		canvas.addEventListener('wheel', onWheel, { passive: false });
		window.addEventListener('resize', resize);
		raf = requestAnimationFrame(frame);

		return () => {
			cancelAnimationFrame(raf);
			canvas.removeEventListener('pointerdown', onPointerDown);
			window.removeEventListener('pointermove', onPointerMove);
			window.removeEventListener('pointerup', onPointerUp);
			canvas.removeEventListener('wheel', onWheel);
			window.removeEventListener('resize', resize);
			disposePlanet();
			renderer.dispose();
		};
	});
</script>

<div class="page">
	<canvas bind:this={canvas}></canvas>

	<div class="panel" class:collapsed>
		<div class="row header">
			<button
				type="button"
				class="collapse"
				aria-expanded={!collapsed}
				aria-label={collapsed ? 'Expand controls' : 'Collapse controls'}
				onclick={() => (collapsed = !collapsed)}
			>
				{collapsed ? '▸' : '▾'}
			</button>
			<span class="title">Atmosphere tuner</span>
			<span class="fps">{fps.toFixed(0)}fps</span>
			<label class="body-select">
				<select
					bind:value={bodyId}
					onchange={() => {
						buildBody();
						push();
					}}
				>
					{#each BODIES as b (b.id)}
						<option value={b.id}>{b.name}</option>
					{/each}
				</select>
			</label>
		</div>

		{#if !collapsed}
			<p class="hint">
				{cameraMode === 'look'
					? 'Drag to look around · wheel = altitude · sliders position the camera'
					: 'Drag to orbit the body · wheel = altitude'}
			</p>

			<div class="section">
				<span>Camera</span>
				<div class="actions">
					<button
						type="button"
						title="Switch between free mouse-look and orbit-the-body"
						onclick={() => setCameraMode(cameraMode === 'look' ? 'orbit' : 'look')}
					>
						{cameraMode === 'look' ? 'free-look' : 'orbit'}
					</button>
					<button type="button" onclick={resetCamera}>reset</button>
				</div>
			</div>
			<div class="presets">
				<button type="button" onclick={() => setAltitude(0)}>Ground</button>
				<button type="button" onclick={() => setAltitude(topAltitudeRadii() / 2)}>Mid atmo</button>
				<button type="button" onclick={() => setAltitude(topAltitudeRadii())}>Atmo top</button>
				<button type="button" onclick={() => setAltitude(1)}>1 R</button>
			</div>
			<div class="grid">
				<span class="lbl" title="Height above the surface, in body radii">Altitude</span>
				<input
					type="range"
					min={Math.log10(ALT_MIN_RADII)}
					max={Math.log10(ALT_MAX_RADII)}
					step="0.01"
					value={Math.log10(Math.max(altRadii, ALT_MIN_RADII))}
					oninput={(e) => setAltitude(10 ** Number(e.currentTarget.value))}
				/>
				<span class="val">{altitudeLabel()}</span>

				<span class="lbl">Longitude</span>
				<input
					type="range"
					min="-180"
					max="180"
					step="1"
					bind:value={camLon}
					oninput={positionCamera}
				/>
				<span class="val">{Math.round(camLon)}°</span>

				<span class="lbl">Latitude</span>
				<input
					type="range"
					min="-89"
					max="89"
					step="1"
					bind:value={camLat}
					oninput={positionCamera}
				/>
				<span class="val">{Math.round(camLat)}°</span>

				<span class="lbl" title="Star-map factor: extinction × exposure compensation">Skybox</span>
				<span></span>
				<span class="val">×{skyDim.toFixed(3)}</span>
			</div>

			<div class="section">
				<span>Sun</span>
				<div class="actions">
					<button type="button" onclick={resetSun}>reset</button>
				</div>
			</div>
			<div class="grid">
				<span class="lbl">Sun azimuth</span>
				<input type="range" min="0" max="360" step="1" bind:value={sunAz} />
				<span class="val">{sunAz}°</span>

				<span class="lbl">Sun elevation</span>
				<input type="range" min="-90" max="90" step="1" bind:value={sunEl} />
				<span class="val">{sunEl}°</span>

				<span class="lbl" title="Multiplies shell + surface sunlight">Sun light</span>
				<input type="range" min="-3" max="3" step="0.05" bind:value={sunScaleX} />
				<span class="val">×{(2 ** sunScaleX).toFixed(2)}</span>

				<span
					class="lbl"
					title="Inverse-square dimming of the disc + shell sunlight: Earth-equivalent (×1) → the body's {currentBody.au} AU"
					>Sun distance</span
				>
				<input type="range" min="0" max="1" step="0.01" bind:value={sunDistT} />
				<span class="val">@{(currentBody.au ** sunDistT).toFixed(2)}AU</span>

				<span></span>
				<div class="marks" aria-hidden="true">
					<span>Earth</span>
					<span>realistic</span>
				</div>
				<span></span>

				<span
					class="lbl"
					title="Camera→sun-centre transmittance chroma ÷ luminance — the disc itself shades per fragment; the shell handles the dimming"
					>Sun tint</span
				>
				<span></span>
				<span
					class="val tint-swatch"
					title={sunTint.map((v) => v.toFixed(2)).join(' / ')}
					style="background: rgb({sunTint
						.map((v) => Math.round((v / Math.max(...sunTint, 1e-6)) * 255))
						.join(' ')})"
				></span>
			</div>

			<div class="section">
				<span>Quality</span>
			</div>
			<div class="presets">
				{#each QUALITY_TIERS as t (t)}
					<button type="button" class:active={qTier === t} onclick={() => setTier(t)}>
						{t === 'medium' ? 'med' : t}
					</button>
				{/each}
			</div>
			<div class="grid">
				<span class="lbl">March steps</span>
				<input
					type="range"
					min="4"
					max="64"
					step="1"
					value={qPrimarySteps}
					oninput={(e) => {
						qPrimarySteps = Number(e.currentTarget.value);
						pushQuality();
					}}
				/>
				<span class="val">{qPrimarySteps}</span>

				<span class="lbl">Sun steps</span>
				<input
					type="range"
					min="1"
					max="16"
					step="1"
					value={qLightSteps}
					oninput={(e) => {
						qLightSteps = Number(e.currentTarget.value);
						pushQuality();
					}}
				/>
				<span class="val">{qLightSteps}</span>
			</div>
			<label class="toggle" title="No occluders in this scene — affects compile cost only">
				<input
					type="checkbox"
					checked={qEclipse}
					onchange={(e) => {
						qEclipse = e.currentTarget.checked;
						pushQuality();
					}}
				/>
				<span>Eclipse shadows</span>
			</label>
			<label class="toggle" title="No rings in this scene — affects compile cost only">
				<input
					type="checkbox"
					checked={qRings}
					onchange={(e) => {
						qRings = e.currentTarget.checked;
						pushQuality();
					}}
				/>
				<span>Ring shadows</span>
			</label>
			<label class="toggle" title="Off: the shell vanishes once the camera enters it">
				<input
					type="checkbox"
					checked={qInside}
					onchange={(e) => {
						qInside = e.currentTarget.checked;
						pushQuality();
					}}
				/>
				<span>Inside view</span>
			</label>
			<label class="toggle" title="Off: untinted sun and white direct light (low/medium default)">
				<input
					type="checkbox"
					checked={qSunTint}
					onchange={(e) => {
						qSunTint = e.currentTarget.checked;
						pushQuality();
					}}
				/>
				<span>Sun tint</span>
			</label>
			<label
				class="toggle"
				title="Piecewise Mie density profiles (Venus decks, Titan detached haze) — high/ultra default"
			>
				<input
					type="checkbox"
					checked={qLayered}
					onchange={(e) => {
						qLayered = e.currentTarget.checked;
						pushQuality();
					}}
				/>
				<span>Layered density</span>
			</label>
			<label class="toggle" title="Ground-bounce boost on the multiple-scatter ambient">
				<input
					type="checkbox"
					checked={qGroundAlbedo}
					onchange={(e) => {
						qGroundAlbedo = e.currentTarget.checked;
						push();
					}}
				/>
				<span>Ground albedo</span>
			</label>
			<label class="toggle" title="Mars dust/pressure cycle at the L_s slider below">
				<input
					type="checkbox"
					checked={qSeasonal}
					onchange={(e) => {
						qSeasonal = e.currentTarget.checked;
						push();
					}}
				/>
				<span>Seasonal (Mars)</span>
			</label>
			<label class="toggle" title="Refraction lift of the sun disc seen from inside the shell">
				<input type="checkbox" bind:checked={qRefraction} />
				<span>Refraction</span>
			</label>

			<div class="section">
				<span>Atmosphere</span>
				<div class="actions">
					<button type="button" onclick={resetShipped}>shipped</button>
					<button type="button" onclick={copyJson}>{copied ? 'copied!' : 'copy JSON'}</button>
				</div>
			</div>
			<div class="grid">
				<span class="lbl" title="0 = pre-compensation look">Baked comp</span>
				<input
					type="range"
					min="0"
					max="1"
					step="0.01"
					value={comp}
					oninput={(e) => {
						comp = Number(e.currentTarget.value);
						push();
					}}
				/>
				<span class="val">{comp.toFixed(2)}</span>

				<span class="lbl">Atmo sun</span>
				<input
					type="range"
					min="0"
					max="40"
					step="0.1"
					value={sunIntensity}
					oninput={(e) => {
						sunIntensity = Number(e.currentTarget.value);
						push();
					}}
				/>
				<span class="val">{sunIntensity.toFixed(1)}</span>

				<span class="lbl">Multi-scat</span>
				<input
					type="range"
					min="0"
					max="3"
					step="0.05"
					value={multiScatter}
					oninput={(e) => {
						multiScatter = Number(e.currentTarget.value);
						push();
					}}
				/>
				<span class="val">{multiScatter.toFixed(2)}</span>

				{#if shipped().seasonal}
					<span class="lbl" title="Mars solar longitude driving the seasonal dust/pressure cycle"
						>Season L_s</span
					>
					<input
						type="range"
						min="0"
						max="360"
						step="1"
						value={lsDeg}
						disabled={!qSeasonal}
						oninput={(e) => {
							lsDeg = Number(e.currentTarget.value);
							push();
						}}
					/>
					<span class="val">{Math.round(lsDeg)}°</span>
				{/if}

				{#each LOG_SLIDERS as s (s.label)}
					<span class="lbl">{s.label}</span>
					<input
						type="range"
						min="-4"
						max="4"
						step="0.05"
						value={s.get()}
						oninput={(e) => {
							s.set(Number(e.currentTarget.value));
							push();
						}}
					/>
					<span class="val">×{(2 ** s.get()).toFixed(2)}</span>
				{/each}
			</div>
		{/if}
	</div>
</div>

<style>
	.page {
		position: fixed;
		inset: 0;
		background: #05070c;
	}
	canvas {
		width: 100%;
		height: 100%;
		display: block;
	}
	.panel {
		position: absolute;
		top: 12px;
		left: 12px;
		width: 340px;
		max-width: calc(100vw - 24px);
		max-height: calc(100vh - 24px);
		overflow-y: auto;
		background: rgba(15, 17, 21, 0.82);
		backdrop-filter: blur(6px);
		border: 1px solid #2b2f38;
		border-radius: 10px;
		padding: 12px 14px;
		color: #e7e9ee;
		font:
			12px/1.4 ui-monospace,
			monospace;
	}
	.panel.collapsed {
		overflow: visible;
	}
	.row.header {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.collapse {
		flex: none;
		width: 22px;
		height: 22px;
		background: #21262d;
		color: #e7e9ee;
		border: 1px solid #2b2f38;
		border-radius: 6px;
		cursor: pointer;
		font: inherit;
		line-height: 1;
	}
	.collapse:hover {
		background: #2b313a;
	}
	.title {
		flex: 1;
		font-weight: 600;
		font-size: 13px;
	}
	.fps {
		color: #9aa1ad;
		font-variant-numeric: tabular-nums;
	}
	.body-select select {
		background: #21262d;
		color: #e7e9ee;
		border: 1px solid #2b2f38;
		border-radius: 6px;
		padding: 3px 6px;
		font: inherit;
	}
	.hint {
		color: #9aa1ad;
		margin: 6px 0 4px;
	}
	.section {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin: 12px 0 6px;
		padding-top: 8px;
		border-top: 1px solid #2b2f3888;
		font-weight: 600;
		color: #c7ccd6;
	}
	.actions {
		display: flex;
		gap: 8px;
	}
	.actions button {
		background: none;
		border: none;
		color: #9aa1ad;
		text-decoration: underline;
		cursor: pointer;
		font: inherit;
	}
	.actions button:hover {
		color: #e7e9ee;
	}
	.presets {
		display: flex;
		gap: 6px;
		margin-bottom: 8px;
	}
	.presets button {
		flex: 1;
		background: #21262d;
		color: #c7ccd6;
		border: 1px solid #2b2f38;
		border-radius: 6px;
		padding: 4px 2px;
		cursor: pointer;
		font: inherit;
	}
	.presets button:hover {
		background: #2b313a;
		color: #e7e9ee;
	}
	.presets button.active {
		background: #2b313a;
		color: #e7e9ee;
		border-color: #4a5160;
	}
	.grid {
		display: grid;
		grid-template-columns: auto 1fr auto;
		gap: 6px 10px;
		align-items: center;
	}
	.lbl {
		color: #9aa1ad;
	}
	.val {
		text-align: end;
		font-variant-numeric: tabular-nums;
		width: 56px;
	}
	/* Hue-only readout (max channel → full): exact values live in the tooltip. */
	.tint-swatch {
		height: 12px;
		border-radius: 3px;
		border: 1px solid #454b57;
	}
	input[type='range'] {
		width: 100%;
		height: 12px;
	}
	/* End labels for the Sun-distance slider (Earth = flat ×1, realistic = body AU). */
	.marks {
		display: flex;
		justify-content: space-between;
		margin-top: -6px;
		font-size: 10px;
		color: #7c828e;
	}
	.toggle {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-top: 8px;
		cursor: pointer;
	}
</style>
