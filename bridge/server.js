#!/usr/bin/env node
/**
 * minecraft-bridge: OpenClaw ↔ Minecraft Java Edition bridge service
 *
 * Start:
 *   node bridge-server.js
 *
 * Environment variables:
 *   MC_HOST          Minecraft server host (default: localhost)
 *   MC_PORT          Game port (default: 25565)
 *   MC_BOT_USERNAME  Bot username (default: ClawBot)
 *   MC_BRIDGE_PORT   Local HTTP service port (default: 3001)
 *   MC_VERSION       Minecraft version (default: 1.21.1)
 *   MC_AUTH          Authentication mode: offline | microsoft (default: offline)
 */

'use strict';

const http = require('http');
const fs = require('fs');
const path = require('path');
const os = require('os');
let mineflayer, pathfinderPlugin, Movements, goals, Vec3;
try {
  mineflayer = require('mineflayer');
  const pf = require('mineflayer-pathfinder');
  pathfinderPlugin = pf.pathfinder;
  Movements = pf.Movements;
  goals = pf.goals;
  Vec3 = require('vec3').Vec3;
} catch (e) {
  console.error('[bridge] Missing dependencies. Install them first:');
  console.error('  npm install mineflayer mineflayer-pathfinder vec3');
  process.exit(1);
}

const CFG = {
  mc: {
    host: process.env.MC_HOST || 'localhost',
    port: parseInt(process.env.MC_PORT) || 25565,
    username: process.env.MC_BOT_USERNAME || 'ClawBot',
    version: process.env.MC_VERSION || '1.21.11',
    auth: process.env.MC_AUTH || 'offline',
  },
  bridge: {
    port: parseInt(process.env.MC_BRIDGE_PORT) || 3001,
    reconnectMs: 5000,
    actionTimeout: 30_000,
    maxRetries: 30,
  },
};

const state = {
  bot: null,
  connected: false,
  retries: 0,
  currentAction: null,
};

const MAX_BODY_BYTES = 64 * 1024;
// Upload endpoint needs a much larger cap — schematics can reach a few MB.
const MAX_UPLOAD_BYTES = 32 * 1024 * 1024;

// ── FAWE schematic dir resolution (3-level fallback) ─────────────────────
// 1. env KASUKABE_FAWE_SCHEM_DIR
// 2. ./plugins/FastAsyncWorldEdit/schematics/ (relative to bridge CWD)
// 3. null (caller gets a useful error)
function resolveFaweSchemDir() {
  const envDir = process.env.KASUKABE_FAWE_SCHEM_DIR;
  if (envDir && fs.existsSync(envDir)) return envDir;
  const cwdDir = path.resolve(process.cwd(), 'plugins/FastAsyncWorldEdit/schematics');
  if (fs.existsSync(cwdDir)) return cwdDir;
  // Also try one level up (bridge is often in ./bridge/ while Paper is at ./)
  const parentDir = path.resolve(process.cwd(), '../plugins/FastAsyncWorldEdit/schematics');
  if (fs.existsSync(parentDir)) return parentDir;
  return null;
}

function isDirWritable(dir) {
  try {
    fs.accessSync(dir, fs.constants.W_OK);
    return true;
  } catch (_) {
    return false;
  }
}

