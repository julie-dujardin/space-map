import { PerspectiveCamera, Quaternion, Vector3 } from 'three';
import { describe, expect, it } from 'vitest';
import { LookOrbitControls, MAX_TILT } from './look-controls';

type Listener = (event: unknown) => void;

/** Just enough of a canvas for OrbitControls, with its listeners kept so a
 *  test can press buttons on it. */
function fakeCanvas() {
	const listeners = new Map<string, Listener[]>();
	const add = (type: string, fn: Listener) =>
		listeners.set(type, [...(listeners.get(type) ?? []), fn]);
	const remove = (type: string, fn: Listener) =>
		listeners.set(
			type,
			(listeners.get(type) ?? []).filter((f) => f !== fn)
		);
	const ownerDocument = { addEventListener: add, removeEventListener: remove };
	const canvas = {
		style: {},
		clientWidth: 1000,
		clientHeight: 1000,
		ownerDocument,
		addEventListener: add,
		removeEventListener: remove,
		getRootNode: () => ({ addEventListener() {}, removeEventListener() {} }),
		setPointerCapture() {},
		releasePointerCapture() {},
		getBoundingClientRect: () => ({ left: 0, top: 0, width: 1000, height: 1000 })
	};
	const fire = (type: string, event: object) => {
		for (const fn of listeners.get(type) ?? []) fn({ preventDefault() {}, ...event });
	};
	return { canvas: canvas as unknown as HTMLElement, fire };
}

const RADIUS = 1;
/** Orbit radius of the camera: 0.4 radii up, where the view tilts freely. */
const ORBIT = 1.4;

function setup(radius: number | null = RADIUS, orbit = ORBIT) {
	const camera = new PerspectiveCamera(50, 1, 0.001, 100);
	camera.position.set(0, 0, orbit);
	const { canvas, fire } = fakeCanvas();
	const controls = new LookOrbitControls(camera, canvas, () => radius);
	controls.update();
	const middleDrag = (dx: number, dy: number) => {
		const base = { pointerId: 1, pointerType: 'mouse', button: 1, clientX: 500, clientY: 500 };
		fire('pointerdown', base);
		fire('pointermove', { ...base, clientX: 500 + dx, clientY: 500 + dy });
		fire('pointerup', { ...base, clientX: 500 + dx, clientY: 500 + dy });
	};
	/** Two fingers come down at `from`, go to `to` in `steps` even moves each,
	 *  one finger and then the other, and lift. */
	const twoFingers = (
		from: [[number, number], [number, number]],
		to: [[number, number], [number, number]],
		steps = 20
	) => {
		const at = (id: number, [x, y]: [number, number]) => ({
			pointerId: id,
			pointerType: 'touch',
			button: 0,
			pageX: x,
			pageY: y,
			clientX: x,
			clientY: y
		});
		const lerp = (i: number, t: number): [number, number] => [
			from[i][0] + (to[i][0] - from[i][0]) * t,
			from[i][1] + (to[i][1] - from[i][1]) * t
		];
		fire('pointerdown', at(1, from[0]));
		fire('pointerdown', at(2, from[1]));
		for (let step = 1; step <= steps; step++) {
			fire('pointermove', at(1, lerp(0, step / steps)));
			fire('pointermove', at(2, lerp(1, step / steps)));
		}
		fire('pointerup', at(1, to[0]));
		fire('pointerup', at(2, to[1]));
		controls.update();
	};
	/** A touch event for finger `id` at (x, y), `t` ms in. */
	const touch = (type: string, id: number, x: number, y: number, t: number) =>
		fire(type, {
			pointerId: id,
			pointerType: 'touch',
			button: 0,
			pageX: x,
			pageY: y,
			clientX: x,
			clientY: y,
			timeStamp: t
		});
	return { camera, controls, middleDrag, twoFingers, touch };
}

/** The ground point the untilted camera looks straight down on. */
function groundUnder(position: Vector3): Vector3 {
	return position.clone().normalize().multiplyScalar(RADIUS);
}

function viewCentreOffset(camera: PerspectiveCamera, point: Vector3): number {
	camera.updateMatrixWorld();
	const ndc = point.clone().project(camera);
	return Math.hypot(ndc.x, ndc.y);
}

