/* Karty rekomendacji AI na stronie symulatora PV: po zmianie mocy PV lub
   parametrów magazynu pobiera świeży plan z /rekomendacje/ i podmienia karty.
   Przy błędzie sieci lub walidacji stare karty zostają bez zmian. */
(function () {
  var section = document.getElementById('recommendations-section');
  var container = document.getElementById('recommendations-cards');
  var labelsEl = document.getElementById('reco-labels');
  if (!section || !container || !labelsEl) return;

  var labels = JSON.parse(labelsEl.textContent);
  var url = section.dataset.recoUrl;
  var ACCENTS = ['border-t-grass', 'border-t-sage', 'border-t-chartreuse'];

  function esc(value) {
    return String(value).replace(/[&<>"']/g, function (ch) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[ch];
    });
  }

  function sourceName(source) {
    return source === 'local_ai' ? labels.source_local_ai : labels.source_fallback;
  }

  function cardHtml(item, index) {
    var name = (labels.devices && labels.devices[item.device]) || item.device;
    var head =
      '<h3 class="col-span-2 m-0 mb-[3px] text-[15px] text-charcoal">' + esc(name) + '</h3>';
    var body;
    if (item.status === 'no_cycle') {
      body =
        '<p class="col-span-2 m-0 text-[13px] leading-[1.5] text-slate">' +
        esc(labels.no_cycle) + '</p>';
    } else if (item.status === 'keep') {
      body =
        '<p class="col-span-2 m-0 text-[13px] leading-[1.5] text-slate">' +
        esc(labels.keep_at) + ' <strong>' + esc(item.from) + '</strong>. ' +
        esc(item.reason) + '</p>';
    } else {
      body =
        '<div><span class="block text-[11px] font-bold text-slate">' + esc(labels.move_start) +
        '</span><strong class="mt-1 block text-xl tracking-[-0.04em] text-charcoal">' +
        esc(item.from) + ' → ' + esc(item.to) + '</strong></div>' +
        '<div><span class="block text-[11px] font-bold text-slate">' + esc(labels.per_cycle) +
        ' · ' + esc(labels.tomorrow) +
        '</span><strong class="mt-1 block text-xl tracking-[-0.04em] text-charcoal">' +
        esc(item.saving_per_cycle) +
        ' <small class="text-[11px] font-[650] tracking-normal">' + esc(labels.currency_symbol) +
        '</small></strong></div>' +
        '<div class="col-span-2"><span class="block text-[11px] font-bold text-slate">' +
        esc(labels.annual) +
        '</span><strong class="mt-1 block text-xl tracking-[-0.04em] text-charcoal">' +
        esc(item.estimated_annual_saving) +
        ' <small class="text-[11px] font-[650] tracking-normal">' + esc(labels.currency_symbol) +
        '/' + esc(labels.year_suffix) + '</small></strong></div>' +
        '<p class="col-span-2 m-0 border-t border-line pt-2 text-[11px] leading-[1.4] text-slate">' +
        esc(item.reason) + '</p>';
    }
    body += '<p class="col-span-2 m-0 text-[11px] leading-[1.4] text-slate">' +
      esc(labels.observed_days) + ': ' + esc(item.history_days) + '/35 · ' +
      esc(labels.matching_days) + ': ' + esc(item.matching_weekday_days) + '</p>';
    return (
      '<article class="grid min-w-0 grid-cols-2 gap-[9px] rounded-[13px] border border-line ' +
      'border-t-4 bg-white/[0.88] p-4 ' + ACCENTS[index % ACCENTS.length] + '">' +
      head + body + '</article>'
    );
  }

  function observedHtml(plan) {
    var events = plan && plan.observed_events || [];
    var html = '<div class="px-[30px] pt-5 max-sm:px-[17px]" id="observed-events">' +
      '<h3 class="m-0 text-[16px] text-charcoal">' + esc(labels.observed_heading) + '</h3>' +
      '<p class="m-0 mt-1 text-[11px] leading-[1.4] text-slate">' +
      esc(labels.observed_caption) + '</p>';
    if (!events.length) {
      return html + '<p class="m-0 mt-3 text-[12px] text-slate">' +
        esc(labels.observed_empty) + '</p></div>';
    }
    html += '<div class="mt-3 grid grid-cols-3 gap-3 max-lg:grid-cols-1">';
    events.forEach(function (event) {
      html += '<article class="rounded-[13px] border border-line bg-white/[0.88] p-4">' +
        '<h4 class="m-0 text-[14px] text-charcoal">' + esc(event.label || event.event) + '</h4>' +
        '<p class="m-0 mt-2 text-[12px] text-slate">' + esc(labels.observed_days) +
        ': <strong>' + esc(event.days_in_history) + '/35</strong> · ' +
        esc(labels.matching_days) + ': <strong>' + esc(event.days_on_matching_weekday) +
        '/' + esc(event.matching_weekdays) + '</strong></p>' +
        '<p class="m-0 mt-2 text-[11px] text-slate">' +
        esc(event.status === 'repeated' ? labels.observed_repeated : labels.observed_only) +
        '</p></article>';
    });
    return html + '</div></div>';
  }

  function activityCardHtml(event) {
    var advice = event.advice;
    var body = advice && advice.status === 'keep' ?
      '<p class="col-span-2 m-0 text-[13px] leading-[1.5] text-slate">' +
      esc(labels.keep_at) + ' <strong>' + esc(advice.from) + '</strong>. ' +
      esc(advice.reason) + '</p>' : advice ?
      '<div><span class="block text-[11px] font-bold text-slate">' + esc(labels.move_start) +
      '</span><strong class="mt-1 block text-xl tracking-[-0.04em] text-charcoal">' +
      esc(advice.from) + ' → ' + esc(advice.to) + '</strong></div>' +
      '<div><span class="block text-[11px] font-bold text-slate">' + esc(labels.per_cycle) +
      ' · ' + esc(labels.tomorrow) + '</span><strong class="mt-1 block text-xl text-charcoal">' +
      esc(advice.saving_per_cycle) + ' ' + esc(labels.currency_symbol) + '</strong></div>' +
      '<div class="col-span-2"><span class="block text-[11px] font-bold text-slate">' +
      esc(labels.annual) + '</span><strong class="mt-1 block text-xl text-charcoal">' +
      esc(advice.estimated_annual_saving) + ' ' + esc(labels.currency_symbol) +
      '/' + esc(labels.year_suffix) + '</strong></div>' +
      '<p class="col-span-2 m-0 border-t border-line pt-2 text-[11px] text-slate">' +
      esc(advice.reason) + '</p>' :
      '<p class="col-span-2 m-0 text-[12px] leading-[1.5] text-slate">' +
      esc(event.event === 'ładowanie EV' ? labels.ev_crosses_midnight : labels.activity_no_advice) +
      '</p>';
    return '<article class="grid min-w-0 grid-cols-2 gap-[9px] rounded-[13px] border ' +
      'border-line border-t-4 border-t-sage bg-white/[0.88] p-4">' +
      '<h3 class="col-span-2 m-0 mb-[3px] text-[15px] text-charcoal">' +
      esc(event.label || event.event) + '</h3>' + body +
      '<p class="col-span-2 m-0 text-[11px] text-slate">' + esc(labels.observed_days) +
      ': ' + esc(event.days_in_history) + '/35 · ' + esc(labels.matching_days) + ': ' +
      esc(event.days_on_matching_weekday) + '/' + esc(event.matching_weekdays) + '</p></article>';
  }

  function render(plan) {
    var notice = plan && plan.tariff_notice ?
      '<p class="m-0 mx-[30px] mt-3 rounded-[13px] border border-line bg-white/[0.88] ' +
      'p-4 text-[12px] leading-[1.5] text-charcoal max-sm:mx-[17px]">' +
      esc(plan.tariff_notice) + '</p>' : '';
    if (!plan || plan.status === 'no_data') {
      container.innerHTML =
        notice + '<div class="px-[30px] pt-3 max-sm:px-[17px]"><p class="m-0 rounded-[13px] border ' +
        'border-line bg-white/[0.88] p-4 text-[13px] leading-[1.5] text-charcoal">' +
        esc(plan && plan.no_data_message || labels.no_data) + '</p></div>' +
        observedHtml(plan);
      return;
    }
    var html = notice +
      '<div class="grid grid-cols-3 gap-3 px-[30px] pt-3 max-lg:grid-cols-1 max-sm:px-[17px]">' +
      (plan.recommendations || []).map(cardHtml).join('') +
      (plan.observed_events || []).map(activityCardHtml).join('') + '</div>';
    if (plan.total_daily_saving) {
      html +=
        '<p class="m-0 px-[30px] pt-3 text-[13px] text-charcoal max-sm:px-[17px]"><strong>' +
        esc(labels.total_tomorrow) + ':</strong> ' + esc(plan.total_daily_saving) + ' ' +
        esc(labels.currency_symbol) + ' · <span class="text-slate">' + esc(labels.source_label) +
        ': ' + esc(sourceName(plan.source)) + '</span></p>';
    }
    container.innerHTML = html;
  }

  function fieldValue(id) {
    var el = document.getElementById(id);
    return el ? el.value : '';
  }

  function refresh() {
    var params = new URLSearchParams({
      kwp: fieldValue('id_kwp'),
      magazyn_kwh: fieldValue('id_magazyn_kwh'),
      magazyn_moc_kw: fieldValue('id_magazyn_moc_kw'),
    });
    fetch(url + '?' + params.toString(), {headers: {Accept: 'application/json'}})
      .then(function (response) {
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return response.json();
      })
      .then(render)
      .catch(function () {
        /* Błąd sieci: stare karty zostają bez zmian. */
      });
  }

  ['id_kwp', 'id_magazyn_kwh', 'id_magazyn_moc_kw'].forEach(function (id) {
    var el = document.getElementById(id);
    if (el) el.addEventListener('change', refresh);
  });
})();