// ── Minimal multipart/form-data parser for a single file field ────────────
// Returns { filename, contentType, data (Buffer) } or throws.
function parseMultipartSingleFile(bodyBuffer, contentTypeHeader) {
  const m = /boundary=(?:"([^"]+)"|([^;]+))/i.exec(contentTypeHeader || '');
  if (!m) throw new Error('multipart boundary not found in Content-Type');
  const boundary = '--' + (m[1] || m[2]);
  const boundaryBuf = Buffer.from(boundary);
  // Split body on boundary
  const parts = [];
  let idx = 0;
  while (idx < bodyBuffer.length) {
    const next = bodyBuffer.indexOf(boundaryBuf, idx);
    if (next < 0) break;
    if (idx > 0) parts.push(bodyBuffer.slice(idx, next));
    idx = next + boundaryBuf.length;
    // skip CRLF after boundary
    if (bodyBuffer[idx] === 0x0d && bodyBuffer[idx + 1] === 0x0a) idx += 2;
  }
  for (const part of parts) {
    // Headers and body separated by CRLF CRLF
    const sep = part.indexOf(Buffer.from('\r\n\r\n'));
    if (sep < 0) continue;
    const headers = part.slice(0, sep).toString('utf8');
    let data = part.slice(sep + 4);
    // trim trailing CRLF before next boundary
    if (data.length >= 2 && data[data.length - 2] === 0x0d && data[data.length - 1] === 0x0a) {
      data = data.slice(0, data.length - 2);
    }
    const disp = /Content-Disposition:\s*form-data;([^\r\n]*)/i.exec(headers);
    if (!disp) continue;
    const fn = /filename="([^"]*)"/i.exec(disp[1]);
    if (!fn) continue;
    const ct = /Content-Type:\s*([^\r\n]+)/i.exec(headers);
    return {
      filename: fn[1],
      contentType: ct ? ct[1].trim() : 'application/octet-stream',
      data,
    };
  }
  throw new Error('no file field found in multipart body');
}

function createBot() {
  if (state.bot) {
    try { state.bot.end(); } catch (_) {}
  }

  console.log(`[bridge] Connecting to ${CFG.mc.host}:${CFG.mc.port} as ${CFG.mc.username}...`);

  state.bot = mineflayer.createBot({
    host: CFG.mc.host,
    port: CFG.mc.port,
    username: CFG.mc.username,
    version: CFG.mc.version,
    auth: CFG.mc.auth,
  });

  state.bot.loadPlugin(pathfinderPlugin);

  state.bot.once('spawn', () => {
    state.connected = true;
    state.retries = 0;
    const mv = new Movements(state.bot);
    state.bot.pathfinder.setMovements(mv);
    console.log(`[bridge] Bot online @ ${JSON.stringify(botPos())}`);
  });

  state.bot.on('error', err => {
    console.error('[bridge] Bot error:', err.message);
  });

  state.bot.on('end', reason => {
    state.connected = false;
    state.currentAction = null;
    console.log(`[bridge] Bot disconnected (${reason}), retrying in ${CFG.bridge.reconnectMs / 1000}s...`);
    if (state.retries < CFG.bridge.maxRetries) {
      state.retries++;
      setTimeout(createBot, CFG.bridge.reconnectMs);
    } else {
      console.error('[bridge] Too many reconnect attempts. Restart manually after checking config.');
    }
  });

  state.bot.on('kicked', reason => {
    console.warn('[bridge] Bot kicked:', reason);
  });
}

function botPos() {
  const p = state.bot?.entity?.position;
  if (!p) return null;
  return { x: Math.round(p.x), y: Math.round(p.y), z: Math.round(p.z) };
}

function requireConnected(res) {
  if (!state.connected || !state.bot) {
    json(res, 503, { error: 'Bot not connected', hint: 'Open Minecraft and check MC_HOST/MC_PORT' });
    return false;
  }
  return true;
}

function json(res, code, body) {
  res.writeHead(code, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(body));
}

function withTimeout(promise, ms = CFG.bridge.actionTimeout) {
  return Promise.race([
    promise,
    new Promise((_, rej) => setTimeout(() => rej(new Error('Action timed out')), ms)),
  ]);
}

