# Subtitle Sync Engine v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a robust, production-grade Subtitle Sync Engine v2 fusing multi-source consensus, audio VAD, framerate drift modeling, forced subtitle filtering, and real-time adaptive playback learning into EvoScrapper.

**Architecture:** Refactor `core/subtitle_sync.py` into a modular `core/subtitle_sync/` package with specialized modules for forced subtitle filtering (`forced_subs.py`), drift estimation (`drift.py`), consensus fusion (`consensus.py`), adaptive user correction tracking (`adaptive.py`), audio VAD (`vad.py`), and the unified coordination engine (`engine.py`). Expose `/api/v1/stream/subtitles/auto-sync-v2` and `/api/v1/stream/subtitles/adjust` endpoints in `routers/stream.py`.

**Tech Stack:** Python 3.14+, FastAPI, Pydantic, FFmpeg silencedetect, Pure Python statistics & linear regression (zero heavy C-extensions like librosa/scipy/cv2 needed).

**Spec:** User architecture blueprint for Subtitle Sync Engine v2 (Signal 3 Multi-Source Consensus, Signal 4 Drift Modeling, Signal 5 Forced Subtitles, Real-Time Adaptive Sync, and Unified Engine).

## Global Constraints

- Must maintain 100% backward compatibility for existing imports from `core.subtitle_sync`.
- Must not introduce heavy scientific packages (`librosa`, `scipy`, `cv2`) to keep Docker images lean and startup instant.
- Linear drift estimation and RANSAC clustering must be implemented in pure Python using `math` / `statistics`.
- All async calls must be non-blocking and safe for concurrent API requests.

## Review Focus

1. **Drift Modeling with identical or near-zero variance**: Degenerate cue arrays must not cause ZeroDivisionError during linear regression.
2. **Empty or noise-only cues**: Subtitles with only forced signs or empty cues must gracefully fall back to zero offset with zero confidence.
3. **Consensus with high outlier ratio**: Multi-source consensus must reject outliers (e.g. 2 sources agree, 1 is 30s off) and cluster the agreement.
4. **Adaptive controller thread safety**: Multiple rapid H/J keypresses concurrently adjusting offset must use `asyncio.Lock` and not race or corrupt history.
5. **Session expiry / cleanup**: In-memory adaptive controllers must not leak indefinitely; LRU / TTL bounded storage.

---

### Task 1: Package Scaffolding & Forced Subtitle Filtering Module

**Files:**
- Create: `core/subtitle_sync/__init__.py`
- Create: `core/subtitle_sync/forced_subs.py`
- Create: `core/subtitle_sync/vad.py` (migrating existing silencedetect & VAD from `core/subtitle_sync.py`)
- Remove/Migrate: `core/subtitle_sync.py` -> moved into `core/subtitle_sync/`
- Test: `tests/test_subtitle_sync_v2.py`

**Interfaces:**
- Consumes: Cues as `List[Tuple[float, float, str]]`
- Produces: `detect_forced_subtitles(cues) -> List[bool]`, `filter_for_sync(cues, forced_mask) -> List[Tuple[float, float, str]]`

- [ ] **Step 1: Write the failing test for forced subtitle detection**
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Migrate legacy `core/subtitle_sync.py` to `core/subtitle_sync/vad.py` and implement `core/subtitle_sync/forced_subs.py`**
- [ ] **Step 4: Re-export legacy functions in `core/subtitle_sync/__init__.py` so existing tests pass**
- [ ] **Step 5: Run tests to verify all tests pass**

---

### Task 2: Pure-Python Drift Modeling Module

**Files:**
- Create: `core/subtitle_sync/drift.py`
- Test: `tests/test_subtitle_sync_v2.py`

**Interfaces:**
- Consumes: `cue_times: List[float]`, `ref_times: List[float]`
- Produces: `DriftModel.fit_drift(cue_times, ref_times) -> dict`, `DriftModel.apply_drift(cue_times, model) -> List[float]`

- [ ] **Step 1: Write failing tests for drift estimation (framerate 23.976 to 25.0 PAL drift, constant offset, degenerate cases)**
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement `DriftModel` in `core/subtitle_sync/drift.py` using closed-form OLS (Ordinary Least Squares)**
- [ ] **Step 4: Run test to verify it passes**

---

### Task 3: Consensus Fusion Module (RANSAC + Weighted Voting)

**Files:**
- Create: `core/subtitle_sync/consensus.py`
- Test: `tests/test_subtitle_sync_v2.py`

**Interfaces:**
- Consumes: `SyncCandidate(offset, confidence, method, metadata)`
- Produces: `ConsensusSync.compute_consensus(candidates) -> Optional[SyncCandidate]`, `calibrate_confidence(...) -> float`

- [ ] **Step 1: Write failing tests for consensus fusion (clustering agreeing candidates, rejecting outliers, multi-signal confidence boost)**
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement `ConsensusSync` and `calibrate_confidence` in `core/subtitle_sync/consensus.py`**
- [ ] **Step 4: Run test to verify it passes**

---

### Task 4: Real-Time Adaptive Sync Controller

**Files:**
- Create: `core/subtitle_sync/adaptive.py`
- Test: `tests/test_subtitle_sync_v2.py`

**Interfaces:**
- Consumes: `position_sec: float`, `delta_ms: int`
- Produces: `AdaptiveSyncController.apply_user_correction()`, `get_offset(position_sec) -> float`, `get_confidence() -> float`

- [ ] **Step 1: Write failing tests for `AdaptiveSyncController` (concurrent corrections, position-weighted exponential decay, confidence scaling)**
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement `AdaptiveSyncController` with `asyncio.Lock` and deque in `core/subtitle_sync/adaptive.py`**
- [ ] **Step 4: Run test to verify it passes**

---

### Task 5: Unified `SubtitleSyncEngine` Orchestrator

**Files:**
- Create: `core/subtitle_sync/engine.py`
- Modify: `core/subtitle_sync/__init__.py`
- Test: `tests/test_subtitle_sync_v2.py`

**Interfaces:**
- Consumes: `video_source: str`, `subtitle_cues: List[Tuple[float, float, str]]`, `embedded_ref_idx: Optional[int]`, `external_cue_sets: Optional[List[List[Tuple[float, float, str]]]]`
- Produces: `SubtitleSyncEngine.sync(...) -> SyncResult`

- [ ] **Step 1: Write failing test for `SubtitleSyncEngine.sync()` combining VAD + Reference + Forced Sub filtering + Consensus**
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement `SubtitleSyncEngine` in `core/subtitle_sync/engine.py`**
- [ ] **Step 4: Run test to verify it passes**

---

### Task 6: API Endpoints `/subtitles/auto-sync-v2` and `/subtitles/adjust`

**Files:**
- Modify: `routers/stream.py`
- Test: `tests/test_subtitle_sync_v2.py`

**Interfaces:**
- Consumes: HTTP POST requests with Pydantic payloads
- Produces: JSON response with offset, confidence, drift_model, signals_used, session_id; and real-time adjust endpoint

- [ ] **Step 1: Write failing integration test for `/api/v1/stream/subtitles/auto-sync-v2` and `/api/v1/stream/subtitles/adjust`**
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement endpoints and bounded session cache in `routers/stream.py`**
- [ ] **Step 4: Run full test suite (`pytest tests/test_subtitle_sync.py tests/test_subtitle_sync_v2.py`)**
- [ ] **Step 5: Verify all tests pass cleanly**
