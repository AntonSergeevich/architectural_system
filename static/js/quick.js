/* Мини-расчёт на первом экране.

   Считает по тем же числам, что и конструктор: цена за метр и фиксы
   приходят из каталога, правило для маленьких помещений — из настроек.
   Разойтись с полным расчётом они не могут, потому что источник один.

   Без JavaScript блок остаётся статичным: показана цена для 84 м²
   и ссылка на конструктор. Ничего не ломается, просто не пересчитывается.
*/

(function () {
  'use strict';

  var root = document.querySelector('[data-quick]');
  if (!root) return;

  var input = root.querySelector('#quick-area');
  var out = root.querySelector('[data-quick-price]');
  var link = root.querySelector('[data-quick-link]');
  if (!input || !out || !link) return;

  var perSqm = Number(root.dataset.perSqm || 0);
  var fixed = Number(root.dataset.fixed || 0);
  var smallOn = root.dataset.smallEnabled === '1';
  var smallLimit = Number(root.dataset.smallThreshold || 0);
  var smallPrice = Number(root.dataset.smallPrice || 0);

  var base = link.getAttribute('href');
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var shown = null;

  function money(value) {
    return String(Math.round(value)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ') + ' ₽';
  }

  function priceFor(area) {
    if (smallOn && area > 0 && area <= smallLimit) return smallPrice;
    return perSqm * area + fixed;
  }

  function render(to) {
    if (reduce || shown === null) {
      shown = to;
      out.textContent = '≈ ' + money(to);
      return;
    }
    var from = shown;
    shown = to;
    var start = performance.now();
    (function frame(now) {
      var t = Math.min((now - start) / 260, 1);
      var eased = 1 - Math.pow(1 - t, 3);
      out.textContent = '≈ ' + money(from + (to - from) * eased);
      if (t < 1) requestAnimationFrame(frame);
    })(start);
  }

  function update() {
    var area = Number(String(input.value).replace(',', '.'));
    if (!area || area < 1) {
      out.textContent = '—';
      shown = null;
      return;
    }
    if (area > 10000) area = 10000;

    render(priceFor(area));
    // Площадь уезжает в конструктор ссылкой: вводить её второй раз
    // человек не должен.
    link.setAttribute('href', base + '?area=' + encodeURIComponent(area));
  }

  input.addEventListener('input', update);
  update();
})();
