(function () {
  const DEFAULT_INTERVAL = 5000;

  const normalizeNumber = (value) => {
    const num = Number(value);
    return Number.isFinite(num) ? num : 0;
  };

  const startPoller = (config) => {
    if (!config || !config.stateUrl) return;
    let currentVersion = normalizeNumber(config.version);
    const interval = Math.max(normalizeNumber(config.interval) || DEFAULT_INTERVAL, 1000);
    const onUpdate = typeof config.onUpdate === 'function'
      ? config.onUpdate
      : () => {
          if (config.reload !== false) {
            window.location.reload();
          }
        };

    const poll = async () => {
      try {
        if (document.hidden && config.skipWhenHidden) {
          window.setTimeout(poll, interval);
          return;
        }
        const response = await fetch(config.stateUrl, {
          cache: 'no-store',
          credentials: 'same-origin',
          headers: { 'Accept': 'application/json' },
        });
        if (!response.ok) {
          throw new Error(`Poll failed (${response.status})`);
        }
        const data = await response.json().catch(() => ({}));
        const nextVersion = normalizeNumber(data?.meta?.version);
        if (nextVersion && nextVersion !== currentVersion) {
          const previousVersion = currentVersion;
          currentVersion = nextVersion;
          onUpdate({ data, version: nextVersion, previousVersion });
        }
      } catch (err) {
        console.error('Judging live poll error:', err);
      } finally {
        window.setTimeout(poll, interval);
      }
    };

    window.setTimeout(poll, interval);
  };

  document.addEventListener('DOMContentLoaded', () => {
    const configs = [];
    if (window.JUDGE_PAGE_STATE?.api?.state) {
      configs.push({
        version: normalizeNumber(window.JUDGE_PAGE_STATE?.meta?.version),
        stateUrl: window.JUDGE_PAGE_STATE.api.state,
        reload: true,
        interval: 4000,
        skipWhenHidden: false,
      });
    }
    if (Array.isArray(window.JUDGING_LIVE_CONFIGS)) {
      window.JUDGING_LIVE_CONFIGS.forEach((cfg) => {
        if (cfg && cfg.stateUrl) {
          configs.push({
            version: normalizeNumber(cfg.version),
            stateUrl: cfg.stateUrl,
            reload: cfg.reload !== false,
            interval: normalizeNumber(cfg.interval) || DEFAULT_INTERVAL,
            skipWhenHidden: cfg.skipWhenHidden !== false,
            onUpdate: cfg.onUpdate,
          });
        }
      });
    }
    configs.forEach(startPoller);
  });
})();
