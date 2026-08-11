/* Конструктор «дом из кубиков».

   Перетаскивание построено на Pointer Events: они одинаково приходят
   от мыши, пальца и стилуса. HTML5 Drag and Drop не используется вообще —
   на мобильных он не работает, и держать два разных механизма означает
   получить два разных набора багов.

   Ключевое для телефона:
   1. Блок берётся УДЕРЖАНИЕМ (180 мс при смещении до 8 px). Сдвинул
      раньше — страница скроллится как обычно. Без этого перетаскивание
      всегда воюет со скроллом и всегда проигрывает.
   2. Блок поднимается на 56 px над пальцем — иначе тащишь то, чего не видишь.
   3. Слоты магнитные: попадать пикселем в пиксель пальцем невозможно.
   4. Автоскролл у краёв, обработка pointercancel (входящий звонок не должен
      оставить блок висеть в воздухе).

   И обязательное дублирование: тап кладёт блок без перетаскивания,
   работает клавиатура, а при выключенном JS остаётся обычная форма.
*/

(function () {
  'use strict';

  var root = document.querySelector('[data-constructor]');
  if (!root) return;

  var CATALOG = JSON.parse(document.getElementById('catalog-data').textContent);
  var HOLD_MS = 180;      // столько нужно удержать, чтобы взять блок
  var MOVE_TOLERANCE = 8; // и не сдвинуться больше, чем на столько
  var LIFT = 56;          // на сколько поднимаем блок над пальцем
  var SNAP = 64;          // радиус притяжения слота
  var EDGE = 80;          // зона автоскролла у края экрана

  var house = root.querySelector('[data-house]');
  var shelf = root.querySelector('[data-shelf]');
  var live = root.querySelector('[data-live]');
  var form = root.querySelector('[data-calc-form]');

  var byId = {};
  CATALOG.modules.forEach(function (m) { byId[m.id] = m; });

  var selected = new Set(
    Array.prototype.map.call(
      root.querySelectorAll('input[name="modules"]:checked'),
      function (i) { return Number(i.value); }
    )
  );

  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // --- Состояние ----------------------------------------------------------

  function moduleOf(el) { return byId[Number(el.dataset.module)]; }

  function select(id, on) {
    var mod = byId[id];
    if (!mod || mod.required) return;

    if (on && mod.group) {
      // Слот принимает ровно один блок: окна — эскизы ИЛИ нейро ИЛИ 3D.
      CATALOG.modules.forEach(function (other) {
        if (other.group === mod.group && other.id !== id) selected.delete(other.id);
      });
    }
    if (on) selected.add(id); else selected.delete(id);

    syncInputs();
    paintShelf();
    paintHouse();
    announce(mod, on);
    recalc();
  }

  function syncInputs() {
    root.querySelectorAll('input[name="modules"]').forEach(function (input) {
      var id = Number(input.value);
      input.checked = selected.has(id) || (byId[id] && byId[id].required);
    });
  }

  function announce(mod, on) {
    if (!live) return;
    live.textContent = mod.title + (on ? ' добавлено' : ' убрано');
  }

  // --- Отрисовка ----------------------------------------------------------

  function paintShelf() {
    shelf.querySelectorAll('[data-module]').forEach(function (el) {
      var mod = moduleOf(el);
      var on = selected.has(mod.id) || mod.required;
      el.classList.toggle('is-selected', on);
      el.setAttribute('aria-pressed', String(on));
    });
  }

  function paintHouse() {
    var filled = {};
    selected.forEach(function (id) {
      var m = byId[id];
      if (m && m.housePart) filled[m.housePart] = true;
    });
    CATALOG.modules.forEach(function (m) {
      if (m.required && m.housePart) filled[m.housePart] = true;
    });

    house.querySelectorAll('.slot').forEach(function (slot) {
      var on = !!filled[slot.dataset.part];
      slot.classList.toggle('is-filled', on);
      slot.classList.toggle('is-empty', !on);
    });

    // Свет в окнах горит только тогда, когда есть и окна, и комплектация:
    // дом, в который въехали.
    var windows = house.querySelector('.slot[data-part="windows"]');
    if (windows) windows.classList.toggle('has-light', !!filled.windows && !!filled.light);
  }

  // --- Пересчёт -----------------------------------------------------------

  var pending = null;

  function recalc() {
    if (!window.fetch || !form) return;
    clearTimeout(pending);
    // Небольшая задержка: при быстрой раскладке блоков это экономит
    // несколько запросов подряд.
    pending = setTimeout(function () {
      var data = new FormData(form);
      fetch(form.dataset.calcUrl, {
        method: 'POST',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        body: data
      })
        .then(function (r) { return r.json(); })
        .then(function (payload) { if (payload.ok) paintTotals(payload.calc); })
        .catch(function () { /* сеть отвалилась — числа просто останутся прежними */ });
    }, 120);
  }

  function money(value) {
    return String(value).replace(/\B(?=(\d{3})+(?!\d))/g, ' ') + ' ₽';
  }

  function countTo(el, to) {
    var from = Number(el.dataset.value || 0);
    el.dataset.value = to;
    if (reduceMotion || from === to) { el.textContent = money(to); return; }

    var start = performance.now();
    var duration = 320;
    (function frame(now) {
      var t = Math.min((now - start) / duration, 1);
      var eased = 1 - Math.pow(1 - t, 3);
      el.textContent = money(Math.round(from + (to - from) * eased));
      if (t < 1) requestAnimationFrame(frame);
    })(start);
  }

  function paintTotals(calc) {
    var map = {
      design: calc.design_total,
      realization: calc.realization_total,
      extra: calc.extra_total,
      grand: calc.grand_total
    };
    Object.keys(map).forEach(function (key) {
      var el = root.querySelector('[data-total="' + key + '"]');
      if (el) countTo(el, map[key]);
    });

    var custom = root.querySelector('[data-custom-note]');
    if (custom) custom.hidden = !calc.has_custom;

    var fixed = root.querySelector('[data-fixed-note]');
    if (fixed) fixed.hidden = !calc.fixed_design;

    var months = root.querySelector('[data-months]');
    if (months) months.textContent = calc.months;

    var box = root.querySelector('[data-warnings]');
    if (!box) return;
    box.innerHTML = '';
    calc.missing.forEach(function (item) {
      if (!item.warning) return;
      var div = document.createElement('div');
      div.className = 'warning';
      var strong = document.createElement('strong');
      strong.textContent = 'Без блока «' + item.title + '»';
      var p = document.createElement('span');
      p.textContent = item.warning;
      div.appendChild(strong);
      div.appendChild(p);
      box.appendChild(div);
    });
  }

  // --- Тап и клавиатура: путь без перетаскивания ---------------------------
  // Не запасной вариант, а требование. Тот, у кого не получилось потащить,
  // не должен уйти с сайта.

  shelf.addEventListener('click', function (e) {
    if (e.target.closest('[data-expand]')) return;
    var el = e.target.closest('[data-module]');
    if (!el || dragMoved) return;
    var mod = moduleOf(el);
    if (mod.required) return;
    select(mod.id, !selected.has(mod.id));
  });

  shelf.addEventListener('keydown', function (e) {
    var el = e.target.closest('[data-module]');
    if (!el) return;
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      var mod = moduleOf(el);
      if (!mod.required) select(mod.id, !selected.has(mod.id));
    }
  });

  root.querySelectorAll('[data-expand]').forEach(function (btn) {
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      var body = document.getElementById(btn.dataset.expand);
      if (!body) return;
      body.hidden = !body.hidden;
      btn.textContent = body.hidden ? 'Подробнее' : 'Свернуть';
    });
  });

  // --- Пресеты ------------------------------------------------------------

  root.querySelectorAll('[data-preset]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var preset = CATALOG.presets.filter(function (p) {
        return p.id === Number(btn.dataset.preset);
      })[0];
      if (!preset) return;
      selected = new Set(preset.modules.filter(function (id) { return byId[id]; }));
      root.querySelectorAll('[data-preset]').forEach(function (b) {
        b.classList.toggle('is-active', b === btn);
      });
      syncInputs();
      paintShelf();
      paintHouse();
      recalc();
    });
  });

  // --- Перетаскивание -----------------------------------------------------

  var drag = null;
  var holdTimer = null;
  var dragMoved = false;

  function slotRects() {
    // Позиции слотов кэшируются в момент захвата, а не считаются на каждом
    // движении: getBoundingClientRect в pointermove — это пересчёт раскладки
    // на каждый кадр.
    return Array.prototype.map.call(house.querySelectorAll('.slot'), function (slot) {
      var r = slot.getBoundingClientRect();
      return { el: slot, part: slot.dataset.part, cx: r.left + r.width / 2, cy: r.top + r.height / 2 };
    });
  }

  function onPointerDown(e) {
    if (e.button !== undefined && e.button !== 0) return;
    var el = e.target.closest('[data-module]');
    if (!el || e.target.closest('[data-expand]')) return;
    var mod = moduleOf(el);
    if (mod.required) return;

    dragMoved = false;
    var startX = e.clientX;
    var startY = e.clientY;

    holdTimer = setTimeout(function () {
      startDrag(el, mod, startX, startY, e.pointerId);
    }, HOLD_MS);

    function cancelHold(ev) {
      if (ev && ev.type === 'pointermove') {
        var moved = Math.hypot(ev.clientX - startX, ev.clientY - startY);
        if (moved < MOVE_TOLERANCE) return;
      }
      clearTimeout(holdTimer);
      window.removeEventListener('pointermove', cancelHold);
      window.removeEventListener('pointerup', cancelHold);
      window.removeEventListener('pointercancel', cancelHold);
    }
    window.addEventListener('pointermove', cancelHold, { passive: true });
    window.addEventListener('pointerup', cancelHold);
    window.addEventListener('pointercancel', cancelHold);
  }

  function startDrag(el, mod, x, y, pointerId) {
    var rect = el.getBoundingClientRect();
    var clone = el.cloneNode(true);
    clone.classList.add('block--dragging');
    clone.style.setProperty('--drag-width', rect.width + 'px');
    document.body.appendChild(clone);
    el.classList.add('block--ghost');

    // Тактильное подтверждение захвата: палец закрывает обзор, и одного
    // визуального сигнала мало.
    if (navigator.vibrate) navigator.vibrate(10);

    drag = {
      el: el, clone: clone, mod: mod, pointerId: pointerId,
      offsetX: rect.width / 2, offsetY: rect.height / 2,
      slots: slotRects(), target: null, frame: null, x: x, y: y
    };

    try { el.setPointerCapture(pointerId); } catch (err) { /* мышь без capture — не беда */ }
    window.addEventListener('pointermove', onPointerMove, { passive: false });
    window.addEventListener('pointerup', onPointerUp);
    window.addEventListener('pointercancel', onPointerCancel);
    window.addEventListener('contextmenu', suppress);

    moveClone(x, y);
  }

  function suppress(e) { e.preventDefault(); }

  function moveClone(x, y) {
    if (!drag) return;
    drag.x = x; drag.y = y;
    if (drag.frame) return;
    drag.frame = requestAnimationFrame(function () {
      drag.frame = null;
      if (!drag) return;
      var tx = drag.x - drag.offsetX;
      var ty = drag.y - drag.offsetY - LIFT;
      drag.clone.style.transform = 'translate3d(' + tx + 'px,' + ty + 'px,0) scale(1.05)';
    });
  }

  function onPointerMove(e) {
    if (!drag) return;
    e.preventDefault();
    dragMoved = true;
    moveClone(e.clientX, e.clientY);
    highlight(e.clientX, e.clientY);
    autoscroll(e.clientY);
  }

  function nearestSlot(x, y) {
    var best = null;
    var bestDistance = Infinity;
    drag.slots.forEach(function (slot) {
      if (slot.part !== drag.mod.housePart) return;
      var d = Math.hypot(x - slot.cx, y - slot.cy);
      if (d < bestDistance) { bestDistance = d; best = slot; }
    });
    // Радиус притяжения плюс половина размера дома: попасть пальцем
    // в конкретный слот сложно, а промахнуться мимо дома целиком — нет.
    return bestDistance <= Math.max(SNAP, house.clientWidth / 3) ? best : null;
  }

  function highlight(x, y) {
    var slot = nearestSlot(x, y);
    if (drag.target && drag.target !== slot) drag.target.el.classList.remove('is-target');
    if (slot) slot.el.classList.add('is-target');
    drag.target = slot;
  }

  function autoscroll(y) {
    if (y < EDGE) window.scrollBy(0, -Math.ceil((EDGE - y) / 6));
    else if (y > window.innerHeight - EDGE) window.scrollBy(0, Math.ceil((y - (window.innerHeight - EDGE)) / 6));
  }

  function endDrag(place) {
    if (!drag) return;
    var mod = drag.mod;
    var target = drag.target;

    if (target) target.el.classList.remove('is-target');
    drag.clone.remove();
    drag.el.classList.remove('block--ghost');
    if (drag.frame) cancelAnimationFrame(drag.frame);
    try { drag.el.releasePointerCapture(drag.pointerId); } catch (err) { /* уже отпущен */ }

    window.removeEventListener('pointermove', onPointerMove);
    window.removeEventListener('pointerup', onPointerUp);
    window.removeEventListener('pointercancel', onPointerCancel);
    window.removeEventListener('contextmenu', suppress);
    drag = null;

    if (place && target) select(mod.id, true);
    // Промахнулся мимо слота — блок просто возвращается на склад.
    // Ничего не пропадает и не требует «отменить».
    setTimeout(function () { dragMoved = false; }, 0);
  }

  function onPointerUp() { endDrag(true); }
  function onPointerCancel() { endDrag(false); }

  shelf.addEventListener('pointerdown', onPointerDown);

  // Тап по заполненному слоту убирает блок: тащить обратно неудобно всем.
  house.addEventListener('click', function (e) {
    var slot = e.target.closest('.slot');
    if (!slot || !slot.classList.contains('is-filled')) return;
    var ids = [];
    selected.forEach(function (id) {
      if (byId[id] && byId[id].housePart === slot.dataset.part && !byId[id].required) ids.push(id);
    });
    ids.forEach(function (id) { select(id, false); });
  });

  // --- Сохранение расчёта --------------------------------------------------

  var saveBtn = root.querySelector('[data-save-quote]');
  if (saveBtn && window.fetch) {
    saveBtn.addEventListener('click', function () {
      saveBtn.disabled = true;
      fetch(saveBtn.dataset.url, { method: 'POST', body: new FormData(form) })
        .then(function (r) { return r.json(); })
        .then(function (payload) {
          if (payload.ok) window.location.href = payload.url;
          else saveBtn.disabled = false;
        })
        .catch(function () { saveBtn.disabled = false; });
    });
  }

  // Первая отрисовка: стартовое состояние — собранный дом «Под ключ».
  syncInputs();
  paintShelf();
  paintHouse();
  recalc();
})();
