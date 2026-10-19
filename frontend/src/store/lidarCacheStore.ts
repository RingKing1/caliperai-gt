import { create } from 'zustand';
import { dataApi } from '@/api/client';
import type { Frame, Scene } from '@/types';

// Level of detail: 'coarse' = deterministic ~1/4 subsample for neighbouring
// frames, 'full' = every point for the current frame.
type LidarTier = 'full' | 'coarse';

interface PointCloudData {
  positions: Float32Array;
  intensities: Float32Array;
  pointCount: number;
  lod?: LidarTier;
}

interface CacheEntry {
  data: PointCloudData;
  loadedAt: number;
  size: number;
  tier: LidarTier;
}

type PrefetchStatus = 'idle' | 'prefetching' | 'complete' | 'error';

interface LidarCacheState {
  cache: Map<string, CacheEntry>;

  prefetchStatus: PrefetchStatus;
  prefetchProgress: number;
  prefetchTotal: number;
  prefetchLoaded: number;
  prefetchErrors: string[];

  currentSceneId: string | null;
  abortController: AbortController | null;

  // Bumped whenever a full cloud replaces a coarse placeholder; consumers
  // (react-query) watch it to upgrade the rendered current frame.
  fullUpgradeTick: number;

  startPrefetch: (scene: Scene, frames: Frame[], centerOffset?: number) => void;
  prefetchAround: (scene: Scene, frames: Frame[], centerIndex: number, windowSize?: number) => void;
  // Kick off a full-tier fetch for a path currently holding coarse data.
  ensureFull: (path: string) => void;
  cancelPrefetch: () => void;
  getCached: (filePath: string, allowCoarse?: boolean) => PointCloudData | null;
  clearCache: () => void;

  getCacheStats: () => { entries: number; totalSize: number; hitRate: number };
}

let cacheHits = 0;
let cacheMisses = 0;

const MAX_CONCURRENT = 6;
const MAX_CONCURRENT_COARSE = 6;

const MAX_CACHE_SIZE = 500 * 1024 * 1024;

// Dedupes in-flight fetches by path+tier.
const inflightLidar = new Set<string>();

// Persistent controller for quiet rolling prefetch; survives the initial
// prefetch completing (store keeps the signal usable across frame changes).
let rollingController: AbortController | null = null;

