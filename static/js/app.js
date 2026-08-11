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
