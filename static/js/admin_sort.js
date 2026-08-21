/* Порядок фотографий — перетаскиванием строк.

   Номерами порядок задавать можно, но нельзя *смотреть*: человек
   раскладывает кадры глазами — «этот после того», — а не считает
   десятки в голове. Поля с номером остаются на месте: без JavaScript
   и для точной правки они единственный способ.

   Тащат за ручку слева, а не за всю строку: внутри строки живут поля,
   которые надо уметь выделять и править. */

(function () {
  'use strict';

  var STEP = 10;   // шаг нумерации: между соседними всегда есть место
  var ready = false;

  /* Считаем только строки с уже сохранённой фотографией.

     Пустые строки «добавить ещё» трогать нельзя: как только в такой
     строке меняется хоть одно поле, Django перестаёт считать её пустой
     и требует картинку — форма не сохраняется вовсе, а человек видит
     ошибку там, где ничего не заполнял. Именно так и вышло с первой
     версией: порядок в разметке менялся, а сохранить его было нельзя. */
  function rows(body) {
    return Array.prototype.filter.call(body.children, function (row) {
      if (row.tagName !== 'TR' || row.classList.contains('empty-form')) return false;
      var id = row.querySelector('input[name$="-id"]');
      return !!(id && id.value) && !!row.querySelector('input[name$="-order"]');
    });
  }

  function renumber(body) {
    rows(body).forEach(function (row, i) {
      var input = row.querySelector('input[name$="-order"]');
      if (input) input.value = (i + 1) * STEP;
    });
  }

  function setup(body) {
    if (body.dataset.sortable) return;
    body.dataset.sortable = '1';

    rows(body).forEach(addHandle);

    // Админка добавляет строки кнопкой «Добавить ещё»: новым строкам
    // ручка нужна так же, как старым.
    new MutationObserver(function (list) {
      list.forEach(function (m) {
        Array.prototype.forEach.call(m.addedNodes, function (node) {
          if (node.tagName === 'TR' && rows(body).indexOf(node) > -1) addHandle(node);
        });
      });
    }).observe(body, { childList: true });
  }

  function addHandle(row) {
    if (row.querySelector('.sort-handle')) return;
    var cell = row.querySelector('td, th');
    if (!cell) return;

    var handle = document.createElement('span');
    handle.className = 'sort-handle';
    handle.title = 'Перетащите, чтобы поменять порядок';
    handle.setAttribute('aria-hidden', 'true');
    cell.insertBefore(handle, cell.firstChild);

    handle.addEventListener('pointerdown', function (e) {
      e.preventDefault();
      start(row, e);
    });
  }

  var drag = null;

  function start(row, e) {
    var body = row.parentNode;
    drag = { row: row, body: body, y: e.clientY };
    row.classList.add('is-moving');
    document.documentElement.classList.add('is-sorting');

    window.addEventListener('pointermove', onMove, { passive: false });
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onUp);
  }

  function onMove(e) {
    if (!drag) return;
    e.preventDefault();

    // Строку не таскаем как картинку: она просто меняется местами
    // с той, над которой оказался курсор. Так порядок виден сразу
    // и не надо угадывать, куда она встанет.
    var others = rows(drag.body).filter(function (r) { return r !== drag.row; });
    for (var i = 0; i < others.length; i++) {
      var box = others[i].getBoundingClientRect();
      var middle = box.top + box.height / 2;
      if (e.clientY < middle && others[i].compareDocumentPosition(drag.row) & Node.DOCUMENT_POSITION_FOLLOWING) {
        drag.body.insertBefore(drag.row, others[i]);
        break;
      }
      if (e.clientY > middle && others[i].compareDocumentPosition(drag.row) & Node.DOCUMENT_POSITION_PRECEDING) {
        drag.body.insertBefore(drag.row, others[i].nextSibling);
        break;
      }
    }
  }

  function onUp() {
    if (!drag) return;
    drag.row.classList.remove('is-moving');
    document.documentElement.classList.remove('is-sorting');
    renumber(drag.body);
    // Строка на секунду подсвечивается: глаз должен найти её на новом
    // месте, иначе после перетаскивания непонятно, что изменилось.
    drag.row.classList.add('is-settled');
    var row = drag.row;
    setTimeout(function () { row.classList.remove('is-settled'); }, 800);

    window.removeEventListener('pointermove', onMove);
    window.removeEventListener('pointerup', onUp);
    window.removeEventListener('pointercancel', onUp);
    drag = null;
  }

  function init() {
    if (ready) return;
    document.querySelectorAll('.inline-group table tbody').forEach(function (body) {
      if (body.querySelector('input[name$="-order"]')) setup(body);
    });
    ready = true;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
