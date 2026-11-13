/**
 * The French Republican calendar, 1793–1805 (and the Paris Commune's 1871).
 *
 * Twelve months of thirty days, each three décades of ten, then five or six
 * complementary days to close the year. The decree of 4 frimaire an II fixed
 * the year to the sky rather than to a leap rule: "chaque année commence à
 * minuit, avec le jour où tombe l'équinoxe vrai d'automne pour l'Observatoire
 * de Paris". So that is how it is computed here: the true September equinox,
 * in Paris apparent solar time. It reproduces the sextile years actually kept
 * (III, VII, XI), and the year a reader scrolls to in 2400 starts on the day
 * the decree says it would.
 *
 * Romme's arithmetic rule, proposed in 1795 and never adopted, is not used.
 */

import { tdbToUtc } from '$lib/time/jd';
import { jdnToGregorian } from './day-number';

/** Gregorian year whose September equinox opens an I. */
const EPOCH_GREGORIAN_YEAR = 1792;

/** Paris Observatory meridian, 2°20′14″ E, as a fraction of a day. */
const PARIS_LONGITUDE_DAYS = (2 + 20 / 60 + 14.025 / 3600) / 360;

const DEG = Math.PI / 180;

/** Meeus, Astronomical Algorithms, table 27.C: the periodic terms that move
 *  an equinox off its mean date (amplitude, phase °, rate °/century). */
const PERIODIC_TERMS: readonly (readonly [number, number, number])[] = [
	[485, 324.96, 1934.136],
	[203, 337.23, 32964.467],
	[199, 342.08, 20.186],
	[182, 27.85, 445267.112],
	[156, 73.14, 45036.886],
	[136, 171.52, 22518.443],
	[77, 222.54, 65928.934],
	[74, 296.72, 3034.906],
	[70, 243.58, 9037.513],
	[58, 119.81, 33718.147],
	[52, 297.17, 150.678],
	[50, 21.02, 2281.226],
	[45, 247.54, 29929.562],
	[44, 325.15, 31555.956],
	[29, 60.93, 4443.417],
	[18, 155.12, 67555.328],
	[17, 288.79, 4562.452],
	[16, 198.04, 62894.029],
	[14, 199.76, 31436.921],
	[12, 95.39, 14577.848],
	[12, 287.11, 31931.756],
	[12, 320.81, 34777.259],
	[9, 227.73, 1222.114],
	[8, 15.45, 16859.074]
];

/**
 * The September equinox of a Gregorian year, as a JDE (TT), after Meeus ch.
 * 27: good to a minute or so across −1000…3000. Outside that the polynomials
 * are extrapolated; they drift by days over millennia, which is still a year
 * of 365 or 366 days, so the calendar stays a calendar.
 */
export function septemberEquinoxJde(year: number): number {
	let jde0: number;
	if (year < 1000) {
		const y = year / 1000;
		jde0 =
			1721325.70455 + 365242.49558 * y - 0.11677 * y ** 2 - 0.00297 * y ** 3 + 0.00074 * y ** 4;
	} else {
		const y = (year - 2000) / 1000;
		jde0 =
			2451810.21715 + 365242.01767 * y - 0.11575 * y ** 2 + 0.00337 * y ** 3 + 0.00078 * y ** 4;
	}
	const t = (jde0 - 2451545) / 36525;
	const w = (35999.373 * t - 2.47) * DEG;
	const dLambda = 1 + 0.0334 * Math.cos(w) + 0.0007 * Math.cos(2 * w);
	let s = 0;
	for (const [a, b, c] of PERIODIC_TERMS) s += a * Math.cos((b + c * t) * DEG);
	return jde0 + (0.00001 * s) / dLambda;
}

