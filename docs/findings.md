# Status after the optimisation pass (2026-09-27)

Everything below was acted on; this section records what landed so the report
stays a useful history.  Measurements: `tools/timedemo.py e1m5` high detail
11.5 -> 6.0 ms mean, low detail 5.5 -> 3.1 ms; `tools/perf_test.py 4` high
10.1 -> 5.9 ms, low 4.4 -> 2.5 ms. The test suite grew from 49 to 70 tests.

| Finding | Status |
| --- | --- |
| P1 / Q1 / B11-B14 | Done: `raycasting.walk` is one DDA per ray over `world.cells`; the same walk serves `line_of_sight` and a world-space `World.hitscan`; tangent spaced columns; slab tested in the camera's own cell; walk stops on distance. Raycast 3.3 -> 1.1 ms. |
| P2 / B6 | Done: 1-texel strips scaled straight into the view surface, branches merged, shade inlined. Walls 5.4 -> 4.1 ms (the prototype's 3.2 was not reached; remaining cost is the C-level scale). |
| P3 | Done earlier on the branch (View, auto/high/low). Auto still triggers on slow frames; default left at auto. |
| P4 / P5 | Done: shaded source through an LRU (`Renderer.shaded_source`), colorkey conversion for binary-alpha frames (`assets.to_colorkey`), soft-alpha kept for projectiles. |
| P6 | Done: opaque pause with baked dim (13.8 -> 0.9 ms), cached dims, demo at low detail, automap tile layer. |
| P7 / B5 | Done: composed status bar rebuilt only on change (0.34 -> 0.04 ms), shared `DigitFont`, LRU text caches (512 entries). |
| P8 | Done: no source caching, lazy shade banks, weapon frames scaled once, textures 1-5 and the candelabra resized offline (`tools/optimize_assets.py`), iCCP chunks gone. Music stays WAV (no OGG encoder available here). |
| P9 | Done: flood only when the player's tile changes, own tile skipped inside `next_step`, list rebuilds only when something died. |
| Q2 / Q7 | Done: `ui/` package (`menu`, `demo`, `screens`, `play`) with a `MenuState` base, `flow.py` for game flow and save payloads, `game.py` is a thin shell with no local imports. |
| Q3 | Done: one `format_time`, `DigitFont`, pickups reuse `level.KEY_KINDS`, `Assets.sprite_frames`, autoplay reuses the monster rule. |
| Q4 | Done: unused parameters, functions, constants and assets removed. |
| Q5 | Done: timing and gameplay constants in `settings.py`, HUD layout table in `hud.py`, one door threshold for walking plus slab-exact tests for shots. |
| Q6 | Done: `set_anim(restart=True)`, dist computed once, `bleeds` attribute, menu guard for all-disabled items, pistol ammo set once. |
| Q8 | Partly: `perf_test.py` reads the real renderer phases; timers were not added inside `Renderer.render`. |
| Q9 | Done where cheap: `Player.take_damage`, `Effects.flash_ms`, `x_side` for ray hits. `Door.open` and string owners kept. |
| B1-B4, B7-B10, B15 | Done, each with a regression test in `tests/test_regressions.py` (fused barrels and in-flight projectiles are still not saved). |
| R1 | Done: `KNOTZDOOM_DATA_DIR` redirects config, saves and records; tests use a temp dir; the smoke tool restores `pg.key.get_pressed`. |
| R2 | Done: atomic writes, level fingerprint, validated payloads, INCOMPATIBLE / DAMAGED slots, migration hook. |
| R3 | Done: `config.SCHEMA` coerces and clamps; records validated. |
| R4 | Done: missing assets reported once at startup, levels validated on load with readable errors, no iCCP warnings. OGG conversion deferred. |
| R5 | Done: regression tests, golden frames at both detail levels, a `perf` marked frame budget test. |
| R6 | Done: `tools/timedemo.py`, `pyproject.toml`, runtime and dev requirements split. No CI configuration exists yet. |

---

# KnotzDoom review: performance, code quality, correctness, robustness

Reviewed revision: **e6cec04**. All `file:line` references point at e6cec04 (`git show e6cec04:<path>`); function names are given too, so they can still be found after edits. While the review was running, a concurrent session pushed 71d5199, db10c1e, 2ec8a5c and 47f02a5 (runtime View with high/low detail, dead-code removal, a shared collision helper, table-driven pickups). Each finding carries a **Status @47f02a5** line. The runnable bug reproductions (B1–B5, B7–B10) were run on exported copies of both revisions and reproduce on both.

## Executive summary

KnotzDoom is a readable, well-organised engine with good gameplay breadth. Its frame time comes almost entirely from two pure-Python per-column loops. On a replay of the e1m5 route (level index 4) at 1600x900, a frame takes 11.6 ms: the raycaster takes 4.0 ms (35%) and the wall drawer 5.4 ms (47%). The whole world update (AI, pathfinding, line of sight) costs 0.2 ms and GC is negligible, so they don't need work. The three biggest wins, all prototyped and measured:

1. **One DDA walk per ray over a flat grid** (P1). The raycast drops from 4.2 to 1.0 ms. The new caster agrees with the current one on 1,245,599 of 1,245,600 rays; the one difference is a ray grazing a wall corner.
2. **Scale 1-texel wall strips straight into the view surface** (P2). Walls drop from 4.95 to 3.2 ms, and this also removes a visible "comb" artefact on near walls (B6).
3. **Shade sprites before scaling instead of after** (P4). In close combat the sprite phase drops from 9.4 to 3.9 ms, with pixel-identical output.

The half-resolution view already on the branch cuts a frame from 11.5 to 5.5 ms. With P1 and P2 on top, the prototype frame is about **3.4 ms**, 70% below the baseline; P4 then removes most of the close-combat spikes.

On correctness, 15 bugs are listed, and all 9 with runnable reproductions still reproduce at 47f02a5. The worst three:
- Finishing a level while dying starts the next level alive with 0 HP.
- A door that closes on a monster's body freezes that monster forever.
- Monsters path into pillars and barrels and get stuck.

The test suite passes (49 tests in 22 s at e6cec04; 53 in 21 s at 47f02a5), but every run rewrites the user's `config.json`, `records.json` and `saves/slot0.json`.

## Environment and method

- Hardware and software: 4 vCPU Xeon @ 2.1 GHz; Python 3.11.15; pygame 2.6.1 (SDL 2.28.4); numpy 2.4.6. SDL dummy video and audio drivers are used everywhere, so `pg.display.flip()` is nearly free here. Its cost on a real window was not measured; of the changes below, only P3(4) would reduce it.
- Apart from three runs of `tools/perf_test.py 4` in the checkout (which writes no files), all measurements ran on `git archive` exports of e6cec04 and 47f02a5 in a scratch directory. Timings are the mean of at least 200 frames, repeated at least twice; run-to-run spread was ±3%.
- **Timedemo.** Most tables use a replay of the camera path that the `tools/autoplay.py` bot walks through e1m5: 2,509 ticks, every 2nd replayed, giving 1,255 frames. Monsters are alive at their spawn points. A self-contained version is in Appendix A. It is more representative than `tools/perf_test.py`, which spins in place at the level start where only 2 sprites are in view.

## Baseline measurements (e6cec04)

| What | Command / setup | Result |
| --- | --- | --- |
| Project perf tool | `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python3 tools/perf_test.py 4` (3 runs) | raycast 3.26–3.37, walls 5.23–5.40, sprites 0.61–0.66, update 0.29–0.30, hud 0.37–0.39, **total 9.8–10.1 ms/frame** |
| Full loop | `game.frame(16)` × 300, player turning 0.01 rad/frame at the e1m5 start | mean **11.2 ms**, median 10.4, p95 14.4–14.8 |
| Per phase, same loop | each phase timed separately | update 0.27 · raycast 3.9 (34%) · sky+floor 0.6 (5%) · walls 5.0 (43%) · sprite projection 0.09 · sprite draw 1.1 (9.5%) · weapon 0.25 · status bar 0.4 · messages+crosshair 0.01 · flip 0.00 (dummy driver) |
| Timedemo e1m5 | Appendix A, 1,255 frames, render only | mean **11.6–11.8**, median 11.4, p95 14.2–15.2, max 22–29 ms. Raycast 4.0 (35%), walls 5.4 (47%), sprites 1.05 (p95 3.6, max 13.4), sky+floor 0.48, weapon 0.25, HUD 0.40. 10.9 sprite requests/frame (max 40) |
| Timedemo e1m1 | same, 603 frames | mean 12.1 ms; raycast 5.4 (44%, open rooms mean longer rays), walls 5.1 |
| Close-range sprites | e1m1, player at (18.6, 14.5) facing east as in `tools/screenshots.py`. Two troopers, a sergeant, a cacodemon, a knight and a cyberdemon placed at 3–10 / 1–3 / 0.6–1.6 tiles | `draw_sprites` **2.1 / 9.4 / 12.8 ms**. Per-frame cost at the closest range: fill 5.4, blit 4.1, scale 3.1 ms |
| Menus | `game.frame(16)` in each state | Title 12.3, main menu 12.4, **Options 17.0, Pause 13.8 ms**. One `draw_dim()` call costs 2.45 ms |
| Automap | all 551 tiles seen | +3.2 ms/frame (`draw_automap` alone 2.6 ms) |
| World update | 19 monsters alerted, 600 frames | **0.21 ms/frame**. Path flood 0.23 ms every 120 ms; 2.3 LOS casts/frame |
| GC | 1,500 frames with gc callbacks | 2 gen-0 collections, 0.1 ms in total. Not a factor |
| Startup | cProfile | `Game()` 0.54 s: PNG decode 0.21, shade banks 0.12, demo world 0.19. `start_level` 18–37 ms warm |
| Memory | surface bytes + `ru_maxrss` | RSS ≈170 MiB with one level loaded. Shade banks 37.5 MiB; sprite frames 35 MiB; +57.8 MiB of raw 970×1050 weapon frames once all weapons are owned; 23.2 MiB of source images no one references |
| Branch head 47f02a5 | Appendix A, `detail` high / low | 11.5 ms / **5.4–5.55 ms** (low: raycast 1.9, walls 1.7). `perf_test.py 4 low`: total 4.39 ms |

**Prototype results.** These are scratch prototypes, not committed. Each "before → after" was measured in the same process on the same e1m5 frames.

| Change | Before → after | Validation |
| --- | --- | --- |
| One DDA per ray, pure Python, flat grid (Appendix B) | raycast **4.17 → 1.00 ms** (e1m5), 5.73 → 1.01 (e1m1); at 400 rays 1.9 → 0.39 | 1,245,600 rays with random door states: 1 differs (a corner graze); automap tile sets identical |
| Same DDA vectorised with numpy | 0.57 ms at 800 rays, 0.49 at 400, 0.46 at 200 | Has a ≈0.45 ms fixed floor, so pure Python wins at low detail |
| Wall strips scaled straight into a subsurface of the view | 4.95 → 3.98 ms | pixel-identical |
| … and 1-texel-wide strips | 4.95 → **3.19 ms** (median 3.14) | fixes B6 |
| DDA + new walls, full resolution | frame 11.6 → **6.7 ms** | timedemo |
| DDA + new walls + half-res view (800×450, 400 rays), including upscale, weapon and full-res HUD | → **3.4 ms** (p95 4.6) | timedemo |
| Sprites shaded at source size | 2.1 → 1.1 / 9.4 → 3.9 / 12.7 → 8.5 ms (far / close / very close) | pixel-identical |
| Colorkey blit instead of per-pixel alpha (1000×900 sprite) | 0.85 → 0.26 ms | NPC frames have 0.03% semi-transparent pixels |
| Status bar from a cached surface | 0.34 → 0.04 ms | when nothing changed |
| Tried with no gain | `Surface.blits()` batching 5.26 ms; full-res numpy wall gather 12.7 ms; opaque (`convert()`) wall banks 5.12 ms | — |
| Upscale costs | `pg.transform.scale` 800×450 → 1600×900 into the screen: **0.54 ms**; `scale2x` 1.39; from 400×225: 1.31 | — |

---

## 1. Performance

### P1. The raycaster walks every ray twice and does tuple-keyed dict lookups per step
- **Severity:** high
- **Location:** `knotzdoom/raycasting.py:27-142` (`RayCaster.cast`), `145-192` (`cast_single_ray`)
- **Evidence:**
  - The raycaster is 35% of the frame: 4.0 ms on the e1m5 timedemo, 5.4 ms on e1m1.
  - Every ray runs a horizontal pass and a vertical pass, and each pass keeps stepping until it finds its own wall. Measured cost: 11.7 grid steps per ray on e1m5 and 16.5 on e1m1. The cells actually crossed before the first hit are only 5.8 and 6.0.
  - Every step builds one or two tuples, calls `int()` twice and does one or two dict lookups (`walls`, `doors_h`/`doors_v`). cProfile counts 2.66 M `dict.get` calls in 200 frames, about 13,300 per frame.
- **Recommendation:** walk each ray once, Lode-style, over a flat list `cells[y*cols+x]`:
  - Encode walls as their texture id (>0) and doors as -(index+1).
  - When the walk enters a door cell, intersect the ray with the slab on the cell's centre line (`x = cx+0.5` or `y = cy+0.5`). It is a hit only if the crossing lies inside the cell and `frac < 1 - door.open`.
  - Precompute the per-ray angle-offset table and the fisheye `cos` table.
  - Keep the `(depth, proj_height, tex, u, vertical)` output so the renderer does not change.
  - Update `cells` on the one runtime wall change, the exit switch turning on (`world.py:228-230`).
  - Appendix B is a tested drop-in. Reuse the same walk for LOS and hitscan (Q1, B11).
- **Expected gain / effort:**
  - Gain: −3.2 ms/frame at high detail (4.17 → 1.00) and −1.5 ms at the branch's low detail (1.9 → 0.39).
  - Risk: low. The new caster was checked against the current one on 1.25 M rays with random door states: one ray differs, and it grazes a corner that the old caster misses.
  - Effort: about half a day including tests.
  - numpy alternative: it only pays off above about 600 rays, because its per-step overhead (about 30 numpy calls times the longest ray) sets a 0.45 ms floor.
- **Status @47f02a5:** open. The View refactor kept the two-pass loop; low detail halves it to 1.6–1.9 ms.

### P2. Wall drawing allocates, scales and blits a temporary surface per column
- **Severity:** high
- **Location:** `knotzdoom/renderer.py:61-99` (`draw_walls`)
- **Evidence:**
  - Walls are 43–47% of the frame (5.0–5.4 ms).
  - For each of 800 columns the code takes a `subsurface`, `pg.transform.scale`s it into a new surface, then `blit`s that; cProfile counts 160 k calls of each per 200 frames.
  - Instrumented split per frame: Python-side shading and lookups 0.57 ms, subsurface 0.52, scale 2.64, blit 1.87.
  - 32% of columns take the clipped branch (wall taller than the screen).
- **Recommendation:**
  - (a) Give `scale` a destination: `pg.transform.scale(strip, (col_w, h), view_surface.subsurface(x, top, col_w, h))`. This removes both the temporary surface and the blit, and the output is pixel-identical (both surfaces are 32 bpp).
  - (b) Sample a 1-texel strip: `texture.subsurface(int(u * TEXTURE_SIZE), tv0, 1, tv1 - tv0)` instead of `SCALE` texels. This fixes B6.
  - (c) Have the caster return the shade level and texel column, or inline `shade_level` and `wall_texture`; the 1,600 Python calls per frame cost about 0.6 ms.
  - (d) Merge the two branches: the unclipped case is the clipped case with `tv0=0, tv1=256`.
- **Expected gain / effort:**
  - (a)+(b): 4.95 → 3.19 ms, measured A/B in one process. (c): a further ≈0.3–0.5 ms.
  - Risk: low. Effort: 2–3 h.
- **Status @47f02a5:** open. The column code was only re-parameterised by the View.

### P3. Internal resolution and low detail (now on the branch)
- **Severity:** high, largely addressed
- **Location:** at e6cec04 the view is fixed at 1600×900 with 800 rays (`settings.py:21-51`). The branch adds `knotzdoom/view.py` and wires it in (71d5199, db10c1e).
- **Evidence:** at 47f02a5, low detail (800×450, 400 rays, `pg.transform.scale` to the window at 0.54 ms) takes 5.4 ms against 11.5 ms at high detail. My e6cec04 emulation of the same idea measured about 5 ms.
- **Recommendation:**
  1. Land P1 and P2 on top of it (prototype frame 3.4 ms, p95 4.6), then P4 for the close-range spikes.
  2. `DetailController` only drops detail when frames average over 19 ms. A machine that already reaches 60 fps at high detail therefore never saves any CPU. If the goal is less CPU per frame, default to `low`, or trigger on work time above about 8 ms.
  3. Fix B4 first: mouse sensitivity currently changes whenever auto mode switches detail.
  4. Later: make the window's logical size the view size with `pg.SCALED`, so the GPU does the upscale and `flip` uploads 4× fewer pixels. This needs a HUD and menus that scale, and the dummy driver cannot measure it.
  5. The 3D view is drawn under the opaque 96 px status bar (`settings.py:63`, `VIEW_HEIGHT = HEIGHT`), so 10.7% of the rows drawn for walls and sprites are wasted. Doom shrank its view instead; this is a design call because it moves the horizon.
- **Expected gain / effort:** −6 ms already realised on the branch; about −2 ms more with (1).
- **Status @47f02a5:** implemented. Items 1–5 are open.

### P4. Sprites are shaded after scaling, at screen size
- **Severity:** high in close combat
- **Location:** `knotzdoom/renderer.py:135-140` (`draw_sprites`)
- **Evidence:**
  - `scaled.fill((k,k,k), special_flags=BLEND_RGB_MULT)` runs on the already-scaled surface, which can be screen-sized.
  - With six monsters at 0.6–1.6 tiles (8 sprite draws), just 2 fills cost 5.4 ms per frame, plus blit 4.1 ms and scale 3.1 ms.
  - `draw_sprites` measures 2.1 / 9.4 / 12.8 ms at far / close / very close range. On the timedemo, sprites are p95 3.6 ms and max 13.4 ms, which makes them a main source of the frame spikes.
- **Recommendation:** shade the clipped source, then scale:
  `src = image.subsurface(clip)` → if the level is above 0, `src = src.copy(); src.fill(...)` → `scale(src, size)`.
  The cost then grows with the source size (at most 282×262) instead of screen pixels. The output is pixel-identical (maximum channel difference 0). A cache keyed by `(frame, level)` saves a little more, but must be an LRU: 176 frames × 9 levels could otherwise hold hundreds of MiB.
- **Expected gain / effort:**
  - Without a cache: 2.1 → 1.1, 9.4 → 3.9, 12.7 → 8.5 ms. With a cache: 0.65 / 2.9 / 7.5 ms.
  - Effort: 1 h.
- **Status @47f02a5:** open.

### P5. Per-pixel alpha is used for sprites whose alpha is binary
- **Severity:** medium
- **Location:** `knotzdoom/assets.py:124-134` (every image is `convert_alpha()`ed), `knotzdoom/renderer.py:141-153`
- **Evidence:**
  - NPC frames have 0.03% semi-transparent pixels on average; decorations 2.6%; pickups 9.5%; projectiles and explosions 15%.
  - Blitting a 1000×900 sprite costs 0.85 ms with SRCALPHA and 0.26 ms with a colorkey. `pg.transform.scale` keeps the colorkey.
  - Once P4 is done, blits are most of the remaining close-range cost.
- **Recommendation:**
  - At load, convert frames with essentially binary alpha (alpha < 128 treated as transparent) to `convert()` + `set_colorkey(MAGENTA)`. Keep SRCALPHA for soft effects: projectiles, explosions, puffs.
  - Shading multiplies the key colour too, so after P4's multiply either re-key to the shaded magenta, or keep pre-shaded colorkey banks for NPCs.
- **Expected gain / effort:** up to 70% less blit time on large sprites, about −2 to −3 ms in the very-close case. Effort: half a day (alpha thresholding, tinted variants).
- **Status @47f02a5:** open.

### P6. Pause and menu frames cost as much as gameplay
- **Severity:** medium
- **Location:** `knotzdoom/states.py:692-744` (`PauseState.transparent = True`), `knotzdoom/game.py:301-307` (`Game.draw`), `knotzdoom/states.py:23-26` (`draw_dim`), `171-211` (`DemoBackground`), `knotzdoom/hud.py:207-240` (`draw_automap`)
- **Evidence:**
  - Pause: `Game.draw` runs `PlayState.draw` (full 3D render plus HUD) on every paused frame, then `PauseState.draw` covers it with its snapshot. That is 10 `render` calls in 10 paused frames, and a paused frame costs 13.8 ms.
  - Dimming: `draw_dim` allocates a 1600×900 SRCALPHA surface on every call (2.45 ms). OptionsState calls it twice per frame (17.0 ms per frame); the title screen takes 12.3 ms.
  - Automap: each frame allocates a 1600×804 SRCALPHA overlay and issues one `pg.draw.rect` per seen tile, 2.6 ms in total.
- **Recommendation:**
  - Set `PauseState.transparent = False`, since it already draws its snapshot, and bake the dim into that snapshot in `enter()`.
  - Cache dim surfaces per (size, alpha): 1.58 ms instead of 2.45. Do not dim with an in-place `BLEND_RGB_MULT` fill, which measured 9.9 ms.
  - Render the demo background at low detail.
  - Keep a pre-rendered automap layer that is only updated when `seen_tiles` grows, and blit it with the player offset.
- **Expected gain / effort:** pause 13.8 → under 1 ms; title and menus 12–17 → about 3–5 ms; automap 2.6 → about 0.3 ms. Effort: 2–4 h.
- **Status @47f02a5:** open.

### P7. The status bar is rebuilt from scratch every frame
- **Severity:** low–medium
- **Location:** `knotzdoom/hud.py:110-165`; dimmed key icons at `150-152`
- **Evidence:**
  - `draw_status_bar` takes 0.34–0.40 ms/frame. That is 3.5% today but about 10% of a 3.4 ms target frame.
  - Each frame it blits about 20 text surfaces, most of them static labels (AMMO, HEALTH, ARMS, ARMOR, KEYS, BULL/SHEL/RCKT, "/").
  - It also makes one `icon.copy()` + `fill` allocation per frame for each key the player does not have (up to three).
  - Blitting a cached bar costs 0.04 ms.
- **Recommendation:**
  - Bake the static labels and dimmed key icons into `self.bar` in `build_bar`.
  - Keep a composed bar and rebuild it only when this tuple changes: (ammo, health, armor, keys, weapon, score, kills, whole seconds, face index, hurt shake).
  - Draw numbers from digit glyphs rather than rendered text; this also fixes B5.
- **Expected gain / effort:** −0.3 ms/frame. Effort: 2 h.
- **Status @47f02a5:** open.

### P8. Memory is held by duplicated and oversized images
- **Severity:** medium
- **Location:**
  - `knotzdoom/assets.py:124-134`: `load_image` caches every decoded file forever.
  - `knotzdoom/assets.py:143-147`: 10 shade copies are built for all 15 textures.
  - `knotzdoom/weapons.py:55-63`: weapon frames are rescaled for every `Weapon` instance.
  - `tools/gen_assets.py`: weapon frames are written at 5× size.
- **Evidence (measured):**
  - `image_cache` holds **23.2 MiB** of sources no one references: `1.png`–`5.png` at 1024² (4 MiB each), skies (1.8 MiB each), `4.png` at 512², and so on.
  - The raw 970×1050 weapon frames stay in `frames_cache`: **57.8 MiB** once all four weapons are owned, while the scaled copies actually used are 9.5 MiB.
  - `gen_assets.py` draws weapons at 194×210, saves them 5× larger, and the game then downscales them 2.5× with `smoothscale`, which also blurs the pixel art.
  - `static_sprites/candlebra.png` is 897×1921 (6.6 MiB decoded) for a prop 0.7 walls tall.
  - The shade banks take 37.5 MiB, but each level uses only 6–9 of the 15 textures.
  - Startup spends 0.21 s decoding PNGs, mostly the four 1024² textures (0.9–2.2 MB files) that are immediately resized to 256².
- **Recommendation:**
  - Do not cache one-shot sources (textures, skies, digits, `win.png`), or clear them once their derived versions are built.
  - Scale weapon frames once in `Assets`, keyed by (name, height), and drop the raw frames. Better still, have `gen_assets` save weapons at their native 194×210 and scale by an integer factor with `pg.transform.scale`, which is also sharper.
  - Pre-size `1.png`–`5.png` to 256² and the candelabra to about 128 px tall, offline.
  - Build shade banks lazily, per texture, on first use.
- **Expected gain / effort:** about −80 to −100 MiB peak (from an estimated ~240 MiB once all weapons are owned), about −0.2 s startup, about −6 MB of repository. Effort: half a day.
- **Status @47f02a5:** open.

### P9. Small costs, and things that do not need optimising
- **Severity:** low
- **Location:** `knotzdoom/npc.py:211`; `knotzdoom/objects.py:62-77`; `knotzdoom/projectiles.py:61`; `knotzdoom/pathfinding.py:52-56`; level-start builders in `knotzdoom/hud.py`, `knotzdoom/weapons.py` and `knotzdoom/renderer.py`
- **Evidence:**
  - The whole world update is 0.21 ms/frame with 19 alerted monsters: one path flood (0.23 ms) every 120 ms, about 2.3 LOS rays per frame, and negligible GC. Do not spend time on AI or pathfinding for speed.
  - Level start rebuilds the HUD (bar, faces, digit smoothscales), the weapon frames (11 ms) and the floor gradient (450 `draw.line` calls, 11 ms) every time.
- **Recommendation:** cheap tidy-ups only:
  - Flood only when the player's tile changes.
  - `NPC.chase` builds `npc_tiles - {self.map_pos}` per monster per frame (`npc.py:211`); pass the set and skip the monster's own tile inside `next_step`.
  - `ObjectHandler.update` rebuilds 4 lists every frame (`objects.py:62-77`), and `shootable()` / `barrels()` allocate on every projectile sub-step (`projectiles.py:61`).
  - Cache the per-level builders in `Assets` or `Game`.
- **Expected gain / effort:** under 0.1 ms/frame; 1 h.
- **Status @47f02a5:** open.

---

## 2. Code quality and cleanup

### Q1. Three copies of the grid walk
- **Severity:** high (pairs with P1)
- **Location:**
  - `knotzdoom/raycasting.py:48-83` and `85-120`: the horizontal and vertical passes are the same code with x and y swapped.
  - `knotzdoom/raycasting.py:145-192`: `cast_single_ray` repeats both passes with a different `blocked` rule and door threshold.
  - `knotzdoom/world.py:245-275`: hitscan does not trace at all; it reads the renderer's depth buffer.
- **Recommendation:** one `walk(ox, oy, cos, sin, max_dist, stop)` DDA over the flat grid (Appendix B), shared by the per-frame caster, `line_of_sight` and a renderer-independent hitscan. This removes about 100 lines and three sources of disagreement (see B12).
- **Status @47f02a5:** open.

### Q2. Menu states and UI idioms are copy-pasted
- **Severity:** medium
- **Location:**
  - `knotzdoom/states.py` `MainMenuState` 247-284, `DifficultyState` 288-311, `OptionsState` 315-375, `PauseState` 692-744, `SaveLoadState` 748-798.
  - "Press any key" test in 6 states (lines 223, 401, 435, 512, 873, 992); blinking prompt in 5.
  - `Menu.handle_event` at 125-134.
- **Evidence:**
  - The five menu states all implement the same three things. `handle_event`: Esc goes back, anything else goes to `menu.handle_event`. `update`: `super()`, `demo.update`, `menu.update`. `draw`: backdrop, heading, `menu.draw`.
  - `event.type == KEYDOWN or (MOUSEBUTTONDOWN and button == 1)` is written out in 6 states. `int(self.time / 500) % 2 == 0` for blinking prompts appears 5 times.
  - `Menu.handle_event` duplicates its LEFT and RIGHT branches.
- **Recommendation:** add a `MenuState(State)` base with `title`, `build_items()`, `backdrop_dim` and `on_back()`, plus helpers `is_confirm(event)` and `draw_blink_prompt(screen, text)`. Estimated −120 lines.
- **Status @47f02a5:** open.

### Q3. Duplicated helpers and tables
- **Severity:** medium–low
- **Location and evidence:**
  - Time formatting: `knotzdoom/hud.py:180-183` prints `MM:SS`, `knotzdoom/states.py:963-966` prints `M:SS` for the same kind of value.
  - Big-digit rendering: `knotzdoom/hud.py:96-108` plus pre-scaled digit dicts at `19-20`, versus `knotzdoom/states.py:949-961`, which lazily caches its own with `hasattr(self, '_digits')`.
  - Key tables: `level.KEY_KINDS` (`level.py:51`) is identical to `pickups.KEY_PICKUPS` (`pickups.py:36`). `hud.KEY_COLORS`, `level.DOOR_CHARS`, and `player.AMMO_NAMES` (unused) versus the HUD's literal ammo rows (`hud.py:154`) overlap too.
  - "Frames or single image" loading is written twice (`pickups.py:52` and `114`).
  - `tools/autoplay.py:40-48` `walkable()` re-implements `PathFinding.passable` plus solid tiles.
- **Recommendation:**
  - One `format_time`.
  - A `DigitFont(size)` in `fonts.py`.
  - One `KEYS` table (colour, pickup kind, door char, HUD colour).
  - `Assets.sprite_frames(defn)`.
  - Let autoplay reuse the pathfinding predicate.
- **Status @47f02a5:** open (the pickup effects themselves became a table in 47f02a5).

### Q4. Dead code still present at 47f02a5
- **Severity:** low
- **Location:** listed below (e6cec04 lines).
- **Evidence:** found with an AST scan and confirmed with grep. Unused imports and write-only attributes were already removed in 2ec8a5c. What remains:
  - **Unused parameters:**
    - `Player.give_weapon(announce)` (`player.py:68`); callers pass `announce=False` at `player.py:47` and `states.py:614`.
    - `Player.get_damage(source, scaled)` (`:153`).
    - `NPC.take_damage(source)` (`npc.py:242`) and `Barrel.take_damage(source)` (`pickups.py:138`).
    - `Projectile.explode(hit_player)` (`projectiles.py:79`).
    - `World.trigger_exit(tile)` (`world.py:222`).
    - `World.noise(pos)` (`:235`); the flow field always starts from the player anyway.
    - `World.hitscan(angle)` (`:245`); it uses `player.angle` instead.
  - **Never called:** `Game.level_count` (`game.py:56`), `LevelData.door_at` (`level.py:177`), `saves.delete_save` (`saves.py:58`), `Animation.reset` (`sprites.py:27`), `Weapon.ready` (`weapons.py:67`), `World.enemies_left` (`world.py:177`).
  - **Unused constants:**
    - `level.SOLID_PROPS` and `level.ITEM_KINDS` (`level.py:52-53`), `player.AMMO_NAMES` (`:14`).
    - `settings.FPS` (`:24`); the config's `fps_cap` is what is used.
    - `settings.PLAYER_SUPER_HEALTH` (`:33`); `pickups.py:90` hard-codes `limit=200` instead.
  - **Identical branches:** in `NPC.can_attack` (`npc.py:153-158`) the melee and non-melee returns are the same.
  - **Unused assets:**
    - `resources/textures/blood_screen.png`, `resources/textures/game_over.png`.
    - `resources/sprites/npc/soldier/0.png`, `resources/sprites/npc/cyber_demon/0.png`. (`caco_demon/0.png` is still used as the window icon.)
- **Recommendation:** delete them, and wire the constants in where values are currently hard-coded (`limit=PLAYER_SUPER_HEALTH`).
- **Status @47f02a5:** open for everything listed. Already fixed in 2ec8a5c: `pixel_small`, `delta_time`, `boss`, `rel`, `Animation.advanced`, `StoryState.text`, `flash_time`, the dead locals, `HALF_TEXTURE_SIZE`, `VIEW_HEIGHT`, the `tools/level_map.py` dead line, and 17 unused imports.

### Q5. Magic numbers and inconsistent thresholds
- **Severity:** medium–low
- **Location and evidence:**
  - **Door passability** uses three different thresholds:
    - movement: `DOOR_PASSABLE = 0.7` (`settings.py:68`);
    - projectiles: a literal `0.5` (`world.py:162`);
    - line of sight: a default of `0.5` (`raycasting.py:145`).

    So a rocket passes through a slab that still covers half the doorway, while the player is blocked by it.
  - **Timers:**
    - door re-check 800 ms (`world.py:84`);
    - LOS every 100 ms (`npc.py:118`);
    - path flood every 120 ms (`pathfinding.py:15`);
    - exit delay 900 ms and death screen delay 1300 ms (`states.py:644-647`);
    - fade-in 700 ms (`states.py:561`, `688`).
  - **Gameplay:**
    - noise radius 11 (`weapons.py:106`);
    - barrel splash 1.9 / 90 (`pickups.py:161`) versus rocket 2.2 / 90 (`projectiles.py`);
    - soulsphere limit 200.
  - **Presentation:**
    - about 40 pixel literals in the HUD (`hud.py:41`, `114-178`);
    - weapon bob constants (`states.py:658-661`);
    - mouse border 80 (`player.py:264`).
- **Recommendation:** add `TIMING` and `GAMEPLAY` blocks to `settings.py`, or put the values in the per-entity definition tables (`NPC_DEFS` already shows the pattern). Describe the HUD layout as a table of named rectangles. Use a single door threshold (see B12).
- **Status @47f02a5:** arrow-key turn speed was fixed in 2ec8a5c (`PLAYER_ROT_SPEED`); everything else is open.

### Q6. Small control-flow smells
- **Severity:** low
- **Location and evidence:**
  - `self.anim_name = None` is set before `set_anim()` to force a restart (`npc.py:163`, `253`, `258`, `275`). Use `set_anim(name, restart=True)`.
  - `NPC.update` recomputes `self.dist` immediately after `check_sight` computed it (`npc.py:95` and `122`).
  - Hitscan recognises monsters with `hasattr(best, 'hp') and getattr(best, 'kind', '') != 'barrel'` (`world.py:264`). Use a `bleeds` class attribute.
  - `DemoBackground.pick_camera_spot` just returns `player_start` (`states.py:190-192`).
  - `Menu.__init__` loops forever if no item is enabled (`states.py:94-95`); latent today.
  - `Player.__init__` gives the pistol, which adds scaled pickup ammo, then overwrites ammo with 50 (`player.py:47-48`).
- **Recommendation:** fix these while doing Q2 and Q3.
- **Status @47f02a5:** open.

### Q7. Module boundaries
- **Severity:** medium–low
- **Location:** `knotzdoom/states.py` (1026 lines; local imports at 180, 550-551, 974), `knotzdoom/game.py:44`, `103`, `108`, `114`, `126`, `137`, `148`, `159`, `170`, `289`
- **Evidence:**
  - `states.py` has 14 classes: menus, play, overlays and screens.
  - `Game` mixes the window, main loop, state stack, level flow, save payloads and records.
  - `Game` imports `states` inside 10 functions to get around an import cycle. `states.py` also imports `renderer`, `hud` and `settings` inside functions (180, 550-551, 974) although no cycle exists there.
- **Recommendation:**
  - Split into `ui/menu.py` (`MenuItem`, `Menu`, `MenuState` and the menu screens), `states/play.py` (Play, Pause, Death) and `states/screens.py` (Story, Intermission, Victory, Credits, Help).
  - Move the flow functions (`start_new_game`, `begin_level`, `level_complete`, `finish_episode`) into `flow.py` so `game.py` needs no local imports.
  - Move payload assembly into `saves.py`.
- **Status @47f02a5:** open. `world.py`'s local imports are gone; `game.py` still has 10.

### Q8. Small duplications in rendering and tools
- **Severity:** low
- **Location:** `knotzdoom/renderer.py:78-99`; `tools/perf_test.py:32-40`
- **Evidence:**
  - `draw_walls` has two nearly identical branches (see P2(d)).
  - `tools/perf_test.py` re-implements the order of `Renderer.render`, so it measures a pipeline that can drift from the real one, and it leaves out the weapon, overlays, present and flip.
- **Recommendation:** merge the branches; put optional per-phase timers inside `Renderer.render` and have the tool read them.
- **Status @47f02a5:** open.

### Q9. Naming
- **Severity:** low
- **Evidence:**
  - Damage entry points: `get_damage` on `Player`, `take_damage` on `NPC` and `Barrel`.
  - `Door.open`: a float fraction that reads like a method, sitting next to `Door.use()`.
  - Two unrelated "light"s: `Effects.light` is a timer in ms, `Renderer.light` is a shade offset.
  - `SCALE`: a column width in pixels. `SpriteObject.scale`: a height in wall units.
  - "vertical": for a door it means the slab runs north–south; for a ray hit it means the ray crossed a vertical grid line.
  - Owners are strings (`'player'` / `'npc'`).
- **Recommendation:** rename in one sweep once the structure has settled.
- **Status @47f02a5:** open.

### Q10. Fixed on the branch
- Duplicated collision code (`Player.collides` and `NPC.collides`, plus two copies of `try_move`) is now `World.circle_blocked` (47f02a5).
- The `Pickup.apply` if-chain is now the `PICKUP_EFFECTS` table (47f02a5).
- Unused imports, write-only attributes, dead locals and dead settings were removed (2ec8a5c).
- `Renderer.set_level` was dropped (db10c1e).

---

## 3. Correctness bugs

B1–B5 and B7–B10 have runnable reproductions and reproduce at both e6cec04 and 47f02a5. B6 and B13 were measured at e6cec04; the code involved is unchanged at 47f02a5. B11, B12, B14 and B15 are argued from the code; apart from B11's new early return (noted in B11), that code is also unchanged at 47f02a5.

### B1. Finishing a level while dying starts the next level alive with 0 HP
- **Severity:** high
- **Location:** `knotzdoom/states.py:644-649` (`PlayState.update` fires the exit whether or not the player is dead); `knotzdoom/game.py:147-156` (`level_complete` carries `player.carry_state()`)
- **Evidence:** if the player dies within the 900 ms exit delay, `level_complete` runs; the death screen only appears once `death_timer > 1300`. The next level then starts with `alive=True, health=0`: the HUD shows 0% health and any hit kills the player. Repro (`game = Game(headless=True)`):
  ```python
  game.start_level(0, 1); w = game.state.world
  w.trigger_exit(); w.player.get_damage(500)       # killed during the exit delay
  for _ in range(70): game.frame(16)               # -> IntermissionState
  game.session['carry']['health']                  # == 0, next level: alive=True health=0
  ```
- **Recommendation:** only fire the exit if the player is alive (`... and world.player.alive`), or make the exit instant and the player invulnerable, as Doom does. Add the repro as a test.

### B2. A door that closes on a monster's body freezes the monster forever
- **Severity:** high
- **Location:** `knotzdoom/world.py:167-171` (`tile_occupied` only knows each monster's centre tile via `npc_tiles`); `74-94` (`Door.update`); `knotzdoom/npc.py:227-239` (a move is rejected if any bounding-box corner is in a blocking tile)
- **Evidence:**
  - A trooper's centre is in tile (11,3) and its body overlaps door tile (10,3) by 0.05. The door times out and closes, because its tile is not in `npc_tiles`.
  - From then on every move is rejected, because the monster already overlaps a solid tile. While chasing a player to the east it moves 0.000 in 4.8 s.
  - This is not contrived: monsters stop moving 1.2–2.5 tiles from a visible player (`npc.py:205`), which can easily be just past a doorway.
  ```python
  w = World(game, game.level_data(0), 1); door = w.doors[(10, 3)]
  door.open, door.state, door.timer = 1.0, 'open', 10.0
  m = NPC(w, 'trooper', (11.5, 3.5)); m.x = 11.0 + m.radius - 0.05; w.objects.npcs = [m]
  w.player.x, w.player.y = 20.5, 3.5
  for _ in range(80): w.update(16)                 # door closes on the monster
  m.alerted = True
  for _ in range(300): w.update(16)                # m.x does not change
  ```
- **Recommendation:** decide door occupancy by bounding-box overlap for every entity. Allow a mover that already overlaps a blocked tile to make moves that reduce the overlap, or ignore the tile it started in.

### B3. Monster pathfinding routes through pillars and barrels
- **Severity:** medium
- **Location:** `knotzdoom/pathfinding.py:23-32` (`passable` ignores `world.solid_tiles`) versus `knotzdoom/world.py:147-156` (`blocks_movement` includes them)
- **Evidence:**
  - All 64 pillar and barrel tiles in the episode are nodes of the flow-field graph (5 / 13 / 13 / 17 / 9 / 7 per level).
  - e1m1: a trooper at (11.5, 2.5), the player at (15.5, 2.5), a pillar at (13,2) in between. `next_step` returns the pillar tile, and after 4.8 s the trooper is still pressed against it at (12.70, 2.50).
- **Recommendation:** leave `solid_tiles` out of the graph, and add the node back when a barrel explodes (`pickups.py:158` already discards the solid tile). Test that `next_step` never returns a solid tile.

### B4. Mouse turn rate is multiplied by frame time
- **Severity:** medium
- **Location:** `knotzdoom/player.py:272` (`angle += rel * MOUSE_SENSITIVITY * sens * dt`); per-frame clamp at `268`
- **Evidence:**
  - Measured through `Player.mouse_control`: 400 px of mouse movement over 0.5 s turns the player 229° at 30 fps, 115° at 60 fps and 48° at 144 fps.
  - Both the FPS-cap option and the branch's auto-detail switching therefore change mouse sensitivity during play.
  - The 40 px per-frame clamp also drops more of a fast flick at low frame rates.
- **Recommendation:** drop `dt` (`angle += rel * RAD_PER_PIXEL * sens`, with `RAD_PER_PIXEL ≈ 0.005`, i.e. 0.0003 × 16.7 ms, to keep today's 60 fps feel) and clamp per second rather than per frame. Test that 30, 60 and 144 fps give the same turn.

### B5. Text caches grow without bound
- **Severity:** medium
- **Location:** `knotzdoom/fonts.py:36-68` (`BigFont.cache`) and `91-106` (`PixelFont.cache`), fed every frame by `knotzdoom/hud.py:162-165` (score, kills, clock) and `204` (FPS)
- **Evidence:** one hour of the HUD clock alone adds 3,615 cached surfaces (23.9 MiB). With score changes it is 7,214 surfaces (81.5 MiB).
- **Recommendation:** use an LRU (`OrderedDict`, about 256 entries) for dynamic text, or draw numbers from glyphs (P7). Keep unbounded caching only for static strings.

### B6. Near walls show a vertical "comb" pattern, and the last texels are never sampled
- **Severity:** medium (visible)
- **Location:** `knotzdoom/renderer.py:67`, `75`, `79`, `97` (`tex_span = TEXTURE_SIZE - SCALE`, `subsurface(u, …, SCALE, …)`)
- **Evidence:**
  - Every 2 px column shows texels `u` and `u+1`, whatever the distance.
  - On a wall 0.8 units away (6.8 px per texel), 78.6% of adjacent pixel columns differ from each other. With 1-texel strips it is 12.3%, close to the correct ~15%.
  - The result is a fine stripe pattern that shimmers as you move.
  - `u` only spans 0–253, so the last two texel columns of every texture never appear.
  - At the branch's low detail the stripes are upscaled 2×.
- **Recommendation:** P2(b): `u = int(offset * TEXTURE_SIZE)`, a 1-texel strip, scaled to (column width, h). This is faster as well as correct.

### B7. "Restart level" keeps the current inventory and score
- **Severity:** medium–low
- **Location:** `knotzdoom/states.py:720-723` (`PauseState.restart` passes `player.carry_state()`); compare `819-820`, where the death restart uses `session['carry']`
- **Evidence:** with score 5000 and 180 bullets, restart returns score 5000 and 180 bullets, and every pickup and monster respawns. Ammo, health and score can be farmed without limit, which also inflates `records.json`'s `best_score`.
- **Recommendation:** restart from `game.session['carry']`, the level-start state.

### B8. Splash damage goes through walls
- **Severity:** low–medium
- **Location:** `knotzdoom/world.py:277-285`; callers at `knotzdoom/pickups.py:161` and `knotzdoom/projectiles.py:87-91`
- **Evidence:** an explosion at (9.8, 1.5) with the player at (11.3, 1.5), wall tile (10,1) between them: the player takes 13 damage. Monsters behind walls are hurt the same way.
- **Recommendation:** require line of sight from the blast to the target, as Doom's radius attack does.

### B9. The death counter is never incremented
- **Severity:** low
- **Location:** `knotzdoom/game.py:115` and `140` initialise `session['deaths']`; `knotzdoom/states.py:809-812` (`DeathState.enter`) only increments `records['deaths']`; `knotzdoom/states.py:1014` displays the session value
- **Evidence:** `session['deaths']` is still 0 after dying, so the victory screen always says "DEATHS 0".
- **Recommendation:** increment `session['deaths']` in `DeathState.enter`.

### B10. Weapon cooldown drops the remainder, so fire rate depends on FPS
- **Severity:** low
- **Location:** `knotzdoom/weapons.py:85-98`
- **Evidence:** the chaingun's nominal rate is 105 ms; it actually fires every 111 ms at 60 fps and every 132 ms at 30 fps, which is 20% less damage per second at 30 fps.
- **Recommendation:** `self.cooldown += d['rate']`, carrying the overshoot into the next shot.

### B11. Hitscan depends on the renderer's previous frame
- **Severity:** low
- **Location:** `knotzdoom/world.py:245-275`
- **Evidence:**
  - Targets and occlusion come from `on_screen` / `screen_x` / `norm_dist` and the depth buffer written by the last render, so they are one frame old (the view has already turned this frame).
  - With no renderer (bots, tests, a headless server) no shot can hit: an NPC with 30 hp stays at 30.
  - At 47f02a5 `hitscan` returns early when there is no renderer.
- **Recommendation:** trace pellets in world space with the shared DDA (Q1) and test targets by ray-to-circle distance. The renderer then becomes optional and the detail level no longer affects aim.

### B12. Door slab rendering and door collision disagree
- **Severity:** low
- **Location:** `knotzdoom/raycasting.py:66-78` and `103-115` (slabs are only tested beyond the camera's own tile); `knotzdoom/world.py:147-165` (tile-level thresholds of 0.7 and 0.5)
- **Evidence** (by construction):
  - From 70% open, the whole door tile is passable while 30% of the slab is still drawn, so the player walks through visible door.
  - When the camera stands inside the door tile, that tile's slab is never tested and disappears.
  - Projectiles and LOS pass at 50% open.
- **Recommendation:** with the DDA, test the slab in the camera's own cell too. Use the slab position, not the tile, for collision and projectiles, or require the door to be fully open. Use one threshold constant (Q5).

### B13. Straight wall edges bow
- **Severity:** low
- **Location:** `knotzdoom/raycasting.py:37` and `142` (rays at equal angle steps); `knotzdoom/sprites.py` `project` (`screen_x = (HALF_NUM_RAYS + delta/DELTA_ANGLE)*SCALE`)
- **Evidence:**
  - Seen obliquely, the top edge of a single straight wall deviates from a straight line by 14.7 px at 0.6 units, 5.9 px at 1.5 and 2.9 px at 3.0.
  - A point 15° right of centre is drawn at x = 1200 instead of 1171.
  - Doom avoided this with a tangent table.
- **Recommendation:** precompute column angles `atan((x + 0.5 - HALF_WIDTH) / SCREEN_DIST)` and project sprites with `SCREEN_DIST * tan(delta)`. It costs nothing at runtime once P1's tables exist.

### B14. Rays give up after 24 grid lines
- **Severity:** low (latent)
- **Location:** `knotzdoom/raycasting.py:57` and `94` (`range(MAX_DEPTH)` counts steps, not distance)
- **Evidence:**
  - When both passes run out, a flat texture-1 wall with `u=0` is drawn at depth 24.
  - An exhaustive sweep (every floor tile × 8 headings × 800 rays, all six maps) found no ray that hits the cap today.
  - The tests allow maps up to 40×40, so any straight sightline of 25+ tiles would show the phantom wall.
- **Recommendation:** stop the walk on distance, or on leaving the grid, not on a step count. The DDA does this.

### B15. Minor gameplay edge cases
- **Severity:** low
- **Location:** `knotzdoom/player.py:234-237`; `knotzdoom/pathfinding.py:23-32` with `knotzdoom/world.py:63-68`; `knotzdoom/npc.py:195-198`; `knotzdoom/objects.py:112-131`
- **Evidence:**
  - Holding W+S (or A+D) counts as moving, so the head bobs with no movement. Holding 3 keys applies the 0.7071 diagonal factor to what is a single-axis move.
  - Monsters path through secret doors and open them, which reveals the secret.
  - A melee hit does not re-check line of sight on the damage frame.
  - Fused barrels and in-flight projectiles are not saved.
- **Recommendation:**
  - Normalise the actual movement vector.
  - Leave secret doors out of the monster graph.
  - Re-check LOS on the damage frame.
  - Save fuse timers and projectiles.

---

## 4. Robustness and maintainability

### R1. Tests modify the user's files and leak global patches
- **Severity:** medium
- **Location:**
  - Writers: `knotzdoom/states.py:354-357` (Options "back" calls `config.save()`), `809-812` and `979-989` (records), `knotzdoom/game.py:177-194` (F5 quick save), all exercised by `tools/smoke_test.py:151`.
  - Hard-coded repository paths: `knotzdoom/settings.py:17-18`, `knotzdoom/game.py:17`.
  - Global patch: `tools/smoke_test.py:42` replaces `pg.key.get_pressed` for the whole pytest session.
- **Evidence:**
  - On a clean export of e6cec04, `pytest` creates `config.json`, `saves/slot0.json` and `records.json` in the project root. Each run adds 1 death and 1 win to `records.json`.
  - In this checkout, `records.json` went from 6 deaths / 4 wins to 9 / 7 during the review without anyone playing, consistent with three test runs by the concurrent session. My single run of the suite at 47f02a5 took it to 10 / 8 and rewrote `saves/slot0.json`; I restored both files afterwards.
  - The smoke test presses RIGHT then LEFT on music volume, so a user volume of 1.0 comes back as 0.9.
- **Recommendation:** an autouse fixture that points the config, save and records paths at `tmp_path` (read them at call time, or inject a paths object into `Game`), and `monkeypatch` for `pg.key.get_pressed`.

### R2. Save files
- **Severity:** medium
- **Location:** `knotzdoom/saves.py:16-38`, `knotzdoom/game.py:177-208`, `knotzdoom/objects.py:112-131`, `knotzdoom/world.py:294-324`
- **Evidence:**
  - An exact version match (`saves.py:36`) makes older saves show as "EMPTY", where they can be overwritten; there is no migration step.
  - There is no level fingerprint. NPCs are restored by list position (`objects.py:120` zips the lists without checking `kind`), and pickups and barrels by thing index. Editing a level's JSON silently scrambles existing saves.
  - Writes are not atomic (`open(path, 'w')` then `json.dump`). A crash mid-write corrupts the slot, which then shows as empty.
  - `load_game` reads `data['level_index']`, `['difficulty']` and `['world']` directly (`game.py:206`). A correctly versioned but partial file raises `KeyError`, and `level_index` is not range-checked.
- **Recommendation:** write to `slotN.json.tmp` then `os.replace`; store a `level_hash` of the grid; validate the payload, with defaults; show "INCOMPATIBLE" rather than "EMPTY"; add a `migrate(version)` step.

### R3. Config and records validation
- **Severity:** low–medium
- **Location:** `knotzdoom/config.py:29-37`; `knotzdoom/states.py:983`
- **Evidence:**
  - `Config.load` accepts a value only when `type(v) is type(default)`. So `"mouse_sensitivity": 1` (an int) is silently ignored.
  - There are no range checks: `music_volume: 5`, `fps_cap: -1` or a sensitivity of `1e9` are all accepted.
  - `records.json` is trusted as-is: a non-numeric `best_score` raises an exception at the victory screen.
- **Recommendation:** a per-key schema that coerces types, clamps ranges and checks allowed values (`fps_cap` in {0, 30, 60, 90, 120, 144}, `detail` in {auto, high, low}), and logs rejected keys.
- **Status @47f02a5:** db10c1e added `detail` to `DEFAULTS`, which it needs: `Config.load` drops unknown keys, so without it the choice would be lost on restart. The rest is open.

### R4. Asset handling
- **Severity:** low–medium
- **Location:** `knotzdoom/assets.py:124-134` and `172-192`; `knotzdoom/level.py:212-216`; the `resources/` tree
- **Evidence:**
  - Missing files silently turn into placeholders. `assets.missing` is only printed by the smoke test.
  - 23 PNGs contain an iCCP chunk, so libpng prints "iCCP: known incorrect sRGB profile" on every start: `textures/1, 2, 3, 5.png`, all 11 digits, and 8 NPC frames.
  - There are oversized assets (P8) and unused assets (Q4).
  - The music ships as 12 MB of WAV.
  - A malformed level JSON raises a raw exception, and `validate_level` only runs in tests.
- **Recommendation:**
  - Log missing assets once at startup and fail CI on them.
  - Strip iCCP chunks (`pngcrush -rem iCCP`, or re-save the files).
  - Use OGG for music; `pygame.mixer.music` plays it and it is about 10× smaller.
  - Run `validate_level` inside `load_level` and report a readable error.

### R5. Test coverage gaps
- **Severity:** medium
- **Evidence:** nothing tests any of the following:
  - hitscan occlusion or aim (only "hits an enemy standing in front");
  - splash damage, or projectiles tunnelling through walls;
  - monster/door interaction (B2) or pathing around props (B3);
  - mouse turn versus `dt` (B4), fire rate (B10), completing a level while dying (B1), restart carry (B7);
  - `Game.save_game` / `load_game` through slot files (only `World.save_state` has a round-trip test);
  - old-version or partial saves, config validation, cache bounds;
  - renderer output (a golden image would have caught B6);
  - performance.

  The walkthrough takes 20 of the suite's 22 s and mostly asserts that screenshots are larger than 1000 bytes.
- **Recommendation:**
  - Turn the reproductions in section 3 into regression tests.
  - Add a golden-image test: a hash of a downscaled frame at 3 fixed camera poses.
  - Add a `perf`-marked timedemo test that fails above 1.5× budget.

### R6. Tooling
- **Severity:** medium
- **Location:** `tools/perf_test.py`; CI configuration (none); `requirements.txt`
- **Evidence:**
  - `tools/perf_test.py` spins in place at the level start (2 sprites in view on e1m5), duplicates the render order, leaves out the weapon, overlays, present and flip, and reports means only.
  - Nothing runs a linter (the code has been pyflakes-clean since 2ec8a5c, but nothing enforces it).
  - `requirements.txt` mixes runtime and test dependencies.
  - With the dummy driver, `flip` cost cannot be measured.
- **Recommendation:**
  - Adopt the Appendix A timedemo (mean, median, p95, max) and keep per-phase timers in `Renderer`.
  - Add ruff or pyflakes to CI with a `pyproject.toml`, and split runtime and dev requirements.
  - Add an optional benchmark that runs in a real window.

---

## 5. Prioritised action plan

| # | Change | Acceptance criterion |
| --- | --- | --- |
| 1 | Replace `RayCaster.cast` with the single-DDA caster (P1, Appendix B), keeping its output format | `tools/perf_test.py 4`: raycast ≤ 1.2 ms at high and ≤ 0.5 ms at low detail; `test_raycasting` passes; a new test compares depths against the old caster on a recorded path (≤ 0.001% of rays differ) |
| 2 | Scale 1-texel wall strips straight into `view.surface` subsurfaces and inline the shade lookup (P2, fixes B6) | walls ≤ 3.3 ms at high / ≤ 1.3 ms at low in `perf_test 4`; on a wall 0.8 units away, ≤ 20% of adjacent columns differ |
| 3 | Fix B1: the exit must not complete while the player is dead | regression test: dying in the exit delay shows DeathState and never IntermissionState |
| 4 | Fix B2 and B3: bounding-box door occupancy, overlap-escape moves, no solid tiles in the path graph | both reproductions move the monster ≥ 1 tile within 5 s; no graph node is in `solid_tiles` |
| 5 | Fix B4: mouse look without `dt` | unit test: the same turn angle at 30, 60 and 144 fps |
| 6 | Pause and menus: `PauseState` opaque with the dim baked in; cached dim surfaces; demo background at low detail (P6) | `renderer.render` not called while paused; pause frame ≤ 1 ms; title frame ≤ 5 ms |
| 7 | Shade sprites at source size, with an optional LRU (P4) | close-sprite scenario: `draw_sprites` ≤ 4 ms at high detail; golden frame pixel-identical |
| 8 | Bounded text caches and a cached status bar (B5, P7) | `fonts.pixel.cache` ≤ 256 entries after 3600 simulated seconds; `draw_status_bar` ≤ 0.1 ms when nothing changed |
| 9 | Hermetic tests (R1) | the md5 of `config.json`, `records.json` and `saves/*` is unchanged by `pytest` |
| 10 | Memory (P8): no caching of sources, weapon frames scaled once, lazy shade banks, pre-sized textures and candelabra | RSS < 150 MiB after `idkfa` on e1m5; `Game()` < 0.35 s |
| 11 | Save robustness (R2): atomic writes, level hash, payload validation | tests for truncated, partial, old-version and edited-level saves |
| 12 | Timedemo tool plus a CI performance budget (R6) | `tools/timedemo.py e1m5 low` ≤ 4 ms mean on the reference machine; CI fails above 1.5× |
| 13 | `MenuState` base, UI helpers, split `states.py` and a `flow.py` (Q2, Q3, Q7) | net −100 lines or more; walkthrough screenshots unchanged |
| 14 | Small correctness batch: B7, B8, B9, B10, B15 | one regression test each |
| 15 | Tangent ray table and consistent door slabs, done together with #1 (B12–B14) | a straight wall edge deviates < 1 px; no ray is capped by step count |

Items 1 and 2 take the low-detail frame from about 5.5 to about 3.4 ms, and the high-detail frame from 11.5 to about 6.7 ms; item 7 removes most of the close-combat spikes. Items 3–5 are the bugs players will notice.

---

## Appendix A: timedemo tool (tested on e6cec04 and 47f02a5)

Save as `tools/timedemo.py`. It records the autoplay bot's route once, then replays it through the real `PlayState.draw` (3D view, weapon, overlays, HUD).

Results on this machine: e6cec04 11.62 ms mean (p95 14.31); 47f02a5 high 11.50 (p95 14.16); 47f02a5 low 5.55 (p95 6.86).

```python
import json, os, statistics, sys, time
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy'); os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, 'tools')]
from autoplay import AutoPlayer                      # noqa: E402
from knotzdoom.game import Game                      # noqa: E402

def record(game, level_id):
    bot = AutoPlayer(game, game.level_data(game.episode['levels'].index(level_id)))
    poses, tick = [], bot.tick
    def recording_tick():
        tick(); poses.append((bot.player.x, bot.player.y, bot.player.angle))
    bot.tick = recording_tick
    bot.run()
    return poses

def replay(game, level_id, poses, detail=None):
    if detail:
        game.config['detail'] = detail
    game.start_level(game.episode['levels'].index(level_id), 1)
    play = game.state
    play.fade = play.title_timer = 0
    player, ms = play.world.player, []
    for x, y, a in poses:
        player.x, player.y, player.angle = x, y, a
        t0 = time.perf_counter()
        play.draw(game.screen)
        ms.append((time.perf_counter() - t0) * 1000)
    ms.sort()
    return statistics.mean(ms), ms[len(ms) // 2], ms[int(len(ms) * 0.95)], ms[-1]

if __name__ == '__main__':
    level_id = sys.argv[1] if len(sys.argv) > 1 else 'e1m5'
    game = Game(headless=True)
    poses = record(game, level_id)[::2]
    mean, med, p95, worst = replay(game, level_id, poses, sys.argv[2] if len(sys.argv) > 2 else None)
    print(f'{level_id}: {len(poses)} frames  mean {mean:.2f}  median {med:.2f}  p95 {p95:.2f}  max {worst:.2f} ms')
```

## Appendix B: single-DDA caster (drop-in for `RayCaster`; validated, 1.00 ms vs 4.17 ms on e1m5)

At 47f02a5, pass `view.num_rays`, `FOV`, `view.screen_dist`, `MAX_DEPTH` and `view.max_proj_height`. For B13, swap `offsets` for `atan` of column positions.

```python
import math

import numpy as np


class GridCaster:
    def __init__(self, world, num_rays, fov, screen_dist, max_depth, max_proj):
        level = world.level
        self.world, self.cols = world, level.cols
        self.cells = [0] * (level.cols * level.rows)          # >0 wall texture, <0 -(door index + 1)
        for (x, y), tex in world.walls.items():
            self.cells[y * level.cols + x] = tex
        self.doors = list(world.doors.values())
        for i, d in enumerate(self.doors):
            self.cells[d.y * level.cols + d.x] = -(i + 1)
        step = fov / num_rays                                  # same ray angles as RayCaster
        self.offsets = [-fov / 2 + 0.0001 + i * step for i in range(num_rays)]
        self.fish = [math.cos(o) for o in self.offsets]        # fisheye correction table
        self.screen_dist, self.max_depth, self.max_proj = screen_dist, max_depth, max_proj
        self.results = [None] * num_rays
        self.depth = np.full(num_rays, float(max_depth), dtype=np.float32)

    def set_wall(self, x, y, tex):                             # e.g. the exit switch turning on
        self.cells[y * self.cols + x] = tex

    def cast(self, cam):
        cells, cols, doors = self.cells, self.cols, self.doors
        ox, oy = cam.x, cam.y
        mx, my = int(ox), int(oy)
        fx, fy = ox - mx, oy - my
        start = my * cols + mx
        cos, sin = math.cos, math.sin
        maxd, sd, mp = self.max_depth, self.screen_dist, self.max_proj
        results, fish, hits, depths = self.results, self.fish, set(), []
        for i, off in enumerate(self.offsets):
            a = cam.angle + off
            c = cos(a) or 1e-9
            s = sin(a) or 1e-9
            if c > 0: stx, ddx = 1, 1.0 / c; sdx = (1.0 - fx) * ddx
            else:     stx, ddx = -1, -1.0 / c; sdx = fx * ddx
            if s > 0: sty, ddy = cols, 1.0 / s; sdy = (1.0 - fy) * ddy
            else:     sty, ddy = -cols, -1.0 / s; sdy = fy * ddy
            cell, t, tex, u, vert = start, maxd, 1, 0.0, False
            while True:
                if sdx < sdy:
                    t_in, xside = sdx, True; sdx += ddx; cell += stx
                else:
                    t_in, xside = sdy, False; sdy += ddy; cell += sty
                if t_in > maxd:
                    break
                v = cells[cell]
                if v > 0:                                      # wall: hit where the ray entered the cell
                    t, tex, vert = t_in, v, xside
                    if xside:
                        f = oy + t * s; f -= int(f); u = f if c > 0 else 1.0 - f
                    else:
                        f = ox + t * c; f -= int(f); u = 1.0 - f if s > 0 else f
                    hits.add(cell)
                    break
                if v < 0:                                      # door: slab on the tile centre line
                    d = doors[-v - 1]
                    cx, cy = cell % cols, cell // cols
                    if d.vertical:
                        ts = (cx + 0.5 - ox) / c; fr = oy + ts * s - cy
                    else:
                        ts = (cy + 0.5 - oy) / s; fr = ox + ts * c - cx
                    if 0.0 <= fr < 1.0 - d.open:
                        uu = min(0.999, fr + d.open)
                        t, tex, vert = ts, d.texture, d.vertical
                        u = (uu if c > 0 else 1.0 - uu) if d.vertical else (1.0 - uu if s > 0 else uu)
                        hits.add(cell)
                        break
            depth = max(t * fish[i], 1e-4)
            results[i] = (depth, min(sd / depth, mp), tex, u, vert)
            depths.append(depth)
        self.depth[:] = depths
        self.world.seen_tiles.update((h % cols, h // cols) for h in hits)
```

Inside the map the walk cannot leave the grid, because `validate_level` requires solid borders. **But the `idclip` cheat lets the camera leave the map**, and then `start` indexes outside `cells` (a negative index would even wrap around in Python). Before shipping, return early (or clamp) when the camera is outside `0 <= x < cols, 0 <= y < rows`, and stop the walk when `cell` leaves the grid. The current dict-based caster tolerates this case.

## Appendix C: the two small render changes (P2, P4)

```python
# P2: in draw_walls, per column (x, top, h, tv0, tv1 computed exactly as today)
tu = int(offset * TEXTURE_SIZE)                                   # 0..255, not 0..253
pg.transform.scale(texture.subsurface(tu, tv0, 1, tv1 - tv0),     # 1-texel strip
                   (col_w, h), surface.subsurface(x, top, col_w, h))  # scale straight into the view

# P4: in draw_sprites, shade the clipped source instead of the scaled result
src = image.subsurface(clip_rect)             # clip_rect = today's (sx0, sy0, sx1-sx0, sy1-sy0)
if not bright and level > 0:
    src = src.copy()
    src.fill((k, k, k), special_flags=pg.BLEND_RGB_MULT)
scaled = pg.transform.scale(src, (vx1 - vx0, vy1 - vy0))
```
