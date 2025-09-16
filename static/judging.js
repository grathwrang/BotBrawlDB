document.addEventListener('DOMContentLoaded', function() {
    // State management
    let currentStep = 1;
    let scores = {
        aggr: { red: null, white: null },
        ctrl: { red: null, white: null },
        dmg: { red: null, white: null }
    };

    // Poll the overlay endpoint for current match
    function updateCurrentMatch() {
        fetch('/overlay')
            .then(response => response.json())
            .then(data => {
                if (data.status === 'empty') {
                    document.getElementById('nowStatus').textContent = 'No matches scheduled';
                    document.getElementById('nowWC').textContent = '—';
                    document.getElementById('nowRedName').textContent = '—';
                    document.getElementById('nowWhiteName').textContent = '—';
                    document.getElementById('nowRedMeta').textContent = '';
                    document.getElementById('nowWhiteMeta').textContent = '';
                    return;
                }

                // Update the "Now" panel
                document.getElementById('nowWC').textContent = data.weight_class || '—';
                document.getElementById('nowRedName').textContent = data.red.name || '—';
                document.getElementById('nowWhiteName').textContent = data.white.name || '—';
                document.getElementById('nowRedMeta').textContent = 
                    `${data.red.driver} • ${data.red.team} • ${data.red.elo} ELO`;
                document.getElementById('nowWhiteMeta').textContent = 
                    `${data.white.driver} • ${data.white.team} • ${data.white.elo} ELO`;
                document.getElementById('nowStatus').textContent = 'Ready to judge';

                // Populate hidden form fields
                document.getElementById('wcInput').value = data.weight_class || '';
                document.getElementById('redInput').value = data.red.name || '';
                document.getElementById('whiteInput').value = data.white.name || '';
            })
            .catch(error => {
                console.error('Error fetching overlay data:', error);
                document.getElementById('nowStatus').textContent = 'Error loading match data';
            });
    }

    // Show specific slide
    function showSlide(step) {
        const slides = document.querySelectorAll('.slide');
        slides.forEach(slide => {
            slide.style.display = slide.dataset.step == step ? 'block' : 'none';
        });
        currentStep = step;
    }

    // Update score display for a category
    function updateScoreDisplay(category, redScore, whiteScore) {
        const redEl = document.getElementById(category + 'Red');
        const whiteEl = document.getElementById(category + 'White');
        if (redEl) redEl.textContent = redScore !== null ? redScore : '–';
        if (whiteEl) whiteEl.textContent = whiteScore !== null ? whiteScore : '–';
    }

    // Update the summary slide
    function updateSummary() {
        let redTotal = 0, whiteTotal = 0;
        
        // Calculate totals
        Object.keys(scores).forEach(cat => {
            if (scores[cat].red !== null) redTotal += scores[cat].red;
            if (scores[cat].white !== null) whiteTotal += scores[cat].white;
        });

        // Update total displays
        document.getElementById('redTotal').textContent = redTotal;
        document.getElementById('whiteTotal').textContent = whiteTotal;

        // Update summary breakdown
        document.getElementById('summaryAggrRed').textContent = scores.aggr.red !== null ? scores.aggr.red : '–';
        document.getElementById('summaryAggrWhite').textContent = scores.aggr.white !== null ? scores.aggr.white : '–';
        document.getElementById('summaryCtrlRed').textContent = scores.ctrl.red !== null ? scores.ctrl.red : '–';
        document.getElementById('summaryCtrlWhite').textContent = scores.ctrl.white !== null ? scores.ctrl.white : '–';
        document.getElementById('summaryDmgRed').textContent = scores.dmg.red !== null ? scores.dmg.red : '–';
        document.getElementById('summaryDmgWhite').textContent = scores.dmg.white !== null ? scores.dmg.white : '–';

        // Determine winner
        let winner = '—';
        let result = '';
        if (redTotal > whiteTotal) {
            winner = 'Red Wins JD';
            result = 'Red wins JD';
        } else if (whiteTotal > redTotal) {
            winner = 'White Wins JD';
            result = 'White wins JD';
        } else if (redTotal === whiteTotal && redTotal > 0) {
            winner = 'Draw';
            result = 'Draw';
        }

        document.getElementById('winner').textContent = winner;
        document.getElementById('resultInput').value = result;

        // Update hidden fields for category breakdown
        document.getElementById('jd_aggr_r').value = scores.aggr.red || 0;
        document.getElementById('jd_aggr_w').value = scores.aggr.white || 0;
        document.getElementById('jd_ctrl_r').value = scores.ctrl.red || 0;
        document.getElementById('jd_ctrl_w').value = scores.ctrl.white || 0;
        document.getElementById('jd_dmg_r').value = scores.dmg.red || 0;
        document.getElementById('jd_dmg_w').value = scores.dmg.white || 0;
    }

    // Check if current step can advance
    function canAdvance(step) {
        switch(step) {
            case 1: // Aggression
                return scores.aggr.red !== null && scores.aggr.white !== null;
            case 2: // Control  
                return scores.ctrl.red !== null && scores.ctrl.white !== null;
            case 3: // Damage
                return scores.dmg.red !== null && scores.dmg.white !== null;
            default:
                return true;
        }
    }

    // Set up event handlers
    function setupEventHandlers() {
        // Score buttons
        document.querySelectorAll('.chip').forEach(button => {
            button.addEventListener('click', function() {
                const category = this.dataset.cat;
                const redScore = parseInt(this.dataset.r);
                const whiteScore = parseInt(this.dataset.w);

                // Update scores
                scores[category].red = redScore;
                scores[category].white = whiteScore;

                // Visual feedback - remove active class from all buttons in this category
                document.querySelectorAll(`[data-cat="${category}"]`).forEach(btn => {
                    btn.classList.remove('active');
                });
                this.classList.add('active');

                // Update display
                updateScoreDisplay(category, redScore, whiteScore);
            });
        });

        // Next buttons
        document.querySelectorAll('.next').forEach(button => {
            button.addEventListener('click', function() {
                if (canAdvance(currentStep)) {
                    showSlide(currentStep + 1);
                    if (currentStep === 4) {
                        updateSummary();
                    }
                } else {
                    alert('Please select a score for this category before proceeding.');
                }
            });
        });

        // Previous buttons
        document.querySelectorAll('.prev').forEach(button => {
            button.addEventListener('click', function() {
                if (currentStep > 1) {
                    showSlide(currentStep - 1);
                }
            });
        });

        // Form submission
        document.getElementById('judgingForm').addEventListener('submit', function(e) {
            const redName = document.getElementById('redInput').value;
            const whiteName = document.getElementById('whiteInput').value;
            const result = document.getElementById('resultInput').value;

            if (!redName || !whiteName || !result) {
                e.preventDefault();
                alert('Match data is incomplete. Please ensure a match is loaded and scores are complete.');
                return;
            }

            // Form will submit normally to /submit_match
        });
    }

    // Add CSS for active buttons
    function addActiveButtonStyles() {
        const style = document.createElement('style');
        style.textContent = `
            .chip.active {
                background: #e53935 !important;
                color: white !important;
                border-color: #c62828 !important;
            }
        `;
        document.head.appendChild(style);
    }

    // Initialize
    updateCurrentMatch();
    setupEventHandlers();
    addActiveButtonStyles();
    showSlide(1);

    // Poll for updates every 5 seconds
    setInterval(updateCurrentMatch, 5000);
});