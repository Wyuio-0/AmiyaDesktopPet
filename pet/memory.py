"""Adaptive memory management for the desktop pet.

Monitors process memory and system RAM to dynamically adjust:
  - Frame cache budget (how many MB of decoded frames we keep)
  - DPR quality factor (full vs reduced rendering)
  - TTS clone service lifetime (idle timeout)

On systems with ample RAM we cache aggressively for best smoothness; when
memory is tight we compress, reduce, or disable caching to keep the pet
lightweight without sacrificing any visible feature.
"""

import gc
import os
import time

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False


# ── adaptive budget tiers (MB) ─────────────────────────────────────
# "Cache budget" is the max total size of *compressed* (PNG) frames held
# in memory for the current looping clip.  A typical idle webm compresses
# ~10-15:1 with PNG, so a 40 MB cache holds ~400-600 MB worth of raw frames.

class Tier:
    __slots__ = ('free_min_mb', 'cache_budget_mb', 'dpr_factor', 'fps_divisor')
    def __init__(self, free_min_mb, cache_budget_mb, dpr_factor=1.0,
                 fps_divisor=1):
        self.free_min_mb = free_min_mb
        self.cache_budget_mb = cache_budget_mb
        self.dpr_factor = dpr_factor
        self.fps_divisor = fps_divisor  # 1=full fps, 2=half, 3=third


# Ordered from most generous to most conservative — first match wins.
_TIERS = [
    Tier(free_min_mb=3072, cache_budget_mb=60,  dpr_factor=1.0,  fps_divisor=1),   # plenty
    Tier(free_min_mb=1536, cache_budget_mb=30,  dpr_factor=1.0,  fps_divisor=1),   # comfortable
    Tier(free_min_mb=768,  cache_budget_mb=12,  dpr_factor=0.75, fps_divisor=2),   # tight
    Tier(free_min_mb=0,    cache_budget_mb=0,   dpr_factor=0.50, fps_divisor=3),   # critical
]


class MemoryManager:
    """Singleton that adapts resource usage to system conditions."""

    def __init__(self):
        self._proc = None
        self._tier_index = 0
        if _HAS_PSUTIL:
            try:
                self._proc = psutil.Process(os.getpid())
            except Exception:
                pass
        self._cache_used_mb = 0.0       # current compressed-cache footprint
        self._last_budget_check = time.time()
        self._gc_counter = 0

    # ── system queries ────────────────────────────────────────────

    def process_rss_mb(self) -> float:
        """Current process RSS in MB (0 if unavailable)."""
        if self._proc:
            try:
                return self._proc.memory_info().rss / (1024 * 1024)
            except Exception:
                pass
        return 0.0

    def system_free_mb(self) -> float:
        """Available system RAM in MB (large sentinel if unmeasurable)."""
        if _HAS_PSUTIL:
            try:
                return psutil.virtual_memory().available / (1024 * 1024)
            except Exception:
                pass
        return 4096.0   # assume enough

    # ── active tier ───────────────────────────────────────────────

    def _pick_tier(self) -> Tier:
        free = self.system_free_mb()
        for t in _TIERS:
            if free >= t.free_min_mb:
                return t
        return _TIERS[-1]

    @property
    def tier(self) -> Tier:
        """Return the current resource tier, re-evaluated periodically."""
        now = time.time()
        if now - self._last_budget_check > 8.0:
            self._tier_index = _TIERS.index(self._pick_tier())
            self._last_budget_check = now
        return _TIERS[self._tier_index]

    # ── cache budget ──────────────────────────────────────────────

    @property
    def cache_budget_mb(self) -> float:
        return self.tier.cache_budget_mb

    @property
    def cache_used_mb(self) -> float:
        return self._cache_used_mb

    def can_cache(self, extra_mb: float = 0.3) -> bool:
        """True if we have room for one more compressed frame."""
        budget = self.cache_budget_mb
        return budget > 0 and (self._cache_used_mb + extra_mb) <= budget

    def cache_full(self) -> bool:
        """True if the cache is at or over budget (stop accumulating)."""
        return self._cache_used_mb >= self.cache_budget_mb

    def add_cached(self, mb: float):
        self._cache_used_mb += mb

    def clear_cache(self):
        """Call when discarding the current clip cache (e.g. action switch)."""
        self._cache_used_mb = 0.0

    # ── DPR quality ───────────────────────────────────────────────

    @property
    def dpr_factor(self) -> float:
        """Scale factor for device-pixel-ratio on low-memory systems."""
        return self.tier.dpr_factor

    # ── frame skip ────────────────────────────────────────────────

    @property
    def fps_divisor(self) -> int:
        """1=full fps, 2=every other frame, 3=every third frame."""
        return self.tier.fps_divisor

    # ── garbage collection ────────────────────────────────────────

    def tick_gc(self):
        """Call periodically (e.g. every frame tick); triggers gc every ~60 calls."""
        self._gc_counter += 1
        if self._gc_counter % 60 == 0:
            gc.collect()

    def force_collect(self):
        """Call at action boundaries to reclaim memory promptly."""
        gc.collect()

    # ── status ────────────────────────────────────────────────────

    def status_line(self) -> str:
        rss = self.process_rss_mb()
        free = self.system_free_mb()
        t = self.tier
        return (f"RSS {rss:.0f} MB | free {free:.0f} MB | "
                f"cache {self._cache_used_mb:.1f}/{t.cache_budget_mb:.0f} MB "
                f"| DPR x{t.dpr_factor:.2f}")


# ── module singleton ──────────────────────────────────────────────

_inst: MemoryManager | None = None


def get() -> MemoryManager:
    global _inst
    if _inst is None:
        _inst = MemoryManager()
    return _inst
