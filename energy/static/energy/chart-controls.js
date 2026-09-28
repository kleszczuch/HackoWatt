document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.interactive-chart').forEach((container) => {
    const graph = document.getElementById(container.dataset.chartId);
    const checkboxes = Array.from(container.querySelectorAll('[data-trace-index]'));
    if (!graph || !window.Plotly) return;

    container.addEventListener('change', (event) => {
      const checkbox = event.target.closest('[data-trace-index]');
      if (!checkbox) return;
      Plotly.restyle(graph, { visible: checkbox.checked }, [Number(checkbox.dataset.traceIndex)]);
    });

    container.addEventListener('click', (event) => {
      const button = event.target.closest('[data-chart-action]');
      if (!button) return;
      const visible = button.dataset.chartAction === 'select-all';
      checkboxes.forEach((checkbox) => { checkbox.checked = visible; });
      Plotly.restyle(graph, { visible: checkboxes.map(() => visible) },
        checkboxes.map((checkbox) => Number(checkbox.dataset.traceIndex)));
    });
  });
});