describe('LookOrbitControls', () => {
	it('tilts about the ground at the centre of the view', () => {
		const { camera, middleDrag } = setup();
		const ground = groundUnder(camera.position);
		const range = camera.position.distanceTo(ground);
		middleDrag(0, -200);
		expect(viewCentreOffset(camera, ground)).toBeLessThan(1e-9);
		expect(camera.position.distanceTo(ground)).toBeCloseTo(range, 9);
		expect(camera.position.length()).toBeLessThan(ORBIT);
		expect(camera.position.y).toBeLessThan(0);
	});

	it('turns the heading about the ground without moving it', () => {
		const { camera, middleDrag } = setup();
		const ground = groundUnder(camera.position);
		middleDrag(0, -200);
		const tilted = camera.position.clone();
		middleDrag(300, 0);
		expect(viewCentreOffset(camera, ground)).toBeLessThan(1e-9);
		expect(camera.position.distanceTo(tilted)).toBeGreaterThan(0.1);
		expect(camera.position.length()).toBeCloseTo(tilted.length(), 9);
	});

	it('stops short of the horizon', () => {
		const { camera, middleDrag } = setup();
		const ground = groundUnder(camera.position);
		middleDrag(0, -5000);
		const view = camera.getWorldDirection(new Vector3());
		const down = ground.clone().normalize().negate();
		expect(view.angleTo(down)).toBeCloseTo(MAX_TILT, 9);
	});

	it('keeps the tilt while the orbit moves under it', () => {
		const { camera, controls, middleDrag } = setup();
		middleDrag(0, -200);
		const tiltedDistance = camera.position.length();
		controls.rotateLeft(0.5);
		controls.update();
		expect(controls.orbitPosition.length()).toBeCloseTo(ORBIT, 9);
		expect(viewCentreOffset(camera, groundUnder(controls.orbitPosition))).toBeLessThan(1e-9);
		expect(camera.position.length()).toBeCloseTo(tiltedDistance, 9);
	});

	it('carries the tilted view round with a spin, tilt and all', () => {
		const { camera, controls, middleDrag } = setup();
		middleDrag(0, -200);
		const spin = new Quaternion().setFromAxisAngle(new Vector3(0, 1, 0), 0.3);
		const ground = groundUnder(controls.orbitPosition).applyQuaternion(spin);
		const expected = camera.position.clone().applyQuaternion(spin);
		controls.carry(spin);
		controls.update();
		expect(camera.position.distanceTo(expected)).toBeLessThan(1e-9);
		expect(viewCentreOffset(camera, ground)).toBeLessThan(1e-9);
	});

	it('ends the turn where the view stands when something else takes the camera', () => {
		const { camera, controls, middleDrag } = setup();
		middleDrag(0, -200);
		const before = camera.position.clone();
		controls.endLook();
		controls.update();
		expect(controls.turned).toBe(false);
		expect(camera.position.distanceTo(before)).toBeLessThan(1e-12);
	});

	it('takes a clamp push into an orbit that moved into the ground', () => {
		const { camera, controls, middleDrag } = setup();
		middleDrag(0, -200);
		controls.rotateLeft(0.01);
		controls.update();
		const ground = groundUnder(controls.orbitPosition);
		camera.position.multiplyScalar(1.02);
		const pushed = camera.position.clone();
		controls.adoptPlacement();
		controls.update();
		expect(controls.turned).toBe(true);
		expect(camera.position.distanceTo(pushed)).toBeLessThan(1e-9);
		expect(viewCentreOffset(camera, ground)).toBeLessThan(1e-9);
	});

	it('lets a push from ground rising under a still view last only as long', () => {
		const { camera, controls, middleDrag } = setup();
		middleDrag(0, -200);
		controls.update();
		const before = camera.position.clone();
		camera.position.multiplyScalar(1.02);
		controls.adoptPlacement();
		controls.update();
		expect(camera.position.distanceTo(before)).toBeLessThan(1e-12);
	});

	it('moves the orbit for a limit, the turn going along', () => {
		const { camera, controls, middleDrag } = setup();
		middleDrag(0, -200);
		controls.moveOrbit((orbit) => orbit.multiplyScalar(1.1));
		expect(controls.orbitPosition.length()).toBeCloseTo(ORBIT * 1.1, 9);
		expect(viewCentreOffset(camera, groundUnder(controls.orbitPosition))).toBeLessThan(1e-9);
		expect(controls.turned).toBe(true);
	});

	it('lets go of the tilt where another writer put the camera', () => {
		const { camera, controls, middleDrag } = setup();
		middleDrag(0, -200);
		camera.position.set(2, 0, 0);
		controls.update();
		expect(controls.orbitPosition).toBe(camera.position);
		expect(viewCentreOffset(camera, new Vector3())).toBeLessThan(1e-9);
	});

	it('takes a clamp push as its own placement', () => {
		const { camera, controls, middleDrag } = setup();
		middleDrag(0, -200);
		camera.position.multiplyScalar(1.01);
		controls.adoptPlacement();
		controls.update();
		expect(controls.orbitPosition).not.toBe(camera.position);
	});

	it('eases the angles out from half a radius up, and does not give them back', () => {
		const { controls, middleDrag } = setup();
		middleDrag(0, -5000);
		// 0.75 radii up allows half of each angle.
		controls.dollyIn(1.75 / ORBIT);
		controls.update();
		const eased = controls['tilt'];
		expect(eased).toBeCloseTo(MAX_TILT / 2, 9);
		controls.dollyIn(ORBIT / 1.75);
		controls.update();
		expect(controls['tilt']).toBeCloseTo(eased, 9);
	});

	it('is back on the plain orbit a radius up', () => {
		const { camera, controls, middleDrag } = setup();
		middleDrag(150, -200);
		controls.dollyIn(2.2 / ORBIT);
		controls.update();
		expect(controls.orbitPosition).toBe(camera.position);
		expect(viewCentreOffset(camera, new Vector3())).toBeLessThan(1e-9);
	});

	it('does not tilt out in space', () => {
		const { camera, middleDrag } = setup(RADIUS, 3);
		const before = camera.position.clone();
		middleDrag(0, -200);
		expect(camera.position.toArray()).toEqual(before.toArray());
	});

	it('does nothing where there is no surface to tilt over', () => {
		const { camera, middleDrag } = setup(null);
		const before = camera.position.clone();
		middleDrag(0, -200);
		expect(camera.position.toArray()).toEqual(before.toArray());
	});

	it('turns a screen drag into the orbit axes the heading turned from', () => {
		const { controls, middleDrag } = setup();
		expect(controls.toOrbitAxes(1, 0)).toEqual([1, 0]);
		// Half a viewport height left is a quarter turn.
		middleDrag(-500, 0);
		const [x, y] = controls.toOrbitAxes(1, 0);
		expect(x).toBeCloseTo(0, 9);
		expect(y).toBeCloseTo(-1, 9);
	});
});

