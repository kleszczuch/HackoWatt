const HOUR_MS = 60 * 60 * 1000;

function timeMs(value) {
  if (value instanceof Date) return value.getTime();
  if (typeof value === 'number') return value;
  if (typeof value !== 'string') return NaN;
  const iso = value.replace(' ', 'T');
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(iso);
  return Date.parse(hasZone ? iso : `${iso}Z`);
}

function clampTimeRange(range, bounds) {
  const [start, end] = range;
  const [min, max] = bounds;
  if (![start, end, min, max].every(Number.isFinite) || max <= min) return null;

  const fullSpan = max - min;
  const span = Math.min(Math.max(end - start, Math.min(HOUR_MS, fullSpan)), fullSpan);
  const center = (start + end) / 2;
  const left = Math.max(min, Math.min(center - span / 2, max - span));
  return [left, left + span];
}

function panTimeRange(range, bounds, deltaPixels, plotWidth) {
  if (!Number.isFinite(plotWidth) || plotWidth <= 0) return null;
  const span = range[1] - range[0];
  const shift = -deltaPixels * span / plotWidth;
  return clampTimeRange([range[0] + shift, range[1] + shift], bounds);
}

function chartRange(axis) {
  if (!axis || !Array.isArray(axis.range)) return null;
  return axis.range.map(timeMs);
}

function chartBounds(axis) {
  if (!axis) return null;
  return [timeMs(axis.minallowed), timeMs(axis.maxallowed)];
}

if (typeof module !== 'undefined') module.exports = { clampTimeRange, panTimeRange, timeMs };

if (typeof document !== 'undefined') document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.interactive-chart').forEach((container) => {
    const graph = document.getElementById(container.dataset.chartId);
    const checkboxes = Array.from(container.querySelectorAll('[data-trace-index]'));
    const zoomIn = container.querySelector('[data-chart-zoom="in"]');
    const zoomOut = container.querySelector('[data-chart-zoom="out"]');
    if (!graph || !window.Plotly) return;

    function updateZoomButtons() {
      if (!zoomIn || !zoomOut) return;
      const bounds = chartBounds(graph.layout.xaxis);
      const range = chartRange(graph.layout.xaxis);
      const clamped = range && clampTimeRange(range, bounds);
      zoomIn.disabled = !clamped || clamped[1] - clamped[0] <= Math.min(HOUR_MS, bounds[1] - bounds[0]) + 1;
      zoomOut.disabled = !clamped || clamped[1] - clamped[0] >= bounds[1] - bounds[0] - 1;
    }

    function setRange(range) {
      return Plotly.relayout(graph, {
        'xaxis.range': range.map((value) => new Date(value).toISOString().slice(0, -1)),
      });
    }

    let drag = null;
    graph.addEventListener('pointerdown', (event) => {
      if (event.button !== 0 || event.isPrimary === false) return;
      const size = graph._fullLayout && graph._fullLayout._size;
      const bounds = chartBounds(graph.layout.xaxis);
      const range = chartRange(graph.layout.xaxis);
      const current = range && clampTimeRange(range, bounds);
      if (!size || !current || current[1] - current[0] >= bounds[1] - bounds[0] - 1) return;
      const rect = graph.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      if (x < size.l || x > size.l + size.w || y < size.t || y > size.t + size.h) return;
      drag = { pointerId: event.pointerId, startX: event.clientX, range: current, bounds, width: size.w };
      graph.setPointerCapture(event.pointerId);
      event.preventDefault();
    });

    graph.addEventListener('pointermove', (event) => {
      if (!drag || event.pointerId !== drag.pointerId) return;
      const next = panTimeRange(drag.range, drag.bounds, event.clientX - drag.startX, drag.width);
      const current = chartRange(graph.layout.xaxis);
      if (next && current && (Math.abs(next[0] - current[0]) > 1 || Math.abs(next[1] - current[1]) > 1)) {
        setRange(next);
      }
      event.preventDefault();
    });

    function stopDrag(event) {
      if (!drag || event.pointerId !== drag.pointerId) return;
      drag = null;
      if (graph.hasPointerCapture(event.pointerId)) graph.releasePointerCapture(event.pointerId);
    }
    graph.addEventListener('pointerup', stopDrag);
    graph.addEventListener('pointercancel', stopDrag);

    if (typeof graph.on === 'function') graph.on('plotly_relayout', () => {
      const bounds = chartBounds(graph.layout.xaxis);
      const range = chartRange(graph.layout.xaxis);
      const clamped = range && clampTimeRange(range, bounds);
      if (clamped && (Math.abs(clamped[0] - range[0]) > 1 || Math.abs(clamped[1] - range[1]) > 1)) {
        setRange(clamped);
      } else {
        updateZoomButtons();
      }
    });
    updateZoomButtons();

    container.addEventListener('change', (event) => {
      const checkbox = event.target.closest('[data-trace-index]');
      if (!checkbox) return;
      Plotly.restyle(graph, { visible: checkbox.checked }, [Number(checkbox.dataset.traceIndex)]);
    });

    container.addEventListener('click', (event) => {
      const zoomButton = event.target.closest('[data-chart-zoom]');
      if (zoomButton) {
        const bounds = chartBounds(graph.layout.xaxis);
        const range = chartRange(graph.layout.xaxis);
        const current = range && clampTimeRange(range, bounds);
        if (!current) return;
        const center = (current[0] + current[1]) / 2;
        const span = (current[1] - current[0]) * (zoomButton.dataset.chartZoom === 'in' ? 0.5 : 2);
        const next = clampTimeRange([center - span / 2, center + span / 2], bounds);
        if (next) setRange(next);
        return;
      }

      const button = event.target.closest('[data-chart-action]');
      if (!button) return;
      const visible = button.dataset.chartAction === 'select-all';
      checkboxes.forEach((checkbox) => { checkbox.checked = visible; });
      Plotly.restyle(graph, { visible: checkboxes.map(() => visible) },
        checkboxes.map((checkbox) => Number(checkbox.dataset.traceIndex)));
    });
  });
});
