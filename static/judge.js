(function() {
  document.addEventListener('DOMContentLoaded', () => {
    const state = window.JUDGE_PAGE_STATE || null;
    const submitBtn = document.getElementById('judge-submit');
    const statusEl = document.getElementById('judge-status');
    const sliderWrappers = Array.from(document.querySelectorAll('.judge-slider'));
    const totalsRedEl = document.querySelector('[data-total-red]');
    const totalsWhiteEl = document.querySelector('[data-total-white]');
    const outcomeEl = document.querySelector('[data-outcome]');

    if (!state || !state.current || !submitBtn) {
      if (submitBtn) {
        submitBtn.disabled = true;
      }
      if (statusEl) {
        statusEl.textContent = 'No active match.';
      }
      return;
    }

    const submitUrl = state.api && state.api.submit;
    if (!submitUrl) {
      submitBtn.disabled = true;
      if (statusEl) {
        statusEl.textContent = 'Submission endpoint unavailable.';
      }
      return;
    }

    const categories = state.categories || [];
    const labelsByKey = {};
    categories.forEach(cat => { labelsByKey[cat.key] = cat.label; });
    const redName = (state.current.red_details && state.current.red_details.name) || state.current.red || 'Red';
    const whiteName = (state.current.white_details && state.current.white_details.name) || state.current.white || 'White';

    const clamp = (value, min, max) => {
      if (!Number.isFinite(value)) {
        return min;
      }
      return Math.min(Math.max(value, min), max);
    };

    sliderWrappers.forEach(wrapper => {
      const input = wrapper.querySelector('input[type="range"]');
      if (!input) return;
      const maxAttr = Number(wrapper.dataset.max || input.max || 0);
      const max = Number.isNaN(maxAttr) ? 0 : maxAttr;
      const raw = Number(input.value || 0);
      const redPoints = clamp(Number.isNaN(raw) ? 0 : raw, 0, max);
      const whiteValue = clamp(max - redPoints, 0, max);
      input.value = String(whiteValue);
    });

    const computeScores = () => {
      let totalRed = 0;
      let totalWhite = 0;
      const sliders = {};
      const breakdown = [];
      sliderWrappers.forEach(wrapper => {
        const key = wrapper.dataset.key;
        const input = wrapper.querySelector('input[type="range"]');
        if (!input) return;
        const maxAttr = Number(wrapper.dataset.max || input.max || 0);
        const maxValue = Number.isNaN(maxAttr) ? 0 : maxAttr;
        const rawWhite = Number(input.value || 0);
        const whitePoints = clamp(Number.isNaN(rawWhite) ? 0 : rawWhite, 0, maxValue);
        const redPoints = clamp(maxValue - whitePoints, 0, maxValue);
        input.value = String(whitePoints);
        const redDisplay = wrapper.querySelector('[data-red-points]');
        const whiteDisplay = wrapper.querySelector('[data-white-points]');
        if (redDisplay) redDisplay.textContent = String(redPoints);
        if (whiteDisplay) whiteDisplay.textContent = String(whitePoints);
        sliders[key] = redPoints;
        totalRed += redPoints;
        totalWhite += whitePoints;
        breakdown.push({
          key,
          label: labelsByKey[key] || key,
          red: redPoints,
          white: whitePoints,
        });
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

    sliderWrappers.forEach(wrapper => {
      const input = wrapper.querySelector('input[type="range"]');
      if (!input) return;
      input.addEventListener('input', () => {
        computeScores();
      });
    });

    computeScores();

    submitBtn.addEventListener('click', () => {
      const { totalRed, totalWhite, sliders, breakdown } = computeScores();
      const scoreline = `${totalRed}-${totalWhite}`;
      const breakdownText = breakdown.map(part => `${part.label} ${part.red}-${part.white}`).join(', ');
      let confirmText;
      if (totalRed > totalWhite) {
        confirmText = `${redName} wins with ${scoreline} (${breakdownText}). Confirm submission?`;
      } else if (totalWhite > totalRed) {
        confirmText = `${whiteName} wins with ${scoreline} (${breakdownText}). Confirm submission?`;
      } else {
        confirmText = `Scorecard is a draw at ${scoreline} (${breakdownText}). Confirm submission?`;
      }
      if (!window.confirm(confirmText)) {
        return;
      }
      submitBtn.disabled = true;
      if (statusEl) {
        statusEl.textContent = 'Submitting...';
      }
      fetch(submitUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          match_id: state.current.match_id,
          sliders,
        }),
      })
        .then(response => response.json().then(data => ({ ok: response.ok, data })))
        .then(({ ok, data }) => {
          if (!ok || (data && data.error)) {
            const message = (data && data.error) || 'Failed to submit card.';
            throw new Error(message);
          }
          window.location.reload();
        })
        .catch(err => {
          if (statusEl) {
            statusEl.textContent = err.message || 'Submission failed.';
          }
          submitBtn.disabled = false;
        });
    });
  });
})();