/** Equation of time, in days: apparent minus mean solar time (Meeus 28.3). */
function equationOfTime(jd: number): number {
	const t = (jd - 2451545) / 36525;
	const l0 = (280.46646 + 36000.76983 * t + 0.0003032 * t * t) * DEG;
	const m = (357.52911 + 35999.05029 * t - 0.0001537 * t * t) * DEG;
	const e = 0.016708634 - 0.000042037 * t - 0.0000001267 * t * t;
	const epsilon = (23.439291 - 0.0130042 * t) * DEG;
	const y = Math.tan(epsilon / 2) ** 2;
	const radians =
		y * Math.sin(2 * l0) -
		2 * e * Math.sin(m) +
		4 * e * y * Math.sin(m) * Math.cos(2 * l0) -
		0.5 * y * y * Math.sin(4 * l0) -
		1.25 * e * e * Math.sin(2 * m);
	return radians / (2 * Math.PI);
}

const newYearCache = new Map<number, number>();

/** JDN of 1 vendémiaire of the Republican year that begins in Gregorian
 *  `gregorianYear`: the Paris apparent-time day holding the true equinox. */
function newYearJdn(gregorianYear: number): number {
	let jdn = newYearCache.get(gregorianYear);
	if (jdn === undefined) {
		const ut = tdbToUtc(septemberEquinoxJde(gregorianYear));
		const parisApparent = ut + PARIS_LONGITUDE_DAYS + equationOfTime(ut);
		jdn = Math.floor(parisApparent + 0.5);
		newYearCache.set(gregorianYear, jdn);
	}
	return jdn;
}

export interface RepublicanDate {
	/** an I is 1792–93. Years before it count down through 0, proleptically. */
	year: number;
	/** 1–12, and 13 for the complementary days. */
	month: number;
	/** 1–30, or 1–6 in month 13. */
	day: number;
	/** 1–10: primidi to décadi. Meaningless in month 13. */
	dayOfDecade: number;
	/** 5 or 6. */
	complementaryDays: number;
}

export function jdnToRepublican(jdn: number): RepublicanDate {
	let gYear = jdnToGregorian(jdn).year;
	let start = newYearJdn(gYear);
	if (jdn < start) start = newYearJdn(--gYear);
	const dayOfYear = jdn - start;
	const month = Math.floor(dayOfYear / 30) + 1;
	const day = (dayOfYear % 30) + 1;
	return {
		year: gYear - EPOCH_GREGORIAN_YEAR + 1,
		month,
		day,
		dayOfDecade: ((day - 1) % 10) + 1,
		complementaryDays: newYearJdn(gYear + 1) - start - 360
	};
}

export function republicanToJdn(year: number, month: number, day: number): number {
	return newYearJdn(year + EPOCH_GREGORIAN_YEAR - 1) + (month - 1) * 30 + day - 1;
}

// ---------------------------------------------------------------------------
// Names

interface RepublicanNames {
	months: readonly string[];
	/** The form a month takes after a day number, where the language inflects
	 *  it (Russian: "18 брюмера"). */
	monthsAfterDay?: readonly string[];
	/** The complementary days as a whole, for where a month name would go. */
	complementary: string;
	/** The six complementary days, which are feasts rather than numbered days. */
	feasts: readonly string[];
	/** Days of the décade. */
	weekdays?: readonly string[];
	/** Year numbers in Roman numerals, as the decrees wrote them. */
	roman: boolean;
	year: (y: string) => string;
	dayMonth: (d: string, m: string, day: number) => string;
	monthYear: (m: string, y: string) => string;
	full: (dayMonth: string, y: string) => string;
}

const FRENCH_MONTHS = [
	'Vendémiaire',
	'Brumaire',
	'Frimaire',
	'Nivôse',
	'Pluviôse',
	'Ventôse',
	'Germinal',
	'Floréal',
	'Prairial',
	'Messidor',
	'Thermidor',
	'Fructidor'
] as const;

const DECADE_DAYS = [
	'primidi',
	'duodi',
	'tridi',
	'quartidi',
	'quintidi',
	'sextidi',
	'septidi',
	'octidi',
	'nonidi',
	'décadi'
] as const;

