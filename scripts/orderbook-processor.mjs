import axios from "axios";

// ─── helpers ────────────────────────────────────────────────────────────────
const sum = (arr) => arr.reduce((a, b) => a + b, 0);
const avg = (arr) => (arr.length ? sum(arr) / arr.length : 0);

/**
 * Return entries within `depthFraction` of the mid-market price.
 * `levels` is a raw L2 array of [price, size] sorted descending (bids) or
 * ascending (asks) — the caller must guarantee sort order so we can break
 * early once entries fall outside the threshold.
 */
function sliceDepth(levels, mid, depthFraction = 0.01) {
  const threshold = mid * depthFraction;
  const out = [];
  for (const [px, sz] of levels) {
    if (Math.abs(px - mid) <= threshold) out.push([px, sz]);
    else break;
  }
  return out;
}

/**
 * Scan top `n` levels and flag any order whose size is >= `multiplier` ×
 * the moving average of the `w` surrounding levels (both sides).
 * Returns an array of { price, size } objects.
 */
function detectWalls(levels, n = 10, w = 3, multiplier = 3) {
  const walls = [];
  for (let i = 0; i < Math.min(n, levels.length); i++) {
    const left = Math.max(0, i - w);
    const right = Math.min(levels.length, i + w + 1);
    const slice = levels.slice(left, right);
    const ma = avg(slice.map(([, s]) => s));
    const [, sz] = levels[i];
    if (sz >= ma * multiplier && ma > 0) {
      walls.push({ price: levels[i][0], size: levels[i][1] });
    }
  }
  return walls;
}

// ─── public API ─────────────────────────────────────────────────────────────

/**
 * Accept raw L2 bid/ask arrays and return compressed analytical metrics.
 *
 * @param {{ bids: [number,number][], asks: [number,number][] }} rawData
 * @returns {{ spread: number, spreadPercent: number, imbalanceRatio: number,
 *            buyWalls: {price:number,size:number}[], sellWalls: {price:number,size:number}[] }}
 */
export function processOrderBook(rawData) {
  const { bids, asks } = rawData;
  if (!bids?.length || !asks?.length) {
    throw new Error("bids and asks arrays must be non-empty");
  }

  const bestBid = bids[0][0];
  const bestAsk = asks[0][0];
  const mid = (bestBid + bestAsk) / 2;

  // Spread
  const spread = bestAsk - bestBid;
  const spreadPercent = (spread / mid) * 100;

  // Volume imbalance limited to the top 1% depth from the mid-price
  const nearBids = sliceDepth(bids, mid, 0.01);
  const nearAsks = sliceDepth(asks, mid, 0.01);
  const bidVol = sum(nearBids.map(([, s]) => s));
  const askVol = sum(nearAsks.map(([, s]) => s));
  const imbalanceRatio = askVol > 0 ? bidVol / askVol : Infinity;

  // Large-lot walls on the first 10 levels
  const buyWalls = detectWalls(bids);
  const sellWalls = detectWalls(asks);

  return { spread, spreadPercent, imbalanceRatio, buyWalls, sellWalls };
}

/**
 * Convert the metrics object (plus optional technicals) into a clean LLM-ready
 * markdown block.
 *
 * @param {ReturnType<typeof processOrderBook>} metrics
 * @param {{ [key:string]: unknown }} [technicals] — extra fields such as
 *   { rsi: 42, emaTrend: "bearish" } appended at the bottom.
 */
export function generateLLMPrompt(metrics, technicals = {}) {
  const { spread, spreadPercent, imbalanceRatio, buyWalls, sellWalls } = metrics;

  const lines = ["### Order Book Snap"];

  // Spread
  lines.push("");
  lines.push(`- **Spread** : \$${spread.toFixed(4)} (${spreadPercent.toFixed(3)}%)`);

  // Imbalance with a human-readable label
  const imbalLabel =
    imbalanceRatio > 1.15
      ? "bullish (more bid volume)"
      : imbalanceRatio < 0.85
        ? "bearish (more ask volume)"
        : "neutral";
  lines.push(`- **Imbalance** : ${imbalanceRatio.toFixed(3)}x — ${imbalLabel}`);

  // Buy / sell walls — only emitted when present
  if (buyWalls.length) {
    lines.push(
      `- **Buy walls** : ${buyWalls.map((w) => `\$${w.price} (${w.size} lots)`).join("; ")}`,
    );
  }
  if (sellWalls.length) {
    lines.push(
      `- **Sell walls** : ${sellWalls.map((w) => `\$${w.price} (${w.size} lots)`).join("; ")}`,
    );
  }

  // Extra technical fields
  const extras = Object.entries(technicals).filter(([, v]) => v !== undefined && v !== null);
  if (extras.length) {
    lines.push("");
    for (const [k, v] of extras) {
      const label = k
        .replace(/([A-Z])/g, " $1")
        .replace(/^./, (s) => s.toUpperCase());
      lines.push(`- **${label}** : ${v}`);
    }
  }

  return lines.join("\n");
}

// ─── HTTP polling convenience ───────────────────────────────────────────────

/**
 * Fetch an L2 snapshot from an exchange REST endpoint, process it, and return
 * the LLM-ready string in one call.
 *
 * @param {string} url — REST endpoint returning { bids: [][], asks: [][] }
 * @param {{ timeout?: number }} [opts]
 */
export async function fetchAndProcess(url, opts = {}) {
  const { data } = await axios.get(url, { timeout: opts.timeout ?? 10_000 });
  const metrics = processOrderBook(data);
  return generateLLMPrompt(metrics);
}
