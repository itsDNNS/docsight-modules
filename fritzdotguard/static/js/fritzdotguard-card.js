(function() {
    // Guard against double-init (SPA view switches re-evaluate the script)
    if (window._fdgCardReady) return;
    window._fdgCardReady = true;

    const STATUS_LABELS = {
        ok: 'DoT Active', cooldown: 'Cooldown', outage: 'Outage!',
        reconnected: 'Reconnected', reconnect_failed: 'Reconnect FAILED',
        transient_error: 'FRITZ!Box unreachable', unknown: 'Waiting...'
    };
    const BADGE_CLASSES = {
        ok: 'badge-success', cooldown: 'badge-info', outage: 'badge-danger',
        reconnected: 'badge-warning', reconnect_failed: 'badge-danger',
        transient_error: 'badge-warning', unknown: 'badge-info'
    };
    const STATUS_COLORS = {
        ok: 'var(--good)', cooldown: 'var(--info)', outage: 'var(--crit)',
        reconnected: 'var(--warn)', reconnect_failed: 'var(--crit)',
        transient_error: 'var(--warn)', unknown: 'var(--info)'
    };
    const ICON_COLORS = {
        ok: 'green', cooldown: 'blue', outage: 'red',
        reconnected: 'amber', reconnect_failed: 'red',
        transient_error: 'amber', unknown: 'blue'
    };

    var _pollTimer = null;

    // --------------- Custom Sparkline (binary DoT data) ---------------
    // Uses its own /api/fritzdotguard/history endpoint because the shared
    // sparklines.js draws line graphs for continuous values – our data
    // is binary (0=outage, 1=ok), better shown as green/red blocks.

    function drawSparkline(data) {
        var el = document.getElementById('fdg-card-sparkline');
        if (!el || !data || !data.timestamps || data.timestamps.length < 2) return;
        el.innerHTML = '';
        var canvas = document.createElement('canvas');
        canvas.style.width = '100%';
        canvas.style.height = '40px';
        el.appendChild(canvas);
        var ctx = canvas.getContext('2d');
        var dpr = window.devicePixelRatio || 1;
        var rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return;
        canvas.width = rect.width * dpr;
        canvas.height = 40 * dpr;
        ctx.scale(dpr, dpr);
        var w = rect.width, h = 40;
        var values = data.dot_ok;
        var n = values.length;
        var stepX = w / (n - 1);
        // Green gradient background
        var grad = ctx.createLinearGradient(0, 0, 0, h);
        grad.addColorStop(0, 'rgba(34,197,94,0.25)');
        grad.addColorStop(1, 'rgba(239,68,68,0.2)');
        ctx.beginPath();
        ctx.moveTo(0, h);
        for (var i = 0; i < n; i++) {
            var x = i * stepX;
            var y = values[i] ? 8 : (h - 8);
            ctx.lineTo(x, y);
        }
        ctx.lineTo(w, h);
        ctx.closePath();
        ctx.fillStyle = grad;
        ctx.fill();
        // Line
        ctx.beginPath();
        for (var i = 0; i < n; i++) {
            var x = i * stepX;
            var y = values[i] ? 8 : (h - 8);
            if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.strokeStyle = 'rgba(34,197,94,0.8)';
        ctx.lineWidth = 2;
        ctx.stroke();
        // Red outage dots
        for (var i = 0; i < n; i++) {
            if (!values[i]) {
                ctx.beginPath();
                ctx.arc(i * stepX, h - 8, 3, 0, Math.PI * 2);
                ctx.fillStyle = 'rgba(239,68,68,0.9)';
                ctx.fill();
            }
        }
    }

    function fetchSparkline() {
        fetch('/api/fritzdotguard/history?hours=6', { credentials: 'same-origin' })
            .then(function(r) { return r.json(); })
            .then(function(data) { drawSparkline(data); })
            .catch(function(){});
    }


    function updateCard(data) {
        const st = data.status || 'unknown';
        const color = STATUS_COLORS[st] || 'var(--info)';

        const statusEl = document.getElementById('fdg-card-status');
        const badgeEl = document.getElementById('fdg-card-badge');
        const detailsEl = document.getElementById('fdg-card-details');
        const reconnectsEl = document.getElementById('fdg-card-reconnects');
        const iconEl = document.getElementById('fdg-card-icon');

        if (statusEl) {
            statusEl.textContent = STATUS_LABELS[st] || st;
            statusEl.style.color = color;
        }
        if (badgeEl) {
            badgeEl.textContent = st.replace(/_/g, ' ');
            badgeEl.className = 'badge ' + (BADGE_CLASSES[st] || 'badge-info');
        }
        if (detailsEl) {
            detailsEl.textContent = data.details || '\u2013';
        }
        if (iconEl) {
            iconEl.className = 'metric-icon ' + (ICON_COLORS[st] || 'blue');
        }
        if (reconnectsEl) {
            let extra = '';
            if (data.reconnect_count > 0) {
                const ts = data.last_reconnect_ts ? new Date(data.last_reconnect_ts).toLocaleString() : '?';
                extra = 'Reconnects: ' + data.reconnect_count + ' (last: ' + ts + ')';
            }
            if (data.last_check_ts) {
                const checkTs = new Date(data.last_check_ts).toLocaleString();
                if (extra) extra += ' \u00b7 ';
                extra += 'Checked: ' + checkTs;
            }
            reconnectsEl.textContent = extra || '';
        }
    }

    async function fetchStatus() {
        try {
            const resp = await fetch('/api/fritzdotguard/status', { credentials: 'same-origin' });
            if (!resp.ok) return;
            updateCard(await resp.json());
        } catch(e) {
            // silently ignore transient fetch errors
        }
    }

    var _sparkTimer = null;

    function start() {
        if (_pollTimer) clearInterval(_pollTimer);
        if (_sparkTimer) clearInterval(_sparkTimer);
        fetchStatus();
        fetchSparkline();
        _pollTimer = setInterval(fetchStatus, 10000);
        _sparkTimer = setInterval(fetchSparkline, 60000);
    }

    // Bootstrap: if card already present, start; otherwise watch for it
    if (document.getElementById('fritzdotguard-card')) {
        start();
    }
    // Keep watching for card re-insertion (SPA navigation / innerHTML refresh).
    // Don't disconnect — the observer needs to catch re-insertion indefinitely.
    new MutationObserver(function() {
        if (document.getElementById('fritzdotguard-card') && !window._fdgCardRunning) {
            window._fdgCardRunning = true;
            start();
        }
    }).observe(document.body, { childList: true, subtree: true });
})();
