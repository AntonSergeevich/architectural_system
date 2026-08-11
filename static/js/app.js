/* Общий интерактив: меню, аккордеоны, куки, раскрытие пунктов договора.
   Всё построено так, чтобы при выключенном JS страница осталась рабочей. */

(function () {
  'use strict';

  function csrf() {
    var m = document.cookie.match(/(^|;\s*)csrftoken=([^;]+)/);
    return m ? m[2] : '';
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
