---
name: kasukabe-pixel
description: >
  Deterministic pixel-level Minecraft reconstruction from a 2D image.
  Zero LLM calls, FAWE schematic paste, OKLab+CIEDE2000 color matching.
---

# Kasukabe Pixel Replica

Build a pixel-level mural/pixel-art into Minecraft using a deterministic
color-matching pipeline. No Architect, no Planner, no Inspector subagent —
all Python.

## Usage

```
/kasukabe-pixel <image> at <x>,<y>,<z>
  [--size WxH] [--axis xy|xz|yz]
  [--dither none|fs-linear] [--fit fit|cover|stretch]
  [--style wood-only|stone-only|concrete-only|grayscale|none]
  [--backlight none|light_block|glowstone_row|auto]
  [--force-flat] [--allow-translucent --backdrop <block>]
  [--region X1,Y1,X2,Y2] [--confirm-preview] [--player <name>]
  [--resume <session_id>]
```

Examples:
- `/kasukabe-pixel portrait.png at 100,64,200 --size 64x64`
- `/kasukabe-pixel logo.jpg at 100,64,200 --axis xz --style concrete-only`
- `/kasukabe-pixel portrait.png at 100,64,200 --region 12,20,28,40 --dither fs-linear --resume <SESSION_ID>` (retry a region of a previous run)

## Pipeline

You are the Foreman. All steps are deterministic — do NOT spawn subagents.

### Step 0: Parse + preflight

Extract from the user's message:
- `input_path`: image file (.jpg/.jpeg/.png/.gif/.webp)
- `origin`: x,y,z (REQUIRED)
- `size`: WxH (optional; auto-detected if omitted)
- `axis`: xy (default, wall mural), xz (floor), yz (side wall)
- `dither`, `fit`, `style`, `backlight`, `region`, `force-flat`, `allow-translucent`, `backdrop`, `confirm-preview`, `player`, `resume` (all optional)

Mode detection:
- If `--region` is set, `mode = "region"` (VANILLA setblock path, no FAWE).
- Otherwise, `mode = "full"` (FAWE schematic path).

Session validation:
- If `--region` is set but `--resume` is NOT, **stop** and tell the user:
  > `--region` requires `--resume <session_id>` from a prior full run. Either
  > run a full build first, or remove `--region` to start fresh.
- If `--resume <session_id>` is set, verify `workspace/<session_id>/blueprint.json`
  exists. If missing, **stop** and tell the user:
  > Session `<session_id>` not found (no `blueprint.json` in
  > `workspace/<session_id>/`). Check the ID, or drop `--resume` to start fresh.

Preflight:
```bash
curl -s --connect-timeout 3 http://localhost:3001/status
```
If the bridge is not reachable, **stop** and tell the user:
> Bridge server is not running. Start it first: `cd bridge && npm install && node server.js`

If `mode == "full"`, also verify FAWE:
```bash
curl -s http://localhost:3001/fawe_check
```
If `installed=false` or `schem_dir_writable=false`, **stop** with a message
pointing at `$KASUKABE_FAWE_SCHEM_DIR` or `./plugins/FastAsyncWorldEdit/schematics/`.

### Step 1: Create or reuse workspace

- If `--resume <session_id>` was supplied (and validated in Step 0):
  ```bash
  SESSION_ID=<session_id>
  # workspace/$SESSION_ID already exists; do NOT mkdir or clean it
  ```
- Otherwise, mint a fresh session:
  ```bash
  SESSION_ID=$(python3 -c "import uuid; print(uuid.uuid4().hex[:12])")
  mkdir -p workspace/$SESSION_ID
  ```

Print `SESSION_ID` so the user can use it with `--resume` later.

### Step 2: Deterministic quantization

```bash
python3 -m kasukabe.pixel_replica \
  --image <input_path> \
  --workspace workspace/$SESSION_ID \
  --origin <x>,<y>,<z> \
  [--size WxH] [--axis xy|xz|yz] \
  [--dither none|fs-linear] [--fit fit|cover|stretch] \
  [--style ...] [--backlight ...] \
  [--force-flat] [--allow-translucent --backdrop <block>] \
  [--region X1,Y1,X2,Y2]
```

Read `workspace/$SESSION_ID/pixel_replica_done.json`:
- If `status == "BLOCKED"`, print `reason` and stop.
- Otherwise continue.

### Step 3: Preview gate

