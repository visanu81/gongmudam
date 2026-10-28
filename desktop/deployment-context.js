(() => {
  'use strict';
  let statusPromise;

  function get() {
    if (!statusPromise) {
      statusPromise = window.fetch('/api/gongmudam/status')
        .then((response) => response.ok ? response.json() : null)
        .then((data) => data && data.status === 'ok' && data.desktop_connected === true && typeof data.public_demo === 'boolean'
          ? { known: true, publicDemo: data.public_demo }
          : { known: false, publicDemo: null })
        .catch(() => ({ known: false, publicDemo: null }));
    }
    return statusPromise;
  }

  function apply(environment) {
    const notice = document.querySelector('.prototype-notice');
    const mode = document.querySelector('.mode-label');
    if (!notice) return;
    const title = notice.children[0];
    const description = notice.children[1];
    if (!environment.known) {
      if (title) title.textContent = '공무담 업무 공간';
      if (description) description.textContent = '서버 연결을 확인할 수 없습니다. 업무 환경을 확인해 주세요.';
      if (mode) mode.textContent = '연결 오류';
    } else if (environment.publicDemo) {
      if (title) title.textContent = '공무담 공개 시연';
      if (description) description.textContent = '모든 방문자가 같은 공개 시연을 봅니다. 실제 개인정보나 업무 자료를 입력하지 마세요.';
      if (mode) mode.textContent = '공개 시연';
    } else {
      if (title) title.textContent = '내 PC 업무 공간';
      if (description) description.textContent = '업무와 등록 자료는 이 PC에 저장됩니다.';
      if (mode) mode.textContent = '내 PC';
    }
  }

  function update() { return get().then((environment) => { apply(environment); return environment; }); }
  window.GongmudamEnvironment = { get, update };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', update, { once: true });
  else update();
})();
