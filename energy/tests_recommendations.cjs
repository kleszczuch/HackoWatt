const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const listeners = {};
const fields = {};
for (const [id, value] of Object.entries({
  id_kwp: '5',
  id_magazyn_kwh: '0',
  id_magazyn_moc_kw: '5',
})) {
  fields[id] = {
    value,
    addEventListener(event, listener) {
      listeners[id + ':' + event] = listener;
    },
  };
}

const section = {dataset: {recoUrl: '/rekomendacje/'}};
const container = {innerHTML: ''};
const labels = {
  devices: {dishwasher: 'Zmywarka', washer: 'Pralka'},
  currency_symbol: '€',
  no_cycle: 'Brak przewidywanego cyklu',
  total_tomorrow: 'Razem na jutro',
  source_label: 'źródło',
  source_fallback: 'wyliczenie zastępcze',
  observed_days: 'Dni w historii',
  matching_days: 'Pasujące dni tygodnia',
  observed_heading: 'Inne aktywności',
  observed_caption: 'Obserwacje z historii',
  observed_repeated: 'Powtarzało się',
  observed_only: 'Zaobserwowano',
  observed_empty: 'Brak innych aktywności',
  move_start: 'Przesuń start', per_cycle: 'Oszczędność na cyklu',
  tomorrow: 'jutro', annual: 'Szacunek roczny', year_suffix: 'rok',
  keep_at: 'Pozostaw o',
};
const elements = {
  'recommendations-section': section,
  'recommendations-cards': container,
  'reco-labels': {textContent: JSON.stringify(labels)},
  ...fields,
};
const requests = [];
const context = {
  document: {getElementById: (id) => elements[id]},
  URLSearchParams,
  fetch(url) {
    requests.push(url);
    const plan = requests.length === 1 ? {
      status: 'ready',
      source: 'calculated_fallback',
      tariff_notice: 'No PSE price for 24 of 24 hours',
      recommendations: [{
        device: 'dishwasher', status: 'no_cycle', history_days: 3,
        matching_weekday_days: 1,
      }, {
        device: 'washer', status: 'keep', from: '19:00', to: '19:00',
        reason: 'Brak tańszej godziny', history_days: 3, matching_weekday_days: 2,
      }],
      total_daily_saving: '0.00',
      observed_events: [{
        event: 'pompa basenu', label: 'Pompa basenu', days_in_history: 2,
        days_on_matching_weekday: 2, matching_weekdays: 5, status: 'repeated',
        advice: {from: '09:00', to: '13:00', saving_per_cycle: '0.40',
          estimated_annual_saving: '4.17', reason: 'Tańsza energia'},
      }],
    } : {
      status: 'no_data',
      missing_data: 'forecast',
      no_data_message: 'Tomorrow forecast is unavailable',
      recommendations: [],
      observed_events: [{
        event: 'pompa basenu', label: 'Pool pump', days_in_history: 35,
        days_on_matching_weekday: 5, matching_weekdays: 5, status: 'repeated',
      }],
    };
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve(plan),
    });
  },
};

vm.runInNewContext(fs.readFileSync('energy/static/energy/recommendations.js', 'utf8'), context);

async function check() {
  assert.equal(Object.keys(listeners).length, 3);
  fields.id_kwp.value = '8';
  fields.id_magazyn_kwh.value = '10';
  fields.id_magazyn_moc_kw.value = '3';
  listeners['id_kwp:change']();
  await new Promise(setImmediate);

  assert.equal(requests.length, 1);
  const url = new URL(requests[0], 'http://localhost');
  assert.equal(url.pathname, '/rekomendacje/');
  assert.equal(url.searchParams.get('kwp'), '8');
  assert.equal(url.searchParams.get('magazyn_kwh'), '10');
  assert.equal(url.searchParams.get('magazyn_moc_kw'), '3');
  assert.match(container.innerHTML, /Brak przewidywanego cyklu/);
  assert.match(container.innerHTML, /Pozostaw o <strong>19:00<\/strong>/);
  assert.doesNotMatch(container.innerHTML, /19:00 → 19:00/);
  assert.match(container.innerHTML, /Razem na jutro/);
  assert.match(container.innerHTML, /Pompa basenu/);
  assert.match(container.innerHTML, /09:00 → 13:00/);
  assert.match(container.innerHTML, /0.40/);
  assert.match(container.innerHTML, /No PSE price for 24 of 24 hours/);
  assert.match(container.innerHTML, /Dni w historii: 3/);

  listeners['id_magazyn_kwh:change']();
  await new Promise(setImmediate);
  assert.equal(requests.length, 2);
  assert.match(container.innerHTML, /Tomorrow forecast is unavailable/);
  assert.match(container.innerHTML, /Pool pump/);
  assert.doesNotMatch(container.innerHTML, /Pompa basenu/);
  assert.doesNotMatch(container.innerHTML, /Razem na jutro/);
}

check().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