Print:
- `preview.png` path (let the user eyeball it)
- `gamut_report.json` summary (`in_gamut_ratio`, `mean_de`)
- `lighting_recommendation.json` summary (`recommended_backlight`, `reason`)

If `in_gamut_ratio < 0.7`: print a WARNING (continue anyway).

If the user passed `--confirm-preview`, **stop** and tell the user:
> Preview generated at `workspace/$SESSION_ID/preview.png`. Review it, then
> re-run the command **without** `--confirm-preview` **and with**
> `--resume $SESSION_ID` to reuse this workspace and proceed.

Otherwise continue immediately.

### Step 4: Command generation

```bash
python3 -m kasukabe.command_gen --workspace workspace/$SESSION_ID \
  [--region X1,Y1,X2,Y2]
```

- Full mode: produces `build.schem` + 3-line `# WORLDEDIT` `commands.txt`.
- Region mode: produces `# VANILLA` setblock-only `commands.txt`, no schematic.

Check `command_gen_done.json`; if BLOCKED, stop.

### Step 5: Upload schematic (full mode only)

Skip entirely if `mode == "region"`.

```bash
curl -s -F "file=@workspace/$SESSION_ID/build.schem" http://localhost:3001/upload_schematic
```

The bridge resolves the target directory via the 3-level fallback:
1. `$KASUKABE_FAWE_SCHEM_DIR`
2. `./plugins/FastAsyncWorldEdit/schematics/` (cwd or one level up)

### Step 5.5: Preflight canary (full mode only)

Skip entirely if `mode == "region"`.

Three checks, in order:

0. **FAWE per-player-schematics probe** — our upload/list endpoints only see
   the top-level schem dir. If FAWE is configured with
   `per-player-schematics: true`, schematics land under `<uuid>/` subdirs
   and `//schem load <name>` silently fails. Refuse to proceed in that
   mode instead of pasting an empty clipboard. See minecraft_context FAWE
   pitfall #3 (bridge is blind to FAWE output).
1. **Filesystem probe** — does `build.schem` live in FAWE's scan directory?
   (FAWE/WorldEdit output is invisible to RCON — its messages route to the
   player chat packet, not the RCON reply buffer — so a filesystem check
   is the only reliable way to verify the upload landed where FAWE will
   find it.)
2. **Paper/RCON health probe** — is vanilla RCON alive? Uses the `list`
   command, which does return over RCON. Skips FAWE entirely for this
   check (see note above).

```bash
python3 -c "
import sys
from kasukabe.bridge_client import BridgeClient
from kasukabe.rcon_client import from_env
bc = BridgeClient()
# 0. FAWE per-player-schematics probe.
try:
    cfg = bc.fawe_per_player_config()
except Exception as e:
    print(f'CANARY FAIL (bridge /fawe_per_player_config): {e!r}', file=sys.stderr); sys.exit(2)
if cfg.get('per_player_schematics') is True:
    print(
        f'CANARY FAIL: FAWE per-player-schematics=true. Our upload path writes '
        f'to the top-level schematics dir, but in this mode FAWE reads from '
        f'<uuid>/ subdirs so //schem load build would silently fail. Set '
        f'per-player-schematics=false in '
        f'{cfg.get(\"config_path\",\"<plugins/FastAsyncWorldEdit/config.yml>\")} '
        f'and restart the server.',
        file=sys.stderr,
    )
    sys.exit(2)
if cfg.get('per_player_schematics') is None:
    print(
        f\"CANARY WARN: cannot confirm per-player-schematics ({cfg.get('reason')}); \"
        f\"proceeding. If paste produces no blocks, recheck FAWE config.\",
        file=sys.stderr,
    )
# 1. Filesystem canary: .schem is where FAWE will scan it.
try:
    names = bc.schem_list()
except Exception as e:
    print(f'CANARY FAIL (bridge /fawe_schem_list): {e!r}', file=sys.stderr); sys.exit(2)
print('SCHEMS:', names)
if 'build' not in names:
    print(f'CANARY FAIL: build.schem not in FAWE schem dir; names={names!r}', file=sys.stderr); sys.exit(2)
# 2. Paper/RCON health probe (avoids FAWE — FAWE output is invisible to RCON).
try:
    r = from_env()
except Exception as e:
    print(f'CANARY FAIL (RCON connect): {e!r}', file=sys.stderr); sys.exit(2)
try:
    resp = r.command('list')
    if 'players online' not in resp:
        print(f'CANARY FAIL (RCON list response unexpected): {resp!r}', file=sys.stderr); sys.exit(2)
finally:
    try: r.close()
    except Exception: pass
print('CANARY: OK')
" || { echo 'BLOCKED: preflight canary failed — see stderr above'; exit 2; }
```

