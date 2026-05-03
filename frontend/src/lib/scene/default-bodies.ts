/**
 * Minor body IDs that should be auto-promoted from point clouds to individual
 * 3D meshes with labels on initial load. One body is promoted per frame to
 * spread GPU work.
 */
export const DEFAULT_PROMOTED_IDS: ReadonlySet<string> = new Set([
	// Spacecraft (deep-space, NAIF trajectories)
	'naif--31', // Voyager 1
	'naif--32', // Voyager 2
	'naif--23', // Pioneer 10
	'naif--24', // Pioneer 11
	'naif--98', // New Horizons
	'naif--96', // Parker Solar Probe
	'naif--170', // James Webb Space Telescope
	'naif--49', // Lucy
	'naif--255', // Psyche
	'naif--159', // Europa Clipper
	'naif--64', // OSIRIS-REx
	'naif--121', // BepiColombo
	'naif--144', // Solar Orbiter
	'naif--37', // Hayabusa 2
	'naif--91', // Hera
	'naif--28', // JUICE
	'naif--227', // Kepler
	'naif--234', // STEREO-A
	'naif--21', // SOHO
	'naif--78', // DSCOVR
	'naif--55', // Ulysses

	// Retired
	// 'naif--79', // Spitzer Space Telescope
	// 'naif--203', // Dawn

	// Mars/moon/... probes - TODO
	// 'naif--41', // Mars Express
	// 'naif--53', // Mars Odyssey
	// 'naif--74', // Mars Reconnaissance Orbiter
	// 'naif--76', // Mars Science Laboratory (Curiosity)
	// 'naif--143', // ExoMars16 TGO
	// 'naif--189', // InSight
	// 'naif--85', // LRO
	// 'naif--61', // Juno

	// Earth-orbiting (NORAD/CelesTrak TLEs)
	'norad_satcat-20580', // HST (Hubble)
	'norad_satcat-25544', // ISS (Zarya)
	'norad_satcat-43435', // TESS
	'norad_satcat-25867', // CXO (Chandra)
	'norad_satcat-48274', // CSS Tianhe (Tiangong)

	// Asteroids (visited, hazardous, or otherwise famous)
	'spkid-20000002', // 2 Pallas
	'spkid-20000003', // 3 Juno
	'spkid-20000004', // 4 Vesta
	'spkid-20000010', // 10 Hygiea
	'spkid-20000016', // 16 Psyche
	'spkid-20000243', // 243 Ida
	'spkid-20000253', // 253 Mathilde
	'spkid-20000433', // 433 Eros
	'spkid-20000511', // 511 Davida
	'spkid-20000588', // 588 Achilles
	'spkid-20000624', // 624 Hektor
	'spkid-20000704', // 704 Interamnia
	'spkid-20000951', // 951 Gaspra
	'spkid-20001862', // 1862 Apollo
	'spkid-20002060', // 2060 Chiron
	'spkid-20004179', // 4179 Toutatis
	'spkid-20025143', // 25143 Itokawa
	'spkid-20099942', // 99942 Apophis
	'spkid-20101955', // 101955 Bennu
	'spkid-20162173', // 162173 Ryugu
	'spkid-20486958', // 486958 Arrokoth
	'spkid-3788040', // 1I/ʻOumuamua

	// Comets
	'spkid-1000036', // 1P/Halley
	'spkid-1000025', // 2P/Encke
	'spkid-1000093', // 9P/Tempel 1
	'spkid-1000109', // 46P/Wirtanen
	'spkid-1000012', // 67P/Churyumov-Gerasimenko
	'spkid-1000107', // 81P/Wild 2
	'spkid-1000041', // 103P/Hartley 2
	'spkid-1000132', // C/1995 O1 (Hale-Bopp)
	'spkid-1003667', // C/2020 F3 (NEOWISE)
	'spkid-1003913' // C/2023 A3 (Tsuchinshan-ATLAS)
]);
