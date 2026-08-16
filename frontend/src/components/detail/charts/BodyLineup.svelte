<script lang="ts" module>
	import type { DisplacementMeta } from '$lib/scene/objects/surface/displacement';

	/** One body in the lineup. Geometry is supplied by the caller (planet/moon
	 *  constants today, export diameters for asteroids later), so this engine
	 *  stays body-class agnostic. */
	export interface LineupBody {
		id: string;
		name: string;
		/** Flat sphere colour when no `low.webp` texture loads. Overrides the
		 *  id-keyed BODY_COLORS lookup — small bodies pass a resolved tint here. */
		color?: string;
		/** Localized Wikidata short description, shown under the name on hover. */
		description?: string;
		/** Equatorial radius (km) = PCK `radii.a`; the value the 3D scene renders
		 *  (`max(a,b,c)`). Drives the sphere's pixel size. */
		radiusKm: number;
		/** Polar ÷ equatorial radius (c/a); flattens oblate giants. Default 1. */
		polarRatio?: number;
		/** IAU pole RA/Dec (deg), for the real obliquity tilt. Omit → no tilt. */
		poleRa?: number;
		poleDec?: number;
		/** Monthly-textured bodies pick one frame (`low_<frame>.webp`) over `low`. */
		surfaceFrame?: string;
		/** System id whose bundle carries cloud metadata, for an overlay. */
		cloudSystem?: string;
		/** DEM sibling bundle — same relief the main map renders. `absolute_radius`
		 *  bodies (Vesta/Ceres) skip the oblateness scale and let it carry the shape. */
		displacement?: DisplacementMeta;
		/** Shape-model slug (`v1/models/<slug>/`); loads the mesh in place of the
		 *  sphere, sized/tilted to match. Falls back to the sphere on any failure. */
		model?: string;
		/** Whether a `v1/textures/<id>/` surface map exists. Explicit `false`
		 *  skips the fetch entirely; absent (pre-flag export) probes as before. */
		texture?: boolean;
	}
</script>

