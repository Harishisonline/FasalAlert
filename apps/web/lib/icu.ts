/**
 * A small ICU MessageFormat subset: {arg}, {arg, plural, =0 {..} one {..} other {..}} with #,
 * and {arg, select, a {..} other {..}}. Nested messages are supported. No string concatenation
 * is needed in components because word order differs between mr, hi and en (design.md 18.3).
 */
type Node =
  | { t: 'text'; v: string }
  | { t: 'arg'; name: string }
  | { t: 'pound' }
  | { t: 'plural'; name: string; options: Record<string, Node[]> }
  | { t: 'select'; name: string; options: Record<string, Node[]> };

export type MessageValues = Record<string, string | number | null | undefined>;

class Parser {
  i = 0;
  constructor(private readonly s: string) {}

  parseMessage(inPlural: boolean, endChar?: string): Node[] {
    const out: Node[] = [];
    let text = '';
    const flush = () => {
      if (text) out.push({ t: 'text', v: text });
      text = '';
    };
    while (this.i < this.s.length) {
      const c = this.s[this.i]!;
      if (endChar && c === endChar) break;
      if (c === "'" && this.s[this.i + 1] === "'") {
        text += "'";
        this.i += 2;
        continue;
      }
      if (c === '{') {
        flush();
        out.push(this.parseArgument());
        continue;
      }
      if (c === '#' && inPlural) {
        flush();
        out.push({ t: 'pound' });
        this.i++;
        continue;
      }
      text += c;
      this.i++;
    }
    flush();
    return out;
  }

  private skipWs() {
    while (this.i < this.s.length && /\s/.test(this.s[this.i]!)) this.i++;
  }

  private readIdent(): string {
    this.skipWs();
    const start = this.i;
    while (this.i < this.s.length && /[^\s,{}]/.test(this.s[this.i]!)) this.i++;
    return this.s.slice(start, this.i);
  }

  private parseArgument(): Node {
    this.i++; // {
    const name = this.readIdent();
    this.skipWs();
    if (this.s[this.i] === '}') {
      this.i++;
      return { t: 'arg', name };
    }
    if (this.s[this.i] !== ',') throw new Error(`ICU: expected , after ${name}`);
    this.i++;
    const kind = this.readIdent();
    this.skipWs();
    if (this.s[this.i] !== ',') throw new Error(`ICU: expected , after ${kind}`);
    this.i++;
    const options: Record<string, Node[]> = {};
    for (;;) {
      this.skipWs();
      if (this.s[this.i] === '}') {
        this.i++;
        break;
      }
      const key = this.readIdent();
      this.skipWs();
      if (this.s[this.i] !== '{') throw new Error(`ICU: expected { after option ${key}`);
      this.i++;
      options[key] = this.parseMessage(kind === 'plural', '}');
      if (this.s[this.i] !== '}') throw new Error('ICU: unterminated option');
      this.i++;
    }
    if (kind === 'plural') return { t: 'plural', name, options };
    if (kind === 'select') return { t: 'select', name, options };
    throw new Error(`ICU: unsupported argument type ${kind}`);
  }
}

const cache = new Map<string, Node[]>();

export function parseMessage(message: string): Node[] {
  let nodes = cache.get(message);
  if (!nodes) {
    nodes = new Parser(message).parseMessage(false);
    cache.set(message, nodes);
  }
  return nodes;
}

export function formatMessage(
  message: string,
  values: MessageValues,
  intlLocale: string,
): string {
  const nf = new Intl.NumberFormat(intlLocale);
  const pr = new Intl.PluralRules(intlLocale);
  const render = (nodes: Node[], pound?: number): string =>
    nodes
      .map((n) => {
        switch (n.t) {
          case 'text':
            return n.v;
          case 'pound':
            return pound === undefined ? '#' : nf.format(pound);
          case 'arg': {
            const v = values[n.name];
            if (v === undefined || v === null) return '';
            return typeof v === 'number' ? nf.format(v) : v;
          }
          case 'plural': {
            const raw = values[n.name];
            const num = typeof raw === 'number' ? raw : Number(raw);
            const exact = n.options[`=${num}`];
            const cat = pr.select(num);
            const chosen = exact ?? n.options[cat] ?? n.options.other ?? [];
            return render(chosen, num);
          }
          case 'select': {
            const raw = values[n.name];
            const key = raw === undefined || raw === null ? 'other' : String(raw);
            return render(n.options[key] ?? n.options.other ?? [], pound);
          }
        }
      })
      .join('');
  return render(parseMessage(message));
}

/** Names of every argument used in a message (used by the parity check). */
export function argumentNames(message: string): string[] {
  const names = new Set<string>();
  const walk = (nodes: Node[]) => {
    for (const n of nodes) {
      if (n.t === 'arg') names.add(n.name);
      if (n.t === 'plural' || n.t === 'select') {
        names.add(n.name);
        Object.values(n.options).forEach(walk);
      }
    }
  };
  walk(parseMessage(message));
  return [...names].sort();
}
