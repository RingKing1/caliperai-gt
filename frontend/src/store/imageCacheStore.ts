import { create } from 'zustand';
import { useAuthStore } from '@/store/authStore';
import type { Frame, Scene } from '@/types';

// Resolution tier for a cached image.
// - 'full': original camera image, required for pixel-space 2D annotation,
//   SAM2 embeddings and the main projection canvas.
// - 'thumb': server-resized preview (THUMB_WIDTH), only safe for pure 3D
//   projection surfaces that anchor their coordinate space to the calibration
//   intrinsic resolution (see FocusedCameraViews).
type ImageTier = 'full' | 'thumb';

interface ImageCacheEntry {
  blob: Blob;
  objectUrl: string;
  loadedAt: number;
  size: number;
  tier: ImageTier;
}

type PrefetchStatus = 'idle' | 'prefetching' | 'complete' | 'error';

interface ImageCacheState {
  cache: Map<string, ImageCacheEntry>;

  prefetchStatus: PrefetchStatus;
  prefetchProgress: number;
  prefetchTotal: number;
  prefetchLoaded: number;
  prefetchErrors: string[];

  currentSceneId: string | null;
  abortController: AbortController | null;

  startPrefetch: (scene: Scene, frames: Frame[], currentFrameIndex?: number) => void;
  followWindow: (
    scene: Scene,
    frames: Frame[],
    centerIndex: number,
    opts?: { initial?: boolean },
  ) => void;
  cancelPrefetch: () => void;
  getCached: (filePath: string, allowThumb?: boolean) => string | null;
  areFrameImagesCached: (scene: Scene, frame: Frame) => boolean;
  clearCache: () => void;

  getCacheStats: () => { entries: number; totalSize: number; hitRate: number };
}

let cacheHits = 0;
let cacheMisses = 0;

// Bounded two-tier prefetch window centred on the current frame:
//   near (±FULL_WINDOW)  -> full-resolution originals, ~31 MB for 7 frames
//   far  (±THUMB_WINDOW) -> 400px thumbnails, ~4.4 MB for 31 frames
// Frames outside the window are fetched incrementally as the user scrubs.
const FULL_WINDOW = 3;
const THUMB_WINDOW = 15;
const THUMB_WIDTH = 400;

const MAX_CONCURRENT_FULL = 12;
const MAX_CONCURRENT_THUMB = 20;

const MAX_CACHE_SIZE = 1024 * 1024 * 1024;

// Dedupes in-flight fetches across startPrefetch/followWindow calls.
const inflight = new Set<string>();

function cameraPathsForFrame(scene: Scene, frame: Frame): Array<{ path: string; cameraId: string; frameIndex: number }> {
  const cameras = scene.storage_paths?.cameras;
  if (!cameras || !frame.file_paths?.cameras) return [];
  const out: Array<{ path: string; cameraId: string; frameIndex: number }> = [];
  for (const [cameraId, basePath] of Object.entries(cameras)) {
    const filename = frame.file_paths.cameras[cameraId];
    if (filename) {
      out.push({
        path: `${basePath.replace(/\/$/, '')}/${filename}`,
        cameraId,
        frameIndex: frame.frame_index,
      });
    }
  }
  return out;
}

// URL is token-free (JWT travels in the Authorization header) so the browser
// disk cache and CDN edge can key on a stable URL across reloads.
function buildImageUrl(path: string, tier: ImageTier): string {
  return tier === 'thumb'
    ? `/api/v1/data/image/${path}?width=${THUMB_WIDTH}`
    : `/api/v1/data/image/${path}`;
}

