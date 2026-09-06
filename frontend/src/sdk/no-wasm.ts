/** Stands in for satellite.js's optional WASM runtime, which nothing here
 *  calls: bundling it would add 310 kB and a top-level await for nothing. */
export default function unavailable(): never {
	throw new Error('satellite.js WASM runtime is not bundled in the spacemap SDK');
}
