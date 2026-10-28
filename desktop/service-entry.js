(function () {
  'use strict';

  const serviceIds = new Map([
    ['/index.html', 'chat'],
    ['/travel.html', 'travel'],
    ['/adhoc.html', 'collection'],
    ['/folders.html', 'folders'],
    ['/folders-advanced.html', 'folders'],
    ['/toolbox.html', 'toolbox'],
    ['/change-inbox.html', 'inbox'],
    ['/calendar.html', 'calendar'],
    ['/local-ai.html', 'models'],
  ]);

  function parseSameOrigin(href) {
    if (typeof href !== 'string' || !href || href.startsWith('//')) return null;
    try {
      const base = window.location.origin + '/';
      const url = new URL(href, base);
      if (url.origin !== window.location.origin || (url.protocol !== 'http:' && url.protocol !== 'https:')) return null;
      return url;
    } catch {
      return null;
    }
  }

  function resolveService(href) {
    const url = parseSameOrigin(href);
    if (!url) return null;
    const id = serviceIds.get(url.pathname);
    return id ? { id, href: url.pathname + url.search + url.hash } : null;
  }

  function desktopHref(href) {
    const url = parseSameOrigin(href);
    if (!url || url.pathname === '/desktop/' || url.pathname === '/desktop') return null;
    if (url.pathname === '/start.html' || (url.pathname === '/index.html' && (url.hash === '' || url.hash === '#home'))) {
      return '/desktop/?variant=B';
    }
    const service = resolveService(url.href);
    return service ? '/desktop/?variant=B&open=' + encodeURIComponent(service.href) : null;
  }

  window.GongmudamEntry = { resolveService, desktopHref };

  if (window.parent !== window) return;
  const target = desktopHref(window.location.href);
  if (!target) return;
  document.documentElement.classList.add('gongmudam-entering');
  window.location.replace(target);
})();