export const useLidarCacheStore = create<LidarCacheState>((set, get) => ({
  cache: new Map(),
  prefetchStatus: 'idle',
  prefetchProgress: 0,
  prefetchTotal: 0,
  prefetchLoaded: 0,
  prefetchErrors: [],
  currentSceneId: null,
  abortController: null,
  fullUpgradeTick: 0,

  startPrefetch: (scene: Scene, frames: Frame[], centerOffset?: number) => {
    const state = get();

    if (state.currentSceneId === scene.id && (state.prefetchStatus === 'prefetching' || state.prefetchStatus === 'complete')) {
      return;
    }

    state.abortController?.abort();

    const abortController = new AbortController();
    rollingController = abortController;
    const lidarBase = scene.storage_paths?.lidar_base?.replace(/\/$/, '') || '';

    if (!lidarBase) return;

    const center = centerOffset ?? Math.floor(frames.length / 2);
    const items = buildWindowItems(frames, lidarBase, center, frames.length - 1);
    const plan = planTierItems(items, get().cache);

    if (plan.length === 0) {
      set({
        prefetchStatus: 'complete',
        prefetchProgress: 100,
        prefetchTotal: items.length,
        prefetchLoaded: items.length,
        currentSceneId: scene.id,
        abortController: null,
      });
      return;
    }

    set({
      prefetchStatus: 'prefetching',
      prefetchProgress: 0,
      prefetchTotal: plan.length,
      prefetchLoaded: 0,
      prefetchErrors: [],
      currentSceneId: scene.id,
      abortController,
    });

    void prefetchTiered(plan, abortController.signal, set, get, { reportProgress: true });
  },

  prefetchAround: (scene: Scene, frames: Frame[], centerIndex: number, windowSize = 3) => {
    const lidarBase = scene.storage_paths?.lidar_base?.replace(/\/$/, '') || '';
    if (!lidarBase) return;

    if (!rollingController || rollingController.signal.aborted) {
      rollingController = new AbortController();
    }
    const signal = rollingController.signal;

    const lo = Math.max(0, centerIndex - windowSize);
    const hi = Math.min(frames.length - 1, centerIndex + windowSize);
    const windowFrames = frames.slice(lo, hi + 1);
    const items = buildWindowItems(windowFrames, lidarBase, centerIndex - lo, windowSize);
    const plan = planTierItems(items, get().cache);
    if (plan.length === 0) return;

    // Quiet: UI progress bar is not reset while scrubbing.
    void prefetchTiered(plan, signal, set, get, { reportProgress: false });
  },

  ensureFull: (path: string) => {
    const entry = get().cache.get(path);
    if (entry?.tier === 'full') return;
    const key = `full:${path}`;
    if (inflightLidar.has(key)) return;
    if (!rollingController || rollingController.signal.aborted) {
      rollingController = new AbortController();
    }
    void fetchOneTier(path, 'full', rollingController.signal, set, get);
  },

  cancelPrefetch: () => {
    const state = get();
    state.abortController?.abort();
    rollingController?.abort();
    rollingController = null;
    set({
      prefetchStatus: 'idle',
      abortController: null,
    });
  },

  // Full tier by default (the current frame renders every point). Pass
  // allowCoarse=true to show the ~1/4 placeholder while full is loading.
  getCached: (filePath: string, allowCoarse = false): PointCloudData | null => {
    const entry = get().cache.get(filePath);
    if (entry && (entry.tier === 'full' || allowCoarse)) {
      cacheHits++;
      return entry.data;
    }
    cacheMisses++;
    return null;
  },

  clearCache: () => {
    const state = get();
    state.abortController?.abort();
    rollingController?.abort();
    rollingController = null;
    inflightLidar.clear();
    cacheHits = 0;
    cacheMisses = 0;
    set({
      cache: new Map(),
      prefetchStatus: 'idle',
      prefetchProgress: 0,
      prefetchTotal: 0,
      prefetchLoaded: 0,
      prefetchErrors: [],
      currentSceneId: null,
      abortController: null,
    });
    console.log('[LiDAR Cache] Cache cleared');
  },

  getCacheStats: () => {
    const cache = get().cache;
    let totalSize = 0;
    cache.forEach(entry => {
      totalSize += entry.size;
    });
    const total = cacheHits + cacheMisses;
    return {
      entries: cache.size,
      totalSize,
      hitRate: total > 0 ? (cacheHits / total) * 100 : 0,
    };
  },
}));

// ---------------------------------------------------------------------------
// Tiered prefetch helpers

type TierItem = { path: string; tier: LidarTier; distance: number };

// Window plan: the frame at centerOffset is full LOD, every other frame in
// the slice is coarse. Caller passes the already-sliced frame window.
function buildWindowItems(
  frames: Frame[],
  lidarBase: string,
  centerOffset: number,
  _maxDistance: number,
): TierItem[] {
  const items: TierItem[] = [];
  frames.forEach((frame, offset) => {
    if (!frame.file_paths?.lidar) return;
    items.push({
      path: `${lidarBase}/${frame.file_paths.lidar}`,
      tier: offset === centerOffset ? 'full' : 'coarse',
      distance: Math.abs(offset - centerOffset),
    });
  });
  return items;
}

// Drop items already satisfied: full cache satisfies both tiers; a full item
// whose cache only holds coarse still needs fetching (upgrade).
function planTierItems(items: TierItem[], cache: Map<string, CacheEntry>): TierItem[] {
  return items.filter((item) => {
    const key = `${item.tier}:${item.path}`;
    if (inflightLidar.has(key)) return false;
    const entry = cache.get(item.path);
    if (!entry) return true;
    if (item.tier === 'full' && entry.tier !== 'full') return true;
    return false;
  }).sort((a, b) => {
    // Full before coarse, then proximity to the centre.
    if (a.tier !== b.tier) return a.tier === 'full' ? -1 : 1;
    return a.distance - b.distance;
  });
}

type StoreSet = (partial: Partial<LidarCacheState> | ((state: LidarCacheState) => Partial<LidarCacheState>)) => void;
type StoreGet = () => LidarCacheState;