If this fails, **stop** and read the stderr line above: it names the
failing endpoint (bridge `/fawe_per_player_config`, `/fawe_schem_list`,
RCON connect, or unexpected RCON response) and includes observable
context (exception repr, schem names list, config path, or raw
response text) so the next action is unambiguous — restart/upgrade the
bridge, flip `per-player-schematics` to false in FAWE's config.yml,
fix `.env` RCON credentials, or re-check that the Paper server is
running with FAWE loaded.

Note: FAWE/WE runtime errors during `//paste` itself (e.g. region-deny,
schem-corrupt) remain invisible to both canary and builder. They surface
later via `replica_inspect`, which compares the built world against the
expected pixel grid block-for-block.

### Step 6: Teleport the player (if `--player` is set)

Place the player in front of the mural, centred, looking at its centre:

```
tp_x = origin.x + W/2
tp_y = origin.y + H/2
tp_z = origin.z - max(H/2, 8)
```

```bash
curl -s -X POST http://localhost:3001/command \
  -H 'Content-Type: application/json' \
  -d '{"command":"tp <name> <tp_x> <tp_y> <tp_z> facing <origin.x + W/2> <origin.y + H/2> <origin.z>"}'
```

### Step 7: Execute commands

Reuse the existing builder — it already supports both `# WORLDEDIT` and
`# VANILLA` sections. builder requires `--origin` and `--size WxHxL`; derive
both from `blueprint.meta` (axis-aware: xy → Wx(H+bl)x1, xz → Wx1x(H+bl),
yz → 1x(H+bl)xW).

```bash
read BUILDER_ORIGIN BUILDER_SIZE <<<"$(python3 -c "
import json
m = json.load(open('workspace/$SESSION_ID/blueprint.json'))['meta']
o = m['origin']; fp = m['actual_footprint']; axis = m['axis']
w, h = fp['w'], fp['h']
if axis == 'xy':   W, H, L = w, h, 1
elif axis == 'xz': W, H, L = w, 1, h
else:              W, H, L = 1, h, w   # yz
print(f'{o[\"x\"]},{o[\"y\"]},{o[\"z\"]} {W}x{H}x{L}')
")"

python3 -m kasukabe.agents.builder \
  --workspace workspace/$SESSION_ID \
  --origin "$BUILDER_ORIGIN" \
  --size "$BUILDER_SIZE"
```

### Step 8: Deterministic inspection

```bash
python3 -m kasukabe.replica_inspect \
  --workspace workspace/$SESSION_ID \
  --source-image <input_path>
```

### Step 9: Report to user

Read `workspace/$SESSION_ID/replica_inspect_done.json` and print:

- `completion_rate` (0–1 float, blocks-in-world vs blueprint)
- `pixel_diff_ratio` (0–1 float, rendered blueprint vs source image)
- `gamut_coverage` (0–1 float or null, share of source pixels representable
  by the active palette)
- `suggested_region_retry` — each entry is `[x1, y1, x2, y2, dither]`; turn
  them into CLI hints that **always include the current `--resume $SESSION_ID`**
  (region retries merge into the existing blueprint and cannot start fresh),
  e.g.
  `/kasukabe-pixel <image> at <origin> --axis <axis> --region X1,Y1,X2,Y2 --dither fs-linear --resume $SESSION_ID`

## Iteration policy

This skill does NOT loop. Max iterations = 1. If the user wants to refine a
region, they re-run with `--region X1,Y1,X2,Y2 --resume <SESSION_ID>` — the
VANILLA path handles sub-rect rewrites cheaply by merging into the existing
blueprint.

## Reporting rule (pixel murals from photos)

Do not claim fidelity to the source from `completion_rate` alone. The
`pixel_diff_ratio` value is the canonical fidelity metric. If the user
reports a semantic mismatch (eyes off by one row, mouth shifted, …), treat
it as a real error and suggest `--region` with the affected sub-rect.

## Minecraft Context

### Valid Block IDs (Minecraft 1.21 Java Edition)
All block IDs use `minecraft:` namespace, lowercase. Common blocks:
- Structural: `oak_planks`, `stone`, `cobblestone`, `oak_log`, `stone_bricks`, `bricks`
- Glass: `glass`, `glass_pane`
- Stairs/Slabs: `oak_stairs`, `oak_slab`, `stone_brick_stairs`
- Decorative: `oak_fence`, `oak_door`, `torch`, `lantern`
- Natural: `dirt`, `sand`, `gravel`, `grass_block`
- Special: `air` (empty)

