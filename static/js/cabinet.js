/* Кабинет: живые мелочи.

   Всё здесь — прогрессивное улучшение. Без JavaScript кабинет остаётся
   рабочим: галочки задач кладутся обычными формами, шкала показывает
   ширину из разметки, чат отправляется перезагрузкой страницы. JS делает
   это быстрее и приятнее, но не является условием работы.
*/

(function () {
  'use strict';

  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function csrf() {
    var input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return input ? input.value : '';
  }

  // --- Шкала этапов --------------------------------------------------------
  // Заливка тянется до центра текущего этапа, а не до «процентов»: человек
  // сверяет её с кружком, и расхождение в полсантиметра читается как ошибка.

  function paintRail() {
    var rail = document.querySelector('[data-rail]');
    if (!rail) return;
    var fill = rail.querySelector('[data-rail-fill]');
    var items = rail.querySelectorAll('.rail__item');
    if (!fill || !items.length) return;

    var current = rail.querySelector('[data-rail-current]');
    var done = rail.querySelectorAll('.rail__item.is-done');
    var target = current || (done.length ? done[done.length - 1] : items[0]);

    var railBox = rail.querySelector('.rail__items').getBoundingClientRect();
    var dot = target.querySelector('.rail__dot').getBoundingClientRect();
    var width = dot.left + dot.width / 2 - railBox.left;

    if (reduceMotion) {
      fill.style.transition = 'none';
      fill.style.width = width + 'px';
      return;
    }
    // Небольшая задержка: шкала должна дорисоваться на глазах, иначе
    // движение остаётся незамеченным.
    requestAnimationFrame(function () {
      setTimeout(function () { fill.style.width = width + 'px'; }, 120);
    });

    // Текущий этап сам подъезжает в видимую часть: на телефоне шкала
    // прокручивается вбок, и восьмой этап иначе остаётся за краем.
    if (current && rail.scrollWidth > rail.clientWidth) {
      rail.scrollTo({
        left: Math.max(current.offsetLeft - rail.clientWidth / 2 + current.offsetWidth / 2, 0),
        behavior: reduceMotion ? 'auto' : 'smooth'
      });
    }
  }

  // --- Полоса оплаты -------------------------------------------------------

  function paintMoney() {
    document.querySelectorAll('[data-fill]').forEach(function (bar) {
      var value = Number(bar.dataset.fill || 0);
      if (reduceMotion) { bar.style.transition = 'none'; bar.style.width = value + '%'; return; }
      setTimeout(function () { bar.style.width = value + '%'; }, 150);
    });
  }

  // --- Задачи --------------------------------------------------------------
  // Отметка уходит на сервер сразу: «сделал» — это действие, после которого
  // человек закрывает вкладку, и требовать от него ещё и «сохранить»
  // означает терять отметки.

  document.addEventListener('click', function (e) {
    var button = e.target.closest('[data-task-toggle]');
    if (!button || button.disabled) return;

    var form = button.closest('form');
    if (!form || !window.fetch) return;  // без JS остаётся обычная отправка формы

    // Отменяем обычную отправку: страница не перезагружается, и человек
    // не теряет место, до которого долистал.
    e.preventDefault();
    var url = form.getAttribute('action');
    var row = button.closest('.task');
    var pressed = button.getAttribute('aria-pressed') === 'true';

    // Показываем результат сразу, не дожидаясь сети: отметка галочки
    // с задержкой в полсекунды ощущается как «не сработало».
    button.setAttribute('aria-pressed', String(!pressed));
    if (row) row.classList.toggle('is-done', !pressed);

    var body = new FormData();
    body.append('task', button.dataset.taskToggle);
    body.append('csrfmiddlewaretoken', csrf());

    fetch(url, { method: 'POST', body: body, headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { return r.json(); })
      .then(function (payload) {
        if (payload.ok) return;
        // Сервер не согласился — возвращаем как было.
        button.setAttribute('aria-pressed', String(pressed));
        if (row) row.classList.toggle('is-done', pressed);
      })
      .catch(function () {
        button.setAttribute('aria-pressed', String(pressed));
        if (row) row.classList.toggle('is-done', pressed);
      });
  });

  // --- Переписка -----------------------------------------------------------

  function setupChat() {
    var chat = document.querySelector('[data-chat]');
    if (chat) chat.scrollTop = chat.scrollHeight;

    var input = document.querySelector('[data-chat-input]');
    if (input) {
      // Поле растёт под текст: писать в две строки через прокрутку
      // в три строки неудобно, а длинные сообщения здесь как раз норма.
      var grow = function () {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 260) + 'px';
      };
      input.addEventListener('input', grow);

      // Ctrl+Enter отправляет: привычка из любого мессенджера.
      input.addEventListener('keydown', function (e) {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
          var form = input.closest('form');
          if (form) form.requestSubmit ? form.requestSubmit() : form.submit();
        }
      });
    }

    var files = document.querySelector('[data-chat-files]');
    var picked = document.querySelector('[data-chat-picked]');
    if (files && picked) {
      files.addEventListener('change', function () {
        var names = Array.prototype.map.call(files.files, function (f) { return f.name; });
        picked.hidden = !names.length;
        picked.textContent = names.length ? 'Приложено: ' + names.join(', ') : '';
      });
    }
  }

  // --- Копирование доступа -------------------------------------------------
  // Логин и пароль Дарья передаёт заказчику, и делать это выделением мышью
  // по буквам — верный способ ошибиться в одном символе.

  document.addEventListener('click', function (e) {
    var box = e.target.closest('[data-copy]');
    if (!box || !navigator.clipboard) return;
    navigator.clipboard.writeText(box.textContent.trim()).then(function () {
      box.classList.add('is-copied');
      var was = box.dataset.was || box.textContent;
      box.dataset.was = was;
      box.textContent = 'Скопировано';
      setTimeout(function () {
        box.textContent = was;
        box.classList.remove('is-copied');
      }, 1200);
    });
  });

  paintRail();
  paintMoney();
  setupChat();
  window.addEventListener('resize', paintRail);
})();
