<script lang="ts">
	import { getContext, untrack } from 'svelte';
	import {
		ACESFilmicToneMapping,
		AdditiveBlending,
		AmbientLight,
		CanvasTexture,
		DirectionalLight,
		Mesh,
		MeshStandardMaterial,
		OrthographicCamera,
		Quaternion,
		Scene,
		SphereGeometry,
		Sprite,
		SpriteMaterial,
		SRGBColorSpace,
		TextureLoader,
		Vector3,
		WebGLRenderer
	} from 'three';
	import type { NotableMemberEntry } from '$lib/fetch/groups/details';
	import type { Orientation } from '$lib/math/orientation';
	import {
		disposeCloudNode,
		loadCloudNode,
		type CloudMeta,
		type CloudNode
	} from '$lib/scene/objects/surface/clouds';
	import { BODY_COLORS, DEFAULT_BODY_COLOR } from '$lib/constants';
	import { DATA_BASE, versionedUrl } from '$lib/fetch/data-base';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import { applyFocus, serializeUrl, urlTypeFromId } from '$lib/state/url';
	import { formatNumber } from '$lib/format/quantities';
	import * as m from '$lib/paraglide/messages.js';

	interface Props {
		members: NotableMemberEntry[];
		localizedNames?: Record<string, string>;
	}
	let { members, localizedNames }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');

	// Equatorial radius (km) = PCK `radii.a`, the export's authoritative size and
	// the value the 3D scene renders (`max(a,b,c)`). Category `notable_members`
	// carry no diameter, so the lineup sizes off these constants; the key set
	// doubles as the planet filter.
	const PLANET_RADIUS_KM: Record<string, number> = {
		'naif-199': 2440.53, // Mercury
		'naif-299': 6051.8, // Venus
		'naif-399': 6378.14, // Earth
		'naif-499': 3396.19, // Mars
		'naif-599': 71492, // Jupiter
		'naif-699': 60268, // Saturn
		'naif-799': 25559, // Uranus
		'naif-899': 24764 // Neptune
	};

	// Polar ÷ equatorial radius (c/a) from the export's PCK radii — the oblateness
	// the 3D scene renders. Scales the sphere's polar axis so the giants flatten.
	const PLANET_POLAR_RATIO: Record<string, number> = {
		'naif-199': 0.99907, // Mercury
		'naif-299': 1.0, // Venus
		'naif-399': 0.996646, // Earth
		'naif-499': 0.994114, // Mars
		'naif-599': 0.935126, // Jupiter
		'naif-699': 0.902037, // Saturn
		'naif-799': 0.97707, // Uranus
		'naif-899': 0.982918 // Neptune
	};

	// Monthly-textured bodies have no plain `low.webp` — pick one frame. Earth's
	// surface is a 12-month composite; others are single-frame.
	const PLANET_SURFACE_FRAME: Record<string, string> = { 'naif-399': '06' };

	// IAU pole RA/Dec (SPICE PCK, mirroring the export) — used only to derive each
	// planet's obliquity, so the stylised tilt below is driven by the real number.
	const PLANET_POLE: Record<string, Pick<Orientation, 'pole_ra_0' | 'pole_dec_0'>> = {
		'naif-199': { pole_ra_0: 281.0103, pole_dec_0: 61.4155 }, // Mercury
		'naif-299': { pole_ra_0: 272.76, pole_dec_0: 67.16 }, // Venus
		'naif-399': { pole_ra_0: 0, pole_dec_0: 90 }, // Earth
		'naif-499': { pole_ra_0: 317.269202, pole_dec_0: 54.432516 }, // Mars
		'naif-599': { pole_ra_0: 268.056595, pole_dec_0: 64.495303 }, // Jupiter
		'naif-699': { pole_ra_0: 40.589, pole_dec_0: 83.537 }, // Saturn
		'naif-799': { pole_ra_0: 257.311, pole_dec_0: -15.175 }, // Uranus
		'naif-899': { pole_ra_0: 299.36, pole_dec_0: 43.46 } // Neptune
	};

	// "Looking from center-north-west" presentation, shared by all planets, while
	// keeping each planet's REAL axial tilt. VIEW_PITCH tips the top toward us (we
	// view from the north, so the equator bows downward). Each planet is then
	// rotated so its real obliquity leans the north pole toward the upper-left —
	// the equator slopes down left→right by the true tilt (Uranus most, Venus
	// barely). FACE_YAW spins the visible face about the pole.
	const DEG2RAD = Math.PI / 180;
	const ECLIPTIC_RAD = 23.4392911 * DEG2RAD;
	const VIEW_PITCH = 0.32;
	const FACE_YAW = 0;
	const AXIS_X = new Vector3(1, 0, 0);
	const AXIS_Y = new Vector3(0, 1, 0);
	const AXIS_Z = new Vector3(0, 0, 1);

	/** Obliquity of the spin axis to the ecliptic (radians), from the IAU pole. */
	function obliquityRad(pole: Pick<Orientation, 'pole_ra_0' | 'pole_dec_0'>): number {
		const ra = pole.pole_ra_0 * DEG2RAD;
		const dec = pole.pole_dec_0 * DEG2RAD;
		const y = Math.cos(dec) * Math.sin(ra);
		const z = Math.sin(dec);
		const zEcl = -y * Math.sin(ECLIPTIC_RAD) + z * Math.cos(ECLIPTIC_RAD);
		return Math.acos(Math.max(-1, Math.min(1, zEcl)));
	}

	/** Sphere orientation for the NW view; +Y is the texture's north. Roll = the
	 *  planet's real obliquity, so the visible tilt is true to the body. */
	function styledQuaternion(id: string): Quaternion {
		const pole = PLANET_POLE[id];
		const roll = pole ? obliquityRad(pole) : 0;
		const q = new Quaternion().setFromAxisAngle(AXIS_Z, roll);
		q.multiply(new Quaternion().setFromAxisAngle(AXIS_X, VIEW_PITCH));
		q.multiply(new Quaternion().setFromAxisAngle(AXIS_Y, FACE_YAW));
		return q;
	}

	interface Planet {
		id: string;
		name: string;
		diameterKm: number;
	}

	let planets = $derived.by<Planet[]>(() => {
		const byId = new Map(members.filter((mm) => mm.id).map((mm) => [mm.id as string, mm]));
		const out: Planet[] = [];
		for (const id of Object.keys(PLANET_RADIUS_KM)) {
			const mm = byId.get(id);
			if (!mm) continue;
			out.push({ id, name: localizedNames?.[id] ?? mm.name, diameterKm: PLANET_RADIUS_KM[id] * 2 });
		}
		return out;
	});

	const HEIGHT = 204;
	// Ortho depth separation between stacked planets — large enough that their
	// 3D geometry never intersects, invisible because the projection is ortho.
	const Z_STEP = 10000;
	let width = $state(0);
	let containerEl = $state<HTMLDivElement | null>(null);
	let hoveredId = $state<string | null>(null);

	interface LaidOut extends Planet {
		pr: number; // sphere pixel radius
		cx: number; // center x (px, left origin)
		cy: number; // center y (px, top origin)
		colLeft: number;
		colWidth: number;
	}

	// Layout knobs (tune freely):
	const VPAD = 10; // equal margin above and below the largest planet
	const SIDE_PAD = 6;

	let layout = $derived.by<LaidOut[]>(() => {
		if (!width || planets.length === 0) return [];
		// Largest → smallest, left → right (mockup order).
		const sorted = [...planets].sort((a, b) => b.diameterKm - a.diameterKm);
		const raw = sorted.map((p) => p.diameterKm / 2);
		// Largest fits the height with equal top/bottom padding; true-linear from there.
		const k = (HEIGHT - 2 * VPAD) / 2 / raw[0];
		const prs = raw.map((r) => Math.max(2, r * k)); // floor so tiny worlds stay visible
		const n = sorted.length;
		// Constant center-to-center spacing, fit so the end spheres touch the pads.
		const step = n > 1 ? (width - prs[0] - prs[n - 1] - 2 * SIDE_PAD) / (n - 1) : 0;
		const baseline = HEIGHT - VPAD;
		const items: LaidOut[] = sorted.map((p, i) => {
			const pr = prs[i];
			const cx = SIDE_PAD + prs[0] + i * step;
			return { ...p, pr, cx, cy: baseline - pr, colLeft: 0, colWidth: 0 };
		});
		// Hit columns span midpoint-to-midpoint so tiny planets get a roomy target.
		for (let i = 0; i < items.length; i++) {
			const left = i === 0 ? 0 : (items[i - 1].cx + items[i].cx) / 2;
			const right = i === items.length - 1 ? width : (items[i].cx + items[i + 1].cx) / 2;
			items[i].colLeft = left;
			items[i].colWidth = right - left;
		}
		return items;
	});

	let hovered = $derived(layout.find((p) => p.id === hoveredId) ?? null);

	/** Planet under the cursor: a sphere it sits inside wins (front-most, i.e. the
	 *  smallest — last in `layout`); otherwise the column it's in. */
	function pickAt(clientX: number, clientY: number): string | null {
		if (!containerEl) return null;
		const r = containerEl.getBoundingClientRect();
		const mx = clientX - r.left;
		const my = clientY - r.top;
		for (let i = layout.length - 1; i >= 0; i--) {
			const p = layout[i];
			const dx = mx - p.cx;
			const dy = my - p.cy;
			if (dx * dx + dy * dy <= p.pr * p.pr) return p.id;
		}
		for (const p of layout) if (mx >= p.colLeft && mx < p.colLeft + p.colWidth) return p.id;
		return null;
	}

	function href(p: Planet): string | undefined {
		if (!appState) return undefined;
		return serializeUrl(
			applyFocus(appState.view, { type: urlTypeFromId(p.id), id: p.id, name: p.name })
		);
	}

	function focusHovered(e: MouseEvent) {
		if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
		if (!focusObject || !hoveredId) return;
		e.preventDefault();
		const p = planets.find((x) => x.id === hoveredId);
		focusObject(hoveredId, p?.name ?? hoveredId, { moveCamera: true });
	}

	// --- Three.js: a flat, orthographic, pixel-space lineup of textured spheres.
	let canvasEl = $state<HTMLCanvasElement | null>(null);
	let renderer: WebGLRenderer | undefined;
	let scene: Scene | undefined;
	let camera: OrthographicCamera | undefined;
	const geometry = new SphereGeometry(1, 48, 48);
	const meshes = new Map<string, Mesh>();
	const cloudNodes = new Map<string, CloudNode>();

	// Hover halo: a depth-tested billboard at the hovered planet's depth, so the
	// depth buffer occludes it behind nearer planets and lets it draw over
	// farther ones. The ring texture is regenerated per planet size so the halo
	// stays a constant pixel width regardless of planet size.
	const GLOW_PX = 14;
	const GLOW_MAX = 0.55; // peak halo opacity
	let glowSprite: Sprite | undefined;
	let glowKey = '';
	let glowOpacity = 0;
	let glowAnimId: number | undefined;

	function makeGlowTexture(pr: number): CanvasTexture {
		const res = 128;
		const c = document.createElement('canvas');
		c.width = c.height = res;
		const ctx = c.getContext('2d')!;
		const R = res / 2;
		const f = pr / (pr + GLOW_PX); // planet edge as a fraction of the sprite radius
		const g = ctx.createRadialGradient(R, R, 0, R, R, R);
		// Transparent inside (the planet covers it), a bright rim at the edge,
		// fading out over GLOW_PX. Transparent core avoids a blob poking past the
		// flattened poles of oblate giants.
		g.addColorStop(0, 'rgba(255,255,255,0)');
		g.addColorStop(Math.max(0, f - 0.12), 'rgba(255,255,255,0)');
		g.addColorStop(Math.min(1, f), 'rgba(255,255,255,1)');
		g.addColorStop(1, 'rgba(255,255,255,0)');
		ctx.fillStyle = g;
		ctx.fillRect(0, 0, res, res);
		const tex = new CanvasTexture(c);
		tex.colorSpace = SRGBColorSpace;
		return tex;
	}

	// Planets with a cloud overlay → their barycenter system file (where the
	// cloud bundle metadata lives).
	const PLANET_CLOUD_SYSTEM: Record<string, string> = {
		'naif-299': 'naif-2', // Venus
		'naif-399': 'naif-3' // Earth
	};

	/** Cloud overlay: a child sphere inheriting the planet's tilt + scale. Frame
	 *  ids can be live timestamps, so read the system meta rather than bake one.
	 *  Best-effort — clouds are optional. */
	async function loadClouds(planetId: string, systemId: string, planetMesh: Mesh) {
		try {
			const res = await fetch(`${DATA_BASE}/v1/systems/${systemId}.json`);
			if (!res.ok) return;
			const sys = await res.json();
			const meta: CloudMeta | undefined = sys[planetId]?.clouds;
			if (!meta?.frames?.length) return;
			const frame = meta.frames[meta.frames.length - 1];
			if (meshes.get(planetId) !== planetMesh) return; // rebuilt while awaiting
			const node = await loadCloudNode(planetMesh, 1, meta, frame);
			if (node) cloudNodes.set(planetId, node);
			render();
		} catch {
			/* clouds are a nice-to-have */
		}
	}

	function clearMeshes() {
		for (const node of cloudNodes.values()) disposeCloudNode(node);
		cloudNodes.clear();
		for (const mesh of meshes.values()) {
			scene?.remove(mesh);
			(mesh.material as MeshStandardMaterial).map?.dispose();
			(mesh.material as MeshStandardMaterial).dispose();
		}
		meshes.clear();
	}

	function buildMeshes() {
		if (!scene) return;
		clearMeshes();
		const loader = new TextureLoader();
		for (const p of planets) {
			const color = BODY_COLORS[p.id] ?? DEFAULT_BODY_COLOR;
			const material = new MeshStandardMaterial({ color, roughness: 1, metalness: 0 });
			const mesh = new Mesh(geometry, material);
			mesh.quaternion.copy(styledQuaternion(p.id));
			scene.add(mesh);
			meshes.set(p.id, mesh);
			const frame = PLANET_SURFACE_FRAME[p.id];
			const url = versionedUrl(
				`/v1/textures/${p.id}/${frame ? `low_${frame}` : 'low'}.webp`,
				'textures'
			);
			loader.load(
				url,
				(tex) => {
					tex.colorSpace = SRGBColorSpace;
					material.map = tex;
					material.color.set(0xffffff);
					material.needsUpdate = true;
					render();
				},
				undefined,
				() => {} // keep the flat color on failure
			);
			const cloudSystem = PLANET_CLOUD_SYSTEM[p.id];
			if (cloudSystem) loadClouds(p.id, cloudSystem, mesh);
		}
	}

	function render() {
		if (!renderer || !scene || !camera || !width) return;
		renderer.setSize(width, HEIGHT, false);
		camera.left = 0;
		camera.right = width;
		camera.top = HEIGHT;
		camera.bottom = 0;
		camera.updateProjectionMatrix();
		const n = layout.length;
		layout.forEach((p, i) => {
			const mesh = meshes.get(p.id);
			if (!mesh) return;
			// Smaller planets (later in `layout`) sit nearer the camera, so they stay
			// visible on top of the giants they overlap — easier to see and click.
			// The depth gaps are huge (no 3D intersection seam) but invisible under
			// the orthographic projection.
			mesh.position.set(p.cx, HEIGHT - p.cy, -(n - 1 - i) * Z_STEP);
			// Non-uniform: flatten the polar (local +Y) axis for oblateness. Applied
			// in local space before the tilt quaternion, so it aligns with the pole.
			mesh.scale.set(p.pr, p.pr * (PLANET_POLAR_RATIO[p.id] ?? 1), p.pr);
		});
		updateGlow();
		renderer.render(scene, camera);
	}

	function updateGlow() {
		if (!glowSprite) return;
		const i = hoveredId ? layout.findIndex((p) => p.id === hoveredId) : -1;
		if (i >= 0) {
			const p = layout[i];
			const half = p.pr + GLOW_PX;
			// Sit just behind the hovered planet (ε ≪ Z_STEP): its own disc masks
			// the halo's core, nearer planets occlude it, farther ones show through.
			glowSprite.position.set(p.cx, HEIGHT - p.cy, -(layout.length - 1 - i) * Z_STEP - 50);
			glowSprite.scale.set(2 * half, 2 * half, 1);
			const key = `${p.id}:${Math.round(p.pr)}`;
			if (key !== glowKey) {
				const mat = glowSprite.material;
				mat.map?.dispose();
				mat.map = makeGlowTexture(p.pr);
				mat.color.set(BODY_COLORS[p.id] ?? DEFAULT_BODY_COLOR);
				mat.needsUpdate = true;
				glowKey = key;
			}
			glowSprite.visible = true; // kept on the last planet while fading out
		}
		animateGlow();
	}

	/** Tween the halo toward its target opacity (GLOW_MAX when hovered, else 0),
	 *  driving an rAF loop only while in transition. */
	function animateGlow() {
		const target = hoveredId ? GLOW_MAX : 0;
		if (glowOpacity === target || glowAnimId !== undefined) return;
		const step = () => {
			glowAnimId = undefined;
			if (!glowSprite || !renderer || !scene || !camera) return;
			const t = hoveredId ? GLOW_MAX : 0;
			glowOpacity += (t - glowOpacity) * 0.25;
			if (Math.abs(t - glowOpacity) < 0.01) glowOpacity = t;
			glowSprite.material.opacity = glowOpacity;
			if (glowOpacity === 0) glowSprite.visible = false;
			renderer.render(scene, camera);
			if (glowOpacity !== t) glowAnimId = requestAnimationFrame(step);
		};
		glowAnimId = requestAnimationFrame(step);
	}

	$effect(() => {
		if (!canvasEl) return;
		renderer = new WebGLRenderer({ canvas: canvasEl, alpha: true, antialias: true });
		renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
		// Match the main scene's colour pipeline (three-boot.ts): sRGB output +
		// ACES, which rolls bright albedos off smoothly instead of hard-clipping
		// to washed-out white.
		renderer.outputColorSpace = SRGBColorSpace;
		renderer.toneMapping = ACESFilmicToneMapping;
		renderer.toneMappingExposure = 1.0;
		scene = new Scene();
		// Frustum is fixed up per-render from `width`; don't read it here, or this
		// setup effect would re-run and orphan the meshes on every resize. Deep
		// near/far range so the z-separated spheres (see Z_STEP) all stay in view.
		camera = new OrthographicCamera(0, 1, HEIGHT, 0, -1e6, 1e6);
		camera.position.z = 10;
		const key = new DirectionalLight(0xffffff, 3.1);
		key.position.set(-0.4, 0.45, 1);
		const ambient = new AmbientLight(0xffffff, 0.12);
		scene.add(key, ambient);
		glowSprite = new Sprite(
			new SpriteMaterial({
				transparent: true,
				opacity: 0,
				depthWrite: false,
				blending: AdditiveBlending
			})
		);
		glowSprite.visible = false;
		glowKey = '';
		glowOpacity = 0;
		scene.add(glowSprite);
		return () => {
			if (glowAnimId !== undefined) cancelAnimationFrame(glowAnimId);
			glowAnimId = undefined;
			clearMeshes();
			glowSprite?.material.map?.dispose();
			glowSprite?.material.dispose();
			glowSprite = undefined;
			renderer?.dispose();
			renderer = scene = camera = undefined;
		};
	});

	// Rebuild meshes only when the planet set changes. The post-build render is
	// untracked so this effect doesn't subscribe to layout/hover/width (reading
	// those in render() would otherwise rebuild — and reload textures — on hover).
	$effect(() => {
		void planets;
		buildMeshes();
		untrack(() => render());
	});
	$effect(() => {
		void layout;
		void hoveredId;
		render();
	});
