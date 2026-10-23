/**
 * Scene scenarios: drives the real app in a headless browser and checks what
 * the scene holds. They cover the rules no unit test can see end to end:
 *
 * - a body with no known place is not drawn, and the camera is never on a
 *   stand-in for it;
 * - a navigation to an object moves the clock to a date the object has a place at;
 * - a body is on the curve drawn for its orbit;
 * - a jump of the clock changes nothing in the scene until the data for the new
 *   date is in, and then the camera is on the body as before;
 * - a lander has its place before the page reads it, on a link and on a click;
 * - the ground under a lander holds still on screen while its body turns;
 * - a link with no camera opens framed on its body;
 * - a click on a star turns the camera to it as a click on a dot does, and a
 *   star that loads after a later navigation does not take the focus.
 *
 * Needs a dev server (its build exposes `__smCtx`, `__smRenderer`, `__smMap`)
 * on an export that carries `coverage` and the stars, and a Chromium with
 * remote debugging:
 *
 *   chromium --headless=new --remote-debugging-port=9222 about:blank
 *   pnpm dev
 *   SM_URL=http://localhost:5173 SM_CDP=http://127.0.0.1:9222 pnpm test:scenes [name...]
 */

const URL_BASE = process.env.SM_URL ?? 'http://localhost:5173';
const CDP = process.env.SM_CDP ?? 'http://127.0.0.1:9222';
const TIMEOUT_MS = 60_000;
const J2000 = 2451545;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** One browser tab, driven over the DevTools protocol. */
class Tab {
	static async open() {
		const target = await (await fetch(`${CDP}/json/new?about:blank`, { method: 'PUT' })).json();
		const tab = new Tab(target);
		await new Promise((resolve, reject) => {
			tab.ws.addEventListener('open', resolve, { once: true });
			tab.ws.addEventListener('error', reject, { once: true });
		});
		await tab.send('Page.enable');
		await tab.send('Runtime.enable');
		await tab.send('Emulation.setDeviceMetricsOverride', {
			width: 1600,
			height: 900,
			deviceScaleFactor: 1,
			mobile: false
		});
		return tab;
	}

	constructor(target) {
		this.target = target;
		this.ws = new WebSocket(target.webSocketDebuggerUrl);
		this.seq = 0;
		this.pending = new Map();
		this.exceptions = [];
		this.ws.addEventListener('message', (event) => {
			const msg = JSON.parse(event.data);
			if (msg.id && this.pending.has(msg.id)) {
				this.pending.get(msg.id)(msg.result ?? msg);
				this.pending.delete(msg.id);
			}
			if (msg.method === 'Runtime.exceptionThrown') {
				const d = msg.params.exceptionDetails;
				this.exceptions.push(d.exception?.description ?? d.text);
			}
		});
	}

	send(method, params = {}) {
		return new Promise((resolve) => {
			this.pending.set(++this.seq, resolve);
			this.ws.send(JSON.stringify({ id: this.seq, method, params }));
		});
	}

	async eval(expression) {
		const r = await this.send('Runtime.evaluate', {
			expression,
			returnByValue: true,
			awaitPromise: true
		});
		if (r.exceptionDetails)
			throw new Error(r.exceptionDetails.exception?.description ?? 'eval failed');
		return r.result?.value;
	}

	async goto(path) {
		this.exceptions.length = 0;
		await this.send('Page.navigate', { url: URL_BASE + path });
	}

	/** Poll `expression` until it is truthy. */
	async until(expression, what) {
		const deadline = Date.now() + TIMEOUT_MS;
		while (Date.now() < deadline) {
			if (await this.eval(expression).catch(() => false)) return;
			await sleep(250);
		}
		throw new Error(`timed out waiting for ${what}`);
	}

	/** A mouse click at (x, y), in CSS px. */
	async click(x, y) {
		const at = { x, y, button: 'left', clickCount: 1 };
		await this.send('Input.dispatchMouseEvent', { ...at, type: 'mouseMoved', buttons: 0 });
		await this.send('Input.dispatchMouseEvent', { ...at, type: 'mousePressed', buttons: 1 });
		await sleep(60);
		await this.send('Input.dispatchMouseEvent', { ...at, type: 'mouseReleased', buttons: 0 });
	}

	async close() {
		await fetch(`${CDP}/json/close/${this.target.id}`);
		this.ws.close();
	}
}

/** Kilometres in a scene unit. */
const KM = 14959787.07;