const handlers = {
  'GET /status': async () => ({
    connected: state.connected,
    username: CFG.mc.username,
    position: botPos(),
    health: state.bot?.health ?? null,
    food: state.bot?.food ?? null,
    saturation: state.bot?.foodSaturation ?? null,
    gameTime: state.bot?.time?.timeOfDay ?? null,
    isDay: (state.bot?.time?.timeOfDay ?? 0) < 13000,
    inventoryCount: state.bot?.inventory?.items()?.length ?? 0,
    currentAction: state.currentAction,
    bridgeVersion: '1.0.0',
  }),

  'GET /inventory': async () => {
    const items = (state.bot.inventory.items() || []).map(i => ({
      name: i.name,
      displayName: i.displayName,
      count: i.count,
      slot: i.slot,
      durability: i.durabilityUsed ?? null,
    }));
    return { items, totalStacks: items.length };
  },

  'GET /position': async () => ({
    ...botPos(),
    yaw: state.bot.entity.yaw,
    pitch: state.bot.entity.pitch,
  }),

  'GET /health': async () => ({
    health: state.bot.health,
    food: state.bot.food,
    saturation: state.bot.foodSaturation,
    isDead: state.bot.health <= 0,
  }),

  'GET /nearby': async (_, q) => {
    const radius = parseInt(q?.radius ?? '16');
    const entities = Object.values(state.bot.entities)
      .filter(e => e !== state.bot.entity && e.position)
      .filter(e => e.position.distanceTo(state.bot.entity.position) <= radius)
      .slice(0, 20)
      .map(e => ({
        name: e.name || e.username || 'unknown',
        type: e.type,
        distance: Math.round(e.position.distanceTo(state.bot.entity.position)),
        position: { x: Math.round(e.position.x), y: Math.round(e.position.y), z: Math.round(e.position.z) },
      }));
    return { entities, radius };
  },

  'POST /chat': async ({ message }) => {
    if (!message) throw new Error('message field required');
    state.bot.chat(String(message).slice(0, 256));
    return { sent: message };
  },

  'POST /command': async ({ command }) => {
    if (!command) throw new Error('command field required');
    const BLOCKED_COMMANDS = /^\/?(?:op|deop|stop|ban|ban-ip|pardon|kick|whitelist|save-off|save-all|save-on|reload|restart)\b/i;
    if (BLOCKED_COMMANDS.test(command.trim())) {
      throw new Error(`Command blocked for safety: "${command}". Use minecraft-server-admin / RCON for server administration.`);
    }
    const cmd = command.startsWith('/') ? command : `/${command}`;
    state.bot.chat(cmd);
    return { executed: cmd };
  },

  'POST /move': async ({ x, y, z }) => {
    if (x === undefined || z === undefined) throw new Error('x and z required');
    const COORD_LIMIT = 30_000_000;
    if (Math.abs(+x) > COORD_LIMIT || Math.abs(+z) > COORD_LIMIT || (y !== undefined && Math.abs(+y) > 320)) {
      throw new Error(`Coordinates out of range (max ±${COORD_LIMIT} XZ, ±320 Y)`);
    }
    state.currentAction = `moving to ${x},${y ?? '?'},${z}`;
    const goal = y !== undefined ? new goals.GoalBlock(+x, +y, +z) : new goals.GoalXZ(+x, +z);
    await withTimeout(new Promise((res, rej) => {
      state.bot.pathfinder.setGoal(goal);
      const onGoal = () => { state.bot.removeListener('path_update', onPath); res(); };
      const onPath = (e) => { if (e.status === 'noPath') { state.bot.removeListener('goal_reached', onGoal); rej(new Error('No path found')); } };
      state.bot.once('goal_reached', onGoal);
      state.bot.on('path_update', onPath);
    }));
    state.currentAction = null;
    return { arrived: botPos() };
  },

  'POST /mine': async ({ blockName, count = 1 }) => {
    if (!blockName) throw new Error('blockName required');
    count = Math.min(Math.max(1, +count), 64);
    const blockId = state.bot.registry.blocksByName[blockName]?.id;
    if (!blockId) throw new Error(`Unknown block: ${blockName}`);

    state.currentAction = `mining ${count}x ${blockName}`;
    let mined = 0;
    for (let i = 0; i < +count; i++) {
      const block = state.bot.findBlock({ matching: blockId, maxDistance: 64 });
      if (!block) break;
      await withTimeout(state.bot.pathfinder.goto(new goals.GoalLookAtBlock(block.position, state.bot.world)));
      await withTimeout(state.bot.dig(block));
      mined++;
    }
    state.currentAction = null;
    return { blockName, requested: +count, mined };
  },

  'POST /collect': async ({ itemName, count = 1 }) => {
    if (!itemName) throw new Error('itemName field required');
    count = Math.min(Math.max(1, +count), 64);
    const targets = Object.values(state.bot.entities)
      .filter(e => e.objectType === 'Item' && e.metadata?.[8]?.itemId)
      .filter(e => {
        const meta = e.metadata[8];
        const id = state.bot.registry.items[meta.itemId]?.name;
        return id === itemName;
      })
      .slice(0, +count);

    if (!targets.length) return { collected: 0, message: `No ${itemName} on the ground nearby` };

    state.currentAction = `collecting ${itemName}`;
    let collected = 0;
    for (const entity of targets) {
      try {
        await withTimeout(state.bot.pathfinder.goto(new goals.GoalFollow(entity, 1)));
        collected++;
      } catch (_) {}
    }
    state.currentAction = null;
    return { itemName, collected };
  },

  'POST /craft': async ({ itemName, count = 1 }) => {
    if (!itemName) throw new Error('itemName required');
    const item = state.bot.registry.itemsByName[itemName];
    if (!item) throw new Error(`Unknown item: ${itemName}`);

    const tableBlock = state.bot.findBlock({
      matching: state.bot.registry.blocksByName['crafting_table']?.id,
      maxDistance: 5,
    });

    const recipes = state.bot.recipesFor(item.id, null, 1, tableBlock);
    if (!recipes.length) throw new Error(`No recipe for ${itemName} (or missing crafting table)`);

    state.currentAction = `crafting ${count}x ${itemName}`;
    await withTimeout(state.bot.craft(recipes[0], +count, tableBlock));
    state.currentAction = null;
    return { crafted: itemName, count: +count };
  },

  'POST /follow': async ({ playerName }) => {
    if (!playerName) throw new Error('playerName required');
    const target = state.bot.players[playerName]?.entity;
    if (!target) throw new Error(`Player ${playerName} not found or too far away`);
    state.currentAction = `following ${playerName}`;
    state.bot.pathfinder.setGoal(new goals.GoalFollow(target, 2), true);
    return { following: playerName };
  },

  'POST /stop': async () => {
    state.bot.pathfinder.setGoal(null);
    state.currentAction = null;
    return { stopped: true };
  },

  // ── FAWE / schematic endpoints ─────────────────────────────────────────
  'GET /fawe_check': async () => {
    const dir = resolveFaweSchemDir();
    return {
      installed: !!dir,         // best-effort: presence of schem dir == FAWE installed
      schem_dir: dir,
      schem_dir_writable: dir ? isDirWritable(dir) : false,
      version: null,            // not introspected; canary in the Skill validates functionality
    };
  },

  'GET /fawe_schem_dir': async () => {
    const dir = resolveFaweSchemDir();
    return { path: dir };
  },

  // Filesystem-level schem listing. Bypasses FAWE entirely because FAWE's
  // `//schem list` output routes to player chat packets and is invisible
  // to RCON, so an RCON-based query always returns empty. The canary only
  // needs to know "did build.schem land in the dir FAWE scans" — that's a
  // filesystem question.
  //
  // Limitation: only scans the top-level dir. If FAWE's
  // per-player-schematics is enabled, files land under `<uuid>/` subdirs;
  // this endpoint will not see them. /upload_schematic also writes to the
  // top level, so both paths require per-player-schematics=false.
  'GET /fawe_schem_list': async () => {
    const dir = resolveFaweSchemDir();
    if (!dir) return { names: [], schem_dir: null };
    let entries;
    try {
      entries = fs.readdirSync(dir);
    } catch (err) {
      return { names: [], schem_dir: dir, error: err.message };
    }
    const names = entries
      .filter(f => /\.schem(atic)?$/i.test(f))
      .map(f => f.replace(/\.schem(atic)?$/i, ''));
    return { names, schem_dir: dir };
  },

  'POST /validate_block': async ({ block }) => {
    if (!block) throw new Error('block field required');
    const bare = String(block).replace(/^minecraft:/, '').replace(/\[[^\]]*\]$/, '');
    const rec = state.bot?.registry?.blocksByName?.[bare];
    return { block, valid: !!rec, id: rec?.id ?? null };
  },

  // Read FAWE's config.yml and report the per-player-schematics flag. When
  // per-player-schematics=true, FAWE stores/reads schematics under
  // <schem_dir>/<uuid>/ subdirs; our upload + list endpoints only see the
  // top-level dir, so that mode silently breaks the full-mode pipeline.
  // The canary in /kasukabe-pixel Step 5.5 uses this to fail fast.
  'GET /fawe_per_player_config': async () => {
    const dir = resolveFaweSchemDir();
    if (!dir) return { per_player_schematics: null, reason: 'schem dir not found' };
    // config.yml is the sibling of schematics/: plugins/FastAsyncWorldEdit/config.yml
    const cfgPath = path.resolve(dir, '..', 'config.yml');
    let raw;
    try {
      raw = fs.readFileSync(cfgPath, 'utf8');
    } catch (err) {
      return { per_player_schematics: null, reason: `cannot read ${cfgPath}: ${err.message}` };
    }
    // Narrow regex probe — avoid pulling in a full YAML dep for one key.
    // Matches indented forms like "  per-player-schematics: true".
    const m = /^[ \t]*per-player-schematics[ \t]*:[ \t]*(true|false)\b/im.exec(raw);
    if (!m) return { per_player_schematics: false, reason: 'key absent, default false', config_path: cfgPath };
    return { per_player_schematics: m[1].toLowerCase() === 'true', config_path: cfgPath };
  },
};

