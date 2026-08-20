/* Воронка заявок: перенос карточки рукой.

   Заявки разбирают пачкой — пять подряд, — и каждый заход внутрь карточки
   ради одного поля «статус» стоит трёх нажатий и потери места в списке.
   Перенос рукой делает то же самое одним движением.

   Мышью карточка берётся сразу, пальцем — после удержания: на телефоне
   доска прокручивается тем же движением, и без задержки прокрутка
   превращалась бы в перетаскивание при каждом касании.

   Без этого файла страница остаётся рабочей: карточка — ссылка внутрь
   заявки, где статус правится выпадающим списком. */

(function () {
  'use strict';

  var board = document.querySelector('[data-board]');
  if (!board || !window.fetch) return;

  /* Родное перетаскивание браузера здесь мешает: в карточке лежит ссылка,
     а ссылку браузер тащит сам — и в этот момент гасит указатель
     событием pointercancel. Наш захват срывался сразу после начала,
     и карточка не двигалась вовсе. */
  board.addEventListener('dragstart', function (e) { e.preventDefault(); });

  var HOLD_MS = 260;          // столько палец держит карточку, прежде чем взять
  var MOVE_TOLERANCE = 8;     // сдвиг раньше срока считается прокруткой
  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function csrf() {
    var m = document.cookie.match(/(^|;\s*)csrftoken=([^;]+)/);
    return m ? m[2] : '';
  }

  function columns() {
    return Array.prototype.map.call(board.querySelectorAll('[data-column]'), function (col) {
      return { el: col, status: col.dataset.column, rect: col.getBoundingClientRect() };
    });
  }

  function recount() {
    board.querySelectorAll('[data-column]').forEach(function (col) {
      var n = col.querySelectorAll('[data-lead]').length;
      var counter = col.querySelector('[data-count]');
      if (counter) counter.textContent = n;
      var empty = col.querySelector('.board__empty');
      // «Пусто» — это состояние столбца, а не строка, которую забыли убрать.
      if (n && empty) empty.remove();
      if (!n && !empty) {
        var p = document.createElement('p');
        p.className = 'board__empty';
        p.textContent = 'Пусто';
        col.querySelector('.board__drop').appendChild(p);
      }
    });
  }

  var drag = null;
  var pending = null;

  document.addEventListener('pointerdown', function (e) {
    var card = e.target.closest('[data-lead]');
    if (!card || e.button > 0) return;

    var touch = e.pointerType !== 'mouse';
    var startX = e.clientX, startY = e.clientY;
    var holdTimer = null;

    function cancel() {
      clearTimeout(holdTimer);
      window.removeEventListener('pointermove', preMove);
      window.removeEventListener('pointerup', cancel);
      window.removeEventListener('pointercancel', cancel);
    }

    function preMove(ev) {
      var moved = Math.hypot(ev.clientX - startX, ev.clientY - startY);
      if (!touch && moved > MOVE_TOLERANCE) {
        cancel();
        start(card, ev.clientX, ev.clientY, e.pointerId);
        return;
      }
      // Палец поехал раньше срока — это прокрутка доски, отдаём её странице.
      if (touch && moved >= MOVE_TOLERANCE) cancel();
    }

    if (touch) {
      holdTimer = setTimeout(function () {
        cancel();
        start(card, startX, startY, e.pointerId);
      }, HOLD_MS);
    }

    window.addEventListener('pointermove', preMove, { passive: true });
    window.addEventListener('pointerup', cancel);
    window.addEventListener('pointercancel', cancel);
  });

  function start(card, x, y, pointerId) {
    var rect = card.getBoundingClientRect();
    var clone = card.cloneNode(true);
    clone.classList.add('house-card--dragging');
    clone.style.width = rect.width + 'px';
    document.body.appendChild(clone);
    card.classList.add('house-card--ghost');
    board.classList.add('is-dragging');

    // Тактильное подтверждение захвата: палец закрывает карточку,
    // и одного визуального сигнала мало.
    if (navigator.vibrate) navigator.vibrate(10);

    drag = {
      card: card, clone: clone, pointerId: pointerId,
      dx: x - rect.left, dy: y - rect.top,
      cols: columns(), target: null, frame: null, x: x, y: y
    };

    window.addEventListener('pointermove', onMove, { passive: false });
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onCancel);
    move(x, y);
  }

  function move(x, y) {
    if (!drag) return;
    drag.x = x; drag.y = y;
    if (drag.frame) return;
    drag.frame = requestAnimationFrame(function () {
      // Проверка идёт первой: карточку могли отпустить между кадрами,
      // и тогда drag уже пуст.
      if (!drag) return;
      drag.frame = null;
      drag.clone.style.transform =
        'translate3d(' + (drag.x - drag.dx) + 'px,' + (drag.y - drag.dy) + 'px,0)' +
        (reduceMotion ? '' : ' rotate(-1.5deg)');
    });
  }

  function onMove(e) {
    if (!drag) return;
    e.preventDefault();
    move(e.clientX, e.clientY);

    var found = null;
    drag.cols.forEach(function (col) {
      var r = col.rect;
      if (e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom) {
        found = col;
      }
      col.el.classList.remove('is-target');
    });
    drag.target = found;
    if (found) found.el.classList.add('is-target');

    // Доска шире экрана: у края она подъезжает сама, иначе до дальнего
    // столбца карточку не донести.
    var edge = 60;
    if (e.clientX < board.getBoundingClientRect().left + edge) board.scrollLeft -= 12;
    if (e.clientX > board.getBoundingClientRect().right - edge) board.scrollLeft += 12;
  }

  function cleanup() {
    if (!drag) return;
    drag.clone.remove();
    drag.card.classList.remove('house-card--ghost');
    board.classList.remove('is-dragging');
    drag.cols.forEach(function (col) { col.el.classList.remove('is-target'); });
    window.removeEventListener('pointermove', onMove);
    window.removeEventListener('pointerup', onUp);
    window.removeEventListener('pointercancel', onCancel);
    drag = null;
  }

  function onCancel() { cleanup(); }

  function onUp() {
    if (!drag) return;
    var card = drag.card;
    var target = drag.target;
    cleanup();
    if (!target || target.status === card.dataset.status) return;

    var from = card.closest('[data-column]');
    var fromStatus = card.dataset.status;

    // Карточка переезжает сразу, не дожидаясь сети: «сделал» с задержкой
    // в полсекунды ощущается как «не сработало».
    target.el.querySelector('.board__drop').appendChild(card);
    card.dataset.status = target.status;
    card.classList.add('house-card--landed');
    setTimeout(function () { card.classList.remove('house-card--landed'); }, 700);
    recount();

    var body = new URLSearchParams({ status: target.status, csrfmiddlewaretoken: csrf() });
    clearTimeout(pending);
    fetch(card.dataset.moveUrl || board.dataset.moveUrl.replace('0', card.dataset.lead), {
      method: 'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      body: body
    })
      .then(function (r) { return r.json(); })
      .then(function (payload) {
        if (payload.ok) return;
        back(card, from, fromStatus);
      })
      .catch(function () { back(card, from, fromStatus); });
  }

  function back(card, column, status) {
    // Сервер не согласился — возвращаем карточку на место. Молча оставить
    // её в новом столбце значит показать неправду.
    column.querySelector('.board__drop').appendChild(card);
    card.dataset.status = status;
    recount();
  }
})();
