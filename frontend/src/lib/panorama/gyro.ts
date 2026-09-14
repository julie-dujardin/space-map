/**
 * The device orientation sensor behind the panorama's motion controls. Its own
 * module so the settings menu can ask whether the sensor is within reach
 * without pulling in the view, and the renderer with it.
 */

/** Why the sensor cannot drive the view, where it cannot: `insecure` for a page
 *  outside a secure context, which browsers withhold the event from,
 *  `unsupported` for anything but a handheld. */
export type GyroAvailability = 'available' | 'insecure' | 'unsupported';

export function gyroAvailability(): GyroAvailability {
	if (typeof window === 'undefined') return 'unsupported';
	if (!window.isSecureContext) return 'insecure';
	// Desktop browsers define the event and never fire it.
	return 'DeviceOrientationEvent' in window && window.matchMedia('(pointer: coarse)').matches
		? 'available'
		: 'unsupported';
}

/** Ask for the sensor where it is gated, which iOS only grants inside the
 *  gesture that asked. */
export async function requestGyroPermission(): Promise<boolean> {
	const request = (
		DeviceOrientationEvent as unknown as { requestPermission?: () => Promise<string> }
	).requestPermission;
	if (typeof request !== 'function') return true;
	try {
		return (await request.call(DeviceOrientationEvent)) === 'granted';
	} catch {
		return false;
	}
}
