(function() {
    // Allow re-initialization on SPA navigation (kill old timers first)
    if (window._fdgDetailPoll) clearInterval(window._fdgDetailPoll);
    if (window._fdgDetailChart) clearInterval(window._fdgDetailChart);
    window._fdgDetailInit = false;

    const STATUS_LABELS = {
        ok: 'DoT Aktiv', cooldown: 'Cooldown', outage: 'Ausfall!',
        reconnected: 'Neu verbunden', reconnect_failed: 'Reconnect FEHLGESCHLAGEN',
        transient_error: 'FRITZ!Box nicht erreichbar', unknown: 'Warte...'
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

    var RANGE_TO_HOURS = {'1h':1,'6h':6,'1d':24,'2d':48,'3d':72,'7d':168,'30d':720,'90d':2160};
    var currentRange = '1d';

    function updateDetail(data) {
        const st = data.status || 'unknown';
        const color = STATUS_COLORS[st] || 'var(--info)';

        const statusText = document.getElementById('fdg-tab-status-text');
        if (statusText) {
            statusText.textContent = STATUS_LABELS[st] || st;
            statusText.style.color = color;
        }
        const badge = document.getElementById('fdg-tab-badge');
        if (badge) {
            badge.textContent = st.replace(/_/g, ' ');
            badge.className = 'badge ' + (BADGE_CLASSES[st] || 'badge-info');
        }
        const iconDiv = document.getElementById('fdg-tab-status-icon');
        if (iconDiv) {
            iconDiv.className = 'metric-icon ' + (ICON_COLORS[st] || 'blue');
        }

        const detailsEl = document.getElementById('fdg-tab-details');
        if (detailsEl) detailsEl.textContent = data.details || '';

        const ipsEl = document.getElementById('fdg-tab-ips');
        if (ipsEl) {
            if (data.details && data.details.indexOf('DoT:') >= 0) {
                const match = data.details.match(/DoT:\s*(.+)/);
                ipsEl.textContent = match ? match[1] : '–';
            } else if (data.dot_ok === true) {
                ipsEl.textContent = '– (DoT aktiv)';
            } else {
                ipsEl.textContent = '\u2013';
            }
        }

        const checkTime = document.getElementById('fdg-tab-check-time');
        if (checkTime) {
            checkTime.textContent = data.last_check_ts
                ? new Date(data.last_check_ts).toLocaleString()
                : '\u2013';
        }

        if (data.config) {
            const f = document.getElementById('fdg-cfg-fritzbox');
            if (f) f.textContent = data.config.fritzbox_url || '\u2013';
            const p = document.getElementById('fdg-cfg-poll');
            if (p) p.textContent = data.config.poll_interval_s + 's';
            const c = document.getElementById('fdg-cfg-cooldown');
            if (c) c.textContent = data.config.cooldown_s + 's';
            const t = document.getElementById('fdg-cfg-telegram');
            if (t) t.textContent = data.config.telegram_configured ? '\u2705 Konfiguriert' : '\u274c Nicht konfiguriert';
        }
    }

    async function fetchStatus() {
        try {
            const resp = await fetch('/api/fritzdotguard/status', { credentials: 'same-origin' });
            if (!resp.ok) return;
            updateDetail(await resp.json());
        } catch(e) {}
    }

    // --- DoT Status Block Chart (Canvas) ---
    var _fdgCtx = null;
    var _fdgMarkers = [];
    var _fdgTooltipEl = null;

    function _fdgBindTooltip(canvas, top, bottom) {
        if (!_fdgTooltipEl) {
            _fdgTooltipEl = document.createElement('div');
            _fdgTooltipEl.style.cssText = 'position:fixed;z-index:9999;pointer-events:none;'
                + 'background:rgba(17,24,39,0.95);color:#fff;padding:6px 9px;border-radius:6px;'
                + 'font-size:11px;line-height:1.35;max-width:280px;display:none;'
                + 'box-shadow:0 4px 12px rgba(0,0,0,0.4);border:1px solid rgba(255,255,255,0.1);';
            document.body.appendChild(_fdgTooltipEl);
        }
        canvas.onmousemove = function(ev) {
            var r = canvas.getBoundingClientRect();
            var mx = ev.clientX - r.left;
            var hit = null, best = 8;
            for (var i = 0; i < _fdgMarkers.length; i++) {
                var d = Math.abs(_fdgMarkers[i].x - mx);
                if (d < best) { best = d; hit = _fdgMarkers[i]; }
            }
            if (hit) {
                var when = new Date(String(hit.ts).replace(/Z$/, '') + 'Z').toLocaleString();
                _fdgTooltipEl.innerHTML = '<strong>' + hit.label + '</strong><br>' + when
                    + (hit.details ? '<br>' + String(hit.details).replace(/</g, '&lt;') : '');
                _fdgTooltipEl.style.display = 'block';
                _fdgTooltipEl.style.left = (ev.clientX + 12) + 'px';
                _fdgTooltipEl.style.top = (ev.clientY + 12) + 'px';
                canvas.style.cursor = 'pointer';
            } else {
                _fdgTooltipEl.style.display = 'none';
                canvas.style.cursor = 'default';
            }
        };
        canvas.onmouseleave = function() {
            if (_fdgTooltipEl) _fdgTooltipEl.style.display = 'none';
        };
    }

    // Event types worth marking on the timeline (from storage save_status)
    var EVENT_STYLES = {
        outage:           { color: 'rgba(239,68,68,0.95)',  label: 'Ausfall erkannt' },
        reconnect_failed: { color: 'rgba(220,38,38,1)',     label: 'Reconnect fehlgeschlagen' },
        reconnect:        { color: 'rgba(245,158,11,0.95)', label: 'Reconnect' },
        recovery:         { color: 'rgba(34,197,94,0.95)',  label: 'Wiederhergestellt' }
    };

    window.fdgLoadChart = function(range, btn) {
        if (!RANGE_TO_HOURS.hasOwnProperty(range)) range = '1d';
        currentRange = range;
        if (btn) {
            document.querySelectorAll('#fdg-range-tabs .trend-tab').forEach(function(b) { b.classList.remove('active'); });
            btn.classList.add('active');
        } else {
            // Mark the matching tab as active when called without a button (initial/auto-refresh)
            document.querySelectorAll('#fdg-range-tabs .trend-tab').forEach(function(b) {
                b.classList.toggle('active', b.getAttribute('data-range') === range);
            });
        }
        fetch('/api/fritzdotguard/history?hours=' + RANGE_TO_HOURS[range], { credentials: 'same-origin' })
            .then(function(r) { return r.json(); })
            .then(function(data) { renderFdgBlocks(data); })
            .catch(function(){});
    };

    function renderFdgBlocks(data) {
        var container = document.getElementById('fdg-chart-container');
        var emptyEl = document.getElementById('fdg-chart-empty');
        if (!container) return;
        // Wait until the container is actually visible with non-zero dimensions
        // (in SPA the detail view may be in the DOM but hidden → 0×0 canvas)
        var rect = container.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) {
            setTimeout(function() { renderFdgBlocks(data); }, 150);
            return;
        }
        if (!data || !data.timestamps || data.timestamps.length < 2) {
            if (emptyEl) emptyEl.style.display = 'block';
            container.innerHTML = '';
            return;
        }
        if (emptyEl) emptyEl.style.display = 'none';
        container.innerHTML = '<canvas style="width:100%;height:280px;"></canvas>';
        var canvas = container.querySelector('canvas');
        var dpr = window.devicePixelRatio || 1;
        var rect = container.getBoundingClientRect();
        canvas.width = rect.width * dpr;
        canvas.height = 280 * dpr;
        var ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);
        var w = rect.width, h = 280;
        _fdgCtx = ctx;

        var timestamps = data.timestamps;
        var dotOk = data.dot_ok;
        var eventTypes = data.event_types || [];
        var detailsArr = data.details || [];
        var n = timestamps.length;
        var toMs = function(ts) { return new Date(String(ts).replace(/Z$/, '') + 'Z').getTime(); };
        var t0 = toMs(timestamps[0]);
        var tEnd = toMs(timestamps[n-1]);
        if (tEnd <= t0) tEnd = t0 + 3600000;
        var timeToX = function(ts) { return ((toMs(ts) - t0) / (tEnd - t0)) * w; };

        var top = 20, bottom = h - 40, trackH = bottom - top;

        // Background: green tint
        ctx.fillStyle = 'rgba(22,163,74,0.06)';
        ctx.fillRect(0, 0, w, h);

        // Grid lines (4 horizontal)
        ctx.strokeStyle = 'rgba(128,128,128,0.15)';
        ctx.lineWidth = 0.5;
        for (var j = 0; j <= 4; j++) {
            var gy = (h / 4) * j;
            ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(w, gy); ctx.stroke();
        }

        // Draw status blocks: iterate adjacent pairs, fill the gap.
        // Outage segments get a minimum width so brief outages stay visible.
        var MIN_OUTAGE_W = 3;
        for (var i = 0; i < n - 1; i++) {
            var x1 = timeToX(timestamps[i]);
            var x2 = timeToX(timestamps[i+1]);
            var blockW = x2 - x1;
            if (dotOk[i]) {
                if (blockW < 0.5) continue;
                ctx.fillStyle = 'rgba(34,197,94,0.45)';
                ctx.fillRect(x1, top, blockW, trackH);
            } else {
                // Outage: enforce a minimum visible width
                var ow = Math.max(blockW, MIN_OUTAGE_W);
                ctx.fillStyle = 'rgba(239,68,68,0.6)';
                ctx.fillRect(x1, top, ow, trackH);
            }
        }

        // Last sample as a narrow block
        var lastX = timeToX(timestamps[n-1]);
        ctx.fillStyle = dotOk[n-1] ? 'rgba(34,197,94,0.45)' : 'rgba(239,68,68,0.6)';
        ctx.fillRect(lastX - 2, top, 4, trackH);

        // --- Event markers: vertical line + dot for state-change events ---
        _fdgMarkers = [];
        var seenTypes = {};
        for (var m = 0; m < n; m++) {
            var et = eventTypes[m];
            var style = EVENT_STYLES[et];
            if (!style) continue;
            var mx = timeToX(timestamps[m]);
            ctx.strokeStyle = style.color;
            ctx.lineWidth = 1.5;
            ctx.beginPath(); ctx.moveTo(mx, top - 6); ctx.lineTo(mx, bottom + 6); ctx.stroke();
            ctx.fillStyle = style.color;
            ctx.beginPath(); ctx.arc(mx, top - 6, 4, 0, Math.PI * 2); ctx.fill();
            seenTypes[et] = style;
            _fdgMarkers.push({ x: mx, type: et, label: style.label,
                ts: timestamps[m], details: detailsArr[m] || '' });
        }

        // Update the "WAN-Reconnects" card to reflect the selected time range
        // (counts both successful reconnects and failed reconnect attempts)
        var rcCount = 0, rcLastTs = null;
        for (var mm = 0; mm < n; mm++) {
            if (eventTypes[mm] === 'reconnect' || eventTypes[mm] === 'reconnect_failed') {
                rcCount++;
                rcLastTs = timestamps[mm];
            }
        }
        var rcEl = document.getElementById('fdg-tab-reconnect-count');
        if (rcEl) rcEl.textContent = rcCount;
        var rcLastEl = document.getElementById('fdg-tab-last-reconnect');
        if (rcLastEl) {
            rcLastEl.textContent = rcLastTs
                ? 'Letzter: ' + new Date(String(rcLastTs).replace(/Z$/, '') + 'Z').toLocaleString()
                : '\u2013';
        }

        // Update the "Wiederherstellungen" card for the selected time range
        var ryCount = 0, ryLastTs = null;
        for (var ry = 0; ry < n; ry++) {
            if (eventTypes[ry] === 'recovery') {
                ryCount++;
                ryLastTs = timestamps[ry];
            }
        }
        var ryEl = document.getElementById('fdg-tab-recovery-count');
        if (ryEl) ryEl.textContent = ryCount;
        var ryLastEl = document.getElementById('fdg-tab-last-recovery');
        if (ryLastEl) {
            ryLastEl.textContent = ryLastTs
                ? 'Letzte: ' + new Date(String(ryLastTs).replace(/Z$/, '') + 'Z').toLocaleString()
                : '\u2013';
        }

        // Axis labels
        ctx.fillStyle = 'rgba(255,255,255,0.85)';
        ctx.font = '11px -apple-system,BlinkMacSystemFont,sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText('DoT OK', 8, h - 32);
        ctx.fillStyle = 'rgba(239,68,68,0.9)';
        ctx.fillText('OUTAGE', 8, 32);

        // Legend: status blocks + any event types present in this range
        var lx = w - 8;
        ctx.textAlign = 'right';
        ctx.font = '9px -apple-system,BlinkMacSystemFont,sans-serif';
        var legendItems = [
            { color: 'rgba(34,197,94,0.6)', label: 'DoT OK' },
            { color: 'rgba(239,68,68,0.6)', label: 'Ausfall' }
        ];
        Object.keys(seenTypes).forEach(function(k) {
            legendItems.push({ color: seenTypes[k].color, label: seenTypes[k].label });
        });
        for (var li = 0; li < legendItems.length; li++) {
            var it = legendItems[li];
            ctx.fillStyle = 'rgba(255,255,255,0.75)';
            ctx.fillText(it.label, lx, h - 10);
            var tw = ctx.measureText(it.label).width;
            ctx.fillStyle = it.color;
            ctx.fillRect(lx - tw - 16, h - 19, 11, 11);
            lx -= (tw + 26);
        }

        // Time axis ticks
        ctx.fillStyle = 'rgba(255,255,255,0.5)';
        ctx.font = '9px -apple-system,BlinkMacSystemFont,sans-serif';
        ctx.textAlign = 'center';
        var tickCount = Math.min(6, n);
        for (var k = 0; k <= tickCount; k++) {
            var idx = Math.floor(k * (n - 1) / tickCount);
            var tx = timeToX(timestamps[idx]);
            var t = new Date(String(timestamps[idx]).replace(/Z$/, '') + 'Z');
            var label = (RANGE_TO_HOURS[currentRange] >= 168)
                ? String(t.getDate()).padStart(2,'0') + '.' + String(t.getMonth()+1).padStart(2,'0')
                : t.getHours() + ':' + String(t.getMinutes()).padStart(2,'0');
            ctx.fillText(label, tx, h - 2);
        }

        _fdgBindTooltip(canvas, top, bottom);
    }

    function loadInitialChart() {
        // Delay to ensure the container is visible and has non-zero dimensions
        setTimeout(function() { window.fdgLoadChart('1d', null); }, 250);
    }

    function start() {
        if (window._fdgDetailPoll) clearInterval(window._fdgDetailPoll);
        if (window._fdgDetailChart) clearInterval(window._fdgDetailChart);
        fetchStatus();
        loadInitialChart();
        window._fdgDetailPoll = setInterval(fetchStatus, 10000);
        window._fdgDetailChart = setInterval(function() { window.fdgLoadChart(currentRange, null); }, 120000);
    }

    // Watch for detail view appearing (SPA navigation) — only once
    if (document.getElementById('fdg-detail-view')) {
        start();
    } else {
        var _obs = new MutationObserver(function() {
            if (document.getElementById('fdg-detail-view')) {
                _obs.disconnect();
                start();
            }
        });
        _obs.observe(document.body, { childList: true, subtree: true });
    }
})();