async function fetchImage(
  item: { path: string; cameraId: string; frameIndex: number },
  tier: ImageTier,
  signal: AbortSignal,
  put: (path: string, tier: ImageTier, blob: Blob) => void,
): Promise<void> {
  const inflightKey = `${tier}:${item.path}`;
  if (inflight.has(inflightKey)) return;
  inflight.add(inflightKey);
  try {
    const token = useAuthStore.getState().accessToken;
    if (!token) throw new Error('No auth token available');

    const response = await fetch(buildImageUrl(item.path, tier), {
      signal,
      // Default caching mode: responses carry long-lived Cache-Control and
      // stable URLs, so reloads are served from the browser disk cache.
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok) throw new Error(`HTTP ${response.status} for ${item.cameraId}/${item.frameIndex}`);
    const blob = await response.blob();
    if (!signal.aborted) put(item.path, tier, blob);
  } catch (err) {
    if (!signal.aborted) {
      console.warn('[ImageCache] fetch failed', tier, item.cameraId, item.frameIndex, err);
    }
  } finally {
    inflight.delete(inflightKey);
  }
}

// Simple concurrency-limited queue; near/full batches always run before
// far/thumb batches so the current frame is visible first.
async function runPool<T>(items: T[], limit: number, worker: (item: T) => Promise<void>): Promise<void> {
  let next = 0;
  const runners = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (next < items.length) {
      const current = next++;
      await worker(items[current]);
    }
  });
  await Promise.all(runners);
}

