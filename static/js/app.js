/* Общий интерактив: меню, аккордеоны, куки, раскрытие пунктов договора.
   Всё построено так, чтобы при выключенном JS страница осталась рабочей. */

(function () {
  'use strict';

  function csrf() {
    var m = document.cookie.match(/(^|;\s*)csrftoken=([^;]+)/);
    return m ? m[2] : '';
  }

  // --- Тема ---------------------------------------------------------------
  // Три состояния, а не два: «как в системе» — это тоже выбор, и сбрасывать
  // его насильно нельзя. Кнопка переключает светлую и тёмную; пока человек
  // её не трогал, работает системная настройка.
  var themeBtn = document.querySelector('[data-theme-toggle]');
  if (themeBtn) {
    var root = document.documentElement;

    function currentTheme() {
      var explicit = root.getAttribute('data-theme');
      if (explicit) return explicit;
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }

    function paintButton() {
      themeBtn.dataset.state = currentTheme();
      themeBtn.setAttribute(
        'aria-label',
        currentTheme() === 'dark' ? 'Включить светлую тему' : 'Включить тёмную тему'
      );
    }

    themeBtn.addEventListener('click', function () {
      var next = currentTheme() === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      try { localStorage.setItem('theme', next); } catch (e) { /* приватный режим */ }
      paintButton();
    });

    // Пока выбор не сделан, следуем за системой — в том числе если она
    // переключилась прямо сейчас.
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function () {
      if (!root.getAttribute('data-theme')) paintButton();
    });

    paintButton();
  }

  // --- Появление секций при прокрутке -------------------------------------
  // Только если человек не просил убрать анимации. И только как украшение:
  // без JS и при reduce-motion всё видно сразу, ничего не прячется навсегда.
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var revealables = document.querySelectorAll('[data-reveal]');
  if (revealables.length && window.IntersectionObserver && !reduce) {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-visible');
        observer.unobserve(entry.target);
      });
    }, { rootMargin: '0px 0px -12% 0px' });

    revealables.forEach(function (el) {
      el.classList.add('will-reveal');
      observer.observe(el);
    });
  }

  // --- Меню ---------------------------------------------------------------
  var toggle = document.querySelector('[data-menu-toggle]');
  var nav = document.getElementById('nav');
  if (toggle && nav) {
    toggle.addEventListener('click', function () {
      var open = nav.classList.toggle('is-open');
      toggle.setAttribute('aria-expanded', String(open));
    });
    nav.addEventListener('click', function (e) {
      if (e.target.tagName === 'A') {
        nav.classList.remove('is-open');
        toggle.setAttribute('aria-expanded', 'false');
      }
    });
  }

  // --- Аккордеоны ---------------------------------------------------------
  document.querySelectorAll('.accordion__head').forEach(function (head) {
    var item = head.closest('.accordion__item');
    var body = item && item.querySelector('.accordion__body');
    if (!body) return;
    body.hidden = !item.classList.contains('is-open');
    head.setAttribute('aria-expanded', String(!body.hidden));
    head.addEventListener('click', function () {
      var open = item.classList.toggle('is-open');
      body.hidden = !open;
      head.setAttribute('aria-expanded', String(open));
    });
  });

  // --- Расшифровки пунктов договора ---------------------------------------
  document.querySelectorAll('.clause__toggle').forEach(function (btn) {
    var target = document.getElementById(btn.dataset.target);
    if (!target) return;
    btn.addEventListener('click', function () {
      target.hidden = !target.hidden;
      btn.textContent = target.hidden ? 'Что это значит' : 'Свернуть';
    });
  });

  // --- Просмотр картинок ---------------------------------------------------
  // Один просмотрщик на весь сайт: и мозаика объекта, и переписка в кабинете
  // открывают кадр одинаково. Фото открывается поверх страницы, а не новой
  // вкладкой: посмотреть и вернуться должно быть одним движением.
  //
  // Без JavaScript ссылка остаётся ссылкой на файл — кадр всё равно
  // откроется, просто отдельной страницей.

  function lightbox(links, index) {
    var box = document.createElement('div');
    var many = links.length > 1;
    box.className = 'lightbox';
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-modal', 'true');
    box.innerHTML =
      '<button class="lightbox__close" type="button" aria-label="Закрыть">×</button>' +
      (many ? '<button class="lightbox__nav lightbox__nav--prev" type="button" aria-label="Предыдущий кадр">‹</button>' : '') +
      (many ? '<button class="lightbox__nav lightbox__nav--next" type="button" aria-label="Следующий кадр">›</button>' : '') +
      '<figure class="lightbox__figure"><img alt=""><figcaption></figcaption>' +
      (many ? '<span class="lightbox__count"></span>' : '') +
      '</figure>';

    var img = box.querySelector('img');
    var caption = box.querySelector('figcaption');
    var count = box.querySelector('.lightbox__count');

    function show(i) {
      index = (i + links.length) % links.length;
      var link = links[index];
      var text = link.dataset.lightbox || '';
      img.src = link.getAttribute('href');
      img.alt = text;
      caption.textContent = text;
      box.setAttribute('aria-label', text || 'Просмотр изображения');
      if (count) count.textContent = (index + 1) + ' из ' + links.length;
    }

    function close() {
      box.classList.remove('is-open');
      document.removeEventListener('keydown', onKey);
      setTimeout(function () { box.remove(); }, reduce ? 0 : 180);
    }

    function onKey(e) {
      if (e.key === 'Escape') close();
      if (many && e.key === 'ArrowRight') show(index + 1);
      if (many && e.key === 'ArrowLeft') show(index - 1);
    }

    box.addEventListener('click', function (e) {
      if (e.target.closest('.lightbox__nav--next')) return show(index + 1);
      if (e.target.closest('.lightbox__nav--prev')) return show(index - 1);
      // Клик мимо картинки — тоже закрытие: так ведёт себя любой просмотрщик.
      if (e.target === box || e.target.closest('.lightbox__close')) close();
    });
    document.addEventListener('keydown', onKey);

    show(index);
    document.body.appendChild(box);
    requestAnimationFrame(function () { box.classList.add('is-open'); });
  }

  document.addEventListener('click', function (e) {
    var link = e.target.closest('[data-lightbox]');
    if (!link) return;
    e.preventDefault();
    // Листаем в пределах одной галереи: кадры объекта — это набор,
    // а картинка из переписки — сама по себе. Набор помечен именем,
    // потому что обложка и мозаика лежат в разных секциях страницы.
    var name = link.dataset.gallery;
    var links = name
      ? Array.prototype.slice.call(
          document.querySelectorAll('[data-lightbox][data-gallery="' + name + '"]')
        )
      : [link];
    lightbox(links, Math.max(links.indexOf(link), 0));
  });

  // --- Торшер на рисунке ---------------------------------------------------
  // Нажатие включает свет: загорается абажур, комната теплеет, и на свет
  // выходит кот. Состояние держится в aria-pressed — оттуда его берут
  // и стили, и скринридер, так что второго источника правды нет.
  //
  // Свет сам гаснет через полминуты. Не ради экономии, а ради второго
  // раза: погасшая лампа снова приглашает нажать, а горящая навсегда
  // через минуту становится просто фоном.
  var stage = document.querySelector('[data-art]');
  if (stage) {
    var offTimer = null;
    // Скрипт есть — значит, нажатие работает, и кнопке место в обходе
    // клавиатурой.
    stage.removeAttribute('tabindex');

    stage.addEventListener('click', function () {
      var lit = stage.getAttribute('aria-pressed') === 'true';
      stage.setAttribute('aria-pressed', String(!lit));
      stage.setAttribute('aria-label', lit ? 'Включить торшер на рисунке' : 'Погасить торшер');

      clearTimeout(offTimer);
      if (!lit) {
        offTimer = setTimeout(function () {
          stage.setAttribute('aria-pressed', 'false');
          stage.setAttribute('aria-label', 'Включить торшер на рисунке');
        }, 30000);
      }
    });
  }

  // --- Куки ---------------------------------------------------------------
  // Форма и без JS работает обычным POST с редиректом. Здесь только убираем
  // перезагрузку страницы, если скрипты доступны.
  var cookieForm = document.querySelector('[data-cookie-form]');
  if (cookieForm && window.fetch) {
    cookieForm.addEventListener('submit', function (e) {
      var choice = e.submitter && e.submitter.value;
      if (!choice) return;
      e.preventDefault();
      fetch(cookieForm.action, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest' },
        body: new URLSearchParams({ choice: choice })
      }).then(function () {
        var banner = document.querySelector('[data-cookies]');
        if (banner) banner.remove();
      });
    });
  }
})();
