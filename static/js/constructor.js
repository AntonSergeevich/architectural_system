/* Конструктор «дом из кубиков».

   Перетаскивание построено на Pointer Events: они одинаково приходят
   от мыши, пальца и стилуса. HTML5 Drag and Drop не используется вообще —
   на мобильных он не работает, и держать два разных механизма означает
   получить два разных набора багов.

   Мышь и палец берут блок по-разному, и это принципиально:
   1. Пальцем — УДЕРЖАНИЕМ (180 мс при смещении до 8 px). Сдвинул раньше —
      страница прокручивается как обычно. Без этого перетаскивание всегда
      воюет с прокруткой и всегда проигрывает.
   1a. Мышью — сразу, как только курсор сдвинулся на 4 px. Мышью
      прокручивают колесом, конфликта нет, а удержание там читается
      как «перетаскивание не работает».
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
  var MOUSE_THRESHOLD = 4; // мышь берёт блок сразу, как только сдвинулась
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

    clearPresetHighlight();
    syncInputs();
    paintShelf();
    paintHouse();
    if (on && mod.housePart) flash(mod.housePart);
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
      paintVariants(el);
      var mod = moduleOf(el);
      var on = selected.has(mod.id) || mod.required;
      el.classList.toggle('is-selected', on);
      el.setAttribute('aria-pressed', String(on));
    });
  }

  /* Блок-группа: потолок, окно, стены. Место в комнате одно, форматов
     несколько — поэтому и блок один, с переключателем внутри. Активный
     вариант — тот, что лежит в комнате; если там пусто, остаётся
     выбранный руками. */
  function paintVariants(el) {
    var chips = el.querySelectorAll('[data-variant]');
    if (!chips.length) return;

    var placed = null;
    chips.forEach(function (chip) {
      if (selected.has(Number(chip.dataset.variant))) placed = chip;
    });
    if (placed) el.dataset.module = placed.dataset.variant;

    var activeId = Number(el.dataset.module);
    chips.forEach(function (chip) {
      var isActive = Number(chip.dataset.variant) === activeId;
      chip.classList.toggle('is-active', isActive);
      chip.setAttribute('aria-pressed', String(isActive));
    });

    var label = el.querySelector('[data-group-price]');
    var source = el.querySelector('[data-variant="' + activeId + '"] .variant__price');
    if (label && source) label.textContent = source.textContent.trim();
  }

  function flash(part) {
    // Вспышка в момент постановки. Без неё блок просто «оказывается»
    // в комнате: на телефоне палец закрывает пол-экрана, а на стенах
    // изменение и вовсе можно не заметить.
    var slot = house.querySelector('.slot[data-part="' + part + '"]');
    if (!slot || reduceMotion) return;
    slot.classList.remove('is-just-placed');
    void slot.offsetWidth; // перезапуск анимации
    slot.classList.add('is-just-placed');
    setTimeout(function () { slot.classList.remove('is-just-placed'); }, 800);
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

  // --- Клавиатура ----------------------------------------------------------
  // Блок ставится только перетаскиванием: так решено, чтобы человек
  // physically собирал дом, а не отмечал галочки. Но клавиатура остаётся —
  // мышью владеют не все, и оставить их без единого пути было бы
  // не решением, а недоделкой.

  shelf.addEventListener('keydown', function (e) {
    var el = e.target.closest('[data-module]');
    if (!el) return;
    // Внутри блока есть свои кнопки: переключатель формата и «подробнее».
    // Enter на них — это они, а не блок.
    if (e.target.closest('[data-variant]') || e.target.closest('[data-expand]')) return;
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      var mod = moduleOf(el);
      if (!mod.required) select(mod.id, !selected.has(mod.id));
    }
  });

  // Переключатель формата внутри блока-группы. Если блок уже лежит
  // в комнате — заменяем прямо там: место одно, значит и менять нечего,
  // кроме содержимого.
  shelf.addEventListener('click', function (e) {
    var chip = e.target.closest('[data-variant]');
    if (!chip) return;
    var card = chip.closest('[data-module]');
    if (!card) return;

    var id = Number(chip.dataset.variant);
    var wasPlaced = selected.has(Number(card.dataset.module));
    card.dataset.module = id;

    if (wasPlaced) select(id, true);  // select сам снимет соседа по группе
    else paintShelf();
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
    if (!el) return;
    // Переключатель формата и «подробнее» — это нажатия, а не захват.
    if (e.target.closest('[data-expand]') || e.target.closest('[data-variant]')) return;
    var mod = moduleOf(el);
    if (mod.required) return;

    dragMoved = false;
    var startX = e.clientX;
    var startY = e.clientY;
    var pointerId = e.pointerId;

    // Мышь и палец берут блок по-разному, и это принципиально.
    //
    // Пальцем удержание обязательно: иначе перетаскивание отбирает у
    // страницы прокрутку и воюет с ней. Мышью прокручивают колесом,
    // никакого конфликта нет — а требовать удержания от мыши значит
    // сделать вид, будто перетаскивание не работает. Именно так это
    // и выглядит: нажал, повёл, ничего не поехало.
    var isTouch = e.pointerType === 'touch' || e.pointerType === 'pen';

    function cleanup() {
      clearTimeout(holdTimer);
      window.removeEventListener('pointermove', onPreMove);
      window.removeEventListener('pointerup', cleanup);
      window.removeEventListener('pointercancel', cleanup);
    }

    function onPreMove(ev) {
      var moved = Math.hypot(ev.clientX - startX, ev.clientY - startY);

      if (!isTouch) {
        // Мышь: поехали сразу, как только курсор сдвинулся заметно.
        if (moved < MOUSE_THRESHOLD) return;
        cleanup();
        startDrag(el, mod, ev.clientX, ev.clientY, pointerId);
        // Не зовём onPointerMove: он гасит событие через preventDefault,
        // а этот обработчик пассивный — браузер такое запрещает и ругается
        // в консоль. Клон и подсветку двигаем напрямую.
        moveClone(ev.clientX, ev.clientY);
        highlight(ev.clientX, ev.clientY);
        return;
      }

      // Палец: сдвинулся раньше срока — значит это прокрутка, отдаём её
      // странице и блок не берём.
      if (moved >= MOVE_TOLERANCE) cleanup();
    }

    if (isTouch) {
      holdTimer = setTimeout(function () {
        cleanup();
        startDrag(el, mod, startX, startY, pointerId);
      }, HOLD_MS);
    }

    window.addEventListener('pointermove', onPreMove, { passive: true });
    window.addEventListener('pointerup', cleanup);
    window.addEventListener('pointercancel', cleanup);
  }

  function startDrag(el, mod, x, y, pointerId) {
    var rect = el.getBoundingClientRect();
    var clone = el.cloneNode(true);
    clone.classList.add('block--dragging');
    clone.style.setProperty('--drag-width', rect.width + 'px');
    document.body.appendChild(clone);
    el.classList.add('block--ghost');

    // Держим блок за середину КЛОНА, а не карточки на складе. У блока
    // с переключателем формата карточка втрое выше: в руке переключатель
    // скрыт, а половина его высоты всё равно уезжала бы вверх — блок
    // взлетал над пальцем и выглядел оторванным от него.
    var held = clone.getBoundingClientRect();

    // Тактильное подтверждение захвата: палец закрывает обзор, и одного
    // визуального сигнала мало.
    if (navigator.vibrate) navigator.vibrate(10);

    drag = {
      el: el, clone: clone, mod: mod, pointerId: pointerId,
      offsetX: held.width / 2, offsetY: held.height / 2,
      slots: slotRects(), target: null, frame: null, x: x, y: y
    };

    // Подсказка появляется в момент взятия, а не при наведении: человек
    // должен видеть, куда нести, ещё до того как понесёт.
    house.classList.add('is-receiving');
    if (mod.housePart) {
      // У блока комнаты одно законное место — его и подсвечиваем.
      drag.slots.forEach(function (slot) {
        if (accepts(slot, mod)) slot.el.classList.add('is-available');
      });
    }
    // У разовой услуги своего места в комнате нет: подсвечена вся комната,
    // подсвечивать при этом каждый слот — только рябить в глазах.

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

  function accepts(slot, mod) {
    // Блок со своим элементом дома идёт в свой слот. Блок без элемента —
    // разовая услуга — кладётся куда угодно в комнату: своего места
    // в комнате у него нет, но и запрещать его перетаскивать незачем.
    return mod.housePart ? slot.part === mod.housePart : true;
  }

  function overHouse(x, y) {
    var r = house.getBoundingClientRect();
    return x >= r.left && x <= r.right && y >= r.top && y <= r.bottom;
  }

  function nearestSlot(x, y) {
    var best = null;
    var bestDistance = Infinity;
    drag.slots.forEach(function (slot) {
      if (!accepts(slot, drag.mod)) return;
      var d = Math.hypot(x - slot.cx, y - slot.cy);
      if (d < bestDistance) { bestDistance = d; best = slot; }
    });
    if (!best) return null;

    // Попасть точно в слот пальцем невозможно, да и не нужно: у блока
    // всё равно одно законное место. Поэтому засчитываем и близкое
    // попадание, и бросок в любую точку дома.
    if (bestDistance <= SNAP || overHouse(x, y)) return best;
    return null;
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
    house.classList.remove('is-receiving');
    drag.slots.forEach(function (slot) { slot.el.classList.remove('is-available'); });
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

  function clearPresetHighlight() {
    root.querySelectorAll('[data-preset]').forEach(function (b) {
      b.classList.remove('is-active');
    });
  }

  // Первая отрисовка.
  syncInputs();
  paintShelf();
  paintHouse();
  recalc();
})();