<script lang="ts">
	import { getContext, untrack } from 'svelte';
	import {
		ACESFilmicToneMapping,
		AmbientLight,
		DirectionalLight,
		Mesh,
		MeshStandardMaterial,
		type Object3D,
		OrthographicCamera,
		Quaternion,
		Scene,
		SphereGeometry,
		SRGBColorSpace,
		TextureLoader,
		Vector3,
		WebGLRenderer
	} from 'three';
	import { SilhouetteGlow } from './lineup-silhouette';
	import { makeLineupSunMaterial } from './lineup-sun';
	import { disposeGltf, fetchBundleMeta, modelLoader } from '$lib/scene/objects/body/model';
	import { lineupDrawsShapeModel } from '$lib/scene/objects/body/shape-model-policy';
	import { attachDisplacementMap } from '$lib/scene/objects/surface/displacement';
	import {
		applyShapeModelMaterial,
		makeShapeModelMaterial,
		setShapeModelMap,
		setSurfaceMap
	} from '$lib/scene/objects/body/model-texture';
	import {
		disposeCloudNode,
		loadCloudNode,
		type CloudMeta,
		type CloudNode
	} from '$lib/scene/objects/surface/clouds';
	import { BODY_COLORS, DEFAULT_BODY_COLOR, SUN_ID } from '$lib/constants';
	import { DATA_BASE, versionedUrl } from '$lib/fetch/data-base';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import { focusHref, isModifiedClick } from '$lib/state/focus-link';
	import { formatQuantity } from '$lib/format/quantities';
	import ChevronLeftIcon from '@lucide/svelte/icons/chevron-left';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import * as m from '$lib/paraglide/messages.js';

	interface Props {
		bodies: LineupBody[];
		ariaLabel: string;
		/** When set and there are more bodies than this, the lineup paginates:
		 *  ordered by size, sliced into pages of `perPage`, each page sized to its
		 *  own largest body. Omit for a single unpaginated row (e.g. planets). */
		perPage?: number;
	}
	let { bodies, ariaLabel, perPage }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');

	// Shared "north-west" viewing angle for every body, layered on top of each
	// body's real axial tilt. VIEW_PITCH tips the equator down (viewed from the
	// north); FACE_YAW spins the visible face about the pole.
	const DEG2RAD = Math.PI / 180;
	const ECLIPTIC_RAD = 23.4392911 * DEG2RAD;
	const VIEW_PITCH = 0.32;
	const FACE_YAW = 0;
	const AXIS_X = new Vector3(1, 0, 0);
	const AXIS_Y = new Vector3(0, 1, 0);
	const AXIS_Z = new Vector3(0, 0, 1);

	/** Obliquity of the spin axis to the ecliptic (radians), from the IAU pole. */
	function obliquityRad(raDeg: number, decDeg: number): number {
		const ra = raDeg * DEG2RAD;
		const dec = decDeg * DEG2RAD;
		const y = Math.cos(dec) * Math.sin(ra);
		const z = Math.sin(dec);
		const zEcl = -y * Math.sin(ECLIPTIC_RAD) + z * Math.cos(ECLIPTIC_RAD);
		return Math.acos(Math.max(-1, Math.min(1, zEcl)));
	}

	/** Sphere orientation for the NW view; +Y is the texture's north. Roll = the
	 *  body's real obliquity, so the visible tilt is true to the body. */
	function styledQuaternion(b: LineupBody): Quaternion {
		const roll = b.poleRa != null && b.poleDec != null ? obliquityRad(b.poleRa, b.poleDec) : 0;
		const q = new Quaternion().setFromAxisAngle(AXIS_Z, roll);
		q.multiply(new Quaternion().setFromAxisAngle(AXIS_X, VIEW_PITCH));
		q.multiply(new Quaternion().setFromAxisAngle(AXIS_Y, FACE_YAW));
		return q;
	}

	interface Body extends LineupBody {
		diameterKm: number;
	}
	let items = $derived<Body[]>(bodies.map((b) => ({ ...b, diameterKm: b.radiusKm * 2 })));

	// Largest → smallest. Pagination slices this, so each page is a size band that
	// (in `layout`) scales to its own largest body — small worlds aren't dwarfed
	// by giants on another page.
	let sorted = $derived<Body[]>([...items].sort((a, b) => b.diameterKm - a.diameterKm));
	let pageCount = $derived(perPage ? Math.max(1, Math.ceil(sorted.length / perPage)) : 1);
	let page = $state(0);
	// Clamp when the body set shrinks (switching collections) so a stale index
	// can't strand the view on an empty slice.
	$effect(() => {
		if (page > pageCount - 1) page = pageCount - 1;
	});
	let visibleItems = $derived.by<Body[]>(() => {
		if (!perPage) return sorted;
		const p = Math.min(page, pageCount - 1);
		return sorted.slice(p * perPage, p * perPage + perPage);
	});

	const HEIGHT = 204;
	// Ortho depth separation between stacked bodies — large enough that their
	// 3D geometry never intersects, invisible because the projection is ortho.
	const Z_STEP = 10000;
	let width = $state(0);
	let containerEl = $state<HTMLDivElement | null>(null);
	let hoveredId = $state<string | null>(null);

	// Hover-capable pointers get real <a> links + live hover; touch gets <button>
	// (no link callout on long-press) + a drag-to-scrub preview. Desktop-default
	// so SSR/first paint renders the link variant.
	let hoverCapable = $state(true);
	$effect(() => {
		const mq = window.matchMedia('(hover: hover)');
		const update = () => (hoverCapable = mq.matches);
		update();
		mq.addEventListener('change', update);
		return () => mq.removeEventListener('change', update);
	});

	// Touch scrub: distinguish a tap (focuses, via native button click) from a
	// drag (previews). We only start previewing past DRAG_SLOP so a tap stays a tap.
	const DRAG_SLOP = 8;
	let downX: number | null = null;
	let downY = 0;
	let scrubbing = false;

	interface LaidOut extends Body {
		pr: number; // sphere pixel radius
		cx: number; // center x (px, left origin)
		cy: number; // center y (px, top origin)
		colLeft: number;
		colWidth: number;
	}

	// Layout knobs (tune freely):
	const VPAD = 10; // equal margin above and below the largest body
	const SIDE_PAD = 6;

	let layout = $derived.by<LaidOut[]>(() => {
		if (!width || visibleItems.length === 0) return [];
		// Already largest → smallest; left → right (mockup order).
		const ordered = visibleItems;
		const raw = ordered.map((p) => p.diameterKm / 2);
		// Largest fits the height with equal top/bottom padding; true-linear from there.
		const k = (HEIGHT - 2 * VPAD) / 2 / raw[0];
		const prs = raw.map((r) => Math.max(2, r * k)); // floor so tiny worlds stay visible
		const n = ordered.length;
		// Constant center-to-center spacing, fit so the end spheres touch the pads.
		const step = n > 1 ? (width - prs[0] - prs[n - 1] - 2 * SIDE_PAD) / (n - 1) : 0;
		const baseline = HEIGHT - VPAD;
		const laid: LaidOut[] = ordered.map((p, i) => {
			const pr = prs[i];
			const cx = SIDE_PAD + prs[0] + i * step;
			return { ...p, pr, cx, cy: baseline - pr, colLeft: 0, colWidth: 0 };
		});
		// Hit columns span midpoint-to-midpoint so tiny bodies get a roomy target.
		for (let i = 0; i < laid.length; i++) {
			const left = i === 0 ? 0 : (laid[i - 1].cx + laid[i].cx) / 2;
			const right = i === laid.length - 1 ? width : (laid[i].cx + laid[i + 1].cx) / 2;
			laid[i].colLeft = left;
			laid[i].colWidth = right - left;
		}
		return laid;
	});

	let hovered = $derived(layout.find((p) => p.id === hoveredId) ?? null);

	// `w-max` + `max-width` sizes the box to its content, capped at the canvas:
	// auto width would shrink-to-fit the space right of `left` and squash it.
	// `tipLeft` then clamps the center so the whole box stays inside the canvas.
	const TIP_MARGIN = 6;
	let tipWidth = $state(0);
	let tipMaxWidth = $derived(Math.max(0, width - 2 * TIP_MARGIN));
	let tipLeft = $derived.by(() => {
		if (!hovered) return 0;
		const half = tipWidth / 2;
		return Math.min(Math.max(hovered.cx, half), Math.max(half, width - half));
	});

	/** Body under the cursor: a sphere it sits inside wins (front-most, i.e. the
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

	function goToPage(p: number) {
		const next = Math.min(Math.max(p, 0), pageCount - 1);
		if (next === page) return;
		page = next;
		hoveredId = null; // a hovered body from the old page would strand the glow
	}

	function focusBody(id: string) {
		if (!focusObject) return;
		const b = items.find((x) => x.id === id);
		focusObject(id, b?.name ?? id, { moveCamera: true });
	}

	function focusHovered(e: MouseEvent) {
		if (isModifiedClick(e) || !focusObject || !hoveredId) return;
		e.preventDefault();
		focusBody(hoveredId);
	}

	// Mouse: hover tracks the pointer directly. Touch/pen: preview only once a
	// drag passes DRAG_SLOP, so a tap (which fires the button's click → focus)
	// never flashes the spread/glow.
	function onPointerMove(e: PointerEvent) {
		if (e.pointerType === 'mouse') {
			hoveredId = pickAt(e.clientX, e.clientY);
			return;
		}
		if (downX === null) return;
		if (!scrubbing && Math.hypot(e.clientX - downX, e.clientY - downY) < DRAG_SLOP) return;
		scrubbing = true;
		hoveredId = pickAt(e.clientX, e.clientY);
	}

	function onPointerDown(e: PointerEvent) {
		downX = e.clientX;
		downY = e.clientY;
		scrubbing = false;
	}

	function endScrub() {
		if (scrubbing) hoveredId = null;
		downX = null;
		scrubbing = false;
	}

	// --- Three.js: a flat, orthographic, pixel-space lineup of textured spheres.
	let canvasEl = $state<HTMLCanvasElement | null>(null);
	let renderer: WebGLRenderer | undefined;
	let scene: Scene | undefined;
	let camera: OrthographicCamera | undefined;
	const geometry = new SphereGeometry(1, 48, 48);
	// Displacement needs the vertices to show relief — match the main map's top LOD.
	const dispGeometry = new SphereGeometry(1, 128, 128);
	const meshes = new Map<string, Mesh>();
	const cloudNodes = new Map<string, CloudNode>();

	// Shape-model members: the loaded GLB root replaces the placeholder sphere,
	// scaled px-per-km (pr / radiusKm) to match the spheres' true scale. A build
	// token discards loads that resolve after a page flip rebuilt the meshes.
	const modelRoots = new Map<string, Object3D>();
	let buildToken = 0;
	const displayObject = (id: string): Object3D | undefined => modelRoots.get(id) ?? meshes.get(id);

	// Hover spin: cache each body's base orientation so a frame is base · spin,
	// letting the hovered body turn about its own pole without losing its tilt.
	const HOVER_SPIN = Math.PI / 2;
	const baseQuats = new Map<string, Quaternion>();
	const spinAngles = new Map<string, number>();
	const spinQuat = new Quaternion();
	let spinAnimId: number | undefined;

	// Hover spread: an eased per-body x-offset layered over the static layout (so
	// hit-testing, on the base columns, is untouched — same trick as the spin).
	const HOVER_MARGIN_BASE = 20; // px floor, so a tiny hovered body still clears its neighbours
	const HOVER_MARGIN_FACTOR = 0.6; // + this × the hovered body's on-screen radius
	const HOVER_COMPRESS = 0.5; // the other gaps shrink to this fraction
	const bodyShift = new Map<string, number>();
	let shiftAnimId: number | undefined;

	// Hover halo: a rim glow that traces the hovered body's true silhouette (see
	// SilhouetteGlow). Sits at the body's depth so the buffer occludes it behind
	// nearer bodies and its own disc masks the rim's core.
	const GLOW_PX = 28;
	const GLOW_MAX = 0.55; // peak halo opacity
	let glowOpacity = 0;
	let glowAnimId: number | undefined;
	let silhouette: SilhouetteGlow | undefined;

	/** Cloud overlay: a child sphere inheriting the body's tilt + scale. Frame
	 *  ids can be live timestamps, so read the system meta rather than bake one.
	 *  Best-effort — clouds are optional. */
	async function loadClouds(bodyId: string, systemId: string, bodyMesh: Mesh) {
		try {
			const res = await fetch(`${DATA_BASE}/v1/systems/${systemId}.json`);
			if (!res.ok) return;
			const sys = await res.json();
			const meta: CloudMeta | undefined = sys[bodyId]?.clouds;
			if (!meta?.frames?.length) return;
			const frame = meta.frames[meta.frames.length - 1];
			if (meshes.get(bodyId) !== bodyMesh) return; // rebuilt while awaiting
			const node = await loadCloudNode(bodyMesh, 1, meta, frame);
			if (node) cloudNodes.set(bodyId, node);
			render();
		} catch {
			/* clouds are a nice-to-have */
		}
	}

	/** DEM relief on the lineup's unit sphere (radius 1 = equatorial `radiusKm`).
	 *  `absolute_radius` texels are radius-from-centre, so the shared bias drops
	 *  the unit sphere (−1) and the layout skips oblateness for those bodies. */
	function loadDisplacement(b: LineupBody, material: MeshStandardMaterial, loader: TextureLoader) {
		if (!b.displacement) return;
		attachDisplacementMap(material, b.displacement, 'low', loader, 1, 1 / b.radiusKm).then(
			(tex) => {
				if (tex) render();
			}
		);
	}

	function clearMeshes() {
		buildToken++; // discard any in-flight model load for the outgoing set
		baseQuats.clear();
		spinAngles.clear();
		bodyShift.clear();
		for (const node of cloudNodes.values()) disposeCloudNode(node);
		cloudNodes.clear();
		for (const mesh of meshes.values()) {
			scene?.remove(mesh);
			(mesh.material as MeshStandardMaterial).map?.dispose();
			(mesh.material as MeshStandardMaterial).displacementMap?.dispose();
			(mesh.material as MeshStandardMaterial).dispose();
		}
		meshes.clear();
		for (const root of modelRoots.values()) {
			scene?.remove(root);
			disposeGltf(root);
		}
		modelRoots.clear();
	}

	function buildMeshes() {
		if (!scene) return;
		clearMeshes();
		const loader = new TextureLoader();
		for (const b of visibleItems) {
			const color = b.color ?? BODY_COLORS[b.id] ?? DEFAULT_BODY_COLOR;
			// The Sun is self-luminous: unlit limb-darkened disc, no model/texture/relief.
			if (b.id === SUN_ID) {
				const mesh = new Mesh(geometry, makeLineupSunMaterial(color));
				baseQuats.set(b.id, styledQuaternion(b));
				mesh.quaternion.copy(baseQuats.get(b.id)!);
				scene.add(mesh);
				meshes.set(b.id, mesh);
				continue;
			}
			const material = new MeshStandardMaterial({ color, roughness: 1, metalness: 0 });
			const mesh = new Mesh(b.displacement ? dispGeometry : geometry, material);
			baseQuats.set(b.id, styledQuaternion(b));
			mesh.quaternion.copy(baseQuats.get(b.id)!);
			scene.add(mesh);
			meshes.set(b.id, mesh);
			// Shape-model members swap in the mesh (unless a DEM exists — the
			// textured relief sphere wins, matching the main scene). The
			// flat-colour sphere is the placeholder and the silent fallback.
			if (lineupDrawsShapeModel(b)) {
				loadModelMesh(b, color, buildToken, loader);
				continue;
			}
			if (b.texture !== false) {
				const url = versionedUrl(
					`/v1/textures/${b.id}/${b.surfaceFrame ? `low_${b.surfaceFrame}` : 'low'}.webp`,
					'textures'
				);
				loader.load(
					url,
					(tex) => {
						setSurfaceMap(material, tex, b.color);
						render();
					},
					undefined,
					() => {} // keep the flat color on failure
				);
			}
			if (b.displacement) loadDisplacement(b, material, loader);
			if (b.cloudSystem) loadClouds(b.id, b.cloudSystem, mesh);
		}
	}

	/** Load a member's shape-model mesh, tinted like the sphere, tilted by the
	 *  same base quaternion, and draped with the body's low-tier surface map
	 *  when one exists. On any failure the placeholder sphere is left in place. */
	async function loadModelMesh(b: Body, color: string, token: number, loader: TextureLoader) {
		if (!b.model) return;
		try {
			const meta = await fetchBundleMeta(b.model);
			// Guard against a spacecraft slug slipping through; those aren't lineup bodies.
			if (meta.kind !== 'shape_model' || !meta.true_scale) return;
			const tier = meta.tiers?.includes('low') ? 'low' : 'high';
			const gltf = await modelLoader.loadAsync(
				versionedUrl(`/v1/models/${b.model}/${tier}.glb`, 'models')
			);
			if (token !== buildToken || !scene) {
				disposeGltf(gltf.scene);
				return;
			}
			const root = gltf.scene;
			applyShapeModelMaterial(root, makeShapeModelMaterial(color));
			if (b.texture !== false) {
				loader.load(
					versionedUrl(`/v1/textures/${b.id}/low.webp`, 'textures'),
					(tex) => {
						if (token !== buildToken) return;
						tex.colorSpace = SRGBColorSpace;
						setShapeModelMap(root, tex, color, b.color);
						render();
					},
					undefined,
					() => {} // keep the tint when the surface map fails to load
				);
			}
			root.quaternion.copy(baseQuats.get(b.id) ?? new Quaternion());
			scene.add(root);
			modelRoots.set(b.id, root);
			meshes.get(b.id)?.removeFromParent(); // sphere placeholder no longer needed
			render();
		} catch {
			/* keep the sphere placeholder */
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
			const obj = displayObject(p.id);
			if (!obj) return;
			// Smaller bodies (later in `layout`) sit nearer the camera, so they render
			// on top of giants they overlap — easier to see and click. Huge depth gaps
			// avoid any 3D intersection, invisible under the orthographic projection.
			obj.position.set(p.cx + (bodyShift.get(p.id) ?? 0), HEIGHT - p.cy, -(n - 1 - i) * Z_STEP);
			const modelRoot = modelRoots.get(p.id);
			if (modelRoot) {
				// Uniform px-per-km: the mesh renders at the same true scale the
				// pr-sized spheres use (shape carries its own oblateness).
				modelRoot.scale.setScalar(p.pr / p.radiusKm);
			} else {
				// Non-uniform: flatten the polar (local +Y) axis for oblateness. Applied
				// in local space before the tilt quaternion, so it aligns with the pole.
				// absolute_radius bodies skip it — their displacement carries the shape.
				const polarY = p.displacement?.absolute_radius ? 1 : (p.polarRatio ?? 1);
				obj.scale.set(p.pr, p.pr * polarY, p.pr);
			}
			applySpin(obj, p.id);
		});
		updateGlow();
		animateSpin();
		animateShift();
		renderer.render(scene, camera);
	}

	/** base · spin(angle about the pole); identity-cheap at rest. */
	function applySpin(obj: Object3D, id: string) {
		const base = baseQuats.get(id);
		if (!base) return;
		const a = spinAngles.get(id) ?? 0;
		if (a === 0) {
			obj.quaternion.copy(base);
			return;
		}
		obj.quaternion.copy(base).multiply(spinQuat.setFromAxisAngle(AXIS_Y, a));
	}

	/** Ease each body's spin toward its target, ticking rAF only while in motion. */
	function animateSpin() {
		if (spinAnimId !== undefined) return;
		const spinTarget = (id: string) => (id === hoveredId ? HOVER_SPIN : 0);
		if (!layout.some((p) => (spinAngles.get(p.id) ?? 0) !== spinTarget(p.id))) return;
		const step = () => {
			spinAnimId = undefined;
			if (!renderer || !scene || !camera) return;
			let active = false;
			for (const p of layout) {
				const target = spinTarget(p.id);
				let a = spinAngles.get(p.id) ?? 0;
				a += (target - a) * 0.1;
				if (Math.abs(target - a) < 0.0005) a = target;
				spinAngles.set(p.id, a);
				const obj = displayObject(p.id);
				if (obj) applySpin(obj, p.id);
				if (a !== target) active = true;
			}
			updateGlow(); // a spinning model turns its silhouette — re-trace the rim
			renderer.render(scene, camera);
			if (active) spinAnimId = requestAnimationFrame(step);
		};
		spinAnimId = requestAnimationFrame(step);
	}

	/** Per-body x-offset for the current hover, built outward from the pinned
	 *  hovered body. Clamped to point *away* from it (left bodies never move
	 *  right and vice-versa) — drifting toward the hovered body looked wrong. */
	function shiftTargets(): Map<string, number> {
		const out = new Map<string, number>();
		for (const p of layout) out.set(p.id, 0);
		const n = layout.length;
		const h = hoveredId ? layout.findIndex((p) => p.id === hoveredId) : -1;
		if (h < 0 || n < 2) return out;
		const cxH = layout[h].cx;
		const margin = HOVER_MARGIN_BASE + HOVER_MARGIN_FACTOR * layout[h].pr;
		let x = cxH;
		for (let i = h - 1; i >= 0; i--) {
			const baseGap = layout[i + 1].cx - layout[i].cx;
			x -= i === h - 1 ? baseGap + margin : baseGap * HOVER_COMPRESS;
			out.set(layout[i].id, Math.min(0, x - layout[i].cx));
		}
		x = cxH;
		for (let i = h + 1; i < n; i++) {
			const baseGap = layout[i].cx - layout[i - 1].cx;
			x += i === h + 1 ? baseGap + margin : baseGap * HOVER_COMPRESS;
			out.set(layout[i].id, Math.max(0, x - layout[i].cx));
		}
		return out;
	}

	/** Ease each body toward its hover-spread offset, ticking rAF only in motion. */
	function animateShift() {
		if (shiftAnimId !== undefined) return;
		const settled = (t: Map<string, number>) =>
			layout.every((p) => Math.abs((bodyShift.get(p.id) ?? 0) - (t.get(p.id) ?? 0)) < 0.5);
		if (settled(shiftTargets())) return;
		const step = () => {
			shiftAnimId = undefined;
			if (!renderer || !scene || !camera) return;
			const targets = shiftTargets(); // recomputed live: hover can change mid-flight
			let active = false;
			for (const p of layout) {
				const target = targets.get(p.id) ?? 0;
				let s = bodyShift.get(p.id) ?? 0;
				s += (target - s) * 0.18;
				if (Math.abs(target - s) < 0.5) s = target;
				bodyShift.set(p.id, s);
				const obj = displayObject(p.id);
				if (obj) obj.position.x = p.cx + s;
				if (s !== target) active = true;
			}
			updateGlow(); // keep the halo on the hovered body as it eases into place
			renderer.render(scene, camera);
			if (active) shiftAnimId = requestAnimationFrame(step);
		};
		shiftAnimId = requestAnimationFrame(step);
	}

	function updateGlow() {
		if (!silhouette || !renderer || !scene) return;
		const i = hoveredId ? layout.findIndex((p) => p.id === hoveredId) : -1;
		if (i >= 0) {
			const p = layout[i];
			// Traces whatever mesh renders the body, so the rim gets the true
			// silhouette (lumps, tilt) for free, live at its animated x-position.
			const disp = displayObject(p.id);
			if (disp) {
				// Sits just behind the body (ε ≪ Z_STEP) so its own disc masks the
				// rim's core while nearer bodies still occlude it.
				const depth = -(layout.length - 1 - i) * Z_STEP;
				// White default when the body has no colour of its own.
				const tint = p.color ?? BODY_COLORS[p.id] ?? '#ffffff';
				silhouette.update(renderer, scene, disp, depth - (p.pr + 60), tint, glowOpacity);
			}
		}
		animateGlow();
	}

	/** Tween the halo toward its target opacity (GLOW_MAX when hovered, else 0),
	 *  driving an rAF loop only while in transition. The frozen rim just dims on
	 *  the way out, so no mask re-render is needed. */
	function animateGlow() {
		const target = hoveredId ? GLOW_MAX : 0;
		if (glowOpacity === target || glowAnimId !== undefined) return;
		const step = () => {
			glowAnimId = undefined;
			if (!silhouette || !renderer || !scene || !camera) return;
			const t = hoveredId ? GLOW_MAX : 0;
			glowOpacity += (t - glowOpacity) * 0.25;
			if (Math.abs(t - glowOpacity) < 0.01) glowOpacity = t;
			silhouette.setOpacity(glowOpacity);
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
		glowOpacity = 0;
		silhouette = new SilhouetteGlow(GLOW_PX);
		scene.add(silhouette.plane);
		return () => {
			if (glowAnimId !== undefined) cancelAnimationFrame(glowAnimId);
			glowAnimId = undefined;
			if (spinAnimId !== undefined) cancelAnimationFrame(spinAnimId);
			spinAnimId = undefined;
			if (shiftAnimId !== undefined) cancelAnimationFrame(shiftAnimId);
			shiftAnimId = undefined;
			clearMeshes();
			silhouette?.dispose();
			silhouette = undefined;
			renderer?.dispose();
			renderer = scene = camera = undefined;
		};
	});

	// Rebuilds meshes only when the visible set changes. The render is untracked
	// so this effect doesn't also subscribe to layout/hover/width — reading
	// those in render() would rebuild (and reload textures) on hover.
	$effect(() => {
		void visibleItems;
		buildMeshes();
		untrack(() => render());
	});
	$effect(() => {
		void layout;
		void hoveredId;
		render();
	});