/** Runs in the page: what the scene holds for `id`, and what must hold for every body. */
const SNAPSHOT = `((id) => {
	const ctx = window.__smCtx, r = window.__smRenderer;
	const KM = ${KM};
	const body = ctx.getBody(id);
	const bo = r.bodyObjects.get(id);
	const km = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]) * KM;
	const basis = r.focus.focusTruePos;
	const earth = ctx.getBody('naif-399')?.position, emb = ctx.getBody('naif-3')?.position;
	const leaks = [];
	for (const o of r.bodyObjects.values()) {
		if (o.body.position) continue;
		if (o.root.visible) leaks.push(o.body.data.id + ':root');
		if (o.trail?.visible) leaks.push(o.body.data.id + ':trail');
		if (o.model?.parent === r.modelScene) leaks.push(o.body.data.id + ':model');
	}
	// A navigation places its target at the new date before the frame that
	// redraws the curves: no curve is read until the scene is at the date of the clock.
	const caughtUp = Math.abs(r.clock.jd - r.placedJd) * 86400 < 1;
	const sub = (u, v) => [u[0] - v[0], u[1] - v[1], u[2] - v[2]];
	const dot = (u, v) => u[0] * v[0] + u[1] * v[1] + u[2] * v[2];
	// How far a body is off the closed curve drawn for it, and how far off the
	// polygon of that curve leaves a body that is on the orbit. Null when no
	// such curve is drawn.
	const offCurve = (o) => {
		const ud = o?.trail?.userData, at = o?.body.trailAnchor ?? o?.body.position;
		if (!caughtUp || !o?.trail?.visible || !ud.sourceCurve || ud.isOpenCurve || !at) return null;
		// The last point is the first one again.
		const pts = ud.sourceCurve, sides = pts.length - 1, c = ud.orbitCenter;
		const q = [at[0] - c.x, at[1] - c.y, at[2] - c.z];
		let off = Infinity, side = 0;
		for (let k = 0; k < sides; k++) {
			const d = sub(pts[k + 1], pts[k]), len2 = dot(d, d);
			if (len2 === 0) continue;
			const w = sub(q, pts[k]);
			const t = Math.max(0, Math.min(1, dot(w, d) / len2));
			const gap = Math.hypot(w[0] - t * d[0], w[1] - t * d[1], w[2] - t * d[2]);
			if (gap < off) { off = gap; side = k; }
		}
		// Sag of the arc over the nearest side, from the circle through that side
		// and the point before it.
		const ab = sub(pts[side + 1], pts[side]);
		const ap = sub(pts[(side + sides - 1) % sides], pts[side]);
		const bp = sub(ap, ab);
		const cross = [ab[1] * ap[2] - ab[2] * ap[1], ab[2] * ap[0] - ab[0] * ap[2], ab[0] * ap[1] - ab[1] * ap[0]];
		const length = Math.hypot(...ab);
		const sag = (length * Math.hypot(...cross)) / (4 * Math.hypot(...ap) * Math.hypot(...bp));
		return { km: off * KM, slackKm: (2 * sag + 0.01 * length) * KM };
	};
	// How far the drawn line is from where the scene has it: its head from the
	// body, and its next point from the points of the curve. Null when no such
	// curve is drawn.
	const drawnOff = (o) => {
		const ud = o?.trail?.userData, at = o?.body.trailAnchor ?? o?.body.position;
		if (!offCurve(o)) return null;
		const drawn = ud.isFatLine ? ud.thinPositions : o.trail.geometry.getAttribute('position').array;
		const c = ud.orbitCenter;
		const head = Math.hypot(drawn[0] - (at[0] - basis[0]), drawn[1] - (at[1] - basis[1]), drawn[2] - (at[2] - basis[2]));
		const next = [drawn[3] + basis[0] - c.x, drawn[4] + basis[1] - c.y, drawn[5] + basis[2] - c.z];
		const fromCurve = Math.min(...ud.sourceCurve.map((p) => Math.hypot(...sub(next, p))));
		return Math.max(head, fromCurve) * KM;
	};
	const offCurves = [];
	for (const o of r.bodyObjects.values()) {
		const c = offCurve(o);
		if (c && c.km > c.slackKm) offCurves.push(o.body.data.id + ' ' + Math.round(c.km) + ' km');
	}
	return {
		jd: r.clock.jd,
		inScene: !!body,
		placed: !!body?.position,
		unplaced: body?.unplaced ?? null,
		focused: r.focusController.current?.data.id ?? null,
		cameraToBodyKm: body?.position ? km(basis, body.position) : null,
		cameraOffKm: r.camera.position.length() * KM,
		cameraToEarthKm: earth ? km(basis, earth) : null,
		bodyToEarthKm: body?.position && earth ? km(body.position, earth) : null,
		earthOffBarycentreKm: earth && emb ? km(earth, emb) : null,
		basisAtOrigin: Math.hypot(...basis) < 1e-9,
		drawn: !!bo?.root.visible,
		offCurveKm: offCurve(bo)?.km ?? null,
		drawnOffKm: drawnOff(bo),
		leaks,
		offCurves,
		toasts: [...document.querySelectorAll('[data-sonner-toast]')].map((e) => e.innerText)
	};
})`;

const READY = `!!window.__smRenderer && !!window.__smMap && window.__smCtx?.loading === false`;
const focusedIs = (id) => `window.__smRenderer?.focusController.current?.data.id === '${id}'`;
const goTo = (id) =>
	`window.__smMap.goTo('${id}').then((a) => ({ outcome: a.outcome, moved: !!a.clockMoved, host: a.host?.data.id ?? null }))`;
const curveDrawn = (id) => `(${SNAPSHOT}('${id}')).offCurveKm !== null`;
const FLY_ENDED = `performance.now() - window.__smRenderer.focus.focusStartTime > window.__smRenderer.focus.focusDurationMs`;
const jdOf = (iso) => Date.parse(iso) / 86400000 + 2440587.5;
/** How long a jump holds each fetch back: the scene has to show what it does
 *  while the data loads. */
const SLOW_FETCH_MS = 600;
/** Move the clock by `days` like the date picker does. Resolves after `ms` with
 *  how long the scene stayed at the old date, what it lost in that time, the
 *  farthest the camera got from Earth, and every notice shown. */
