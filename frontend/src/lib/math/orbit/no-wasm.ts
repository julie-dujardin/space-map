/** Stands in for satellite.js's optional WASM runtime, which nothing here
 *  calls: bundled, it is a 310 kB chunk with a top-level await for nothing. */
export default function unavailable(): never {
	throw new Error('satellite.js WASM runtime is not bundled');
}
