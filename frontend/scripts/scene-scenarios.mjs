/**
 * Scene scenarios: drives the real app in a headless browser and checks what
 * the scene holds. They cover the rules no unit test can see end to end:
 *
 * - a body with no known place is not drawn, and the camera is never on a
 *   stand-in for it;
 * - a navigation to an object moves the clock to a date the object has a place at;
 * - a body is on the curve drawn for its orbit;
 * - a jump of the clock leaves the camera on a body whose data has to load.
 *
 * Needs a dev server (its build exposes `__smCtx`, `__smRenderer`, `__smMap`)
 * on an export that carries `coverage`, and a Chromium with remote debugging:
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

	async close() {
		await fetch(`${CDP}/json/close/${this.target.id}`);
		this.ws.close();
	}
}

/** Runs in the page: what the scene holds for `id`, and what must hold for every body. */
const SNAPSHOT = `((id) => {
	const ctx = window.__smCtx, r = window.__smRenderer;
	const KM = 14959787.07;
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
/** Move the clock by `days` like the date picker does. Resolves after `ms`
 *  with every notice shown in that time. */
const jumpAndWatch = (days, ms) => `(async () => {
	const clock = window.__smRenderer.clock;
	clock.jumpTo(clock.jd + ${days});
	const seen = new Set();
	const end = performance.now() + ${ms};
	while (performance.now() < end) {
		for (const e of document.querySelectorAll('[data-sonner-toast]')) seen.add(e.innerText);
		await new Promise((r) => setTimeout(r, 30));
	}
	return [...seen];
})()`;
const NO_DATA_NOTICE = 'selected object has no data';

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

/** Open the page of `id`, jump the clock by `days` to a date whose data is not
 *  loaded, and check the camera is on the body as it was before the jump. */
async function jumpKeepsCamera(tab, failures, path, id, days) {
	await tab.goto(path);
	await tab.until(
		`${READY} && ${focusedIs(id)} && ${FLY_ENDED} && !!window.__smCtx.getBody('${id}')?.position`,
		`${id} placed`
	);
	await sleep(1500);
	const before = await tab.eval(`${SNAPSHOT}('${id}')`);
	const notices = await tab.eval(jumpAndWatch(days, 4000));
	const s = await tab.eval(`${SNAPSHOT}('${id}')`);
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
		!notices.some((t) => t.includes(NO_DATA_NOTICE)),
		`notices: ${notices.join(' | ')}`
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
	async 'date jump keeps the camera on a moon while the data of its parent loads'(tab, f) {
		return jumpKeepsCamera(tab, f, '/b/301/Moon', 'naif-301', 3653);
	},

	/** The moons of Saturn come in chunks of 46 days. */
	async 'date jump keeps the camera on a moon while its own data loads'(tab, f) {
		return jumpKeepsCamera(tab, f, '/b/606/Titan', 'naif-606', 200);
	},

	async 'date jump keeps the camera on a probe while its data loads'(tab, f) {
		return jumpKeepsCamera(tab, f, '/p/49065984/Voyager%201', 'probe-49065984', -3300);
	},

	/** In 2002 the chunk has to load before it can tell the telescope is not in it. */
	async 'date jump to before a launch moves the camera to the host and tells'(tab, f) {
		const JWST = 'probe-115347456';
		await tab.goto('/p/115347456/James%20Webb%20Space%20Telescope');
		await tab.until(
			`${READY} && ${focusedIs(JWST)} && ${FLY_ENDED} && !!window.__smCtx.getBody('${JWST}')?.position`,
			'the telescope placed'
		);
		await sleep(1500);
		const notices = await tab.eval(jumpAndWatch(-9000, 5000));
		const s = await tab.eval(`${SNAPSHOT}('${JWST}')`);
		check(f, s.focused === JWST && !s.placed, `focused ${s.focused}, placed=${s.placed}`);
		check(f, s.cameraToEarthKm < 1, `camera ${s.cameraToEarthKm} km from Earth`);
		check(
			f,
			notices.some((t) => t.includes(NO_DATA_NOTICE)),
			`notices: ${notices.join(' | ')}`
		);
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
