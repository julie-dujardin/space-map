import { Vector3 } from 'three';
import { describe, expect, it } from 'vitest';
import { stopAtCamera } from './stop-at-camera';

const EYE = new Vector3(0, 0, 0);
const AHEAD = new Vector3(0, 0, -1);
const CLEARANCE = 1;

/** A line along the view axis, at these distances ahead of the camera. */
function line(...depths: number[]): Float32Array {
	return Float32Array.from(depths.flatMap((depth) => [depth, 0, -depth]));
}

/** The depth of each sample of a line, as the camera sees it. */
const depths = (positions: Float32Array) => Array.from(positions.filter((_, i) => i % 3 === 0));

describe('stopAtCamera', () => {
	it('leaves a line with both ends ahead of the camera, whatever its middle does', () => {
		const positions = line(5, -3, 8);
		stopAtCamera(positions, 3, EYE, AHEAD, CLEARANCE);
		expect(positions).toEqual(line(5, -3, 8));
	});

	it('leaves a line that is all behind the camera', () => {
		const positions = line(-5, -2);
		stopAtCamera(positions, 2, EYE, AHEAD, CLEARANCE);
		expect(positions).toEqual(line(-5, -2));
	});

	it('stops the start of a line just ahead of the camera, on the segment that crosses', () => {
		const positions = line(-20, -10, 10, 30);
		stopAtCamera(positions, 4, EYE, AHEAD, CLEARANCE);
		expect(depths(positions)).toEqual([1, 1, 10, 30]);
	});

	it('stops the end of a line the same way', () => {
		const positions = line(30, 10, -10, -20);
		stopAtCamera(positions, 4, EYE, AHEAD, CLEARANCE);
		expect(depths(positions)).toEqual([30, 10, 1, 1]);
	});

	it('stops both ends of a line that passes ahead of the camera', () => {
		const positions = line(-10, 10, 10, -10);
		stopAtCamera(positions, 4, EYE, AHEAD, CLEARANCE);
		expect(depths(positions)).toEqual([1, 10, 10, 1]);
	});
});