const ENGLISH: RepublicanNames = {
	months: FRENCH_MONTHS,
	complementary: 'Sansculottides',
	feasts: [
		'Virtue Day',
		'Genius Day',
		'Labour Day',
		'Opinion Day',
		'Rewards Day',
		'Revolution Day'
	],
	roman: true,
	year: (y) => `Year ${y}`,
	dayMonth: (d, m) => `${d} ${m}`,
	monthYear: (m, y) => `${m}, Year ${y}`,
	full: (dm, y) => `${dm}, Year ${y}`
};

/**
 * The months as a British wag had them, shortly after the calendar itself:
 * Wheezy, Sneezy and Freezy; Slippy, Drippy and Nippy; Showery, Flowery and
 * Bowery; Hoppy, Croppy and Poppy. A reader in Britain gets these.
 */
const BRITISH: RepublicanNames = {
	...ENGLISH,
	months: [
		'Wheezy',
		'Sneezy',
		'Freezy',
		'Slippy',
		'Drippy',
		'Nippy',
		'Showery',
		'Flowery',
		'Bowery',
		'Hoppy',
		'Croppy',
		'Poppy'
	]
};

const NAMES: Record<string, RepublicanNames> = {
	en: ENGLISH,
	fr: {
		months: FRENCH_MONTHS.map((m) => m.toLowerCase()),
		complementary: 'sans-culottides',
		feasts: [
			'jour de la Vertu',
			'jour du Génie',
			'jour du Travail',
			"jour de l'Opinion",
			'jour des Récompenses',
			'jour de la Révolution'
		],
		roman: true,
		year: (y) => `an ${y}`,
		dayMonth: (d, m, day) => `${day === 1 ? '1er' : d} ${m}`,
		monthYear: (m, y) => `${m} an ${y}`,
		full: (dm, y) => `${dm} an ${y}`
	},
	de: {
		months: FRENCH_MONTHS,
		complementary: 'Sansculottiden',
		feasts: [
			'Tag der Tugend',
			'Tag des Genies',
			'Tag der Arbeit',
			'Tag der Meinung',
			'Tag der Belohnungen',
			'Tag der Revolution'
		],
		roman: true,
		year: (y) => `Jahr ${y}`,
		dayMonth: (d, m) => `${d}. ${m}`,
		monthYear: (m, y) => `${m} des Jahres ${y}`,
		full: (dm, y) => `${dm} des Jahres ${y}`
	},
	it: {
		months: [
			'vendemmiaio',
			'brumaio',
			'frimaio',
			'nevoso',
			'piovoso',
			'ventoso',
			'germinale',
			'fiorile',
			'pratile',
			'messidoro',
			'termidoro',
			'fruttidoro'
		],
		complementary: 'sanculottidi',
		feasts: [
			'giorno della Virtù',
			'giorno del Genio',
			'giorno del Lavoro',
			"giorno dell'Opinione",
			'giorno delle Ricompense',
			'giorno della Rivoluzione'
		],
		roman: true,
		year: (y) => `anno ${y}`,
		dayMonth: (d, m) => `${d} ${m}`,
		monthYear: (m, y) => `${m} anno ${y}`,
		full: (dm, y) => `${dm} anno ${y}`
	},
	es: {
		months: [
			'vendimiario',
			'brumario',
			'frimario',
			'nivoso',
			'pluvioso',
			'ventoso',
			'germinal',
			'floreal',
			'pradial',
			'mesidor',
			'termidor',
			'fructidor'
		],
		complementary: 'sansculótidas',
		feasts: [
			'día de la Virtud',
			'día del Genio',
			'día del Trabajo',
			'día de la Opinión',
			'día de las Recompensas',
			'día de la Revolución'
		],
		roman: true,
		year: (y) => `año ${y}`,
		dayMonth: (d, m) => `${d} de ${m}`,
		monthYear: (m, y) => `${m} del año ${y}`,
		full: (dm, y) => `${dm} del año ${y}`
	},
	pt: {
		months: [
			'vindemiário',
			'brumário',
			'frimário',
			'nivoso',
			'pluvioso',
			'ventoso',
			'germinal',
			'floreal',
			'prairial',
			'messidor',
			'termidor',
			'frutidor'
		],
		complementary: 'sans-culottides',
		feasts: [
			'dia da Virtude',
			'dia do Gênio',
			'dia do Trabalho',
			'dia da Opinião',
			'dia das Recompensas',
			'dia da Revolução'
		],
		roman: true,
		year: (y) => `ano ${y}`,
		dayMonth: (d, m) => `${d} de ${m}`,
		monthYear: (m, y) => `${m} do ano ${y}`,
		full: (dm, y) => `${dm} do ano ${y}`
	},
	ru: {
		months: [
			'вандемьер',
			'брюмер',
			'фример',
			'нивоз',
			'плювиоз',
			'вантоз',
			'жерминаль',
			'флореаль',
			'прериаль',
			'мессидор',
			'термидор',
			'фрюктидор'
		],
		monthsAfterDay: [
			'вандемьера',
			'брюмера',
			'фримера',
			'нивоза',
			'плювиоза',
			'вантоза',
			'жерминаля',
			'флореаля',
			'прериаля',
			'мессидора',
			'термидора',
			'фрюктидора'
		],
		complementary: 'санкюлотиды',
		feasts: [
			'День добродетели',
			'День гения',
			'День труда',
			'День убеждений',
			'День наград',
			'День революции'
		],
		roman: true,
		year: (y) => `${y} год`,
		dayMonth: (d, m) => `${d} ${m}`,
		monthYear: (m, y) => `${m} ${y} года`,
		full: (dm, y) => `${dm} ${y} года`
	},
	pl: {
		months: FRENCH_MONTHS.map((m) => m.toLowerCase()),
		complementary: 'sankiulotydy',
		feasts: [
			'Dzień Cnoty',
			'Dzień Geniuszu',
			'Dzień Pracy',
			'Dzień Opinii',
			'Dzień Nagród',
			'Dzień Rewolucji'
		],
		roman: true,
		year: (y) => `rok ${y}`,
		dayMonth: (d, m) => `${d} ${m}`,
		monthYear: (m, y) => `${m} roku ${y}`,
		full: (dm, y) => `${dm} roku ${y}`
	},
	ja: {
		months: [
			'葡萄月',
			'霧月',
			'霜月',
			'雪月',
			'雨月',
			'風月',
			'芽月',
			'花月',
			'牧草月',
			'収穫月',
			'熱月',
			'実月'
		],
		complementary: 'サンキュロットの日',
		feasts: ['美徳の日', '才能の日', '労働の日', '意見の日', '褒賞の日', '革命の日'],
		roman: false,
		year: (y) => `共和暦${y}年`,
		dayMonth: (d, m) => `${m}${d}日`,
		monthYear: (m, y) => `共和暦${y}年${m}`,
		full: (dm, y) => `共和暦${y}年${dm}`
	},
	zh: {
		months: [
			'葡月',
			'雾月',
			'霜月',
			'雪月',
			'雨月',
			'风月',
			'芽月',
			'花月',
			'牧月',
			'获月',
			'热月',
			'果月'
		],
		complementary: '无套裤汉日',
		feasts: ['美德节', '天才节', '劳动节', '舆论节', '奖赏节', '革命节'],
		roman: false,
		year: (y) => `共和历${y}年`,
		dayMonth: (d, m) => `${m}${d}日`,
		monthYear: (m, y) => `共和历${y}年${m}`,
		full: (dm, y) => `共和历${y}年${dm}`
	},
	ar: {
		months: [
			'فاندميير',
			'برومير',
			'فريمير',
			'نيفوز',
			'بلوفيوز',
			'فانتوز',
			'جرمينال',
			'فلوريال',
			'بريريال',
			'ميسيدور',
			'ترميدور',
			'فروكتيدور'
		],
		complementary: 'أيام السانكولوت',
		feasts: ['يوم الفضيلة', 'يوم العبقرية', 'يوم العمل', 'يوم الرأي', 'يوم المكافآت', 'يوم الثورة'],
		roman: false,
		year: (y) => `السنة ${y}`,
		dayMonth: (d, m) => `${d} ${m}`,
		monthYear: (m, y) => `${m}، السنة ${y}`,
		full: (dm, y) => `${dm}، السنة ${y}`
	},
	he: {
		months: [
			'ונדמייר',
			'ברומר',
			'פרימר',
			'ניבוז',
			'פלוביוז',
			'ונטוז',
			"ז'רמינל",
			'פלוראל',
			'פרריאל',
			'מסידור',
			'תרמידור',
			'פרוקטידור'
		],
		complementary: 'ימי הסאנקילוטים',
		feasts: ['יום המידה הטובה', 'יום הגאונות', 'יום העבודה', 'יום הדעה', 'יום הגמול', 'יום המהפכה'],
		roman: false,
		year: (y) => `שנה ${y}`,
		dayMonth: (d, m) => `${d} ב${m}`,
		monthYear: (m, y) => `${m}, שנה ${y}`,
		full: (dm, y) => `${dm}, שנה ${y}`
	}
};