// NOTE: /upload_schematic is handled directly in the HTTP request dispatch
// (needs raw Buffer body + multipart parsing, bypassing the handlers dict).

const server = http.createServer((req, res) => {
  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  const urlNoQs = req.url.split('?')[0];
  const isUpload = req.method === 'POST' && urlNoQs === '/upload_schematic';
  const maxBytes = isUpload ? MAX_UPLOAD_BYTES : MAX_BODY_BYTES;

  // Collect body as Buffer chunks so we can handle both JSON (utf8) and binary (multipart).
  const chunks = [];
  let bodyBytes = 0;
  let aborted = false;
  req.on('data', c => {
    bodyBytes += c.length;
    if (bodyBytes > maxBytes) {
      if (!aborted) {
        aborted = true;
        json(res, 413, { success: false, error: 'Request body too large' });
        req.destroy();
      }
      return;
    }
    chunks.push(c);
  });

  req.on('end', async () => {
    if (aborted) return;
    const bodyBuf = Buffer.concat(chunks);
    const body = bodyBuf.toString('utf8');
    const url = req.url.split('?')[0];
    const qs = Object.fromEntries(new URLSearchParams(req.url.split('?')[1] || ''));
    const key = `${req.method} ${url}`;

    // GET /block/:x/:y/:z  — single block query
    const blockMatch = url.match(/^\/block\/(-?\d+)\/(-?\d+)\/(-?\d+)$/);
    if (req.method === 'GET' && blockMatch) {
      if (!state.bot || !state.bot.entity) {
        json(res, 503, { error: 'Bot not connected', hint: 'Start the bridge server and connect the bot first' });
        return;
      }
      const x = parseInt(blockMatch[1], 10);
      const y = parseInt(blockMatch[2], 10);
      const z = parseInt(blockMatch[3], 10);
      try {
        const block = state.bot.blockAt(new Vec3(x, y, z));
        if (!block) {
          json(res, 200, { success: true, x, y, z, block: 'minecraft:air', found: false });
          return;
        }
        const blockName = block.name.includes(':') ? block.name : `minecraft:${block.name}`;
        json(res, 200, { success: true, x, y, z, block: blockName, found: true,
                         displayName: block.displayName || block.name });
      } catch (err) {
        json(res, 500, { success: false, error: err.message });
      }
      return;
    }

    // POST /blocks  — batch block query (up to 200 positions)
    if (req.method === 'POST' && url === '/blocks') {
      if (!state.bot || !state.bot.entity) {
        json(res, 503, { error: 'Bot not connected', hint: 'Start the bridge server and connect the bot first' });
        return;
      }
      let positions;
      try {
        const parsed = JSON.parse(body || '{}');
        positions = parsed.positions;
        if (!Array.isArray(positions)) throw new Error('positions must be an array');
        if (positions.length > 200) throw new Error('max 200 positions per request');
      } catch (err) {
        json(res, 400, { success: false, error: err.message });
        return;
      }
      try {
        const blocks = positions.map(({ x, y, z }) => {
          const vec = new Vec3(+x, +y, +z);
          const block = state.bot.blockAt(vec);
          if (!block) {
            return { x: +x, y: +y, z: +z, block: 'minecraft:air', found: false };
          }
          const blockName = block.name.includes(':') ? block.name : `minecraft:${block.name}`;
          return { x: +x, y: +y, z: +z, block: blockName, found: true };
        });
        json(res, 200, { success: true, blocks, count: blocks.length });
      } catch (err) {
        json(res, 500, { success: false, error: err.message });
      }
      return;
    }

    // POST /upload_schematic — multipart file upload to FAWE schematics dir.
    // Does NOT require bot connection (the schematic goes to the Paper plugin
    // directory on disk; FAWE picks it up on next //schem load).
    if (req.method === 'POST' && url === '/upload_schematic') {
      try {
        const dir = resolveFaweSchemDir();
        if (!dir) {
          json(res, 500, {
            success: false,
            error: 'FAWE schematics directory not found',
            hint: 'Set KASUKABE_FAWE_SCHEM_DIR env var or ensure ./plugins/FastAsyncWorldEdit/schematics/ exists',
          });
          return;
        }
        if (!isDirWritable(dir)) {
          json(res, 500, { success: false, error: `FAWE schem dir not writable: ${dir}` });
          return;
        }
        const ct = req.headers['content-type'] || '';
        const { filename, data } = parseMultipartSingleFile(bodyBuf, ct);
        // Safety: strip any path components from the filename
        const safeName = path.basename(filename).replace(/[^A-Za-z0-9._-]/g, '_');
        if (!safeName) throw new Error('invalid filename');
        // Enforce .schem or .schematic extension
        if (!/\.schem(atic)?$/i.test(safeName)) {
          throw new Error('filename must end with .schem or .schematic');
        }
        const destPath = path.join(dir, safeName);
        const tmpPath = destPath + '.tmp';
        fs.writeFileSync(tmpPath, data);
        fs.renameSync(tmpPath, destPath);
        json(res, 200, { success: true, path: destPath, bytes: data.length, filename: safeName });
      } catch (err) {
        console.error('[bridge] /upload_schematic error:', err.message);
        json(res, 500, { success: false, error: err.message });
      }
      return;
    }

    const handler = handlers[key];

    if (!handler) {
      json(res, 404, { error: 'Unknown route', available: Object.keys(handlers) });
      return;
    }

    // Routes that do not require a connected bot
    const NO_BOT_REQUIRED = new Set(['GET /status', 'GET /fawe_check', 'GET /fawe_schem_dir', 'GET /fawe_schem_list', 'GET /fawe_per_player_config']);
    if (!NO_BOT_REQUIRED.has(key) && !requireConnected(res)) return;

    try {
      const parsed = body ? JSON.parse(body) : {};
      const result = await handler(parsed, qs);
      json(res, 200, { success: true, ...result });
    } catch (err) {
      console.error(`[bridge] ${key} error:`, err.message);
      json(res, 500, { success: false, error: err.message });
    }
  });
});

server.listen(CFG.bridge.port, '127.0.0.1', () => {
  console.log('Minecraft Bridge v1.0.0');
  console.log(`HTTP API -> http://localhost:${CFG.bridge.port}`);
  console.log('Bound to 127.0.0.1 only — do not expose this service publicly.');
  console.log('Note: CORS headers are not sent — only same-origin or non-browser clients can access this API.');
  console.log(`Connecting to Minecraft ${CFG.mc.host}:${CFG.mc.port}...`);
  console.log(`  version=${CFG.mc.version}, auth=${CFG.mc.auth}`);
  createBot();
});

server.on('error', err => {
  if (err.code === 'EADDRINUSE') {
    console.error(`[bridge] Port ${CFG.bridge.port} already in use — bridge may already be running.`);
    console.error(`  Check: curl http://localhost:${CFG.bridge.port}/status`);
  } else {
    console.error('[bridge] Server error:', err);
  }
  process.exit(1);
});

process.on('SIGINT', () => {
  console.log('\n[bridge] Shutting down...');
  try { state.bot?.end(); } catch (_) {}
  server.close(() => process.exit(0));
});
