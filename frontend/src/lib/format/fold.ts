/** Lower case with no accents: a reader types "mocovi" for "Mocoví". */
export function foldForSearch(text: string): string {
	return text.normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase();
}
