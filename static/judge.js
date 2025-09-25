(function () {
  document.addEventListener('DOMContentLoaded', () => {
    const state = window.JUDGE_PAGE_STATE || null;
    const submitBtn = document.getElementById('judge-submit');
    const statusEl = document.getElementById('judge-status');
    const judgeNameInput = document.getElementById('judge-name');
    const sliderWrappers = Array.from(document.querySelectorAll('.judge-slider'));
    const totalsRedEl = document.querySelector('[data-total-red]');
    const totalsWhiteEl = document.querySelector('[data-total-white]');
    const outcomeEl = document.querySelector('[data-outcome]');

    const setStatus = (msg, opts = {}) => {
      if (statusEl) {
        statusEl.textContent = msg || '';
        statusEl.setAttribute('aria-live', 'polite');
        if (opts.error) statusEl.dataset.error = '1'; else delete statusEl.dataset.error;
      }
    };

    if (!state || !state.current || !submitBtn) {
      if (submitBtn) submitBtn.disabled = true;
      setStatus('No active match.');
      return;
    }

    const submitUrl = state.api && state.api.submit;
    if (!submitUrl) {
      if (submitBtn) submitBtn.disabled = true;
      setStatus('Submission endpoint unavailable.');
      return;
    }

    const categories = Array.isArray(state.categories) ? state.categories : [];
    const labelsByKey = Object.create(null);
    categories.forEach(c => { if (c && c.key) labelsByKey[c.key] = c.label || c.key; });

    const redName = (state.current.red_details && state.current.red_details.name) || state.current.red || 'Red';
    const whiteName = (state.current.white_details && state.current.white_details.name) || state.current.white || 'White';

    const clamp = (value, min, max) => {
      const n = Number(value);
      if (!Number.isFinite(n)) return min;
      return Math.min(Math.max(n, min), max);
    };

    const storageKeyFor = (key) => `judge_slider_${key}`;

    // Initialize sliders (one slider = WHITE points; RED = max - WHITE)
    sliderWrappers.forEach(wrapper => {
      const key = wrapper.dataset.key || '';
      const input = wrapper.querySelector('input[type="range"]');
      if (!input) return;

      const maxAttr = Number(wrapper.dataset.max || input.max || 0);
      const max = Number.isNaN(maxAttr) ? 0 : maxAttr;

      // Restore last value from localStorage if present, else use current input
      let initialWhite = 0;
      try {
        const stored = window.localStorage?.getItem(storageKeyFor(key));
        if (stored != null) initialWhite = clamp(Number(stored), 0, max);
      } catch (_) { /* ignore */ }
      if (initialWhite === 0) {
        initialWhite = clamp(Number(input.value || 0), 0, max);
      }

      input.min = '0';
      input.max = String(max);
      input.step = input.step || '1';
      input.value = String(initialWhite);
    });

    const computeScores = () => {
      let totalRed = 0;
      let totalWhite = 0;
      const sliders = {};
      const breakdown = [];

      sliderWrappers.forEach(wrapper => {
        const key = wrapper.dataset.key || '';
        const label = labelsByKey[key] || key || 'Category';
        const input = wrapper.querySelector('input[type="range"]');
        if (!input) return;

        const maxAttr = Number(wrapper.dataset.max || input.max || 0);
        const max = Number.isNaN(maxAttr) ? 0 : maxAttr;

        const whitePoints = clamp(input.value, 0, max);
        const redPoints = clamp(max - whitePoints, 0, max);

        // Persist the white value
        try { window.localStorage?.setItem(storageKeyFor(key), String(whitePoints)); } catch (_) { /* ignore */ }

        // Update displays
        const redDisplay = wrapper.querySelector('[data-red-points]');
        const whiteDisplay = wrapper.querySelector('[data-white-points]');
        if (redDisplay) redDisplay.textContent = String(redPoints);
        if (whiteDisplay) whiteDisplay.textContent = String(whitePoints);

        sliders[key] = redPoints; // backend expects RED per key; change if yours expects white
        totalRed += redPoints;
        totalWhite += whitePoints;

        breakdown.push({ key, label, red: redPoints, white: whitePoints });
      });

      if (totalsRedEl) totalsRedEl.textContent = String(totalRed);
      if (totalsWhiteEl) totalsWhiteEl.textContent = String(totalWhite);

      if (outcomeEl) {
        if (totalRed > totalWhite) {
          outcomeEl.textContent = `${redName} leads ${totalRed}-${totalWhite}`;
        } else if (totalWhite > totalRed) {
          outcomeEl.textContent = `${whiteName} leads ${totalWhite}-${totalRed}`;
        } else {
          outcomeEl.textContent = `Draw ${totalRed}-${totalWhite}`;
        }
      }

      return { totalRed, totalWhite, sliders, breakdown };
    };

    // Recompute on input
    sliderWrappers.forEach(wrapper => {
      const input = wrapper.querySelector('input[type="range"]');
      if (!input) return;
      input.addEventListener('input', computeScores);
    });

    // Judge name persistence
    if (judgeNameInput) {
      const existingValue = judgeNameInput.value && judgeNameInput.value.trim();
      if (!existingValue) {
        try {
          const stored = window.localStorage?.getItem('judge_name_input');
          if (stored && !judgeNameInput.value) judgeNameInput.value = stored;
        } catch (_) { /* ignore */ }
      }
      judgeNameInput.addEventListener('input', () => {
        setStatus('');
        const val = judgeNameInput.value.trim();
        try {
          if (val) window.localStorage?.setItem('judge_name_input', val);
          else window.localStorage?.removeItem('judge_name_input');
        } catch (_) { /* ignore */ }
      });
    }

    // First paint
    computeScores();

    const withTimeout = (ms) => {
      const controller = new AbortController();
      const t = setTimeout(() => controller.abort(), ms);
      return { signal: controller.signal, cancel: () => clearTimeout(t) };
    };

    const lockSubmit = (locked) => {
      if (!submitBtn) return;
      submitBtn.disabled = !!locked;
    };

    const buildConfirmText = ({ totalRed, totalWhite, breakdown }) => {
      const scoreline = `${totalRed}-${totalWhite}`;
      const parts = breakdown.map(p => `${p.label} ${p.red}-${p.white}`).join(', ');
      if (totalRed > totalWhite) return `${redName} wins ${scoreline} (${parts}). Confirm submission?`;
      if (totalWhite > totalRed) return `${whiteName} wins ${scoreline} (${parts}). Confirm submission?`;
      return `Scorecard is a draw at ${scoreline} (${parts}). Confirm submission?`;
    };

    submitBtn?.addEventListener('click', async () => {
      const judgeName = (judgeNameInput?.value || '').trim();
      if (!judgeName) {
        setStatus('Please enter your name before submitting.', { error: true });
        judgeNameInput?.focus();
        return;
      }

      const { totalRed, totalWhite, sliders, breakdown } = computeScores();
      if (!window.confirm(buildConfirmText({ totalRed, totalWhite, breakdown }))) return;

      lockSubmit(true);
      setStatus('Submitting...');

      const { signal, cancel } = withTimeout(15000); // 15s timeout

      try {
        const res = await fetch(submitUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            match_id: state.current.match_id,
            sliders,          // RED points by category
            judge_name: judgeName,
          }),
          signal,
          credentials: 'same-origin',
        });

        const data = await res.json().catch(() => ({}));
        if (!res.ok || (data && data.error)) {
          const msg = (data && data.error) || 'Failed to submit card.';
          throw new Error(msg);
        }

        setStatus('Submitted. Refreshing…');
        window.location.reload();
      } catch (err) {
        setStatus(err?.message || 'Submission failed.', { error: true });
        lockSubmit(false);
      } finally {
        cancel();
      }
    });
  });
})();