/** Whether the reader is British: English on the page, and the browser's
 *  first English preference is en-GB. */
function readerIsBritish(locale: string): boolean {
	if (locale.split('-')[0] !== 'en') return false;
	if (/^en-(GB|UK)\b/i.test(locale)) return true;
	if (typeof navigator === 'undefined') return false;
	const languages = navigator.languages?.length ? navigator.languages : [navigator.language];
	const english = languages.find((tag) => tag?.toLowerCase().startsWith('en'));
	return english !== undefined && /^en-(GB|UK)\b/i.test(english);
}

function namesFor(locale: string): RepublicanNames {
	if (readerIsBritish(locale)) return BRITISH;
	return NAMES[locale.split('-')[0]] ?? ENGLISH;
}

/** The ten days of the décade, primidi to décadi, for a picker's columns. */
export function decadeDayNames(locale: string): readonly string[] {
	return namesFor(locale).weekdays ?? DECADE_DAYS;
}

const ROMAN: readonly [number, string][] = [
	[1000, 'M'],
	[900, 'CM'],
	[500, 'D'],
	[400, 'CD'],
	[100, 'C'],
	[90, 'XC'],
	[50, 'L'],
	[40, 'XL'],
	[10, 'X'],
	[9, 'IX'],
	[5, 'V'],
	[4, 'IV'],
	[1, 'I']
];

