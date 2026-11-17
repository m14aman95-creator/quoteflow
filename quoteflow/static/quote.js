// Quote editor: add/remove items and live totals. All money maths is done by the server (money.py).
(function () {
  var form = document.getElementById('qform');
  if (!form) return;
  var itemsEl = document.getElementById('items');
  var countEl = document.getElementById('item_count');
  var tpl = document.getElementById('itemtpl').innerHTML;
  var timer = null;

  function cards() { return [].slice.call(itemsEl.querySelectorAll('.itemcard')); }
  function val(card, name) { var el = card.querySelector('[name="' + name + '_' + card.dataset.i + '"]'); return el ? el.value : ''; }

  function refresh() {
    clearTimeout(timer);
    timer = setTimeout(function () {
      var live = cards().filter(function (c) { return c.style.display !== 'none'; });
      var payload = {
        items: live.map(function (c) { var o = c.querySelector('[name="optional_' + c.dataset.i + '"]'); return { qty: val(c, 'qty'), price: val(c, 'price'), tax: val(c, 'tax'), optional: !!(o && o.checked) }; }),
        discount_type: form.querySelector('[name=discount_type]').value,
        discount_value: form.querySelector('[name=discount_value]').value
      };
      fetch(form.dataset.totals, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': form.dataset.csrf },
        body: JSON.stringify(payload)
      }).then(function (r) { return r.json(); }).then(function (j) {
        var warn = document.getElementById('t_warn');
        if (j.error) { warn.textContent = j.error; return; }
        document.getElementById('t_sub').textContent = j.subtotal;
        document.getElementById('t_disc').textContent = (j.discount === '0.000' ? '' : '-') + j.discount;
        document.getElementById('t_vat').textContent = j.vat;
        document.getElementById('t_total').textContent = j.total;
        warn.innerHTML = '';
        j.warnings.forEach(function (w) { var d = document.createElement('div'); d.textContent = w; warn.appendChild(d); });
        live.forEach(function (c, i) { var s = c.querySelector('.linetotal'); if (s) s.textContent = j.lines[i]; });
      }).catch(function () {});
    }, 250);
  }

  function wire(card) {
    card.querySelectorAll('.calc').forEach(function (el) { el.addEventListener('input', refresh); el.addEventListener('change', refresh); });
    card.querySelector('.delbtn').addEventListener('click', function () {
      if (!confirm('Remove this item?')) return;
      card.querySelector('.delflag').value = '1';
      card.style.display = 'none';
      refresh();
    });
  }

  function addItem(preset) {
    var i = parseInt(countEl.value, 10);
    var holder = document.createElement('div');
    holder.innerHTML = tpl.replace(/__i__/g, i);
    var card = holder.firstElementChild;
    if (preset) {
      var set = function (n, v) { var el = card.querySelector('[name="' + n + '_' + i + '"]'); if (el) el.value = v; };
      set('service_id', preset.id); set('title_en', preset.en); set('title_ar', preset.ar);
      set('desc_en', preset.den); set('desc_ar', preset.dar); set('unit', preset.unit); set('price', preset.price); set('tax', preset.tax);
    }
    itemsEl.appendChild(card);
    countEl.value = i + 1;
    wire(card);
    refresh();
    card.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  cards().forEach(wire);
  form.querySelectorAll('[name=discount_type],[name=discount_value]').forEach(function (el) {
    el.addEventListener('input', refresh); el.addEventListener('change', refresh);
  });
  document.getElementById('addblank').addEventListener('click', function () { addItem(null); });
  document.getElementById('addsvc').addEventListener('change', function () {
    var o = this.options[this.selectedIndex];
    if (!o.value) return;
    addItem({ id: o.value, en: o.dataset.en, ar: o.dataset.ar, den: o.dataset.den, dar: o.dataset.dar, unit: o.dataset.unit, price: o.dataset.price, tax: o.dataset.tax });
    this.value = '';
  });
  refresh();
})();