const jumpAndWatch = (days, ms) => `(async () => {
	const r = window.__smRenderer, ctx = window.__smCtx, clock = r.clock;
	const fetchNow = window.fetch;
	window.fetch = (...a) =>
		new Promise((go) => setTimeout(go, ${SLOW_FETCH_MS})).then(() => fetchNow(...a));
	const drawn = [...r.bodyObjects.values()].filter((o) => o.root.visible);
	const system = ctx.visibility.focusedSystemId;
	const earth = ctx.getBody('naif-399');
	const lost = new Set(), notices = new Set();
	let heldMs = 0, farthestFromEarthKm = 0, last = performance.now();
	const end = last + ${ms};
	clock.jumpTo(clock.jd + ${days});
	while (performance.now() < end) {
		await new Promise((go) => requestAnimationFrame(go));
		const now = performance.now();
		if (Math.abs(clock.jd - r.placedJd) > 1) {
			heldMs += now - last;
			// A reader that asks at the date of the clock, as a click does.
			for (const o of drawn) ctx.place(o.body, clock.jd);
			for (const o of drawn) if (!o.root.visible || !o.body.position) lost.add(o.body.data.id);
			if (ctx.visibility.focusedSystemId !== system) lost.add('the focused system');
		}
		last = now;
		const at = earth?.position, basis = r.focus.focusTruePos;
		if (at) {
			const km = Math.hypot(at[0] - basis[0], at[1] - basis[1], at[2] - basis[2]) * ${KM};
			farthestFromEarthKm = Math.max(farthestFromEarthKm, km);
		}
		for (const e of document.querySelectorAll('[data-sonner-toast]')) notices.add(e.innerText);
	}
	window.fetch = fetchNow;
	return { heldMs, lost: [...lost], farthestFromEarthKm, notices: [...notices] };
})()`;
const NO_DATA_NOTICE = 'selected object has no data';
/**
 * Draws `frames` frames of the scene and compares each with the one before.
 * Resolves with the median change between two frames, as a part of the full
 * range of a pixel, and the contrast of the picture: a flat one cannot change.
 * The median, because a tile that loads changes one frame.
 */
const frameChange = (frames) => `(async () => {
	const r = window.__smRenderer, canvas = r.renderer.domElement;
	const W = canvas.width >> 1, H = canvas.height >> 1;
	const copy = document.createElement('canvas');
	copy.width = W;
	copy.height = H;
	const g = copy.getContext('2d', { willReadFrequently: true });
	// The right half: the drawer covers the left on a page.
	const x0 = W >> 1, n = (W - x0) * H;
	const greys = [];
	const render = r.composer.render;
	// Read in the call that drew it: the buffer is gone after the frame.
	await new Promise((done) => {
		r.composer.render = function (...a) {
			render.apply(this, a);
			g.drawImage(canvas, 0, 0, W, H);
			const d = g.getImageData(x0, 0, W - x0, H).data;
			const grey = new Float32Array(n);
			for (let i = 0; i < n; i++) grey[i] = (d[4 * i] + d[4 * i + 1] + d[4 * i + 2]) / 765;
			greys.push(grey);
			if (greys.length < ${frames}) return;
			r.composer.render = render;
			done();
		};
	});
	const changes = [];
	for (let k = 1; k < greys.length; k++) {
		let sum = 0;
		for (let i = 0; i < n; i++) sum += Math.abs(greys[k][i] - greys[k - 1][i]);
		changes.push(sum / n);
	}
	changes.sort((a, b) => a - b);
	let min = 1, max = 0;
	for (const v of greys[0]) {
		min = Math.min(min, v);
		max = Math.max(max, v);
	}
	return { change: changes[changes.length >> 1], contrast: max - min };
})()`;

/** Runs in the page: the camera's place in the scene, in float64. */
const CAMERA_PLACE = `(() => {
	const r = window.__smRenderer, f = r.focus.focusTruePos, c = r.camera.position;
	return [f[0] + c.x, f[1] + c.y, f[2] + c.z];
})()`;

/**
 * Open Earth's page, take the camera 2,000 AU out with Orion ahead, and wait
 * for the stars. Resolves with a bright drawn star right of the middle of the
 * view that no other drawn star comes within 16 px of: its screen place, node
 * and row.
 */
