const test = require('node:test');
const assert = require('node:assert/strict');
require('../../extension/views.js');

test('concept graph tolerates cycles and escapes lesson data', () => {
  const html = globalThis.LoomViews.graph({
    concept_nodes: [
      { node_id: 'a', label: '<script>alert(1)</script>', prerequisites: ['b'], evidence: { segment_ids: ['s'] } },
      { node_id: 'b', label: 'Base', prerequisites: ['a'], evidence: {} },
    ], transcript: [{ seg_id: 's', start: 12 }], objects: [],
  });
  assert.match(html, /data-act="concept"/);
  assert.match(html, /data-t="12"/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;/);
});

test('map highlights retrieved items, clamps coordinates and escapes labels', () => {
  const html = globalThis.LoomViews.map({ items: [
    { id: 'a', kind: 'concept', label: '<unsafe>', t: 9, x: 0.2, y: 0.3 },
    { id: 'b', kind: 'speech', label: 'Other', t: 4, x: -20, y: 22 },
  ], edges: [['a', 'b', 0.5]] }, ['a']);
  assert.match(html, /your question/);
  assert.match(html, /data-t="9"/);
  assert.match(html, /&lt;unsafe&gt;/);
  assert.doesNotMatch(html, /<unsafe>/);
  assert.match(html, /cx="20" cy="320"/);
});

test('empty lesson visualizations have useful empty states', () => {
  assert.match(globalThis.LoomViews.graph({}), /No concepts/);
  assert.match(globalThis.LoomViews.map({}, []), /No indexed/);
});