describe('LookOrbitControls two fingers', () => {
	it('tilts the view as both fingers slide up side by side', () => {
		const { camera, controls, twoFingers } = setup();
		const ground = groundUnder(camera.position);
		twoFingers(
			[
				[400, 600],
				[600, 600]
			],
			[
				[400, 400],
				[600, 400]
			]
		);
		expect(controls.look.tilt).toBeGreaterThan(0.5);
		expect(controls.look.heading).toBeCloseTo(0, 9);
		expect(viewCentreOffset(camera, ground)).toBeLessThan(1e-9);
		// As far as a middle drag the same way.
		const twoFingerTilt = controls.look.tilt;
		controls.endLook();
		const fresh = setup();
		fresh.middleDrag(0, -200);
		expect(fresh.controls.look.tilt).toBeCloseTo(twoFingerTilt, 9);
	});

	it('turns the map with the fingers as they twist', () => {
		const { camera, controls, twoFingers } = setup();
		const c = [500, 500] as const;
		const at = (angle: number, r: number): [number, number] => [
			c[0] + r * Math.cos(angle),
			c[1] + r * Math.sin(angle)
		];
		// A ground point just right of the centre of the view.
		const point = new Vector3(0.05, 0, 1).normalize().multiplyScalar(RADIUS);
		camera.updateMatrixWorld();
		const before = point.clone().project(camera);
		expect(before.x).toBeGreaterThan(0);
		expect(before.y).toBeCloseTo(0, 9);
		// 60° clockwise on screen.
		const twist = Math.PI / 3;
		twoFingers([at(Math.PI, 100), at(0, 100)], [at(Math.PI + twist, 100), at(twist, 100)], 60);
		camera.updateMatrixWorld();
		const after = point.clone().project(camera);
		// Clockwise with y down is down the screen from the right: ndc y < 0.
		const turnedBy = -Math.atan2(after.y, after.x);
		expect(turnedBy).toBeGreaterThan(twist - 0.25);
		expect(turnedBy).toBeLessThan(twist);
		expect(controls.look.tilt).toBeCloseTo(0, 9);
	});

	it('leaves a twist alone out in space', () => {
		const { camera, twoFingers } = setup(RADIUS, 3);
		const before = camera.quaternion.clone();
		twoFingers(
			[
				[400, 500],
				[600, 500]
			],
			[
				[500, 400],
				[500, 600]
			]
		);
		expect(camera.quaternion.angleTo(before)).toBeLessThan(1e-9);
	});

	it('still pinches to zoom', () => {
		const { camera, twoFingers } = setup();
		const range = camera.position.length();
		twoFingers(
			[
				[450, 500],
				[550, 500]
			],
			[
				[350, 500],
				[650, 500]
			]
		);
		expect(camera.position.length()).toBeLessThan(range);
	});
});