async function openOnStars(tab) {
	await tab.goto('/b/399/Earth');
	// The page frames Earth once the small bodies are in. The move comes after that.
	await tab.until(
		`${READY} && ${focusedIs('naif-399')} && window.__smCtx.bodies.minorStreaming === false`,
		'Earth focused, the small bodies in'
	);
	await sleep(1500);
	await tab.eval(`(() => {
		const r = window.__smRenderer;
		// Away from Betelgeuse (RA 88.8°, Dec 7.4°), in the scene's ecliptic axes.
		const a = (268.8 * Math.PI) / 180, d = (-7.4 * Math.PI) / 180, e = (23.4393 * Math.PI) / 180;
		const x = Math.cos(d) * Math.cos(a), y = Math.cos(d) * Math.sin(a), z = Math.sin(d);
		r.camera.position.set(x, -y * Math.sin(e) + z * Math.cos(e), -(y * Math.cos(e) + z * Math.sin(e)));
		r.camera.position.multiplyScalar(20000);
		r.controls.update();
		r.invalidate();
	})()`);
	await tab.until(
		`window.__smRenderer.camera.position.length() > 19000 && window.__smRenderer.starfield.share() > 0.3 && window.__smRenderer.starfield.stats().loading === 0`,
		'the camera 2,000 AU out and the stars drawn'
	);
	await sleep(1500);
	const star = await tab.eval(`(() => {
		const r = window.__smRenderer, cam = r.camera, s = r.starfield;
		cam.updateMatrixWorld();
		const rect = r.renderer.domElement.getBoundingClientRect();
		const P = cam.projectionMatrix.elements, limit = s.stats().limit, PC = (648000 / Math.PI) * 10;
		const stars = [];
		for (const n of s.drawnNodes()) {
			if (!n.points.visible) continue;
			const mv = cam.matrixWorldInverse.clone().multiply(n.points.matrixWorld).elements;
			const pos = n.points.geometry.getAttribute('position').array;
			const mag = n.points.geometry.getAttribute('mag').array;
			for (let i = 0; i < n.rows; i++) {
				const [x, y, z] = [pos[3 * i], pos[3 * i + 1], pos[3 * i + 2]];
				const ex = mv[0] * x + mv[4] * y + mv[8] * z + mv[12];
				const ey = mv[1] * x + mv[5] * y + mv[9] * z + mv[13];
				const ez = mv[2] * x + mv[6] * y + mv[10] * z + mv[14];
				if (ez >= 0) continue;
				const above = limit - mag[i] - 5 * Math.log10(Math.hypot(ex, ey, ez) / PC) + 5;
				if (above <= 0) continue;
				const sx = rect.left + ((P[0] * ex + P[8] * ez) / -ez + 1) / 2 * rect.width;
				const sy = rect.top + (1 - (P[5] * ey + P[9] * ez) / -ez) / 2 * rect.height;
				stars.push({ node: n.name, row: i, above, x: sx, y: sy });
			}
		}
		// Clear of the solar system in the middle and of the panel on the left.
		const off = (p) => Math.hypot(p.x - rect.left - rect.width / 2, p.y - rect.top - rect.height / 2);
		const ring = (p) => off(p) > 200 && off(p) < 400 && p.x > rect.left + rect.width / 2;
		const alone = (p) => stars.every((o) => o === p || Math.hypot(o.x - p.x, o.y - p.y) > 16);
		return stars.filter((p) => p.above > 2 && ring(p)).sort((a, b) => b.above - a.above).find(alone) ?? null;
	})()`);
	if (!star) throw new Error('no drawn star stands alone in the middle of the view');
	return star;
}

/** Runs in the page: the ID of the star `openOnStars` found. */
const starIdOf = (star) =>
	`window.__smRenderer.starfield.starId({ node: '${star.node}', row: ${star.row} })`;

function check(failures, ok, message) {
	if (!ok) failures.push(message);
}

/** Wait for the curve of the moon `id` to be drawn, then check the moon is on it. */
async function onItsCurve(tab, failures, id) {
	await tab.until(curveDrawn(id), `the curve of ${id} drawn`);
	await sleep(1500);
	const s = await tab.eval(`${SNAPSHOT}('${id}')`);
	check(
		failures,
		s.offCurveKm !== null && s.offCurveKm < 100,
		`${id} is ${s.offCurveKm} km off its curve`
	);
	check(
		failures,
		s.drawnOffKm !== null && s.drawnOffKm < 100,
		`the line drawn for ${id} is ${s.drawnOffKm} km off its curve`
	);
	return s;
}

/** The scene stayed as it was for the time the data took to load. */
function heldTheScene(failures, watch) {
	check(
		failures,
		watch.heldMs > SLOW_FETCH_MS / 2,
		`the scene stayed at the old date for ${Math.round(watch.heldMs)} ms`
	);
	check(failures, watch.lost.length === 0, `lost while the data loaded: ${watch.lost.join(', ')}`);
}

/** Open the page of `id`, jump the clock by `days` to a date whose data is not
 *  loaded, and check the scene waits for the data and the camera is then on the
 *  body as it was before the jump. */
async function jumpWaitsForData(tab, failures, path, id, days) {
	await tab.goto(path);
	await tab.until(
		`${READY} && ${focusedIs(id)} && ${FLY_ENDED} && !!window.__smCtx.getBody('${id}')?.position`,
		`${id} placed`
	);
	await sleep(1500);
	const before = await tab.eval(`${SNAPSHOT}('${id}')`);
	const watch = await tab.eval(jumpAndWatch(days, 4000));
	const s = await tab.eval(`${SNAPSHOT}('${id}')`);
	heldTheScene(failures, watch);
	check(failures, Math.abs(s.jd - before.jd - days) < 0.01, `clock at jd ${s.jd}`);
	check(
		failures,
		s.placed && s.cameraToBodyKm < 1,
		`placed=${s.placed}, camera ${s.cameraToBodyKm} km from ${id}`
	);
	check(
		failures,
		Math.abs(s.cameraOffKm / before.cameraOffKm - 1) < 0.01,
		`the camera went from ${before.cameraOffKm} km to ${s.cameraOffKm} km off ${id}`
	);
	check(
		failures,
		!watch.notices.some((t) => t.includes(NO_DATA_NOTICE)),
		`notices: ${watch.notices.join(' | ')}`
	);
	return s;
}

/** What must hold after every scenario. */
function invariants(failures, s) {
	check(failures, s.leaks.length === 0, `drawn with no place: ${s.leaks.join(', ')}`);
	check(
		failures,
		s.offCurves.length === 0,
		`off the curve of its orbit: ${s.offCurves.join(', ')}`
	);
	check(failures, !s.basisAtOrigin, 'the camera basis is on the barycentre of the Solar System');
	check(
		failures,
		s.earthOffBarycentreKm === null || s.earthOffBarycentreKm > 1000,
		`Earth is ${s.earthOffBarycentreKm} km from the Earth-Moon barycentre`
	);
}

