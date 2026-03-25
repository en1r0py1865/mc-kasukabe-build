/**
 * kasukabe bridge extension — block query routes
 *
 * These two route handlers should be injected into bridge-server.js
 * inside the req.on('end', async () => { ... }) callback,
 * BEFORE the existing `const handler = handlers[key]` lookup.
 *
 * Requires: Vec3 (already imported in bridge-server.js)
 *
 * Routes added:
 *   GET  /block/:x/:y/:z  — query a single block at absolute world coordinates
 *   POST /blocks           — batch query up to 200 block positions
 *
 * Note: state.bot.blockAt() returns null if the chunk is not loaded.
 * The Builder always calls `forceload add` before placing blocks,
 * so this should not be an issue during normal inspection.
 */

// ─── PASTE THIS BLOCK inside req.on('end', async () => { ... })
//     BEFORE the line: const handler = handlers[key]  ────────────────────────

/*
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
*/
