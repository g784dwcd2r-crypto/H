// Per-browser memory: recently opened companies and the watchlist. No account needed.
export type Remembered = { cik: number; name: string; ticker: string | null };

const RECENT = "fh:recent";
const WATCH = "fh:watchlist";

function read<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* private mode or full: forget silently */
  }
}

export const recents = {
  list: (): Remembered[] => read<Remembered[]>(RECENT, []),
  remember: (c: Remembered) => {
    const rest = recents.list().filter((x) => x.cik !== c.cik);
    write(RECENT, [c, ...rest].slice(0, 8));
  },
};

export const watchlist = {
  list: (): Remembered[] => read<Remembered[]>(WATCH, []),
  has: (cik: number) => watchlist.list().some((x) => x.cik === cik),
  toggle: (c: Remembered): boolean => {
    const cur = watchlist.list();
    const on = cur.some((x) => x.cik === c.cik);
    write(WATCH, on ? cur.filter((x) => x.cik !== c.cik) : [...cur, c]);
    return !on;
  },
};
