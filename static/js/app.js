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

  // Высота шапки — в переменную: под ней прилипают оглавления страниц,
  // а шапка на узком экране и при крупном шрифте бывает разной высоты.
  var header = document.querySelector('.header');
  function headerHeight() {
    if (header) document.documentElement.style.setProperty('--header-h', header.offsetHeight + 'px');
  }
  headerHeight();
  window.addEventListener('resize', headerHeight);
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
      // Соседние кадры подгружаем заранее: листают быстро, и пустой
      // кадр на полсекунды выглядит как поломка.
      if (many) {
        [index + 1, index - 1].forEach(function (n) {
          var next = links[(n + links.length) % links.length];
          (new Image()).src = next.getAttribute('href');
        });
      }
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

    // --- Свайпы ------------------------------------------------------------
    // На телефоне кадры листают пальцем, а не целятся в стрелки по краям:
    // влево-вправо — соседний кадр, вниз — закрыть, как в галерее телефона.
    // Кадр едет за пальцем, поэтому жест виден ещё до того, как сработал.
    //
    // Слушаем touch, а не pointer: два пальца — это увеличение, и его мы
    // браузеру оставляем. Pointer-события пришлось бы глушить целиком
    // через touch-action, и увеличить кадр стало бы нельзя.
    var figure = box.querySelector('.lightbox__figure');
    var touch = null;

    function setDrag(x, y) {
      figure.style.transform = 'translate(' + x + 'px,' + y + 'px)';
      var fade = Math.min(Math.abs(y) / 400, 0.6);
      box.style.backgroundColor = 'rgba(12, 10, 8,' + (0.88 - fade) + ')';
    }

    function settle() {
      figure.style.transition = reduce ? '' : 'transform .22s ease';
      box.style.transition = 'background-color .22s ease';
      setDrag(0, 0);
      box.style.backgroundColor = '';
      setTimeout(function () { figure.style.transition = ''; }, 240);
    }

    function slide(step) {
      if (reduce) { show(index + step); return; }
      var out = step > 0 ? -window.innerWidth : window.innerWidth;
      figure.style.transition = 'transform .18s ease-in, opacity .18s';
      figure.style.transform = 'translateX(' + out + 'px)';
      figure.style.opacity = '0';
      setTimeout(function () {
        show(index + step);
        figure.style.transition = 'none';
        figure.style.transform = 'translateX(' + (-out / 3) + 'px)';
        requestAnimationFrame(function () {
          figure.style.transition = 'transform .22s ease-out, opacity .22s';
          figure.style.transform = '';
          figure.style.opacity = '';
        });
      }, 170);
    }

    box.addEventListener('touchstart', function (e) {
      if (e.touches.length !== 1) { touch = null; settle(); return; }
      var t = e.touches[0];
      touch = { x: t.clientX, y: t.clientY, dx: 0, dy: 0, axis: null, at: Date.now() };
      figure.style.transition = 'none';
    }, { passive: true });

    box.addEventListener('touchmove', function (e) {
      if (!touch || e.touches.length !== 1) return;
      var t = e.touches[0];
      touch.dx = t.clientX - touch.x;
      touch.dy = t.clientY - touch.y;
      // Направление решается один раз, по первым десяти пикселям:
      // иначе диагональный жест дёргает кадр в обе стороны.
      if (!touch.axis && Math.abs(touch.dx) + Math.abs(touch.dy) > 10) {
        touch.axis = Math.abs(touch.dx) > Math.abs(touch.dy) ? 'x' : 'y';
      }
      if (!touch.axis) return;
      e.preventDefault();
      if (touch.axis === 'x') setDrag(many ? touch.dx : touch.dx / 4, 0);
      else setDrag(0, Math.max(touch.dy, touch.dy / 4));
    }, { passive: false });

    box.addEventListener('touchend', function () {
      if (!touch || !touch.axis) { touch = null; return; }
      var fast = Date.now() - touch.at < 250;
      var gone = touch;
      touch = null;
      if (gone.axis === 'x' && many && (Math.abs(gone.dx) > 70 || (fast && Math.abs(gone.dx) > 30))) {
        slide(gone.dx < 0 ? 1 : -1);
      } else if (gone.axis === 'y' && (gone.dy > 110 || (fast && gone.dy > 50))) {
        close();
      } else {
        settle();
      }
    });

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

  // --- Кнопка расчёта на телефоне -------------------------------------------
  // Видна, пока на экране нет ни расчёта первого экрана, ни подвала,
  // и только после того, как человек начал листать.
  var fab = document.querySelector('[data-fab]');
  if (fab && 'IntersectionObserver' in window) {
    var blockers = Array.prototype.slice.call(document.querySelectorAll('[data-quick], .footer, .cookies'));
    var inView = new Set();
    // Баннер cookie после ответа удаляется со страницы, а наблюдатель
    // об удалении не сообщает: считаем только тех, кто ещё на месте.
    function refreshFab() {
      var covered = Array.prototype.some.call(Array.from(inView), function (el) { return el.isConnected; });
      fab.hidden = covered || window.scrollY < 300;
    }
    var fabObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) inView.add(en.target); else inView.delete(en.target);
      });
      refreshFab();
    });
    blockers.forEach(function (el) { fabObserver.observe(el); });
    window.addEventListener('scroll', refreshFab, { passive: true });
  }

  // --- Этапы услуги: по одному, как окна ----------------------------------
  // Лента листается сама (scroll-snap) — пальцем, тачпадом, стрелками.
  // Здесь то, чего CSS не умеет: кружки «1 — 2 — 3», «Понятно, дальше»
  // без прыжка страницы и высота ленты по текущему этапу, чтобы короткий
  // этап не оставлял под собой пустоту длинного. Работает и на странице
  // услуги, и в окне поверх других страниц.
  function initStages(box, onDone) {
    var track = box.querySelector('[data-stage-track]');
    var cards = Array.prototype.slice.call(track.children);
    var dots = box.querySelectorAll('.stepper [data-stage-go]');
    var sheet = box.closest('dialog');
    var current = -1;

    function fit() {
      var card = cards[current];
      if (card) track.style.height = card.offsetHeight + 'px';
    }
    function mark(index) {
      if (index === current) return fit();
      current = index;
      dots.forEach(function (dot, i) {
        dot.classList.toggle('is-active', i === index);
        dot.classList.toggle('is-done', i < index);
        if (i === index) dot.setAttribute('aria-current', 'step'); else dot.removeAttribute('aria-current');
      });
      fit();
    }
    function go(index, smooth, keepPage) {
      var card = cards[Math.max(0, Math.min(cards.length - 1, index))];
      if (!card) return;
      track.scrollTo({ left: card.offsetLeft - track.offsetLeft, behavior: smooth && !reduce ? 'smooth' : 'auto' });
      mark(cards.indexOf(card));
      if (keepPage) return;
      // Нажали «дальше» внизу длинного этапа — показываем начало следующего
      if (sheet) { sheet.scrollTo({ top: 0, behavior: reduce ? 'auto' : 'smooth' }); return; }
      var top = box.getBoundingClientRect().top - (header ? header.offsetHeight : 0) - 16;
      if (top < 0) window.scrollBy({ top: top, behavior: reduce ? 'auto' : 'smooth' });
    }

    box.addEventListener('click', function (e) {
      var done = e.target.closest('[data-stage-done]');
      if (done && onDone) { e.preventDefault(); onDone(); return; }
      var link = e.target.closest('[data-stage-go]');
      if (!link) return;
      e.preventDefault();
      go(Number(link.dataset.stageGo), true);
      if (!sheet && history.replaceState) history.replaceState(null, '', link.getAttribute('href'));
    });

    var timer;
    track.addEventListener('scroll', function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        var left = track.scrollLeft, best = 0, bestDist = Infinity;
        cards.forEach(function (card, i) {
          var dist = Math.abs(card.offsetLeft - track.offsetLeft - left);
          if (dist < bestDist) { bestDist = dist; best = i; }
        });
        mark(best);
      }, 80);
    }, { passive: true });

    track.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowRight') { e.preventDefault(); go(current + 1, true, true); }
      if (e.key === 'ArrowLeft') { e.preventDefault(); go(current - 1, true, true); }
    });

    // Раскрыли пункт — этап стал выше
    track.addEventListener('toggle', fit, true);
    window.addEventListener('resize', function () { go(current, false, true); });

    var start = sheet ? 0 : cards.findIndex(function (c) { return '#' + c.id === location.hash; });
    mark(start > 0 ? start : 0);
    if (start > 0) track.scrollLeft = cards[start].offsetLeft - track.offsetLeft;
    return { fit: fit };
  }

  document.querySelectorAll('[data-stages]').forEach(function (box) { initStages(box); });

  // Окно с этапами поверх страницы услуг, конструктора и КП.
  // Ссылка остаётся обычной ссылкой: без <dialog>, с Ctrl/Cmd или при
  // ошибке сети человек просто попадает на страницу этапов.
  var sheetCache = {};
  document.addEventListener('click', function (e) {
    var link = e.target.closest('a[data-stages-popup]');
    if (!link || e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || e.button > 0) return;
    if (typeof HTMLDialogElement !== 'function') return;
    e.preventDefault();
    e.stopPropagation();
    var url = link.href;
    var html = sheetCache[url];
    (html ? Promise.resolve(html) : fetch(url, { credentials: 'same-origin' }).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.text();
    })).then(function (text) {
      sheetCache[url] = text;
      var doc = new DOMParser().parseFromString(text, 'text/html');
      var stages = doc.querySelector('[data-stages]');
      if (!stages) throw new Error('no stages');
      openSheet(stages, url, link);
    }).catch(function () { window.location.href = url; });
  });

  function openSheet(stages, url, opener) {
    var sheet = document.createElement('dialog');
    sheet.className = 'sheet';
    sheet.setAttribute('aria-labelledby', 'sheet-title');
    var inner = document.createElement('div');
    inner.className = 'sheet__inner';
    var head = document.createElement('div');
    head.className = 'sheet__head';
    var title = document.createElement('h2');
    title.className = 'sheet__title';
    title.id = 'sheet-title';
    title.textContent = stages.dataset.title || '';
    var close = document.createElement('button');
    close.type = 'button';
    close.className = 'sheet__close';
    close.setAttribute('aria-label', 'Закрыть');
    close.textContent = '×';
    head.appendChild(title);
    head.appendChild(close);
    inner.appendChild(head);
    // id из страницы этапов здесь не нужны: якоря ведут на её адрес
    stages.querySelectorAll('[id]').forEach(function (el) { el.removeAttribute('id'); });
    stages.querySelectorAll('a[href^="#"]').forEach(function (a) { a.setAttribute('href', url + a.getAttribute('href')); });
    inner.appendChild(document.importNode(stages, true));
    sheet.appendChild(inner);
    document.body.appendChild(sheet);

    function done() { sheet.close(); }
    close.addEventListener('click', done);
    // Нажатие мимо окна — закрыть
    sheet.addEventListener('click', function (e) { if (e.target === sheet) done(); });
    sheet.addEventListener('close', function () {
      sheet.remove();
      if (opener && opener.focus) opener.focus({ preventScroll: true });
    });
    sheet.showModal();
    var api = initStages(sheet.querySelector('[data-stages]'), done);
    requestAnimationFrame(api.fit);
  }
})();
