const assert = require('node:assert/strict');
const test = require('node:test');

const { clampTimeRange, panTimeRange, timeMs } = require('./static/energy/chart-controls.js');
const hour = 60 * 60 * 1000;

test('converts local hour labels without a timezone shift', () => {
  assert.equal(timeMs('2026-09-28 12:00:00'), Date.UTC(2026, 8, 28, 12));
  assert.equal(timeMs('2026-09-28T12:00:00'), Date.UTC(2026, 8, 28, 12));
});

test('keeps a panned range at the first and last hour', () => {
  const bounds = [0, 24 * hour];
  assert.deepEqual(clampTimeRange([-2 * hour, 4 * hour], bounds), [0, 6 * hour]);
  assert.deepEqual(clampTimeRange([22 * hour, 28 * hour], bounds), [18 * hour, 24 * hour]);
});

test('limits zoom to one hour and the complete data range', () => {
  const bounds = [0, 24 * hour];
  assert.deepEqual(clampTimeRange([10 * hour, 10.5 * hour], bounds), [9.75 * hour, 10.75 * hour]);
  assert.deepEqual(clampTimeRange([-100 * hour, 100 * hour], bounds), bounds);
  assert.deepEqual(clampTimeRange([0, hour / 2], [0, hour / 2]), [0, hour / 2]);
  assert.equal(clampTimeRange([0, hour], [NaN, NaN]), null);
});

test('dragging stops at the data edges without changing the visible duration', () => {
  const bounds = [0, 24 * hour];
  const range = [10 * hour, 12 * hour];
  assert.deepEqual(panTimeRange(range, bounds, 5000, 500), [0, 2 * hour]);
  assert.deepEqual(panTimeRange(range, bounds, -5000, 500), [22 * hour, 24 * hour]);
  assert.deepEqual(panTimeRange(range, bounds, 125, 500), [9.5 * hour, 11.5 * hour]);
  assert.equal(panTimeRange(range, bounds, 10, 0), null);
});

test('zoom buttons change only their chart and stop at both limits', () => {
  const charts = [0, 1].map((index) => {
    const graph = {
      layout: { xaxis: {
        range: ['2026-09-28T00:00:00', '2026-09-29T00:00:00'],
        minallowed: '2026-09-28T00:00:00',
        maxallowed: '2026-09-29T00:00:00',
      } },
      on(name, callback) { this.onRelayout = callback; },
      addEventListener(name, callback) { this[name] = callback; },
      getBoundingClientRect: () => ({ left: 0, top: 0 }),
      setPointerCapture() { this.captured = true; },
      hasPointerCapture() { return this.captured; },
      releasePointerCapture() { this.captured = false; },
      _fullLayout: { _size: { l: 50, t: 20, w: 500, h: 300 } },
    };
    const zoomIn = { dataset: { chartZoom: 'in' } };
    const zoomOut = { dataset: { chartZoom: 'out' } };
    const container = {
      dataset: { chartId: `chart-${index}` },
      querySelectorAll: () => [],
      querySelector: (selector) => selector.includes('"in"') ? zoomIn : zoomOut,
      addEventListener(name, callback) { this[name] = callback; },
    };
    return { graph, container, zoomIn, zoomOut };
  });
  global.document = {
    addEventListener(name, callback) { this.onReady = callback; },
    querySelectorAll: () => charts.map(({ container }) => container),
    getElementById: (id) => charts.find(({ container }) => container.dataset.chartId === id).graph,
  };
  global.window = { Plotly: {
    relayout(graph, update) {
      graph.layout.xaxis.range = update['xaxis.range'];
      graph.onRelayout();
    },
  } };
  global.Plotly = window.Plotly;
  delete require.cache[require.resolve('./static/energy/chart-controls.js')];
  require('./static/energy/chart-controls.js');
  document.onReady();

  const [first, second] = charts;
  assert.equal(first.zoomOut.disabled, true);
  first.container.click({ target: { closest: () => first.zoomIn } });
  assert.equal(first.zoomOut.disabled, false);
  assert.equal(timeMs(first.graph.layout.xaxis.range[1]) - timeMs(first.graph.layout.xaxis.range[0]), 12 * hour);
  assert.equal(timeMs(second.graph.layout.xaxis.range[1]) - timeMs(second.graph.layout.xaxis.range[0]), 24 * hour);
  for (let index = 0; index < 10; index += 1) {
    first.container.click({ target: { closest: () => first.zoomIn } });
  }
  assert.equal(timeMs(first.graph.layout.xaxis.range[1]) - timeMs(first.graph.layout.xaxis.range[0]), hour);
  assert.equal(first.zoomIn.disabled, true);
  first.container.click({ target: { closest: () => first.zoomOut } });
  assert.equal(timeMs(first.graph.layout.xaxis.range[1]) - timeMs(first.graph.layout.xaxis.range[0]), 2 * hour);
  const start = Date.UTC(2026, 8, 28);
  first.graph.layout.xaxis.range = [new Date(start - 3 * hour), new Date(start - hour)];
  first.graph.onRelayout();
  assert.deepEqual(first.graph.layout.xaxis.range.map(timeMs), [start, start + 2 * hour]);
  first.graph.layout.xaxis.range = [new Date(start + 25 * hour), new Date(start + 27 * hour)];
  first.graph.onRelayout();
  assert.deepEqual(first.graph.layout.xaxis.range.map(timeMs), [start + 22 * hour, start + 24 * hour]);
  first.graph.pointerdown({ button: 0, pointerId: 1, clientX: 100, clientY: 100, preventDefault() {} });
  first.graph.pointermove({ pointerId: 1, clientX: 10100, preventDefault() {} });
  assert.deepEqual(first.graph.layout.xaxis.range.map(timeMs), [start, start + 2 * hour]);
  first.graph.pointermove({ pointerId: 1, clientX: -4900, preventDefault() {} });
  assert.deepEqual(first.graph.layout.xaxis.range.map(timeMs), [start + 22 * hour, start + 24 * hour]);
  first.graph.pointerup({ pointerId: 1 });
  assert.equal(first.graph.captured, false);
  delete global.document;
  delete global.window;
  delete global.Plotly;
});
