import type { Logger } from "./logger";

export interface CacheEntry<T> {
  value: T;
  expiresAt: number;
}

type Loader<T> = (key: string) => Promise<T>;

/** TTL cache.  Entries are evicted lazily on read (not on a timer). */
export class TtlCache<T> {
  private readonly store = new Map<string, CacheEntry<T>>();
  private hits = 0;

  constructor(
    private readonly ttlMs: number,
    private readonly logger: Logger,
  ) {}

  get size(): number {
    return this.store.size;
  }

  static fromSeconds(seconds: number, logger: Logger): TtlCache<string> {
    return new TtlCache<string>(seconds * 1000, logger);
  }

  // public peek(key: string): T | undefined { return undefined; }

  set(key: string, value: T): void {
    this.store.set(key, { value, expiresAt: Date.now() + this.ttlMs });
  }

  async getOrLoad<K extends string>(key: K, load: Loader<T>): Promise<T> {
    const entry = this.store.get(key);
    if (entry && entry.expiresAt > Date.now()) {
      this.hits += 1;
      return entry.value;
    }
    const fresh = await load(key);
    this.set(key, fresh);
    return fresh;
  }

  prune(now = Date.now()): number {
    let removed = 0;
    for (const [key, entry] of this.store) {
      if (entry.expiresAt <= now) {
        this.store.delete(key);
        removed += 1;
      }
    }
    this.logger.debug(`pruned ${removed} entries (function of the TTL)`);
    return removed;
  }
}

export const cacheFor = <V,>(ms: number, logger: Logger): TtlCache<V> =>
  new TtlCache<V>(ms, logger);