describe('LookOrbitControls glide', () => {
	it('carries a tilt on after the drag, to the whole of it', () => {
		const { controls, middleDrag } = setup();
		controls.enableDamping = true;
		controls.dampingFactor = 0.1;
		middleDrag(0, -200);
		controls.update();
		const full = (200 * Math.PI) / 1000;
		const soon = controls.look.tilt;
		expect(soon).toBeGreaterThan(0);
		expect(soon).toBeLessThan(full / 2);
		for (let i = 0; i < 300; i++) controls.update();
		expect(controls.look.tilt).toBeCloseTo(full, 4);
	});

	it('stops gliding when a finger comes down', () => {
		const { controls, middleDrag, touch } = setup();
		controls.enableDamping = true;
		controls.dampingFactor = 0.1;
		middleDrag(0, -200);
		for (let i = 0; i < 3; i++) controls.update();
		touch('pointerdown', 5, 500, 500, 0);
		const caught = controls.look.tilt;
		for (let i = 0; i < 50; i++) controls.update();
		expect(controls.look.tilt).toBeCloseTo(caught, 12);
	});

	it('stops gliding when something else takes the camera', () => {
		const { controls, middleDrag } = setup();
		controls.enableDamping = true;
		middleDrag(0, -200);
		controls.update();
		controls.endLook();
		controls.update();
		expect(controls.turned).toBe(false);
		for (let i = 0; i < 20; i++) controls.update();
		expect(controls.turned).toBe(false);
	});
});

describe('LookOrbitControls looking on at ground', () => {
	/** Camera 0.3 radii up, off the vertical of the ground it looks at. */
	const cases: [number, number, number][] = [
		[0.05, 0.02, 1],
		[0.3, 0.1, 0.95],
		[-0.2, 0.25, 0.95]
	];

	it('turns the view where the camera stands, onto the ground', () => {
		for (const g of cases) {
			const { camera, controls } = setup();
			camera.position.set(0.1, 0.05, 1.3);
			controls.update();
			const ground = new Vector3(...g).normalize();
			const before = camera.position.clone();
			const pose = controls.lookPose(before.clone(), ground, new Quaternion());
			controls.lookToward(ground);
			expect(camera.position.distanceTo(before)).toBeLessThan(1e-12);
			expect(viewCentreOffset(camera, ground)).toBeLessThan(1e-9);
			expect(camera.quaternion.angleTo(pose)).toBeLessThan(1e-6);
			controls.update();
			expect(camera.position.distanceTo(before)).toBeLessThan(1e-12);
		}
	});

	it('holds the view in space while north turns under a turn of its own', () => {
		const { camera, controls } = setup();
		camera.position.set(0.1, 0.05, 1.3);
		controls.update();
		const ground = new Vector3(0.3, 0.1, 0.95).normalize();
		controls.lookToward(ground);
		const before = camera.position.clone();
		const quat = camera.quaternion.clone();
		camera.up.set(0.3, 1, 0).normalize();
		controls.update();
		expect(camera.position.distanceTo(before)).toBeLessThan(1e-12);
		expect(camera.quaternion.angleTo(quat)).toBeLessThan(1e-6);
	});

	it('keeps a placed bearing off north while north turns', () => {
		const { camera, controls } = setup();
		controls.setLook({ tilt: 0.6, heading: 0.4 });
		camera.up.set(0.3, 1, 0).normalize();
		controls.update();
		expect(controls.look.heading).toBeCloseTo(0.4, 12);
	});
});