function putCloud(
  set: StoreSet,
  path: string,
  tier: LidarTier,
  response: { positions: Float32Array; intensities: Float32Array; pointCount: number },
) {
  const size = response.positions.byteLength + response.intensities.byteLength + 4;
  let upgraded = false;
  set((state) => {
    const newCache = new Map(state.cache);
    const previous = newCache.get(path);
    if (previous?.tier === 'full') return {};
    if (previous && previous.tier === tier && previous.data.pointCount === response.pointCount) return {};
    if (previous?.tier === 'coarse' && tier === 'full') upgraded = true;

    let currentSize = 0;
    newCache.forEach((e) => { currentSize += e.size; });
    if (previous) currentSize -= previous.size;
    if (currentSize + size > MAX_CACHE_SIZE) {
      const sorted = Array.from(newCache.entries()).sort((a, b) => a[1].loadedAt - b[1].loadedAt);
      while (currentSize + size > MAX_CACHE_SIZE && sorted.length > 0) {
        const [oldPath, oldEntry] = sorted.shift()!;
        if (oldPath === path) continue;
        currentSize -= oldEntry.size;
        newCache.delete(oldPath);
      }
    }
    newCache.set(path, {
      data: { positions: response.positions, intensities: response.intensities, pointCount: response.pointCount, lod: tier },
      loadedAt: Date.now(),
      size,
      tier,
    });
    return { cache: newCache, ...(upgraded ? { fullUpgradeTick: state.fullUpgradeTick + 1 } : {}) };
  });
}

async function fetchOneTier(
  path: string,
  tier: LidarTier,
  signal: AbortSignal,
  set: StoreSet,
  get: StoreGet,
): Promise<boolean> {
  const key = `${tier}:${path}`;
  if (inflightLidar.has(key)) return false;
  inflightLidar.add(key);
  try {
    const response = await dataApi.getLidarData(path, tier === 'coarse' ? { lod: 'coarse' } : undefined);
    if (!signal.aborted) putCloud(set, path, tier, response);
    return true;
  } catch (err) {
    if (!signal.aborted) console.warn('[LiDAR Cache] fetch failed', tier, path.split('/').pop(), err);
    return false;
  } finally {
    inflightLidar.delete(key);
  }
  void get;
}

async function runLidarPool(items: TierItem[], limit: number, signal: AbortSignal, set: StoreSet, get: StoreGet) {
  let next = 0;
  const runners = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (next < items.length) {
      const item = items[next++];
      await fetchOneTier(item.path, item.tier, signal, set, get);
    }
  });
  await Promise.all(runners);
}

// Fetch full-tier items first (instant scrubbing onto real data), then coarse
// neighbours for fluid playback.
async function prefetchTiered(
  items: TierItem[],
  signal: AbortSignal,
  set: StoreSet,
  get: StoreGet,
  opts: { reportProgress: boolean },
) {
  const fullItems = items.filter((i) => i.tier === 'full');
  const coarseItems = items.filter((i) => i.tier === 'coarse');
  let loaded = 0;
  const total = items.length;

  const tick = () => {
    if (!opts.reportProgress || signal.aborted) return;
    loaded++;
    set((s) => ({
      prefetchLoaded: (s.prefetchLoaded ?? 0) + 1,
      prefetchProgress: s.prefetchTotal > 0 ? Math.min(100, Math.round((s.prefetchLoaded / s.prefetchTotal) * 100)) : 0,
    }));
  };

  await runLidarPool(fullItems, MAX_CONCURRENT, signal, set, get);
  loaded += fullItems.length;
  if (opts.reportProgress) {
    set((s) => ({ prefetchLoaded: Math.max(s.prefetchLoaded, loaded), prefetchProgress: total ? Math.round((loaded / total) * 100) : 100 }));
  }
  if (signal.aborted) return;

  const coarseBatchSize = MAX_CONCURRENT_COARSE;
  for (let i = 0; i < coarseItems.length; i += coarseBatchSize) {
    if (signal.aborted) return;
    const batch = coarseItems.slice(i, i + coarseBatchSize);
    await Promise.all(batch.map((item) => fetchOneTier(item.path, item.tier, signal, set, get).then(tick)));
  }

  if (opts.reportProgress && !signal.aborted) {
    set({ prefetchStatus: 'complete', prefetchProgress: 100, abortController: null });
  }
}

// Hook to use cached data with fallback to API
export function useCachedLidarData(filePath: string | null) {
  const getCached = useLidarCacheStore(s => s.getCached);

  // Check cache first
  if (filePath) {
    const cached = getCached(filePath);
    if (cached) {
      return { data: cached, isFromCache: true };
    }
  }

  return { data: null, isFromCache: false };
}

// Export for external use
export type { PointCloudData, PrefetchStatus };