/** Roman numerals stop at 3999 and never had a zero or a minus; past those
 *  the year is written in figures. */
export function toRoman(n: number): string | null {
	if (!Number.isInteger(n) || n < 1 || n > 3999) return null;
	let out = '';
	for (const [value, numeral] of ROMAN) {
		while (n >= value) {
			out += numeral;
			n -= value;
		}
	}
	return out;
}

export interface RepublicanFormatOptions {
	year?: boolean;
	month?: boolean;
	day?: boolean;
	weekday?: boolean;
}

/** One Republican date in words, holding only the fields asked for. */
export function formatRepublican(
	date: RepublicanDate,
	locale: string,
	{ year = false, month = false, day = false, weekday = false }: RepublicanFormatOptions
): string {
	const names = namesFor(locale);
	const number = new Intl.NumberFormat(locale, { useGrouping: false });
	const yearText = (names.roman && toRoman(date.year)) || number.format(date.year);
	const complementary = date.month === 13;

	let dayMonth: string | undefined;
	if (day && month) {
		dayMonth = complementary
			? names.feasts[date.day - 1]
			: names.dayMonth(
					number.format(date.day),
					(names.monthsAfterDay ?? names.months)[date.month - 1],
					date.day
				);
		if (weekday && !complementary) {
			dayMonth = `${(names.weekdays ?? DECADE_DAYS)[date.dayOfDecade - 1]} ${dayMonth}`;
		}
	}
	const monthName = complementary ? names.complementary : names.months[date.month - 1];

	if (dayMonth !== undefined) return year ? names.full(dayMonth, yearText) : dayMonth;
	if (month) return year ? names.monthYear(monthName, yearText) : monthName;
	if (day) return number.format(date.day);
	return names.year(yearText);
}
