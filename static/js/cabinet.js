/* Кабинет: живые мелочи.

   Всё здесь — прогрессивное улучшение. Без JavaScript кабинет остаётся
   рабочим: галочки задач кладутся обычными формами, шкала показывает
   ширину из разметки, чат отправляется перезагрузкой страницы. JS делает
   это быстрее и приятнее, но не является условием работы.
*/

(function () {
  'use strict';

  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* Токен берём из cookie, а не из разметки.

     Разметка стареет: вкладку с кабинетом открыли вчера, сегодня зашли
     заново — и токен в форме уже не тот, что в браузере. Django отвечает
     на это «Ошибка проверки CSRF, запрос отклонён», и человек видит её
     ровно в тот момент, когда отправляет фотографии с телефона, где
     вкладки живут месяцами. Cookie при этом всегда свежая. */
  function csrf() {
    var match = document.cookie.match(/(^|;\s*)csrftoken=([^;]+)/);
    if (match) return decodeURIComponent(match[2]);
    var input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return input ? input.value : '';
  }

  // --- Короткое сообщение --------------------------------------------------
  // Ответ на действие нужен всегда: без перезагрузки страницы пропадает
  // и полоса сообщений сверху, а «нажал и ничего не произошло» — это
  // повод нажать второй раз.

  var toastTimer = null;

  function toast(text, kind) {
    if (!text) return;
    var box = document.querySelector('[data-toast]');
    if (!box) {
      box = document.createElement('div');
      box.className = 'toast';
      box.setAttribute('data-toast', '');
      box.setAttribute('role', 'status');
      box.setAttribute('aria-live', 'polite');
      document.body.appendChild(box);
    }
    box.textContent = text;
    box.classList.toggle('toast--error', kind === 'error');
    box.classList.add('is-open');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { box.classList.remove('is-open'); }, 2600);
  }

  // --- Формы без перезагрузки ----------------------------------------------
  // Одно правило на весь кабинет: форма с data-async уходит запросом,
  // сервер возвращает перерисованный кусок страницы. Разметку по-прежнему
  // собирает шаблон — второй её копии на JavaScript не появляется.
  //
  // Без JavaScript ничего не меняется: та же форма отправляется обычным
  // способом, сервер отвечает страницей.

  /* Что было раскрыто до подмены карточки.

     Свежая разметка приходит в исходном виде: раскрытые «Добавить задачу»
     и «Этап: статус, заметка, файлы» захлопываются, режим правки заготовок
     выключается. Человек в этот момент как раз работал внутри — добавлял
     вторую заготовку, дописывал третью задачу, — и захлопнувшаяся панель
     читается как «сбросилось». */
  function rememberOpen(card) {
    var keys = [];
    if (!card) return keys;
    card.querySelectorAll('details[data-keep]').forEach(function (box) {
      if (box.open) keys.push(box.dataset.keep);
    });
    if (card.querySelector('.presets.is-editing')) keys.push('presets-editing');
    return keys;
  }

  function restoreOpen(card, keys) {
    if (!card || !keys.length) return;
    card.querySelectorAll('details[data-keep]').forEach(function (box) {
      if (keys.indexOf(box.dataset.keep) >= 0) box.open = true;
    });
    if (keys.indexOf('presets-editing') >= 0) {
      var toggle = card.querySelector('[data-presets-edit]');
      if (toggle) toggle.click();
    }
  }

  function swap(payload) {
    if (payload.stage) {
      var card = document.getElementById(payload.stage_id);
      if (card) {
        var wasOpen = rememberOpen(card);
        card.outerHTML = payload.stage;
        // Свежая карточка приходит без пометки «свёрнута»: раскладку
        // этапов восстанавливаем сами.
        applyStages(payload.stage_id, false);
        restoreOpen(document.getElementById(payload.stage_id), wasOpen);
        armAll();
      }
    }
    if (payload.rail) {
      var rail = document.querySelector('[data-rail]');
      if (rail) {
        rail.outerHTML = payload.rail;
        applyStages(openStageId, false);
        paintRail();
      }
    }
    if (typeof payload.progress === 'number') {
      document.querySelectorAll('[data-progress]').forEach(function (el) {
        el.textContent = payload.progress;
      });
    }
  }

  /* Ответ приходит в одном из двух видов, и это не усложнение, а экономия.

     Этап отвечает готовым куском разметки: там действия частые, и гонять
     ради галочки всю страницу незачем. Всё остальное — оплаты, договоры,
     карточка — отвечает обычной страницей, как и без JavaScript; мы просто
     достаём из неё нужные панели и подменяем их на месте. Так ни один
     из десятка видов не пришлось переписывать под запрос. */
  function refreshFrom(html, form) {
    var doc = new DOMParser().parseFromString(html, 'text/html');
    var targets = (form.dataset.refresh || '').split(',').map(function (s) { return s.trim(); });

    targets.filter(Boolean).forEach(function (selector) {
      var fresh = doc.querySelector(selector);
      var old = document.querySelector(selector);
      if (fresh && old) old.replaceWith(fresh);
    });

    // Подменённые панели приезжают в исходном виде: свёрнутые этапы
    // снова развёрнуты, полосы обнулены. Возвращаем состояние на место.
    applyStages(openStageId, false);
    paintRail();
    paintMoney();
    armAll();

    var said = doc.querySelector('.message');
    if (said) {
      toast(said.textContent.trim(), said.classList.contains('message--error') ? 'error' : '');
    }
  }

  function send(form) {
    var body = new FormData(form);
    // Токен подменяем свежим: в форме он мог устареть вместе со вкладкой.
    body.set('csrfmiddlewaretoken', csrf());

    var button = form.querySelector('[type="submit"]');
    if (button) button.disabled = true;
    form.classList.add('is-busy');

    function done() {
      if (button) button.disabled = false;
      form.classList.remove('is-busy');
    }

    fetch(form.action, {
      method: 'POST',
      body: body,
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    })
      .then(function (response) {
        var json = (response.headers.get('Content-Type') || '').indexOf('json') >= 0;
        return response.text().then(function (text) {
          return { ok: response.ok, json: json, text: text };
        });
      })
      .then(function (answer) {
        done();

        if (!answer.json) {
          if (!answer.ok) { form.submit(); return; }
          refreshFrom(answer.text, form);
          form.reset();
          return;
        }

        var payload;
        try { payload = JSON.parse(answer.text); } catch (e) { form.submit(); return; }

        if (payload.ok === false) {
          toast(payload.error || 'Не получилось. Попробуйте ещё раз.', 'error');
          return;
        }
        swap(payload);
        toast(payload.message);
        form.reset();
      })
      .catch(function () {
        done();
        form.submit();  // сеть отвалилась — пусть работает обычная отправка
      });
  }

  document.addEventListener('submit', function (e) {
    var form = e.target.closest('form[data-async]');
    if (!form || !window.fetch) return;
    if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) {
      e.preventDefault();
      return;
    }
    e.preventDefault();
    send(form);
  });

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

  var openStageId = '';

  /* Раскладка этапов применяется заново после каждой подмены карточки:
     список узлов кэшировать нельзя — после ответа сервера он состоит
     из отсоединённых от страницы элементов, и раскладка молча перестаёт
     работать. */
  function applyStages(id, animate) {
    var host = document.querySelector('[data-stages]');
    if (!host) return false;
    var stages = host.querySelectorAll('[data-stage]');
    if (stages.length < 2) return false;

    var found = false;
    stages.forEach(function (stage) {
      var mine = stage.id === id;
      stage.hidden = !mine;
      if (mine) found = true;
    });
    // Незнакомый якорь не должен схлопывать всё: пусть лучше останется
    // открытым текущий этап.
    if (!found) return false;

    openStageId = id;
    document.querySelectorAll('[data-rail-link]').forEach(function (link) {
      var mine = link.dataset.railLink === id;
      link.classList.toggle('is-open', mine);
      if (link.hasAttribute('aria-expanded')) link.setAttribute('aria-expanded', String(mine));
    });

    var card = document.getElementById(id);
    if (card && animate && !reduceMotion) {
      card.classList.remove('stage--in');
      void card.offsetWidth;  // перезапуск анимации
      card.classList.add('stage--in');
    }
    return true;
  }

  function setupStages() {
    var host = document.querySelector('[data-stages]');
    if (!host) return;
    var stages = host.querySelectorAll('[data-stage]');
    if (stages.length < 2) return;

    var start = (location.hash || '').replace('#', '');
    var current = host.querySelector('.stage--current') || stages[0];
    if (!start || !applyStages(start, false)) applyStages(current.id, false);

    document.addEventListener('click', function (e) {
      var link = e.target.closest('[data-rail-link]');
      if (!link) return;
      e.preventDefault();
      if (!applyStages(link.dataset.railLink, true)) return;
      // Страница не прыгает: этап и так под шкалой, а прокрутка к нему
      // выглядит как перезагрузка — ровно то ощущение, от которого
      // и уходим. Адрес меняем без перехода: ссылкой можно поделиться.
      if (history.replaceState) history.replaceState(null, '', '#' + link.dataset.railLink);
    });
  }

  // --- Правка задачи -------------------------------------------------------
  // Форма живёт рядом со строкой и раскрывается по карандашу. Отдельной
  // страницы у задачи нет намеренно: строка в две секунды не заслуживает
  // перехода туда и обратно.

  document.addEventListener('click', function (e) {
    var open = e.target.closest('[data-task-edit]');
    var close = e.target.closest('[data-task-cancel]');
    if (!open && !close) return;
    var id = (open || close).dataset.taskEdit || (open || close).dataset.taskCancel;
    var form = document.querySelector('[data-task-form="' + id + '"]');
    var row = document.querySelector('.task[data-task="' + id + '"]');
    if (!form) return;
    e.preventDefault();
    form.hidden = !!close;
    if (row) row.hidden = !close;
    if (!close) {
      var field = form.querySelector('textarea');
      if (field) field.focus();
    }
  });

  // --- Правка заготовок ----------------------------------------------------
  // Переключатель, а не долгое нажатие: скрытый жест на телефоне не находит
  // никто, а на мыши его нет вовсе. Пока правка выключена, нажатие на
  // заготовку ставит задачу — то есть обычная работа ничем не осложнена.

  document.addEventListener('click', function (e) {
    var toggle = e.target.closest('[data-presets-edit]');
    if (toggle) {
      e.preventDefault();
      var box = toggle.closest('[data-presets]');
      var on = box.classList.toggle('is-editing');
      toggle.textContent = on ? 'готово' : 'править';
      box.querySelectorAll('[data-preset-drop]').forEach(function (form) { form.hidden = !on; });
      var adder = box.querySelector('[data-preset-new]');
      if (adder) adder.hidden = !on;
      if (!on) {
        box.querySelectorAll('[data-preset-form]').forEach(function (form) { form.hidden = true; });
        box.querySelectorAll('[data-preset-chip]').forEach(function (chip) { chip.hidden = false; });
      }
      return;
    }

    // В режиме правки нажатие на саму заготовку открывает её, а не ставит
    // задачу: иначе «поправить» и «поставить» жили бы на одной кнопке.
    /* Ищем внутри своей карточки этапа, а не по всей странице.

       Одна и та же заготовка показана на нескольких этапах, и на странице
       восемь карточек — семь из них свёрнуты. Поиск по документу находил
       копию в свёрнутой карточке и открывал её там: на экране не менялось
       ничего, кроме исчезнувшей заготовки. */
    var chip = e.target.closest('[data-preset-chip]');
    if (chip && chip.closest('.is-editing')) {
      e.preventDefault();
      var here = chip.closest('[data-presets]');
      var id = chip.dataset.presetChip;
      var form = here.querySelector('[data-preset-form="' + id + '"]');
      if (!form) return;
      chip.hidden = true;
      var drop = here.querySelector('[data-preset-drop="' + id + '"]');
      if (drop) drop.hidden = true;
      form.hidden = false;
      var field = form.querySelector('textarea');
      if (field) field.focus();
      return;
    }

    var cancel = e.target.closest('[data-preset-cancel]');
    if (cancel) {
      e.preventDefault();
      var mine = cancel.closest('[data-presets]');
      var pid = cancel.dataset.presetCancel;
      var back = mine.querySelector('[data-preset-chip="' + pid + '"]');
      var editing = mine.querySelector('[data-preset-form="' + pid + '"]');
      var remove = mine.querySelector('[data-preset-drop="' + pid + '"]');
      if (editing) editing.hidden = true;
      if (back) back.hidden = false;
      if (remove) remove.hidden = false;
    }
  });

  // --- Спящая кнопка -------------------------------------------------------
  // Всегда красная кнопка «Отправить» читается как «у тебя что-то
  // не отправлено», и это ощущение висит над человеком всё время, пока он
  // листает страницу. Кнопка спит, пока отправлять нечего, и загорается,
  // как только появилось что отправить.

  function armForm(form) {
    var button = form.querySelector('[data-arm-button]');
    if (!button) return;

    var start = form.dataset.armState;
    if (start === undefined) {
      start = formState(form);
      form.dataset.armState = start;
    }
    var changed = formState(form) !== start;
    button.classList.toggle('btn--asleep', !changed);
    button.disabled = !changed;
  }

  function formState(form) {
    var parts = [];
    Array.prototype.forEach.call(form.elements, function (el) {
      if (!el.name || el.type === 'hidden' || el.type === 'submit') return;
      if (el.type === 'file') parts.push(el.files.length);
      else parts.push(el.value);
    });
    return parts.join('\u0001');
  }

  function armAll() {
    document.querySelectorAll('form[data-armed]').forEach(armForm);
  }

  ['input', 'change'].forEach(function (name) {
    document.addEventListener(name, function (e) {
      var form = e.target.closest('form[data-armed]');
      if (form) armForm(form);
    });
  });

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
    box.className = 'msg ' + (item.mine ? 'msg--mine' : 'msg--theirs') +
      (item.decision ? ' msg--decision' : '');
    box.id = 'msg-' + item.id;
    box.dataset.message = item.id;
    box.dataset.editLeft = item.edit_left || 0;
    if (item.own) box.dataset.own = '';

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

    box.appendChild(messageTools(item));
    return box;
  }

  /* Инструменты сообщения: «это решение» и «поправить».

     Правка живёт минуту и только у автора — этого хватает на «отправил
     не ту цифру» и не хватает, чтобы переписать историю. Кнопка гаснет
     сама, а не остаётся до перезагрузки, чтобы потом получить отказ. */
  function messageTools(item) {
    var tools = document.createElement('div');
    tools.className = 'msg__tools';

    var decide = document.createElement('button');
    decide.type = 'button';
    decide.className = 'msg__tool';
    decide.dataset.decide = item.id;
    decide.setAttribute('aria-pressed', String(!!item.decision));
    decide.textContent = item.decision ? '✓ решение' : '✓ это решение';
    tools.appendChild(decide);

    var edit = document.createElement('button');
    edit.type = 'button';
    edit.className = 'msg__tool';
    edit.dataset.edit = item.id;
    edit.textContent = 'поправить';
    edit.hidden = true;
    tools.appendChild(edit);
    return tools;
  }

  /* Окно правки: кнопка появляется у своих сообщений и гаснет сама.

     Считаем по секундам, оставшимся с сервера: часы в браузере могут
     врать на минуты, и доверять им в вопросе «прошла ли минута» нельзя. */
  function watchEditWindow() {
    document.querySelectorAll('.msg[data-own]').forEach(function (node) {
      var left = Number(node.dataset.editLeft || 0);
      var button = node.querySelector('[data-edit]');
      if (!button) return;
      button.hidden = left <= 0;
      if (left > 0) {
        node.dataset.editLeft = left - 1;
        if (left - 1 <= 0) closeEdit(node);
      }
    });
  }

  function closeEdit(node) {
    var form = node.querySelector('.msg__edit');
    if (form) form.remove();
    var text = node.querySelector('.msg__text');
    if (text) text.hidden = false;
    var button = node.querySelector('[data-edit]');
    if (button) button.hidden = true;
  }

  document.addEventListener('click', function (e) {
    var start = e.target.closest('[data-edit]');
    if (start) {
      var node = start.closest('.msg');
      if (!node || node.querySelector('.msg__edit')) return;
      var text = node.querySelector('.msg__text');

      var form = document.createElement('form');
      form.className = 'msg__edit';
      var field = document.createElement('textarea');
      field.rows = 2;
      field.value = text ? text.textContent.trim() : '';
      var save = document.createElement('button');
      save.type = 'submit';
      save.className = 'btn';
      save.textContent = 'Сохранить';
      var cancel = document.createElement('button');
      cancel.type = 'button';
      cancel.className = 'btn btn--ghost';
      cancel.textContent = 'Отмена';
      cancel.addEventListener('click', function () { closeEdit(node); });
      form.appendChild(field);
      form.appendChild(save);
      form.appendChild(cancel);

      form.addEventListener('submit', function (event) {
        event.preventDefault();
        var panel = document.querySelector('[data-chat-panel]');
        var body = new FormData();
        body.append('message', node.dataset.message);
        body.append('text', field.value);
        body.append('csrfmiddlewaretoken', csrf());
        fetch(panel.dataset.editUrl, {
          method: 'POST', body: body, headers: { 'X-Requested-With': 'XMLHttpRequest' }
        })
          .then(function (r) { return r.json(); })
          .then(function (payload) {
            if (!payload.ok) { toast(payload.error, 'error'); return; }
            if (text) text.textContent = payload.message.text;
            var meta = node.querySelector('.msg__meta');
            if (meta && !meta.querySelector('.msg__edited')) {
              var mark = document.createElement('span');
              mark.className = 'muted msg__edited';
              mark.textContent = '· поправлено';
              meta.appendChild(mark);
            }
            closeEdit(node);
          })
          .catch(function () { toast('Не отправилось. Попробуйте ещё раз.', 'error'); });
      });

      if (text) text.hidden = true;
      node.insertBefore(form, node.querySelector('.msg__tools'));
      field.focus();
      return;
    }

    /* Метка «решение». Ставит любая сторона: договорённость — это то,
       о чём договорились оба, и подтвердить её может каждый. */
    var decide = e.target.closest('[data-decide]');
    if (!decide) return;
    var msg = decide.closest('.msg');
    var panel = document.querySelector('[data-chat-panel]');
    if (!msg || !panel || !window.fetch) return;

    var body = new FormData();
    body.append('message', decide.dataset.decide);
    body.append('csrfmiddlewaretoken', csrf());
    decide.disabled = true;

    fetch(panel.dataset.decisionUrl, {
      method: 'POST', body: body, headers: { 'X-Requested-With': 'XMLHttpRequest' }
    })
      .then(function (r) { return r.json(); })
      .then(function (payload) {
        decide.disabled = false;
        if (!payload.ok) { toast(payload.error, 'error'); return; }
        var on = payload.message.decision;
        msg.classList.toggle('msg--decision', on);
        decide.setAttribute('aria-pressed', String(on));
        decide.textContent = on ? '✓ решение' : '✓ это решение';
        paintDecisions(payload.message, on);
        toast(on ? 'Записано в решения.' : 'Метка снята.');
      })
      .catch(function () { decide.disabled = false; });
  });

  // Список решений держим в согласии с лентой: иначе он расходится
  // с ней до первой перезагрузки, а верить нужно обоим.
  function paintDecisions(item, on) {
    var box = document.querySelector('[data-decisions]');
    if (!box) return;
    var list = box.querySelector('.decisions__list');
    var existing = list && list.querySelector('[href="#msg-' + item.id + '"]');

    if (on && !existing && list) {
      var li = document.createElement('li');
      var link = document.createElement('a');
      link.href = '#msg-' + item.id;
      link.textContent = item.text.slice(0, 120);
      var who = document.createElement('span');
      who.className = 'muted';
      who.textContent = item.author + ' · ' + item.at.slice(0, 10);
      li.appendChild(link);
      li.appendChild(who);
      list.appendChild(li);
    }
    if (!on && existing) existing.closest('li').remove();

    var count = list ? list.children.length : 0;
    box.hidden = count === 0;
    if (count) box.open = true;
    var label = box.querySelector('[data-decisions-count]');
    if (label) label.textContent = '(' + count + ')';
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

      var body = new FormData(form);
      body.set('csrfmiddlewaretoken', csrf());  // свежий токен, а не из старой вкладки

      fetch(form.getAttribute('action'), {
        method: 'POST',
        body: body,
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
      })
        .then(function (r) { return r.json(); })
        .then(function (payload) {
          if (button) button.disabled = false;
          if (!payload.ok) {
            if (payload.error) toast(payload.error, 'error');
            return;
          }
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

  /* Обработчики висят на документе, а не на каждой зоне.

     Карточка этапа перерисовывается после каждого действия, и зона
     приезжает новая. Обработчики, повешенные при загрузке страницы,
     остались бы на выброшенном узле — перетаскивание тихо переставало
     бы работать после первого же добавления файла. */

  function showPicked(zone) {
    var input = zone.querySelector('[data-drop-input]');
    var picked = zone.parentElement && zone.parentElement.querySelector('[data-drop-picked]');
    if (!input || !picked) return;
    picked.hidden = !input.files.length;
    picked.textContent = input.files.length ? 'Готово к отправке: ' + names(input.files) : '';
  }

  document.addEventListener('change', function (e) {
    var zone = e.target.closest('[data-drop]');
    if (zone) showPicked(zone);
  });

  ['dragenter', 'dragover'].forEach(function (name) {
    document.addEventListener(name, function (e) {
      var zone = e.target.closest('[data-drop]');
      if (!zone) return;
      e.preventDefault();
      zone.classList.add('is-over');
    });
  });

  document.addEventListener('dragleave', function (e) {
    var zone = e.target.closest('[data-drop]');
    if (zone) zone.classList.remove('is-over');
  });

  document.addEventListener('drop', function (e) {
    var zone = e.target.closest('[data-drop]');
    if (!zone) return;
    e.preventDefault();
    zone.classList.remove('is-over');
    var input = zone.querySelector('[data-drop-input]');
    if (!input || !e.dataTransfer || !e.dataTransfer.files.length) return;
    // Кладём файлы прямо в поле формы: обычная отправка работает так же,
    // как если бы их выбрали кнопкой.
    input.files = e.dataTransfer.files;
    showPicked(zone);
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
  watchEditWindow();
  setInterval(watchEditWindow, 1000);
  armAll();
  window.addEventListener('resize', paintRail);
})();
