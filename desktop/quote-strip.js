(() => {
  const sayings = [
    '오늘의 작은 정리가 내일의 여유를 만듭니다.',
    '중요한 일은 기억보다 기록에 맡겨두세요.',
    '한꺼번에 끝내려 하기보다, 다음 한 단계부터.',
    '함께 확인한 기준은 더 믿음직한 업무가 됩니다.',
    '잠깐 정리하면 필요한 일이 또렷해집니다.',
    '차분히 살핀 한 번이 여러 번의 수고를 덜어줍니다.',
    '서로의 수고를 알아보는 말도 좋은 업무입니다.',
    '오늘 해낸 만큼, 다음 일도 조금 가벼워집니다.',
  ];
  const intervalMs = 45_000;
  const storageKey = 'gongmudam.header-quote.paused.v1';

  function init(options = {}) {
    const root = options.root || document;
    const doc = options.document || root.ownerDocument || document;
    const quote = root.querySelector('#header-quote-text');
    const nextButton = root.querySelector('#header-quote-next');
    const toggleButton = root.querySelector('#header-quote-toggle');
    if (!quote || !nextButton || !toggleButton) return null;

    const pauseIcon = toggleButton.querySelector('[data-quote-icon="pause"]');
    const playIcon = toggleButton.querySelector('[data-quote-icon="play"]');
    const getStorage = options.getStorage || (() => window.localStorage);
    const setTimer = options.setTimeout || window.setTimeout.bind(window);
    const clearTimer = options.clearTimeout || window.clearTimeout.bind(window);
    let index = Math.max(0, sayings.indexOf(quote.textContent.trim()));
    let paused = false;
    let timer = null;

    try { paused = getStorage()?.getItem(storageKey) === 'true'; } catch { /* Storage may be blocked. */ }

    function cancelTimer() {
      if (timer !== null) clearTimer(timer);
      timer = null;
    }
    function schedule() {
      cancelTimer();
      if (!paused && !doc.hidden) timer = setTimer(advance, intervalMs);
    }
    function updatePauseButton() {
      const label = paused ? '문구 자동 변경 시작' : '문구 자동 변경 멈춤';
      toggleButton.setAttribute('aria-pressed', String(paused));
      toggleButton.setAttribute('aria-label', label);
      toggleButton.title = label;
      if (pauseIcon) {
        if (paused) pauseIcon.setAttribute('hidden', '');
        else pauseIcon.removeAttribute('hidden');
      }
      if (playIcon) {
        if (paused) playIcon.removeAttribute('hidden');
        else playIcon.setAttribute('hidden', '');
      }
    }
    function advance() {
      index = (index + 1) % sayings.length;
      quote.textContent = sayings[index];
      schedule();
    }
    function togglePause() {
      paused = !paused;
      updatePauseButton();
      try { getStorage()?.setItem(storageKey, String(paused)); } catch { /* Storage may be blocked. */ }
      schedule();
    }
    function onVisibilityChange() { schedule(); }

    quote.setAttribute('aria-live', 'off');
    updatePauseButton();
    nextButton.addEventListener('click', advance);
    toggleButton.addEventListener('click', togglePause);
    doc.addEventListener('visibilitychange', onVisibilityChange);
    schedule();

    return {
      advance,
      dispose() {
        cancelTimer();
        nextButton.removeEventListener('click', advance);
        toggleButton.removeEventListener('click', togglePause);
        doc.removeEventListener('visibilitychange', onVisibilityChange);
      },
    };
  }

  window.GongmudamQuoteStrip = Object.freeze({ init, sayings, intervalMs, storageKey });
  if (typeof document !== 'undefined' && document.querySelector('#header-quote-text')) init();
})();