### Coordinate Rules
- Coordinates in blueprint `blocks[]` are RELATIVE to origin (0-indexed)
- All commands must use ABSOLUTE world coordinates: `origin.x + rel_x`, `origin.y + rel_y`, `origin.z + rel_z`
- y=0 is ground level; y increases upward
- No relative coordinates (~) in commands

### Command Format (commands.txt)
```
# VANILLA
fill x1 y1 z1 x2 y2 z2 minecraft:block
setblock x y z minecraft:block
# WORLDEDIT
//pos1 x1 y1 z1
//pos2 x2 y2 z2
//set minecraft:block
```
- No leading slash in vanilla commands
- Section headers `# VANILLA` and `# WORLDEDIT` control routing

### FAWE / WorldEdit Command Semantics (common pitfalls)

These behaviors have bitten past runs. Read before emitting or debugging WE commands.

1. **`//paste` ALWAYS uses the player's (bot's) current position.**
   `//pos1 X Y Z` does **not** set the paste target — it only configures the
   first corner of the player's *selection*, which is consumed by `//set`,
   `//copy`, `//cut`, `//replace`, not by `//paste`. To paste a schematic at
   absolute coordinates, teleport the bot first:
   ```
   # WORLDEDIT
   /tp @s <ox> <oy> <oz>
   //schem load <name>
   //paste
   ```

2. **`//paste -a` means "skip air blocks", NOT "absolute".**
   A common misread. To paste at clipboard-saved origin, the flag is `-o`,
   and it requires the `.schem` file to carry a non-zero `WEOffsetX/Y/Z`
   NBT — which `mcschematic` does not write. So `-o` won't rescue a
   missing teleport.

3. **Bridge `POST /command` is fire-and-forget.**
   It returns `{executed: "/..."}` the moment `bot.chat` flushes to the
   socket. FAWE/WorldEdit routes its own output to the player chat
   packet, not to RCON or to the bridge response — **success on the
   bridge side does not imply FAWE executed correctly**. If blocks did
   not appear at the target, do NOT conclude "permission" or "session
   state" by default; first check whether the bot was teleported to the
   paste target.

4. **`//schem load` is asynchronous.**
   FAWE reads the `.schem` off disk on a worker thread. A very fast
   follow-up `//paste` may arrive before the clipboard is populated and
   silently fail with "no clipboard". If a large schematic fails but a
   small one succeeds, raise the inter-command delay or switch to
   `//schem paste <name>` (single synchronous command).

5. **`//paste` does NOT use or care about `//pos1` / `//pos2`.**
   Same as (1), stated as a regression-prevention note: if you see a
   commands.txt emitting `//pos1 … //paste` with no intervening `/tp`,
   that is the bug — add the `/tp @s`, do not "fix" the coords on `//pos1`.

6. **`//schem load` → `//paste` requires continuous bot session.**
   FAWE clipboards are in-memory per-player. If the bridge reconnects
   between load and paste (bot rejoins with a new session), FAWE discards
   the clipboard and `//paste` silently pastes nothing — bridge still
   returns `{executed: "/..."}`, but no blocks appear. If a run fails
   with target-region all-air and `completion_rate=0`, check bridge logs
   for "player joined" events during the WORLDEDIT section before
   blaming FAWE config or permissions.

### Environment
Connection details are configured via environment variables (see `.env`). Defaults for local development:
- RCON: `$CRAFTSMEN_RCON_HOST:$CRAFTSMEN_RCON_PORT` (default `127.0.0.1:25575`)
- RCON password: `$CRAFTSMEN_RCON_PASSWORD` (default for local dev only)
- Mineflayer bridge: `$KASUKABE_BRIDGE_URL` (default `http://localhost:3001`)
- Bridge endpoints: `GET /status`, `POST /command`, `GET /block/:x/:y/:z`, `POST /blocks`

## Platform Instructions (Codex)

### Tool Usage
- **Read files/images**: Use your file read capabilities
- **Write files**: Use your file write capabilities
- **Run commands**: Use shell execution

### Execution Mode
In Codex, this skill runs as an inline step within the Foreman's execution context. There is no separate subagent — complete each step sequentially and write your output files before moving to the next step.

