# Design System — EvoScrapper

A locked design system for EvoScrapper generated via the Hallmark design framework.
All views, components, modals, HUD overlays, and controls adhere to this specification.

## 1. Genre
**atmospheric // modern-minimal**
A high-performance cinematic terminal aesthetic: deep optical dark canvas, restrained spectral accents (<=3% viewport footprint), precision typography, razor-thin structured boundaries, and high data density without clutter.

## 2. Macrostructure Family
- **App Workbench**: Primary workspace housing the torrent terminal query bar, stream telemetry indicators, metadata bars, collapsible shelves, and interactive data grids.
- **Cinematic Theater HUD**: Non-intrusive floating control stage for P2P video streaming, audio switching, real-time subtitle calibration, and swarm telemetry.
- **System Control Center**: Clean dual-pane master console for engine configuration, diagnostics, and scraper parameters.

## 3. Themes & OKLCH Color Architecture
EvoScrapper supports 5 calibrated OKLCH dark palettes. Each colorway satisfies APCA Lc >= 60 / WCAG 4.5:1 text contrast and avoids pure black (`#000`) or flat zero-chroma grey.

### Palette 1: Emerald Matrix (Default)
- `--color-paper`: `oklch(14% 0.012 165)`
- `--color-paper-2`: `oklch(18% 0.016 165)`
- `--color-paper-3`: `oklch(23% 0.020 165)`
- `--color-ink`: `oklch(96% 0.008 165)`
- `--color-ink-2`: `oklch(78% 0.012 165)`
- `--color-ink-dim`: `oklch(55% 0.010 165)`
- `--color-rule`: `oklch(28% 0.018 165)`
- `--color-rule-subtle`: `oklch(22% 0.014 165)`
- `--color-accent`: `oklch(78% 0.19 158)`
- `--color-accent-ink`: `oklch(12% 0.02 165)`
- `--color-focus`: `oklch(80% 0.18 158)`

### Palette 2: Cyberpunk Neon
- `--color-paper`: `oklch(13% 0.025 295)`
- `--color-paper-2`: `oklch(17% 0.030 295)`
- `--color-paper-3`: `oklch(22% 0.035 295)`
- `--color-ink`: `oklch(96% 0.010 295)`
- `--color-ink-2`: `oklch(79% 0.018 295)`
- `--color-ink-dim`: `oklch(56% 0.014 295)`
- `--color-rule`: `oklch(29% 0.032 295)`
- `--color-rule-subtle`: `oklch(23% 0.022 295)`
- `--color-accent`: `oklch(76% 0.17 210)`
- `--color-accent-ink`: `oklch(12% 0.02 210)`
- `--color-focus`: `oklch(78% 0.18 210)`

### Palette 3: OLED Midnight
- `--color-paper`: `oklch(10% 0.005 240)`
- `--color-paper-2`: `oklch(14% 0.006 240)`
- `--color-paper-3`: `oklch(19% 0.008 240)`
- `--color-ink`: `oklch(97% 0.004 240)`
- `--color-ink-2`: `oklch(78% 0.006 240)`
- `--color-ink-dim`: `oklch(54% 0.006 240)`
- `--color-rule`: `oklch(25% 0.006 240)`
- `--color-rule-subtle`: `oklch(18% 0.005 240)`
- `--color-accent`: `oklch(82% 0.16 150)`
- `--color-accent-ink`: `oklch(10% 0.01 150)`
- `--color-focus`: `oklch(82% 0.16 150)`

### Palette 4: Netflix Red (Cinema)
- `--color-paper`: `oklch(13% 0.008 25)`
- `--color-paper-2`: `oklch(17% 0.010 25)`
- `--color-paper-3`: `oklch(22% 0.012 25)`
- `--color-ink`: `oklch(96% 0.006 25)`
- `--color-ink-2`: `oklch(78% 0.008 25)`
- `--color-ink-dim`: `oklch(55% 0.008 25)`
- `--color-rule`: `oklch(27% 0.012 25)`
- `--color-rule-subtle`: `oklch(20% 0.009 25)`
- `--color-accent`: `oklch(62% 0.23 28)`
- `--color-accent-ink`: `oklch(98% 0.005 28)`
- `--color-focus`: `oklch(65% 0.22 28)`

### Palette 5: Obsidian Amethyst
- `--color-paper`: `oklch(13% 0.015 310)`
- `--color-paper-2`: `oklch(17% 0.020 310)`
- `--color-paper-3`: `oklch(22% 0.025 310)`
- `--color-ink`: `oklch(96% 0.008 310)`
- `--color-ink-2`: `oklch(78% 0.012 310)`
- `--color-ink-dim`: `oklch(55% 0.010 310)`
- `--color-rule`: `oklch(28% 0.022 310)`
- `--color-rule-subtle`: `oklch(21% 0.015 310)`
- `--color-accent`: `oklch(75% 0.14 305)`
- `--color-accent-ink`: `oklch(12% 0.02 310)`
- `--color-focus`: `oklch(76% 0.15 305)`

## 4. Typography (The 2+1 Discipline)
Three typefaces strictly bound to their registers:
1. **Display Face**: `Space Grotesk` (weights 600, 700). Letter-spacing `-0.025em`. Roman only — no italic headers.
2. **Body Face**: `Geist` (weights 400, 500). High legibility, crisp optical metrics for UI elements, modals, and lists.
3. **Outlier / Data Face**: `JetBrains Mono` (weights 400, 500, 600). Used strictly for data telemetry, hashes, torrent seed counts, bitfield indicators, and timecodes.

## 5. Spacing Scale (4-Point Semantic)
- `--space-3xs`: 0.25rem (4px)
- `--space-2xs`: 0.5rem (8px)
- `--space-xs`: 0.75rem (12px)
- `--space-sm`: 1rem (16px)
- `--space-md`: 1.5rem (24px)
- `--space-lg`: 2rem (32px)
- `--space-xl`: 3rem (48px)
- `--space-2xl`: 4.5rem (72px)
- `--space-3xl`: 6rem (96px)

## 6. Motion & Microinteractions
- **Easing**: `cubic-bezier(0.16, 1, 0.3, 1)` (`--ease-out`)
- **Duration**: `--dur-fast`: 140ms; `--dur-base`: 220ms
- **State Changes**: Animate opacity and transform only. Never layout geometry (width, height, padding, margin).
- **Reduced Motion**: Full `@media (prefers-reduced-motion: reduce)` collapsing all animations to instant opacity transitions (<=150ms).
- **Focus Rings**: Instantaneous 2px outline with 2px offset (`outline: 2px solid var(--color-focus); outline-offset: 2px`). Never transition focus appearance.
- **Hover/Focus Delays**: 800ms hover delay, 0ms focus delay on tooltips.

## 7. Interactive State Discipline (8 Mandatory States)
All interactive affordances (buttons, chips, pills, inputs, selects, cards, modal toggles) must provide explicit CSS styling for:
1. `default`
2. `hover`
3. `:focus-visible`
4. `:active`
5. `disabled`
6. `loading`
7. `error`
8. `success`

## 8. Mobile Responsiveness Floors
- Strict `overflow-x: clip` on both `html` and `body`.
- All clickable text (buttons, nav items, chips) must fit a single line without wrapping at 320px, 375px, 414px, and 768px.
- Grid tracks rendering cards or posters must use `minmax(0, 1fr)`.