</script>

<!-- Wrapper isn't clipped, so the hover tooltip can sit below the canvas. -->
<div class="relative w-full">
	<div
		bind:this={containerEl}
		bind:clientWidth={width}
		onpointerdown={onPointerDown}
		onpointermove={onPointerMove}
		onpointerup={endScrub}
		onpointercancel={endScrub}
		onpointerleave={() => {
			hoveredId = null;
			endScrub();
		}}
		class="bg-muted/30 relative w-full touch-pan-y overflow-hidden rounded-md"
		style="height: {HEIGHT}px"
		role="group"
		aria-label={ariaLabel}
	>
		<canvas bind:this={canvasEl} class="absolute inset-0 h-full w-full"></canvas>

		{#each layout as p (p.id)}
			<!-- Per-body hit column; hover is resolved by pickAt (mesh-priority), not
		     these columns. Hover-capable pointers get a real <a> (middle/⌘-click
		     opens the URL); touch gets a <button> so long-press shows no callout.
		     Mouse focus is suppressed — these columns can disagree with pickAt's
		     sphere-priority pick, so a mouse-focused link would flip the hover on
		     click. Keyboard focus still mirrors hover, unaffected by the guard. -->
			{#if hoverCapable}
				<a
					href={focusHref(appState, p.id, p.name)}
					onclick={focusHovered}
					onmousedown={(e) => e.button === 0 && e.preventDefault()}
					onfocus={(e) => e.currentTarget.matches(':focus-visible') && (hoveredId = p.id)}
					onblur={() => hoveredId === p.id && (hoveredId = null)}
					aria-label={p.name}
					class="pointer-events-auto absolute top-0 bottom-0 outline-none"
					style="left: {p.colLeft}px; width: {p.colWidth}px"
				></a>
			{:else}
				<button
					type="button"
					onclick={() => focusBody(p.id)}
					aria-label={p.name}
					class="pointer-events-auto absolute top-0 bottom-0 outline-none"
					style="left: {p.colLeft}px; width: {p.colWidth}px"
				></button>
			{/if}
		{/each}

		{#if pageCount > 1}
			<!-- Controls suppress body hover: stopPropagation stops the container
		     resolving a body under the cursor, pointerenter clears a lingering glow. -->
			<button
				type="button"
				onclick={() => goToPage(page - 1)}
				onpointerenter={() => (hoveredId = null)}
				onpointermove={(e) => e.stopPropagation()}
				aria-disabled={page === 0}
				aria-label={m.search_prev_page()}
				class="bg-background/70 text-foreground/80 pointer-events-auto absolute top-1/2 left-1 z-20 -translate-y-1/2 rounded-full p-1 shadow-sm backdrop-blur-sm transition {page ===
				0
					? 'cursor-default opacity-30'
					: 'hover:bg-background'}"
			>
				<ChevronLeftIcon size={18} />
			</button>
			<button
				type="button"
				onclick={() => goToPage(page + 1)}
				onpointerenter={() => (hoveredId = null)}
				onpointermove={(e) => e.stopPropagation()}
				aria-disabled={page === pageCount - 1}
				aria-label={m.search_next_page()}
				class="bg-background/70 text-foreground/80 pointer-events-auto absolute top-1/2 right-1 z-20 -translate-y-1/2 rounded-full p-1 shadow-sm backdrop-blur-sm transition {page ===
				pageCount - 1
					? 'cursor-default opacity-30'
					: 'hover:bg-background'}"
			>
				<ChevronRightIcon size={18} />
			</button>
			<div
				role="group"
				aria-label={ariaLabel}
				onpointerenter={() => (hoveredId = null)}
				onpointermove={(e) => e.stopPropagation()}
				class="pointer-events-auto absolute bottom-2 left-1/2 z-20 flex -translate-x-1/2 gap-1.5"
			>
				{#each Array.from({ length: pageCount }).map((_x, i) => i) as i (i)}
					<button
						type="button"
						onclick={() => goToPage(i)}
						aria-label={m.pagination_go_to_page({ n: i + 1 })}
						aria-current={i === page}
						class="h-1.5 w-1.5 rounded-full transition {i === page
							? 'bg-foreground/80'
							: 'bg-foreground/30 hover:bg-foreground/50'}"
					></button>
				{/each}
			</div>
		{/if}
	</div>

	{#if hovered}
		<!-- Offset below the canvas so it never covers the bodies. -->
		<div
			bind:clientWidth={tipWidth}
			class="bg-popover text-popover-foreground border-border pointer-events-none absolute z-10 w-max -translate-x-1/2 rounded-md border px-2 py-1 text-center shadow-md"
			style="left: {tipLeft}px; top: {HEIGHT +
				6}px; max-width: {tipMaxWidth}px; visibility: {tipWidth === 0 ? 'hidden' : 'visible'}"
		>
			<div class="text-xs font-medium whitespace-nowrap">{hovered.name}</div>
			{#if hovered.description}
				<div class="text-muted-foreground text-[11px]">{hovered.description}</div>
			{/if}
			<div class="text-muted-foreground text-[11px] tabular-nums">
				{m.diameter()}: {formatQuantity({ value: hovered.diameterKm, unit: 'kilometre' }, true)}
			</div>
		</div>
	{/if}
</div>