export const useImageCacheStore = create<ImageCacheState>((set, get) => ({
  cache: new Map(),
  prefetchStatus: 'idle',
  prefetchProgress: 0,
  prefetchTotal: 0,
  prefetchLoaded: 0,
  prefetchErrors: [],
  currentSceneId: null,
  abortController: null,

  startPrefetch: (scene: Scene, frames: Frame[], currentFrameIndex: number = 0) => {
    const state = get();
    if (state.currentSceneId === scene.id && (state.prefetchStatus === 'prefetching' || state.prefetchStatus === 'complete')) {
      return;
    }
    state.abortController?.abort();

    const abortController = new AbortController();
    set({
      prefetchStatus: 'prefetching',
      prefetchProgress: 0,
      prefetchLoaded: 0,
      prefetchErrors: [],
      currentSceneId: scene.id,
      abortController,
    });
    void get().followWindow(scene, frames, currentFrameIndex, { initial: true });
  },

  // Incrementally fills the two-tier window around centerIndex. Frames within
  // FULL_WINDOW get originals; frames within THUMB_WINDOW (but outside the
  // near window) get 400px thumbnails. Already-cached/in-flight items are
  // skipped, so scrubbing only ever fetches what is newly in range.
  followWindow: (scene: Scene, frames: Frame[], centerIndex: number, opts?: { initial?: boolean; signal?: AbortSignal }) => {
    const state = get();
    if (!scene.storage_paths?.cameras || frames.length === 0) return;

    const signal = state.abortController?.signal;
    if (!signal) return;

    const cache = state.cache;
    const fullItems: Array<{ path: string; cameraId: string; frameIndex: number }> = [];
    const thumbItems: Array<{ path: string; cameraId: string; frameIndex: number }> = [];

    const lo = Math.max(0, centerIndex - THUMB_WINDOW);
    const hi = Math.min(frames.length, centerIndex + THUMB_WINDOW + 1);
    for (let i = lo; i < hi; i++) {
      const distance = Math.abs(i - centerIndex);
      const tier: ImageTier = distance <= FULL_WINDOW ? 'full' : 'thumb';
      for (const item of cameraPathsForFrame(scene, frames[i])) {
        const entry = cache.get(item.path);
        // Full satisfies both tiers; a thumb only satisfies thumb requests.
        if (entry && (entry.tier === 'full' || tier === 'thumb')) continue;
        if (inflight.has(`${tier}:${item.path}`)) continue;
        // A full fetch already in flight will supersede a pending thumb.
        if (tier === 'thumb' && inflight.has(`full:${item.path}`)) continue;
        (tier === 'full' ? fullItems : thumbItems).push(item);
      }
    }

    // Near frames first, sorted by distance so the current frame lands first.
    fullItems.sort((a, b) => Math.abs(a.frameIndex - centerIndex) - Math.abs(b.frameIndex - centerIndex));

    const total = fullItems.length + thumbItems.length;
    if (opts?.initial) {
      set({ prefetchTotal: total, prefetchLoaded: 0 });
    }
    if (total === 0) {
      if (opts?.initial) {
        set({ prefetchStatus: 'complete', prefetchProgress: 100, prefetchLoaded: 0 });
      }
      return;
    }

    let done = 0;
    const bumpProgress = () => {
      done++;
      if (!opts?.initial) return;
      set((s) => ({
        prefetchLoaded: (s.prefetchLoaded ?? 0) + 1,
        prefetchProgress: s.prefetchTotal > 0
          ? Math.min(100, Math.round(((s.prefetchLoaded ?? 0) / s.prefetchTotal) * 100))
          : 0,
      }));
    };

    const put = (path: string, tier: ImageTier, blob: Blob) => {
      set((s) => {
        const newCache = new Map(s.cache);
        const previous = newCache.get(path);
        // Never downgrade full to thumb; revoke replaced blob URL.
        if (previous && (previous.tier === 'full' || (previous.tier === tier && previous.size === blob.size))) {
          return {};
        }
        const objectUrl = URL.createObjectURL(blob);
        let currentSize = 0;
        newCache.forEach((e) => { currentSize += e.size; });
        if (previous) {
          currentSize -= previous.size;
          URL.revokeObjectURL(previous.objectUrl);
        }
        if (currentSize + blob.size > MAX_CACHE_SIZE) {
          const sorted = Array.from(newCache.entries()).sort((a, b) => a[1].loadedAt - b[1].loadedAt);
          while (currentSize + blob.size > MAX_CACHE_SIZE && sorted.length > 0) {
            const [oldPath, oldEntry] = sorted.shift()!;
            if (oldPath === path) continue;
            currentSize -= oldEntry.size;
            URL.revokeObjectURL(oldEntry.objectUrl);
            newCache.delete(oldPath);
          }
        }
        newCache.set(path, { blob, objectUrl, loadedAt: Date.now(), size: blob.size, tier });
        return { cache: newCache };
      });
    };

    void (async () => {
      await runPool(fullItems, MAX_CONCURRENT_FULL, async (item) => {
        await fetchImage(item, 'full', signal!, put);
        bumpProgress();
      });
      if (signal.aborted) return;
      await runPool(thumbItems, MAX_CONCURRENT_THUMB, async (item) => {
        await fetchImage(item, 'thumb', signal!, put);
        bumpProgress();
      });
      if (opts?.initial && !signal.aborted) {
        set({ prefetchStatus: 'complete', prefetchProgress: 100 });
      }
    })();
  },

  cancelPrefetch: () => {
    const state = get();
    if (state.abortController) {
      state.abortController.abort();
    }

    // Clean up object URLs
    state.cache.forEach(entry => {
      URL.revokeObjectURL(entry.objectUrl);
    });

    set({
      prefetchStatus: 'idle',
      abortController: null,
      cache: new Map(),
    });
  },

  // Defaults to full-resolution only (pixel-space annotation must never get
  // a thumbnail). Pass allowThumb=true on pure 3D projection surfaces.
  getCached: (filePath: string, allowThumb = false): string | null => {
    const entry = get().cache.get(filePath);
    if (entry && (entry.tier === 'full' || allowThumb)) {
      cacheHits++;
      return entry.objectUrl;
    }
    cacheMisses++;
    return null;
  },

  // Check if all images for a specific frame are cached (any tier)
  areFrameImagesCached: (scene: Scene, frame: Frame): boolean => {
    const cameras = scene.storage_paths?.cameras;
    if (!cameras || Object.keys(cameras).length === 0) {
      return true; // No cameras to check
    }

    const cache = get().cache;
    return Object.entries(cameras).every(([cameraId, basePath]) => {
      const filename = frame.file_paths?.cameras?.[cameraId];
      if (!filename) return true; // Skip missing camera files
      const cleanBasePath = basePath.replace(/\/$/, '');
      const fullPath = `${cleanBasePath}/${filename}`;
      return cache.has(fullPath);
    });
  },

  clearCache: () => {
    const state = get();
    if (state.abortController) {
      state.abortController.abort();
    }

    // Clean up all object URLs
    state.cache.forEach(entry => {
      URL.revokeObjectURL(entry.objectUrl);
    });

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


// Export for external use
export type { PrefetchStatus };
