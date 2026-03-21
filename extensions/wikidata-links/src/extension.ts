import * as vscode from "vscode";

const WIKIDATA_ID_PATTERN = /\b([QP]\d+)\b/g;

function wikidataUrl(id: string): string {
  if (id.startsWith("P")) {
    return `https://www.wikidata.org/wiki/Property:${id}`;
  }
  return `https://www.wikidata.org/wiki/${id}`;
}

class WikidataLinkProvider implements vscode.DocumentLinkProvider {
  provideDocumentLinks(document: vscode.TextDocument): vscode.DocumentLink[] {
    const links: vscode.DocumentLink[] = [];
    const text = document.getText();
    let match: RegExpExecArray | null;

    while ((match = WIKIDATA_ID_PATTERN.exec(text)) !== null) {
      const id = match[1];
      const startPos = document.positionAt(match.index);
      const endPos = document.positionAt(match.index + id.length);
      const range = new vscode.Range(startPos, endPos);
      const uri = vscode.Uri.parse(wikidataUrl(id));
      const link = new vscode.DocumentLink(range, uri);
      link.tooltip = `Open ${id} on Wikidata`;
      links.push(link);
    }

    return links;
  }
}

export function activate(context: vscode.ExtensionContext): void {
  const disposable = vscode.languages.registerDocumentLinkProvider(
    { scheme: "file" },
    new WikidataLinkProvider()
  );
  context.subscriptions.push(disposable);
}

export function deactivate(): void {}
