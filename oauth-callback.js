    // Страница-приёмник OAuth-редиректа GitHub. Сам код обрабатывает
    // background (callback launchWebAuthFlow получает итоговый URL);
    // здесь только сообщаем пользователю, что окно можно закрыть.
    (function () {
      const msg = document.getElementById('msg');
      const params = new URLSearchParams(location.search);
      if (params.get('error')) {
        msg.textContent = 'Ошибка авторизации: ' + params.get('error');
      } else {
        msg.textContent = 'Готово! Это окно можно закрыть.';
      }
    })();