describe('LookOrbitControls wheel', () => {
	/** The ground under pixel (x, y) of the 1000 px fake canvas, or null. */
	function groundAt(camera: PerspectiveCamera, x: number, y: number): Vector3 | null {
		camera.updateMatrixWorld();
		const dir = new Vector3(x / 500 - 1, 1 - y / 500, 0.5)
			.unproject(camera)
			.sub(camera.position)
			.normalize();
		const b = camera.position.dot(dir);
		const disc = b * b - (camera.position.lengthSq() - RADIUS * RADIUS);
		return disc < 0 ? null : camera.position.clone().addScaledVector(dir, -b - Math.sqrt(disc));
	}

	function pixelOf(camera: PerspectiveCamera, point: Vector3): [number, number] {
		camera.updateMatrixWorld();
		const ndc = point.clone().project(camera);
		return [(ndc.x + 1) * 500, (1 - ndc.y) * 500];
	}

	function wheelSetup(tilted: boolean, orbit = ORBIT) {
		const camera = new PerspectiveCamera(50, 1, 0.001, 100);
		camera.position.set(0, 0, orbit);
		const { canvas, fire } = fakeCanvas();
		const controls = new LookOrbitControls(camera, canvas, () => RADIUS);
		controls.enableDamping = false;
		controls.update();
		if (tilted) {
			const base = { pointerId: 1, pointerType: 'mouse', button: 1, clientX: 500, clientY: 500 };
			fire('pointerdown', base);
			fire('pointermove', { ...base, clientY: 400, clientX: 560 });
			fire('pointerup', { ...base, clientY: 400, clientX: 560 });
		}
		const wheel = (x: number, y: number, deltaY: number) =>
			fire('wheel', { clientX: x, clientY: y, deltaY, deltaMode: 0, ctrlKey: false });
		return { camera, controls, wheel };
	}

	for (const tilted of [false, true]) {
		it(`keeps the ground under the pointer${tilted ? ' in a tilted view' : ''}`, () => {
			const { camera, controls, wheel } = wheelSetup(tilted);
			const ground = groundAt(camera, 700, 650)!;
			const range = controls.orbitPosition.length();
			wheel(700, 650, -100);
			expect(controls.orbitPosition.length()).toBeLessThan(range);
			const [x, y] = pixelOf(camera, ground);
			expect(x).toBeCloseTo(700, 1);
			expect(y).toBeCloseTo(650, 1);
		});
	}

	it('leaves the orbit alone where the host barred turning it', () => {
		const { camera, controls, wheel } = wheelSetup(false);
		controls.enableRotate = false;
		const before = camera.position.clone().normalize();
		wheel(700, 650, -100);
		expect(controls.orbitPosition.length()).toBeLessThan(ORBIT);
		expect(camera.position.clone().normalize().angleTo(before)).toBeLessThan(1e-12);
	});

	it('zooms on the centre off the ground', () => {
		const { camera, controls, wheel } = wheelSetup(false, 3);
		const before = camera.position.clone().normalize();
		wheel(990, 10, -100);
		expect(controls.orbitPosition.length()).toBeLessThan(3);
		expect(camera.position.clone().normalize().angleTo(before)).toBeLessThan(1e-12);
	});
});
