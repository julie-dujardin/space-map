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
		/** Model bundle slug (`v1/models/<slug>/`); loads the mesh in place of the
		 *  sphere, sized/tilted to match. Falls back to the sphere on any failure. */
		model?: string;
		/** A spacecraft: `model` is the craft itself, so there is no sphere under
		 *  it and no surface to texture, and `radiusKm` is half the craft's real
		 *  body length rather than a measured body radius. */
		craft?: boolean;
		/** Craft only: the mesh's full span ÷ the body `radiusKm` sizes the slot
		 *  on. Above 1 where the model draws booms or antennas, which then
		 *  overhang the slot instead of shrinking the craft. Default 1. */
		meshSpanRatio?: number;
		/** Whether a `v1/textures/<id>/` surface map exists. Explicit `false`
		 *  skips the fetch entirely; absent (pre-flag export) probes as before. */
		texture?: boolean;
		/** Not a member of the row, but a neighbouring size band's body drawn at
		 *  the row's own scale against one edge — the step in scale, shown rather
		 *  than stated. It takes no slot, no name and no hover. */
		aside?: 'start' | 'end';
	}
</script>

<script lang="ts">
	import { getContext, untrack } from 'svelte';
	import {
		ACESFilmicToneMapping,
		AmbientLight,
		Box3,
		DirectionalLight,
		Group,
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
	import {
		cheapTier,
		craftTier,
		disposeGltf,
		fetchBundleMeta,
		modelLoader
	} from '$lib/scene/objects/body/model';
	import { lineupDrawsShapeModel } from '$lib/scene/objects/body/shape-model-policy';
	import { attachDisplacementMap } from '$lib/scene/objects/surface/displacement';
	import {
		attachSelfShadowToBody,
		type SelfShadowUniforms
	} from '$lib/scene/objects/surface/self-shadow';
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
	import { makeEnvMap } from '$lib/scene/lighting';
	import { frameMapQuaternion } from '$lib/math/orientation';
	import { BODY_COLORS, DEFAULT_BODY_COLOR, SUN_ID } from '$lib/constants';
	import { dataBase, versionedUrl } from '$lib/fetch/data-base';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import { focusHref } from '$lib/state/focus-link';
	import { bodyHref } from '$lib/state/url';
	import { isModifiedClick } from '$lib/modified-click';
	import { createScrub } from '$lib/charts/scrub';
	import { formatQuantity } from '$lib/format/quantities';
	import ChevronLeftIcon from '@lucide/svelte/icons/chevron-left';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import * as m from '$lib/paraglide/messages.js';

	/** The strip height a drawer row uses. */
	const DEFAULT_HEIGHT = 204;

	interface Props {
		bodies: LineupBody[];
		ariaLabel: string;
		/** When set and there are more bodies than this, the lineup paginates:
		 *  ordered by size, sliced into pages of `perPage`, each page sized to its
		 *  own largest body. Omit for a single unpaginated row (e.g. planets). */
		perPage?: number;
		/** Canvas height in px. The default suits a row inside the drawer; a page
		 *  that gives the lineup a stage of its own passes more. */
		height?: number;
		/** Give every body its own box, side by side, the way a craft row already
		 *  lays out. Meshes that overlap read as one object rather than several. */
		boxed?: boolean;
		/** Name and size under each body, in place of the hover tooltip — for a
		 *  lineup that is the page rather than a strip beside its own list. */
		labels?: boolean;
		/** Where each body ended up, reported whenever the row is laid out. The
		 *  scale it is drawn on (px per km) is `pr / radiusKm` on any of them,
		 *  which is what a scale bar or a body drawn beside the row needs. */
		onlayout?: (
			bodies: {
				id: string;
				cx: number;
				cy: number;
				pr: number;
				radiusKm: number;
				aside?: 'start' | 'end';
			}[]
		) => void;
		/** Right click on a body, for a caller that opens its own menu. The
		 *  default menu is suppressed only when a body is actually under the
		 *  pointer. */
		oncontextpick?: (id: string, clientX: number, clientY: number) => void;
		/** The row's own ground. Defaults to the drawer's faint panel; a page
		 *  that supplies its own sky passes a colour (or `transparent`). */
		ground?: string;
		/** Whether hovering a body pushes its neighbours aside. The drawer's
		 *  strip needs it to get at a crowded body; a row with room does not. */
		spread?: boolean;
	}
	let {
		bodies,
		ariaLabel,
		perPage,
		height = DEFAULT_HEIGHT,
		boxed = false,
		labels = false,
		onlayout,
		oncontextpick,
		ground,
		spread = true
	}: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');

	// Shared "north-west" viewing angle for every body, layered on top of each
	// body's real axial tilt. VIEW_PITCH tips the equator down (viewed from the
	// north); FACE_YAW spins the visible face about the pole.
	const DEG2RAD = Math.PI / 180;
	const ECLIPTIC_RAD = 23.4392911 * DEG2RAD;
	const VIEW_PITCH = 0.32;
	const FACE_YAW = 0;
	// Craft have no pole to tilt on, so their pose is pure staging: a
	// three-quarter view that reads a bus and its booms as one shape.
	const CRAFT_VIEW_PITCH = 0.24;
	const CRAFT_VIEW_YAW = -0.7;
	// The row's key light, shared by the DirectionalLight and the relief shader
	// (which needs the same direction to shade and shadow the height field).
	const KEY_LIGHT_DIR = { value: new Vector3(-0.4, 0.45, 1).normalize() };
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
		if (b.craft) {
			const q = new Quaternion().setFromAxisAngle(AXIS_X, CRAFT_VIEW_PITCH);
			return q.multiply(new Quaternion().setFromAxisAngle(AXIS_Y, CRAFT_VIEW_YAW));
		}
		const roll = b.poleRa != null && b.poleDec != null ? obliquityRad(b.poleRa, b.poleDec) : 0;
		const q = new Quaternion().setFromAxisAngle(AXIS_Z, roll);
		q.multiply(new Quaternion().setFromAxisAngle(AXIS_X, VIEW_PITCH));
		q.multiply(new Quaternion().setFromAxisAngle(AXIS_Y, FACE_YAW));
		return q;
	}

	interface Body extends LineupBody {
		diameterKm: number;
	}
	const sized = (b: LineupBody): Body => ({ ...b, diameterKm: b.radiusKm * 2 });
	let items = $derived<Body[]>(bodies.filter((b) => !b.aside).map(sized));
	// A neighbouring band is fitted to its strip by the vertices it draws, and
	// relief is applied in the shader where that fit cannot see it — so the one
	// place it is dropped is here, where a few pixels of misfit is the whole
	// body missing the screen.
	let asides = $derived<Body[]>(
		bodies.filter((b) => b.aside).map((b) => sized({ ...b, displacement: undefined }))
	);

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

	// Enough room reflection to model a craft's foil and panels without washing
	// out the key light's shading. Craft rows only — see setRoomEnvironment.
	const CRAFT_ENV_INTENSITY = 0.45;

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

	interface LaidOut extends Body {
		pr: number; // sphere pixel radius
		cx: number; // center x (px, left origin)
		cy: number; // center y (px, top origin)
		colLeft: number;
		colWidth: number;
		/** Room a name has under the body without reaching its neighbour's. */
		labelWidth: number;
	}

	// Layout knobs (tune freely):
	const VPAD = 10; // equal margin above and below the largest body
	const SIDE_PAD = 6;
	const CRAFT_GAP = 8; // clear air between neighbouring craft boxes
	// A craft fills its box to the edge, so a paginated row must keep clear of the
	// page chevrons; spheres taper away from them on their own.
	const CHEVRON_PAD = 26;
	// Labels are laid left to right and each takes what the one before it left,
	// up to the cap; a body with less than the floor goes unnamed rather than
	// overlapping its neighbour. The caller's own list names every one of them.
	const LABEL_MIN_WIDTH = 44;
	const LABEL_MAX_WIDTH = 180;
	// Edge room for a neighbouring band: the band before it gets this share of
	// the row, the same on every page so it reads as an edge rather than as a
	// body of its own; the band after needs only its own width.
	const LIMB_SHARE = 0.065;
	const LIMB_MIN = 44;
	const LIMB_MAX = 120;
	const ASIDE_END_PAD = 44;
	const ASIDE_MAX_PR = 20000;
	/** The strip at the start of the row given to the band before it. */
	const limbStrip = (w: number) => Math.max(LIMB_MIN, Math.min(LIMB_MAX, w * LIMB_SHARE));

	let layout = $derived.by<LaidOut[]>(() => {
		if (!width || visibleItems.length === 0) return [];
		// Already largest → smallest; left → right (mockup order).
		const ordered = visibleItems;
		const raw = ordered.map((p) => p.diameterKm / 2);
		const n = ordered.length;
		// Largest fits the height with equal top/bottom padding; true-linear from there.
		const heightK = (height - 2 * VPAD) / 2 / raw[0];
		// Overlapping discs still read as discs, so spheres take the height and
		// crowd. A craft's mesh is its own silhouette — two of them overlapping
		// read as one machine — so the row must fit them side by side as well,
		// on the one scale that keeps the comparison honest.
		const boxRow = boxed || ordered.some((p) => p.craft);
		const sidePad = pageCount > 1 ? CHEVRON_PAD : SIDE_PAD;
		const padStart = asides.some((a) => a.aside === 'start') ? limbStrip(width) : 0;
		const padEnd = asides.some((a) => a.aside === 'end') ? ASIDE_END_PAD : 0;
		const boxes = raw.reduce((a, r) => a + 2 * r, 0);
		const boxRun0 = width - 2 * sidePad - padStart - padEnd;
		const k = boxRow ? Math.min(heightK, (boxRun0 - (n - 1) * CRAFT_GAP) / boxes) : heightK;
		const prs = raw.map((r) => Math.max(2, r * k)); // floor so tiny worlds stay visible
		// Craft sit in their own boxes end to end, centred in the row; spheres get
		// a constant centre-to-centre step, fit so the end ones touch the pads.
		const spanLeft = SIDE_PAD + padStart;
		const spanWidth = width - 2 * SIDE_PAD - padStart - padEnd;
		const step = n > 1 ? (spanWidth - prs[0] - prs[n - 1]) / (n - 1) : 0;
		const boxRun = prs.reduce((a, pr) => a + 2 * pr, 0) + (n - 1) * CRAFT_GAP;
		let boxX = sidePad + padStart + (boxRun0 - boxRun) / 2;
		const baseline = height - VPAD;
		const laid: LaidOut[] = ordered.map((p, i) => {
			const pr = prs[i];
			let cx: number;
			if (boxRow) {
				cx = boxX + pr;
				boxX += 2 * pr + CRAFT_GAP;
			} else {
				cx = spanLeft + prs[0] + i * step;
			}
			// A sphere stands on the row's baseline; a craft has no ground to stand
			// on, and the width fit leaves it well short of the height, so it reads
			// better centred than sunk to the floor.
			return {
				...p,
				pr,
				cx,
				cy: boxRow ? height / 2 : baseline - pr,
				colLeft: 0,
				colWidth: 0,
				labelWidth: 0
			};
		});
		// Hit columns span midpoint-to-midpoint so tiny bodies get a roomy target.
		for (let i = 0; i < laid.length; i++) {
			const left = i === 0 ? 0 : (laid[i - 1].cx + laid[i].cx) / 2;
			const right = i === laid.length - 1 ? width : (laid[i].cx + laid[i + 1].cx) / 2;
			laid[i].colLeft = left;
			laid[i].colWidth = right - left;
		}
		// Names, left to right: each is centred on its body and takes what the
		// last one left, so a crowd of small bodies loses its names rather than
		// piling them on top of each other.
		let taken = 0;
		for (const p of laid) {
			const half = Math.min(LABEL_MAX_WIDTH / 2, p.cx - taken, width - p.cx);
			if (half * 2 < LABEL_MIN_WIDTH) continue;
			p.labelWidth = half * 2;
			taken = p.cx + half;
		}
		return laid;
	});

	/** A neighbouring band's body, on this row's scale: the one before it drawn
	 *  against the start edge, where only its limb fits, and the one after it as
	 *  the speck it really is at the end. */
	let asideLayout = $derived.by<LaidOut[]>(() => {
		if (!width || layout.length === 0 || asides.length === 0) return [];
		const k = layout[0].pr / layout[0].radiusKm;
		return asides.map((b) => {
			// Past a few screens across, the limb is a straight edge and more size
			// changes nothing on screen — while the real number runs into the
			// millions of pixels, where float precision and the frustum give out.
			const pr = Math.min(ASIDE_MAX_PR, Math.max(2, (b.diameterKm / 2) * k));
			// The one before runs off the edge, showing whatever limb fits; the one
			// after sits in the middle of its own gutter, where the caller has room
			// to mark it — at true size it is a few pixels across.
			const cx =
				b.aside === 'start'
					? Math.min(limbStrip(width) - SIDE_PAD, pr) - pr
					: width - SIDE_PAD - ASIDE_END_PAD / 2;
			return { ...b, pr, cx, cy: height / 2, colLeft: 0, colWidth: 0, labelWidth: 0 };
		});
	});

	/** Everything with a mesh: the row, plus the bands on either side of it. */
	let drawn = $derived<Body[]>([...visibleItems, ...asides]);

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

	/** How big the body is, in the unit its class is read in: a craft's span in
	 *  metres, a body's diameter in kilometres. A craft is quoted across the
	 *  whole mesh, booms included, which is what the row draws — its slot is the
	 *  narrower body. */
	function sizeText(b: Body): string {
		return b.craft
			? formatQuantity({ value: b.diameterKm * (b.meshSpanRatio ?? 1) * 1000, unit: 'metre' }, true)
			: formatQuantity({ value: b.diameterKm, unit: 'kilometre' }, true);
	}

	const scrub = createScrub({
		onScrub: (clientX, clientY) => (hoveredId = pickAt(clientX, clientY)),
		onEnd: () => (hoveredId = null)
	});

	// Mouse hover tracks the pointer directly; touch/pen goes through the scrub
	// gesture so a tap (which fires the button's click → focus) never flashes the
	// spread/glow.
	function onPointerMove(e: PointerEvent) {
		if (e.pointerType === 'mouse') {
			hoveredId = pickAt(e.clientX, e.clientY);
			return;
		}
		scrub.onpointermove(e);
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
	/** The pose and place a neighbouring band had to take to show itself; see
	 *  showAside. */
	const asideFit = new Map<string, { mark: string; roll: number; dx: number; dy: number }>();
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
			const res = await fetch(`${dataBase()}/v1/systems/${systemId}.json`);
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
	 *  the unit sphere (−1) and the layout skips oblateness for those bodies.
	 *
	 *  Vertex displacement alone leaves the sphere's own normals, so a lumpy body
	 *  still shades as a smooth ellipsoid beside the shape models. The same
	 *  height-gradient relief + self-shadow pass the main map runs gives it the
	 *  geometry's shading instead. */
	function loadDisplacement(b: LineupBody, material: MeshStandardMaterial, loader: TextureLoader) {
		if (!b.displacement) return;
		attachDisplacementMap(material, b.displacement, 'low', loader, 1, 1 / b.radiusKm).then(
			(tex) => {
				if (!tex) return;
				// Slopes are measured against the mesh's world radius, which `place`
				// sets in row pixels — so is this, and it follows the scale there.
				attachSelfShadowToBody(material, tex, material.displacementScale, KEY_LIGHT_DIR);
				render();
			}
		);
	}

	function clearMeshes() {
		buildToken++; // discard any in-flight model load for the outgoing set
		asideFit.clear();
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

	/** Room reflections belong to craft rows only: they carry a spacecraft's
	 *  metal, but on a sphere they would wash out the albedo the surface maps are
	 *  tuned against. One instance survives paging within a craft lineup. */
	function setRoomEnvironment(wanted: boolean) {
		if (!scene || !renderer) return;
		if (wanted && !scene.environment) {
			scene.environment = makeEnvMap(renderer);
			scene.environmentIntensity = CRAFT_ENV_INTENSITY;
		} else if (!wanted && scene.environment) {
			scene.environment.dispose();
			scene.environment = null;
		}
	}

	function buildMeshes() {
		if (!scene) return;
		clearMeshes();
		setRoomEnvironment(drawn.some((b) => b.craft));
		const loader = new TextureLoader();
		for (const b of drawn) {
			// A craft is only ever its mesh: nothing stands in while it loads, and
			// nothing is left behind if it fails.
			if (b.craft) {
				baseQuats.set(b.id, styledQuaternion(b));
				loadCraftMesh(b, buildToken);
				continue;
			}
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

	/** Load a spacecraft member's mesh, keeping the bundle's own materials — a
	 *  craft's colour is its foil and panels, not a body tint. The mesh is
	 *  normalised to unit radius inside a wrapper the view pose turns, so
	 *  `render` scales that wrapper straight to the member's pixel size. */
	async function loadCraftMesh(b: Body, token: number) {
		if (!b.model) return;
		try {
			const meta = await fetchBundleMeta(b.model);
			const gltf = await modelLoader.loadAsync(
				versionedUrl(`/v1/models/${b.model}/${craftTier(meta)}.glb`, 'models')
			);
			if (token !== buildToken || !scene || !renderer) {
				disposeGltf(gltf.scene);
				return;
			}
			// The bundle's frame map is the model's own authoring convention, so it
			// applies under the shared view pose — the order the scene uses too.
			const baseFrame = meta.frame_map ? frameMapQuaternion(meta.frame_map) : null;
			if (baseFrame) gltf.scene.quaternion.copy(baseFrame);
			const fitted = new Group();
			fitted.add(gltf.scene);
			const anchor = meta.model_anchor ? new Vector3(...meta.model_anchor) : null;
			fitUnitRadius(fitted, anchor && baseFrame ? anchor.applyQuaternion(baseFrame) : anchor);
			const root = new Group();
			root.quaternion.copy(baseQuats.get(b.id) ?? new Quaternion());
			root.add(fitted);
			scene.add(root);
			modelRoots.set(b.id, root);
			render();
		} catch {
			/* a craft with no usable mesh simply isn't drawn */
		}
	}

	/** Scale + recentre `group`'s contents so its bounding box spans 2 units on
	 *  its longest axis, origin at the craft body (`anchor`) or else the box
	 *  centre — the same normalisation the main scene applies, so `scale_meters`
	 *  means the same thing in both. */
	function fitUnitRadius(group: Group, anchor: Vector3 | null = null): void {
		group.updateMatrixWorld(true);
		// Precise, for the reason the scene's fitToUnitRadius gives.
		const bbox = new Box3().setFromObject(group, true);
		const maxDim = Math.max(...bbox.getSize(new Vector3()).toArray());
		if (maxDim <= 0) return;
		const k = 2 / maxDim;
		const centre = bbox.getCenter(new Vector3());
		if (anchor) centre.addScaledVector(anchor, maxDim / 2);
		group.scale.setScalar(k);
		group.position.copy(centre).multiplyScalar(-k);
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
			const gltf = await modelLoader.loadAsync(
				versionedUrl(`/v1/models/${b.model}/${cheapTier(meta)}.glb`, 'models')
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
		renderer.setSize(width, height, false);
		camera.left = 0;
		camera.right = width;
		camera.top = height;
		camera.bottom = 0;
		// A sphere is as deep as it is wide, and the band before this one can be
		// drawn thousands of screens across: clip to whatever is actually here,
		// or it falls outside the frustum and vanishes.
		const reach = Math.max(
			1e6,
			2 *
				([...layout, ...asideLayout].reduce((a, p) => Math.max(a, p.pr), 0) +
					layout.length * Z_STEP)
		);
		camera.near = -reach;
		camera.far = reach;
		camera.updateProjectionMatrix();
		const n = layout.length;
		// Smaller bodies (later in `layout`) sit nearer the camera, so they render
		// on top of giants they overlap — easier to see and click. Huge depth gaps
		// avoid any 3D intersection, invisible under the orthographic projection.
		layout.forEach((p, i) => place(p, -(n - 1 - i) * Z_STEP, bodyShift.get(p.id) ?? 0));
		// The neighbouring bands sit behind every one of them.
		asideLayout.forEach((p) => {
			place(p, -n * Z_STEP, 0);
			showAside(p);
		});
		updateGlow();
		animateSpin();
		animateShift();
		draw();
	}

	function draw() {
		if (renderer && scene && camera) renderer.render(scene, camera);
	}

	/** Put one body where the layout says, at the given depth and on the row's
	 *  scale. */
	function place(p: LaidOut, z: number, shift: number) {
		const obj = displayObject(p.id);
		if (!obj) return;
		obj.position.set(p.cx + shift, height - p.cy, z);
		const modelRoot = modelRoots.get(p.id);
		if (modelRoot) {
			// Uniform px per real unit: a shape model carries true km, a craft's
			// wrapper is already normalised to the unit radius `pr` measures —
			// grown back to the mesh's full span, which reaches past the body
			// the slot was sized on.
			modelRoot.scale.setScalar(p.craft ? p.pr * (p.meshSpanRatio ?? 1) : p.pr / p.radiusKm);
		} else {
			// Non-uniform: flatten the polar (local +Y) axis for oblateness. Applied
			// in local space before the tilt quaternion, so it aligns with the pole.
			// absolute_radius bodies skip it — their displacement carries the shape.
			const polarY = p.displacement?.absolute_radius ? 1 : (p.polarRatio ?? 1);
			obj.scale.set(p.pr, p.pr * polarY, p.pr);
			// The relief shader measures slopes against the world radius the scale
			// above just set, so its height scale is the local one times that.
			const material = (obj as Mesh).material as MeshStandardMaterial;
			const relief = material.userData.selfShadow as SelfShadowUniforms | undefined;
			if (relief) relief.uSelfScale.value = material.displacementScale * p.pr;
		}
		applySpin(obj, p.id);
	}

	/** How much of its own surface a neighbouring band shows, as light: the row
	 *  is lit from the left, and the band before it is on screen only by the
	 *  limb turned away from that, which comes out black. */
	const ASIDE_EMISSIVE = 0.35;

	/** Poses tried for the band before this one, and how many of its own
	 *  vertices are read to try them. */
	const LIMB_ROLLS = 12;
	const LIMB_SAMPLES = 1500;
	const rollQuat = new Quaternion();

	/** What is drawn, sampled in row pixels about the object's own origin. The
	 *  projection is orthographic down −z, so x and y are already the screen. */
	function asideSamples(obj: Object3D): number[] {
		const pts: number[] = [];
		obj.updateWorldMatrix(true, true);
		const v = new Vector3();
		const { x: ox, y: oy } = obj.position;
		obj.traverse((o) => {
			if (!(o instanceof Mesh)) return;
			const pos = o.geometry?.attributes?.position;
			if (!pos) return;
			const stride = Math.max(1, Math.floor(pos.count / LIMB_SAMPLES));
			for (let i = 0; i < pos.count; i += stride) {
				v.fromBufferAttribute(pos, i).applyMatrix4(o.matrixWorld);
				pts.push(v.x - ox, v.y - oy);
			}
		});
		return pts;
	}

	/**
	 * The pose that fills the strip: a body meets it edge-on at one roll and
	 * broadside at another, and only the second says anything about its size.
	 * Rolled about the view axis, so the face it shows is still its own —
	 * `strip` is the width it has to fill, `right` where its outermost surface
	 * goes, both in row pixels about the object's origin.
	 */
	function fitLimb(pts: number[], strip: number, right: number) {
		let best = { roll: 0, dx: 0, dy: 0, shown: -1 };
		for (let step = 0; step < LIMB_ROLLS; step++) {
			const roll = (step * Math.PI) / LIMB_ROLLS;
			const cos = Math.cos(roll);
			const sin = Math.sin(roll);
			let far = -Infinity;
			for (let i = 0; i < pts.length; i += 2) {
				const x = pts[i] * cos - pts[i + 1] * sin;
				if (x > far) far = x;
			}
			let top = Infinity;
			let bottom = -Infinity;
			for (let i = 0; i < pts.length; i += 2) {
				if (pts[i] * cos - pts[i + 1] * sin < far - strip) continue;
				const y = pts[i] * sin + pts[i + 1] * cos;
				if (y < top) top = y;
				if (y > bottom) bottom = y;
			}
			// Past the row's own height there is nothing left to win, so the
			// squarest pose that fills it wins on the +1 rather than on a sliver.
			const shown = Math.min(bottom - top, height);
			if (shown > best.shown + 1) {
				best = { roll, dx: right - far, dy: -(top + bottom) / 2, shown };
			}
		}
		return best;
	}

	/**
	 * Place a neighbouring band by what it actually draws, not by the sphere its
	 * size implies: a shape model's mesh sits where its own origin puts it, and
	 * presents whatever it happens to present, which for a body drawn as a strip
	 * at the edge decides whether any of it lands on screen at all. Its surface
	 * lights itself, at the same time, for the same reason — nothing else here
	 * can reach it.
	 */
	function showAside(p: LaidOut) {
		const obj = displayObject(p.id);
		if (!obj) return;
		// Kept until the scale changes or the mesh itself is swapped in.
		const mark = `${Math.round(p.cx)}:${Math.round(p.pr)}:${modelRoots.has(p.id) ? 'mesh' : 'sphere'}`;
		let fit = asideFit.get(p.id);
		if (fit?.mark !== mark) {
			if (p.aside === 'start') {
				const { roll, dx, dy } = fitLimb(asideSamples(obj), p.cx + p.pr, p.pr);
				fit = { mark, roll, dx, dy };
			} else {
				// The band after is a speck: it only has to sit on its mark.
				const box = new Box3().setFromObject(obj, true);
				fit = box.isEmpty()
					? { mark, roll: 0, dx: 0, dy: 0 }
					: {
							mark,
							roll: 0,
							dx: p.cx - (box.min.x + box.max.x) / 2,
							dy: height - p.cy - (box.min.y + box.max.y) / 2
						};
			}
			asideFit.set(p.id, fit);
		}
		if (fit.roll) obj.quaternion.premultiply(rollQuat.setFromAxisAngle(AXIS_Z, fit.roll));
		obj.position.x += fit.dx;
		obj.position.y += fit.dy;
		obj.traverse((o) => {
			const mat = (o as Mesh).material as MeshStandardMaterial | undefined;
			if (!mat?.isMeshStandardMaterial) return;
			if (mat.emissiveIntensity !== ASIDE_EMISSIVE) {
				mat.emissive.copy(mat.color);
				mat.emissiveIntensity = ASIDE_EMISSIVE;
			}
			// The surface map arrives later; the glow has to carry it too, or the
			// body reads as a flat cut-out.
			if (mat.map && mat.emissiveMap !== mat.map) {
				mat.emissive.setRGB(1, 1, 1);
				mat.emissiveMap = mat.map;
				mat.needsUpdate = true;
			}
		});
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
			draw();
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
		const h = spread && hoveredId ? layout.findIndex((p) => p.id === hoveredId) : -1;
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
			draw();
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
			draw();
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
		// Frustum is fixed up per-render from `width` and `height`; don't read
		// either here, or this setup effect would re-run and orphan the meshes on
		// every resize. Deep
		// near/far range so the z-separated spheres (see Z_STEP) all stay in view.
		camera = new OrthographicCamera(0, 1, 1, 0, -1e6, 1e6);
		camera.position.z = 10;
		const key = new DirectionalLight(0xffffff, 3.1);
		key.position.copy(KEY_LIGHT_DIR.value);
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
			// PMREM output belongs to this renderer; it can't outlive the context.
			scene?.environment?.dispose();
			silhouette?.dispose();
			silhouette = undefined;
			// Safe across effect re-runs: three re-uploads a disposed geometry's
			// buffers on the next render.
			geometry.dispose();
			dispGeometry.dispose();
			// dispose() alone leaves the GL context alive until GC; the browser
			// caps live contexts (~16) and force-drops the oldest.
			renderer?.forceContextLoss();
			renderer?.dispose();
			renderer = scene = camera = undefined;
		};
	});

	// Rebuilds meshes only when the visible set changes. The render is untracked
	// so this effect doesn't also subscribe to layout/hover/width — reading
	// those in render() would rebuild (and reload textures) on hover.
	$effect(() => {
		void drawn;
		buildMeshes();
		untrack(() => render());
	});
	$effect(() => {
		void layout;
		void asideLayout;
		void hoveredId;
		render();
	});
	$effect(() => {
		const laid = [...layout, ...asideLayout].map((p) => ({
			id: p.id,
			cx: p.cx,
			cy: p.cy,
			pr: p.pr,
			radiusKm: p.radiusKm,
			aside: p.aside
		}));
		untrack(() => onlayout?.(laid));
	});
</script>

<!-- Wrapper isn't clipped, so the hover tooltip can sit below the canvas. -->
<div class="relative w-full">
	<div
		bind:this={containerEl}
		bind:clientWidth={width}
		oncontextmenu={(e) => {
			const id = pickAt(e.clientX, e.clientY);
			if (!id || !oncontextpick) return;
			e.preventDefault();
			oncontextpick(id, e.clientX, e.clientY);
		}}
		onpointerdown={scrub.onpointerdown}
		onpointermove={onPointerMove}
		onpointerup={scrub.onpointerup}
		onpointercancel={scrub.onpointercancel}
		onpointerleave={() => {
			hoveredId = null;
			scrub.onpointerleave();
		}}
		class="relative w-full touch-pan-y overflow-hidden rounded-md {ground ? '' : 'bg-muted/30'}"
		style="height: {height}px; {ground ? `background: ${ground}` : ''}"
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
					href={focusHref(appState, p.id, p.name) ?? bodyHref(p.id, p.name)}
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

	{#if labels}
		<!-- The name sits under the body it belongs to. One left unnamed by the
		     declutter is still named by hovering it, and by the caller's list. -->
		<div class="relative h-9" aria-hidden="true">
			{#each layout as p (p.id)}
				{#if p.labelWidth >= LABEL_MIN_WIDTH}
					<div
						class="absolute top-1.5 -translate-x-1/2 text-center leading-tight"
						style="left: {p.cx}px; max-width: {p.labelWidth}px"
					>
						<div class="truncate text-[11px] font-medium">{p.name}</div>
						<div class="truncate text-[11px] text-muted-foreground tabular-nums">
							{sizeText(p)}
						</div>
					</div>
				{/if}
			{/each}
		</div>
	{/if}

	<!-- Named under the row already, unless the crowd left it unnamed — then the
	     tooltip is the only way to read what it is. -->
	{#if hovered && !hovered.labelWidth}
		<!-- Offset below the canvas so it never covers the bodies. -->
		<div
			bind:clientWidth={tipWidth}
			class="bg-popover text-popover-foreground border-border pointer-events-none absolute z-10 w-max -translate-x-1/2 rounded-md border px-2 py-1 text-center shadow-md"
			style="left: {tipLeft}px; top: {height +
				6}px; max-width: {tipMaxWidth}px; visibility: {tipWidth === 0 ? 'hidden' : 'visible'}"
		>
			<div class="text-xs font-medium whitespace-nowrap">{hovered.name}</div>
			{#if hovered.description}
				<div class="text-muted-foreground text-[11px]">{hovered.description}</div>
			{/if}
			<div class="text-muted-foreground text-[11px] tabular-nums">
				{hovered.craft ? m.lineup_span() : m.diameter()}: {sizeText(hovered)}
			</div>
		</div>
	{/if}
</div>
