// Auto-reload the page once a running refresh finishes.
(function () {
  const btn = document.querySelector('button[disabled]');
  if (!btn || !btn.textContent.toLowerCase().includes('refresh')) return;

  let attempts = 0;
  const poll = async () => {
    attempts += 1;
    try {
      const r = await fetch('/api/status');
      const j = await r.json();
      if (!j.refreshing) {
        window.location.reload();
        return;
      }
    } catch (e) {
      // ignore, retry
    }
    if (attempts < 240) setTimeout(poll, 3000);
  };
  setTimeout(poll, 3000);
})();
