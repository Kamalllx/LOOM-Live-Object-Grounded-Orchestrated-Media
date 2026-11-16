// Exact-shape masks: decode LOOM's "rle:<h>x<w>:<COCO compressed counts>" strings into alpha canvases.
// Copied from loom/gateway/static/rle.js and wrapped for a classic content script: exposes self.LoomRle.
(() => {
  const cache = new Map();

  function countsFromString(s) {
    const cnts = [];
    let p = 0;
    while (p < s.length) {
      let x = 0, k = 0, more = 1, c = 0;
      while (more) {
        c = s.charCodeAt(p) - 48;
        x |= (c & 0x1f) << (5 * k);
        more = c & 0x20;
        p++; k++;
        if (!more && (c & 0x10)) x |= -1 << (5 * k);
      }
      if (cnts.length > 2) x += cnts[cnts.length - 2];
      cnts.push(x);
    }
    return cnts;
  }

  /** -> {h, w, data: Uint8Array row-major 0/1} */
  function decodeRle(value) {
    // counts use the alphabet "0".."o", which contains ":" - split only at the first two colons
    const i1 = value.indexOf(":"), i2 = value.indexOf(":", i1 + 1);
    const size = value.slice(i1 + 1, i2), counts = value.slice(i2 + 1);
    const [h, w] = size.split("x").map(Number);
    const runs = countsFromString(counts);
    const data = new Uint8Array(h * w);
    let idx = 0, v = 0;
    for (const run of runs) {
      if (v) for (let i = idx; i < idx + run; i++) { const col = (i / h) | 0, row = i - col * h; data[row * w + col] = 1; }
      idx += run; v ^= 1;
    }
    return { h, w, data };
  }

  /** Cached {fill, edge, m} canvases for one mask string; fill = solid alpha, edge = outline pixels. */
  function maskCanvases(value) {
    let hit = cache.get(value);
    if (hit) return hit;
    const m = decodeRle(value);
    const fill = document.createElement("canvas"), edge = document.createElement("canvas");
    fill.width = edge.width = m.w; fill.height = edge.height = m.h;
    const fi = new ImageData(m.w, m.h), ei = new ImageData(m.w, m.h);
    for (let y = 0; y < m.h; y++) for (let x = 0; x < m.w; x++) {
      const i = y * m.w + x;
      if (!m.data[i]) continue;
      fi.data[i * 4 + 3] = 255;
      const inside = x > 0 && y > 0 && x < m.w - 1 && y < m.h - 1 && m.data[i - 1] && m.data[i + 1] && m.data[i - m.w] && m.data[i + m.w];
      if (!inside) { ei.data[i * 4] = 255; ei.data[i * 4 + 1] = 255; ei.data[i * 4 + 2] = 255; ei.data[i * 4 + 3] = 255; }
    }
    fill.getContext("2d").putImageData(fi, 0, 0);
    edge.getContext("2d").putImageData(ei, 0, 0);
    hit = { fill, edge, m };
    if (cache.size > 600) cache.delete(cache.keys().next().value);
    cache.set(value, hit);
    return hit;
  }

  /** Is the picture-normalized point (u, v) inside the mask? */
  function hit(value, u, v) {
    const { m } = maskCanvases(value);
    const x = Math.floor(u * m.w), y = Math.floor(v * m.h);
    return x >= 0 && y >= 0 && x < m.w && y < m.h && m.data[y * m.w + x] === 1;
  }

  /** The sample to show at time t (track sorted by t; callers check the instance span first). A mask holds until the
   * next sample: board elements are re-sampled only when their ink changes (every 2-10 s), so a nearest-sample window
   * made them blink. Dense tracks (SAM 2.1, 5 fps) interpolate the box and take the nearest mask; sparse ones keep the
   * last mask and box, so strokes never appear before they are drawn. `maxGap` bounds how far a sample may be held. */
  function sampleAt(track, t, maxGap = Infinity) {
    const n = track.length;
    if (!n) return null;
    let lo = 0, hi = n;  // first index with s.t > t
    while (lo < hi) { const mid = (lo + hi) >> 1; if (track[mid].t <= t) lo = mid + 1; else hi = mid; }
    const a = track[lo - 1], b = track[lo];
    if (!a) return b.t - t <= maxGap ? b : null;
    if (!b) return t - a.t <= maxGap ? a : null;
    if (t - a.t > maxGap && b.t - t > maxGap) return null;
    const span = b.t - a.t;
    if (span > 0.5) return a;
    const k = span > 0 ? (t - a.t) / span : 0;
    return { t, mask: k > 0.5 ? b.mask : a.mask, bbox: a.bbox.map((v, j) => v + (b.bbox[j] - v) * k) };
  }

  self.LoomRle = { decodeRle, maskCanvases, hit, sampleAt };
})();