</script>

<div
	bind:this={containerEl}
	bind:clientWidth={width}
	onpointermove={(e) => (hoveredId = pickAt(e.clientX, e.clientY))}
	onpointerleave={() => (hoveredId = null)}
	class="bg-muted/30 relative w-full overflow-hidden rounded-md"
	style="height: {HEIGHT}px"
	role="group"
	aria-label={m.type_planet()}
>
	<canvas bind:this={canvasEl} class="absolute inset-0 h-full w-full"></canvas>

	{#each layout as p (p.id)}
		<!-- Keyboard/href target per planet column; mouse hover is resolved by
		     pickAt (mesh-priority) on the container, and click focuses whatever is
		     hovered. -->
		<a
			href={href(p)}
			onclick={focusHovered}
			onfocus={() => (hoveredId = p.id)}
			onblur={() => hoveredId === p.id && (hoveredId = null)}
			aria-label={p.name}
			class="pointer-events-auto absolute top-0 bottom-0 outline-none"
			style="left: {p.colLeft}px; width: {p.colWidth}px"
		></a>
	{/each}

	{#if hovered}
		<div
			class="bg-popover text-popover-foreground border-border pointer-events-none absolute z-10 -translate-x-1/2 rounded-md border px-2 py-1 text-center shadow-md"
			style="left: {Math.min(Math.max(hovered.cx, 48), width - 48)}px; top: 6px"
		>
			<div class="text-xs font-medium">{hovered.name}</div>
			<div class="text-muted-foreground text-[11px] tabular-nums">
				{m.diameter()}: {formatNumber(Math.round(hovered.diameterKm))} km
			</div>
		</div>
	{/if}
</div>
