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

  // --- Этап раскрывается со шкалы -----------------------------------------
  // Восемь карточек подряд повторяют то, что уже сказала шкала, и человек
  // читает одно и то же дважды. Поэтому открыт один этап — тот, о котором
  // спрашивают. Остальные не удалены и не спрятаны от поиска: они здесь же,
  // просто свёрнуты, и без JavaScript открыты все.

  function setupStages() {
    var host = document.querySelector('[data-stages]');
    if (!host) return;
    var stages = host.querySelectorAll('[data-stage]');
    if (stages.length < 2) return;

    function open(id, scroll) {
      var found = false;
      stages.forEach(function (stage) {
        var mine = stage.id === id;
        stage.hidden = !mine;
        if (mine) found = true;
      });
      // Незнакомый якорь не должен схлопывать всё: пусть лучше
      // останется открытым текущий этап.
      if (!found) return false;

      document.querySelectorAll('[data-rail-link]').forEach(function (link) {
        link.classList.toggle('is-open', link.dataset.railLink === id);
      });

      var stage = document.getElementById(id);
      if (stage && !reduceMotion) {
        stage.classList.remove('stage--in');
        void stage.offsetWidth;  // перезапуск анимации
        stage.classList.add('stage--in');
      }
      if (scroll && stage) {
        // Шапка сайта липкая: без отступа на её высоту заголовок панели
        // уезжает под неё, и кажется, что открылось что-то не то.
        var header = document.querySelector('.header');
        var offset = (header ? header.offsetHeight : 0) + 16;
        var top = host.getBoundingClientRect().top + window.pageYOffset - offset;
        window.scrollTo({ top: Math.max(top, 0), behavior: reduceMotion ? 'auto' : 'smooth' });
      }
      return true;
    }

    var start = (location.hash || '').replace('#', '');
    var current = host.querySelector('.stage--current') || stages[0];
    if (!start || !open(start, false)) open(current.id, false);

    document.addEventListener('click', function (e) {
      var link = e.target.closest('[data-rail-link]');
      if (!link) return;
      if (!open(link.dataset.railLink, true)) return;
      e.preventDefault();
      // Адрес меняем без прыжка: ссылкой на этап можно поделиться.
      if (history.replaceState) history.replaceState(null, '', '#' + link.dataset.railLink);
    });
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

    setupChatExchange(chat, input, files, picked);
  }

  // --- Обмен сообщениями без перезагрузки -----------------------------------
  // Обе стороны сидят в кабинете и ждут ответа. Обновлять страницу ради
  // этого не должен никто: отправка уходит запросом, а новые сообщения
  // подтягиваются опросом раз в несколько секунд.
  //
  // Опрос, а не постоянное соединение: держать его ради двух собеседников —
  // это отдельный процесс, который надо запускать, сторожить и
  // перезапускать. Здесь цена ошибки — задержка в несколько секунд.

  var POLL_ACTIVE = 6000;    // пока вкладка открыта и на виду
  var POLL_HIDDEN = 30000;   // вкладку свернули — торопиться некуда

  function messageNode(item) {
    var box = document.createElement('div');
    box.className = 'msg ' + (item.mine ? 'msg--mine' : 'msg--theirs');
    box.dataset.message = item.id;

    var meta = document.createElement('div');
    meta.className = 'msg__meta';
    var who = document.createElement('strong');
    who.textContent = item.author || '—';
    var when = document.createElement('time');
    when.textContent = item.at;
    meta.appendChild(who);
    meta.appendChild(when);
    if (item.stage) {
      var stage = document.createElement('span');
      stage.className = 'muted';
      stage.textContent = '· ' + item.stage;
      meta.appendChild(stage);
    }
    box.appendChild(meta);

    if (item.text) {
      var text = document.createElement('p');
      text.className = 'msg__text';
      // Текст кладём как текст, а не как разметку: сообщение пишет
      // человек, и оно не должно уметь превращаться в HTML.
      text.textContent = item.text;
      box.appendChild(text);
    }

    if (item.files && item.files.length) {
      var wrap = document.createElement('div');
      wrap.className = 'msg__files';
      item.files.forEach(function (file) {
        var link = document.createElement('a');
        link.href = file.url;
        if (file.image) {
          link.className = 'msg__thumb';
          link.dataset.lightbox = file.name;
          var img = document.createElement('img');
          img.src = file.url;
          img.alt = file.name;
          img.loading = 'lazy';
          link.appendChild(img);
        } else {
          link.className = 'msg__file';
          link.target = '_blank';
          link.rel = 'noopener';
          var name = document.createElement('span');
          name.className = 'msg__file-name';
          name.textContent = file.name;
          var size = document.createElement('span');
          size.className = 'muted';
          size.textContent = file.size;
          link.appendChild(name);
          link.appendChild(size);
        }
        wrap.appendChild(link);
      });
      box.appendChild(wrap);
    }
    return box;
  }

  function setupChatExchange(chat, input, files, picked) {
    var panel = document.querySelector('[data-chat-panel]');
    var form = document.querySelector('[data-chat-form]');
    if (!panel || !chat || !form || !window.fetch) return;

    var lastId = 0;
    chat.querySelectorAll('[data-message]').forEach(function (node) {
      lastId = Math.max(lastId, Number(node.dataset.message));
    });

    function append(list) {
      if (!list || !list.length) return;
      var empty = chat.querySelector('[data-chat-empty]');
      if (empty) empty.remove();

      // Держим прокрутку внизу, только если человек и так был внизу:
      // иначе он читает старое, а лента прыгает под руками.
      var atBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
      list.forEach(function (item) {
        if (chat.querySelector('[data-message="' + item.id + '"]')) return;
        chat.appendChild(messageNode(item));
        lastId = Math.max(lastId, item.id);
      });
      if (atBottom) chat.scrollTop = chat.scrollHeight;
    }

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var button = form.querySelector('button[type="submit"]');
      if (button) button.disabled = true;

      fetch(form.getAttribute('action'), {
        method: 'POST',
        body: new FormData(form),
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
      })
        .then(function (r) { return r.json(); })
        .then(function (payload) {
          if (button) button.disabled = false;
          if (!payload.ok) return;
          append(payload.messages);
          form.reset();
          if (input) input.style.height = 'auto';
          if (picked) { picked.hidden = true; picked.textContent = ''; }
        })
        .catch(function () {
          // Сеть отвалилась — отдаём форму обычной отправке, чтобы
          // написанное не пропало.
          if (button) button.disabled = false;
          form.submit();
        });
    });

    function poll() {
      fetch(panel.dataset.pollUrl + '?after=' + lastId, {
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
      })
        .then(function (r) { return r.json(); })
        .then(function (payload) { if (payload.ok) append(payload.messages); })
        .catch(function () { /* связь пропала — попробуем в следующий раз */ });
    }

    var timer = setInterval(poll, POLL_ACTIVE);
    document.addEventListener('visibilitychange', function () {
      clearInterval(timer);
      timer = setInterval(poll, document.hidden ? POLL_HIDDEN : POLL_ACTIVE);
      if (!document.hidden) poll();
    });
  }

  // --- Перетаскивание файлов ------------------------------------------------
  // Файлы бросают мышью из папки — так их и передают в жизни. Кнопка при
  // этом остаётся: перетаскивание умеют не все, а на телефоне его нет.

  function names(list) {
    return Array.prototype.map.call(list, function (f) { return f.name; }).join(', ');
  }

  document.querySelectorAll('[data-drop]').forEach(function (zone) {
    var input = zone.querySelector('[data-drop-input]');
    var picked = zone.parentElement.querySelector('[data-drop-picked]');
    if (!input) return;

    function show() {
      if (!picked) return;
      picked.hidden = !input.files.length;
      picked.textContent = input.files.length
        ? 'Готово к отправке: ' + names(input.files)
        : '';
    }

    input.addEventListener('change', show);

    ['dragenter', 'dragover'].forEach(function (name) {
      zone.addEventListener(name, function (e) {
        e.preventDefault();
        zone.classList.add('is-over');
      });
    });
    ['dragleave', 'drop'].forEach(function (name) {
      zone.addEventListener(name, function (e) {
        e.preventDefault();
        zone.classList.remove('is-over');
      });
    });

    zone.addEventListener('drop', function (e) {
      if (!e.dataTransfer || !e.dataTransfer.files.length) return;
      // Кладём файлы прямо в поле формы: тогда обычная отправка работает
      // так же, как если бы их выбрали кнопкой.
      input.files = e.dataTransfer.files;
      show();
    });
  });

  // --- Копирование доступа -------------------------------------------------
  // Логин и пароль Дарья передаёт заказчику, и делать это выделением мышью
  // по буквам — верный способ ошибиться в одном символе.

  function copy(text) {
    if (navigator.clipboard) return navigator.clipboard.writeText(text);
    // Запасной путь: буфер обмена доступен только по HTTPS, а кабинет
    // иногда открывают по локальному адресу.
    var area = document.createElement('textarea');
    area.value = text;
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    try { document.execCommand('copy'); } catch (err) { /* ничего не поделать */ }
    area.remove();
    return Promise.resolve();
  }

  document.addEventListener('click', function (e) {
    var box = e.target.closest('[data-copy]');
    if (box) {
      copy(box.textContent.trim()).then(function () {
        box.classList.add('is-copied');
        var was = box.dataset.was || box.textContent;
        box.dataset.was = was;
        box.textContent = 'Скопировано';
        setTimeout(function () {
          box.textContent = was;
          box.classList.remove('is-copied');
        }, 1200);
      });
      return;
    }

    // Кнопка «Скопировать сообщение»: целиком, готовым текстом.
    var all = e.target.closest('[data-copy-all]');
    if (all) {
      var source = document.querySelector('[data-copy-source]');
      if (!source) return;
      copy(source.value).then(function () {
        var was = all.dataset.was || all.textContent;
        all.dataset.was = was;
        all.textContent = 'Скопировано';
        setTimeout(function () { all.textContent = was; }, 1500);
      });
    }
  });

  // Окно с доступом закрывается и без перезагрузки — но ссылка в нём
  // остаётся рабочей, если JavaScript выключен.
  document.addEventListener('click', function (e) {
    var close = e.target.closest('[data-modal-close]');
    if (!close) return;
    var modal = close.closest('[data-modal]');
    if (!modal) return;
    e.preventDefault();
    modal.remove();
  });

  paintRail();
  paintMoney();
  setupChat();
  setupStages();
  window.addEventListener('resize', paintRail);
})();