const MIR = 'norad_satcat-16609';
const CURIOSITY = 'probe-100265984';
/** Noon at Gale crater: the ground under Curiosity is lit. */
const GALE_NOON = '2026-08-30T13:06:00.000Z';
/** Camera distance of the lander links, in scene units: 11.5 m. */
const LANDER_ZOOM = 7.7e-10;
const ISS = 'norad_satcat-25544';
const SPUTNIK = 'norad_satcat-2';

const SCENARIOS = {
	/** A satellite that re-entered in 2001, opened today. */
	async 'decayed satellite opens at its last covered date'(tab, f) {
		await tab.goto('/e/16609/Mir');
		await tab.until(
			`${READY} && ${focusedIs(MIR)} && !!window.__smCtx.getBody('${MIR}')?.position`,
			'Mir placed'
		);
		const s = await tab.eval(`${SNAPSHOT}('${MIR}')`);
		check(
			f,
			s.jd > jdOf('2001-03-01') && s.jd < jdOf('2001-03-23'),
			`clock at jd ${s.jd}, not in March 2001`
		);
		check(f, s.cameraToBodyKm < 1, `camera ${s.cameraToBodyKm} km from Mir`);
		check(f, s.bodyToEarthKm < 7000, `Mir ${s.bodyToEarthKm} km from Earth`);
		check(
			f,
			s.toasts.some((t) => t.includes('2001')),
			'no notice that the date changed'
		);
		return s;
	},

	/** The archive starts in 1959: nothing can place Sputnik 1. */
	async 'object with no place opens its page and frames its host'(tab, f) {
		await tab.goto('/e/2/Sputnik%201');
		await tab.until(`${READY} && ${focusedIs(SPUTNIK)}`, 'Sputnik 1 focused');
		await sleep(3000);
		const s = await tab.eval(`${SNAPSHOT}('${SPUTNIK}')`);
		check(f, !s.placed && s.unplaced === 'never', `placed=${s.placed} unplaced=${s.unplaced}`);
		check(f, !s.drawn, 'its root is drawn');
		check(f, s.cameraToEarthKm < 1, `camera ${s.cameraToEarthKm} km from Earth`);
		check(f, Math.abs(s.jd - jdOf(new Date().toISOString())) < 1, 'the clock moved');
		check(
			f,
			s.toasts.some((t) => t.includes('Earth')),
			'no notice that the map shows Earth'
		);
		return s;
	},

	async 'satellite deep link inside its coverage keeps the date'(tab, f) {
		await tab.goto('/e/16609/Mir?at=1995-06-01T12:00:00.000Z');
		await tab.until(
			`${READY} && ${focusedIs(MIR)} && !!window.__smCtx.getBody('${MIR}')?.position`,
			'Mir placed'
		);
		const s = await tab.eval(`${SNAPSHOT}('${MIR}')`);
		check(f, Math.abs(s.jd - jdOf('1995-06-01T12:00:00Z')) < 0.01, `clock at jd ${s.jd}`);
		check(f, s.bodyToEarthKm < 7000, `Mir ${s.bodyToEarthKm} km from Earth`);
		check(f, s.toasts.length === 0, `toasts: ${s.toasts.join(' | ')}`);
		return s;
	},

	/** The current elements of the ISS do not reach 2010: the row of that week does. */
	async 'live satellite at an old date uses the elements of that date'(tab, f) {
		await tab.goto('/e/25544/ISS?at=2010-01-01T00:00:00.000Z');
		await tab.until(
			`${READY} && ${focusedIs(ISS)} && !!window.__smCtx.getBody('${ISS}')?.position`,
			'ISS placed'
		);
		const s = await tab.eval(`${SNAPSHOT}('${ISS}')`);
		check(f, Math.abs(s.jd - jdOf('2010-01-01T00:00:00Z')) < 0.01, `clock at jd ${s.jd}`);
		check(f, s.bodyToEarthKm < 7000, `ISS ${s.bodyToEarthKm} km from Earth`);
		return s;
	},

	async 'moon opened before its discovery goes to the discovery date'(tab, f) {
		await tab.goto('/b/904/Kerberos?at=2000-01-01T00:00:00.000Z');
		await tab.until(
			`${READY} && ${focusedIs('naif-904')} && !!window.__smCtx.getBody('naif-904')?.position`,
			'Kerberos placed'
		);
		const s = await tab.eval(`${SNAPSHOT}('naif-904')`);
		check(f, s.jd > J2000 + 4000, `clock at jd ${s.jd}, before the discovery`);
		check(f, s.cameraToBodyKm < 1, `camera ${s.cameraToBodyKm} km from Kerberos`);
		return s;
	},

	async 'in-session navigation moves the clock, then places and frames'(tab, f) {
		await tab.goto('/e/25544/ISS');
		await tab.until(`${READY} && ${focusedIs(ISS)}`, 'ISS focused');
		const toMir = await tab.eval(goTo(MIR));
		check(f, toMir.outcome === 'placed' && toMir.moved, `to Mir: ${JSON.stringify(toMir)}`);
		// Launched in 2019: the clock leaves 2001 for it.
		const toStarlink = await tab.eval(goTo('norad_satcat-44714'));
		check(
			f,
			toStarlink.outcome === 'placed' && toStarlink.moved,
			`to Starlink: ${JSON.stringify(toStarlink)}`
		);
		const toSputnik = await tab.eval(goTo(SPUTNIK));
		check(
			f,
			toSputnik.outcome === 'host' && toSputnik.host === 'naif-399',
			`to Sputnik 1: ${JSON.stringify(toSputnik)}`
		);
		const s = await tab.eval(`${SNAPSHOT}('norad_satcat-44714')`);
		check(f, s.jd > jdOf('2019-11-01'), `clock at jd ${s.jd}`);
		return s;
	},

	async 'later navigation supersedes an earlier one'(tab, f) {
		await tab.goto('/e/25544/ISS');
		await tab.until(`${READY} && ${focusedIs(ISS)}`, 'ISS focused');
		const [first, second] = await tab.eval(
			`Promise.all([${goTo('probe-49065984')}, ${goTo(MIR)}])`
		);
		check(f, first.outcome === 'superseded', `first: ${first.outcome}`);
		check(f, second.outcome === 'placed', `second: ${second.outcome}`);
		await sleep(2500);
		const s = await tab.eval(`${SNAPSHOT}('${MIR}')`);
		check(f, s.focused === MIR, `focused ${s.focused}`);
		return s;
	},

	async 'live satellite today has a place and no notice'(tab, f) {
		await tab.goto('/e/44714/STARLINK-1008');
		await tab.until(
			`${READY} && ${focusedIs('norad_satcat-44714')} && !!window.__smCtx.getBody('norad_satcat-44714')?.position`,
			'Starlink placed'
		);
		await sleep(1500);
		const s = await tab.eval(`${SNAPSHOT}('norad_satcat-44714')`);
		check(f, s.cameraToBodyKm < 1, `camera ${s.cameraToBodyKm} km from the satellite`);
		check(f, s.toasts.length === 0, `toasts: ${s.toasts.join(' | ')}`);
		return s;
	},

	/** Through the page's own navigation: a featured chip, then the Back button. */
	async 'back returns to the object and to its date'(tab, f) {
		await tab.goto('/e/16609/Mir');
		await tab.until(`${READY} && ${focusedIs(MIR)}`, 'Mir focused');
		await sleep(1500);
		const clicked = await tab.eval(
			`(() => { const chip = [...document.querySelectorAll('a, button')].find((e) => e.textContent.trim() === 'Mars'); chip?.click(); return !!chip; })()`
		);
		check(f, clicked, 'no Mars chip to click');
		await tab.until(focusedIs('naif-499'), 'Mars focused');
		await sleep(1500);
		await tab.eval('history.back()');
		await tab.until(
			`${focusedIs(MIR)} && !!window.__smCtx.getBody('${MIR}')?.position`,
			'Mir focused again'
		);
		await sleep(2500);
		const s = await tab.eval(`${SNAPSHOT}('${MIR}')`);
		check(f, s.jd > jdOf('2001-03-01') && s.jd < jdOf('2001-03-23'), `clock at jd ${s.jd}`);
		check(f, s.cameraToBodyKm < 1, `camera ${s.cameraToBodyKm} km from Mir`);
		return s;
	},

	/** Pluto is 2,100 km off the barycentre of its system: a curve drawn on the
	 *  barycentre leaves Charon beside it. */
	async 'Charon is on the curve of its orbit'(tab, f) {
		await tab.goto('/b/901/Charon?at=now,80,0,0.004');
		await tab.until(`${READY} && ${focusedIs('naif-901')}`, 'Charon focused');
		return onItsCurve(tab, f, 'naif-901');
	},

	/** Earth is 4,600 km off the barycentre of its system. The last check is
	 *  after three days in another system: elements that old put the curve
	 *  some 1,000 km off the Moon. */
	async 'Moon is on the curve of its orbit, also after a stay in another system'(tab, f) {
		const MOON = 'naif-301';
		await tab.goto('/b/301/Moon?at=now,80,0,0.0064');
		await tab.until(`${READY} && ${focusedIs(MOON)}`, 'Moon focused');
		await onItsCurve(tab, f, MOON);
		// A quarter of an hour on, with the curve on screen: the line follows the Moon.
		await tab.eval(`window.__smRenderer.clock.setJD(window.__smRenderer.clock.jd + 0.01)`);
		await onItsCurve(tab, f, MOON);
		const toMars = await tab.eval(goTo('naif-499'));
		check(f, toMars.outcome === 'placed', `to Mars: ${JSON.stringify(toMars)}`);
		await tab.until(`${focusedIs('naif-499')} && ${FLY_ENDED}`, 'the camera on Mars');
		await tab.eval(`window.__smRenderer.clock.setJD(window.__smRenderer.clock.jd + 3)`);
		await sleep(1500);
		const back = await tab.eval(goTo(MOON));
		check(f, back.outcome === 'placed', `back to the Moon: ${JSON.stringify(back)}`);
		await tab.until(`${focusedIs(MOON)} && ${FLY_ENDED}`, 'the camera on the Moon');
		// The camera stops too near the Moon for its curve to show.
		await tab.eval(`window.__smRenderer.camera.position.set(0, 0.0064, 0.0011)`);
		return onItsCurve(tab, f, MOON);
	},

	/** Ten years on is another chunk of the planets: the barycentre the Moon is
	 *  placed from has no place until it is here. */
	async 'date jump holds the scene on a moon while the data of its parent loads'(tab, f) {
		return jumpWaitsForData(tab, f, '/b/301/Moon', 'naif-301', 3653);
	},

	/** The moons of Saturn come in chunks of 46 days. */
	async 'date jump holds the scene on a moon while its own data loads'(tab, f) {
		return jumpWaitsForData(tab, f, '/b/606/Titan', 'naif-606', 200);
	},

	async 'date jump holds the scene on a probe while its data loads'(tab, f) {
		return jumpWaitsForData(tab, f, '/p/49065984/Voyager%201', 'probe-49065984', -3300);
	},

	/** In 2002 the chunk has to load before it can tell the telescope is not in
	 *  it. The camera then goes to Earth from where it was about Earth. */
	async 'date jump to before a launch moves the camera to the host and tells'(tab, f) {
		const JWST = 'probe-115347456';
		await tab.goto('/p/115347456/James%20Webb%20Space%20Telescope');
		await tab.until(
			`${READY} && ${focusedIs(JWST)} && ${FLY_ENDED} && !!window.__smCtx.getBody('${JWST}')?.position`,
			'the telescope placed'
		);
		await sleep(1500);
		const before = await tab.eval(`${SNAPSHOT}('${JWST}')`);
		const watch = await tab.eval(jumpAndWatch(-9000, 5000));
		const s = await tab.eval(`${SNAPSHOT}('${JWST}')`);
		heldTheScene(f, watch);
		check(f, s.focused === JWST && !s.placed, `focused ${s.focused}, placed=${s.placed}`);
		check(f, s.cameraToEarthKm < 1, `camera ${s.cameraToEarthKm} km from Earth`);
		check(
			f,
			watch.farthestFromEarthKm < before.cameraToEarthKm * 1.01,
			`the camera got ${watch.farthestFromEarthKm} km from Earth, from ${before.cameraToEarthKm} km`
		);
		check(
			f,
			watch.notices.some((t) => t.includes(NO_DATA_NOTICE)),
			`notices: ${watch.notices.join(' | ')}`
		);
		return s;
	},

	/** A lander is placed from the spin of Mars, which the scene reads with the
	 *  system in focus: the page must not read the place before it. */
	async 'lander deep link opens on the lander, at the camera of the link'(tab, f) {
		await tab.goto(`/p/100265984/Curiosity?at=${GALE_NOON},35,70,${LANDER_ZOOM}`);
		await tab.until(`${READY} && ${focusedIs(CURIOSITY)}`, 'Curiosity focused');
		await sleep(1500);
		const s = await tab.eval(`${SNAPSHOT}('${CURIOSITY}')`);
		check(f, s.placed, `unplaced=${s.unplaced}`);
		check(f, s.toasts.length === 0, `toasts: ${s.toasts.join(' | ')}`);
		check(
			f,
			Math.abs(s.cameraOffKm / (LANDER_ZOOM * KM) - 1) < 0.01,
			`camera ${s.cameraOffKm} km from Curiosity`
		);
		return s;
	},

	/** The scene is at rest: the clock stands still and no body arrives. A
	 *  reader settles the lander with no place just before the spin of Mars
	 *  arrives, so only that spin can start the pass that places it. */
	async 'in-session navigation to a lander in another system places it'(tab, f) {
		await tab.goto('/b/399/Earth');
		await tab.until(
			`${READY} && ${focusedIs('naif-399')} && window.__smCtx.bodies.minorStreaming === false`,
			'Earth focused, the small bodies in'
		);
		const toLander = await tab.eval(`(async () => {
			const r = window.__smRenderer, ctx = window.__smCtx;
			r.clock.pause();
			const fetchNow = window.fetch;
			let unplacedBefore = false;
			window.fetch = async (...a) => {
				const response = await fetchNow(...a);
				if (String(a[0]?.url ?? a[0]).includes('/systems/naif-4.json')) {
					const lander = ctx.getBody('${CURIOSITY}');
					unplacedBefore = !!lander && ctx.place(lander, r.clock.jd) === null;
				}
				return response;
			};
			const arrival = await ${goTo(CURIOSITY)};
			window.fetch = fetchNow;
			return { ...arrival, unplacedBefore };
		})()`);
		check(f, toLander.unplacedBefore, 'the lander was not settled with no place before the spin');
		check(
			f,
			toLander.outcome === 'placed' && !toLander.moved,
			`to Curiosity: ${JSON.stringify(toLander)}`
		);
		const s = await tab.eval(`${SNAPSHOT}('${CURIOSITY}')`);
		check(f, s.toasts.length === 0, `toasts: ${s.toasts.join(' | ')}`);
		return s;
	},

	/** A vertex of Mars and the camera are both a radius from the mesh origin:
	 *  at 32 bits their difference is good to 22 cm, and the camera is 11 m away. */
	async 'ground under a lander holds still while its body turns'(tab, f) {
		await tab.goto(`/p/100265984/Curiosity?at=${GALE_NOON},35,70,${LANDER_ZOOM}`);
		await tab.until(
			`${READY} && ${focusedIs(CURIOSITY)} && !!window.__smRenderer.bodyObjects.get('naif-499')?.terrainWindow`,
			'the terrain under Curiosity built'
		);
		// On a cold cache the rover and the tiles come later.
		await tab.until(`${frameChange(2)}.then((p) => p.contrast > 0.05)`, 'a picture with detail');
		await sleep(3000);
		const { change, contrast } = await tab.eval(frameChange(40));
		check(f, contrast > 0.05, `the ground is flat on screen: contrast ${contrast}`);
		check(f, change < 2e-4, `two frames differ by ${change} of the range of a pixel`);
		return tab.eval(`${SNAPSHOT}('${CURIOSITY}')`);
	},

	/** The page frames Saturn after the scene has put the camera 1.5 AU out, the
	 *  view of a link with no camera: that view must not come back. */
	async 'link with no camera opens framed on its body'(tab, f) {
		const linkCamera = `new URLSearchParams(location.search).get('at')?.split(',')[3]`;
		await tab.goto('/b/699/Saturn');
		await tab.until(
			`${READY} && ${focusedIs('naif-699')} && !!${linkCamera} && window.__smCtx.bodies.orientationRead.has('naif-699')`,
			'Saturn framed and its spin read'
		);
		// The old view came back with the data of the system, after the spin.
		await sleep(1500);
		const s = await tab.eval(`${SNAPSHOT}('naif-699')`);
		const linkKm = (await tab.eval(`Number(${linkCamera})`)) * KM;
		check(f, linkKm < 1e6, `the link has the camera ${linkKm} km out`);
		check(
			f,
			Math.abs(s.cameraOffKm / linkKm - 1) < 0.01,
			`camera ${s.cameraOffKm} km from Saturn, ${linkKm} km in the link`
		);
		return s;
	},

	/** The camera stays where it is and turns to the star, as for a dot of a
	 *  cloud: no flight to it. The URL and the panel follow the focus. */
	async 'a click on a star turns the camera to it'(tab, f) {
		const star = await openOnStars(tab);
		const id = `x-${await tab.eval(starIdOf(star))}`;
		const before = await tab.eval(CAMERA_PLACE);
		await tab.click(star.x, star.y);
		await tab.until(`${focusedIs(id)} && ${FLY_ENDED}`, `${id} focused`);
		const name = await tab.eval(`window.__smCtx.getBody('${id}').data.name`);
		await tab.until(
			`document.querySelector('#detail-drawer-title')?.textContent.trim() === ${JSON.stringify(name)}`,
			'the panel of the star'
		);
		const after = await tab.eval(CAMERA_PLACE);
		const s = await tab.eval(`${SNAPSHOT}('${id}')`);
		const moved = Math.hypot(...after.map((v, i) => v - before[i]));
		check(f, moved < s.cameraOffKm / KM / 1e9, `the camera moved ${moved * KM} km`);
		const path = await tab.eval('decodeURIComponent(location.pathname)');
		check(f, path === `/x/${id.slice(2)}/${name}`, `URL ${path}`);
		return s;
	},

	/** The ID file of the star comes 2 s late: a link followed in that time
	 *  keeps the focus. */
	async 'a star that loads after a later navigation does not take the focus'(tab, f) {
		const star = await openOnStars(tab);
		await tab.eval(`(() => {
			const fetchNow = window.fetch;
			window.__idAsked = false;
			window.fetch = (...a) => {
				if (!String(a[0]?.url ?? a[0]).includes('/mw/id/')) return fetchNow(...a);
				window.__idAsked = true;
				return new Promise((go) => setTimeout(go, 2000)).then(() => fetchNow(...a));
			};
		})()`);
		await tab.click(star.x, star.y);
		await tab.eval(`window.__smFocusObject('naif-499', 'Mars')`);
		await tab.until(`${focusedIs('naif-499')} && ${FLY_ENDED}`, 'Mars focused');
		await sleep(3000);
		const s = await tab.eval(`${SNAPSHOT}('naif-499')`);
		check(f, await tab.eval('window.__idAsked'), 'the click did not ask for the ID file');
		check(f, s.focused === 'naif-499', `focused ${s.focused}`);
		const path = await tab.eval('location.pathname');
		check(f, path.startsWith('/b/499/'), `URL ${path}`);
		return s;
	},

	async 'home view'(tab, f) {
		await tab.goto('/b/399/Earth');
		await tab.until(`${READY} && ${focusedIs('naif-399')}`, 'Earth focused');
		await sleep(1500);
		const s = await tab.eval(`${SNAPSHOT}('naif-399')`);
		check(
			f,
			s.placed && s.cameraToBodyKm < 1,
			`Earth placed=${s.placed}, camera ${s.cameraToBodyKm} km away`
		);
		check(f, s.toasts.length === 0, `toasts: ${s.toasts.join(' | ')}`);
		return s;
	}
};

const wanted = process.argv.slice(2);
const names = Object.keys(SCENARIOS).filter(
	(n) => wanted.length === 0 || wanted.some((w) => n.includes(w))
);
let failed = 0;
for (const name of names) {
	const tab = await Tab.open();
	const failures = [];
	try {
		const snapshot = await SCENARIOS[name](tab, failures);
		invariants(failures, snapshot);
		// The search service is not part of the scene: its absence is not a failure.
		const thrown = tab.exceptions.filter((e) => !/meilisearch/i.test(e));
		check(failures, thrown.length === 0, `uncaught: ${thrown.slice(0, 3).join(' | ')}`);
	} catch (e) {
		failures.push(String(e.message ?? e));
	} finally {
		await tab.close();
	}
	if (failures.length > 0) failed++;
	console.log(`${failures.length === 0 ? 'ok  ' : 'FAIL'} ${name}`);
	for (const f of failures) console.log(`       ${f}`);
}
console.log(`\n${names.length - failed}/${names.length} scenarios passed`);
process.exit(failed === 0 ? 0 : 1);
