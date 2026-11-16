// PassivMOS Webapp — Frontend

const API_URL = '/api';
let currentCode = '';
let displayCurrency = 'USD';
let eurRate = null;
let lastPortfolio = null;

async function fetchEurRate() {
    try {
        const resp = await fetch('https://api.frankfurter.app/latest?from=USD&to=EUR');
        const data = await resp.json();
        eurRate = data.rates.EUR;
    } catch (_) {
        eurRate = 0.92; // ponytail: fallback if API unreachable
    }
    if (lastPortfolio) updateSummaryEur(lastPortfolio);
}

function fmtEur(usd) {
    if (!eurRate) return '';
    return new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR', minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(usd * eurRate);
}

function updateSummaryEur(portfolio) {
    const pairs = [
        ['totalValueEur',      portfolio.total_value_usd],
        ['dailyEarningsEur',   portfolio.daily_earnings],
        ['monthlyEarningsEur', portfolio.monthly_earnings],
        ['yearlyEarningsEur',  portfolio.yearly_earnings],
    ];
    pairs.forEach(([id, usd]) => {
        const el = document.getElementById(id);
        if (el) el.textContent = fmtEur(usd);
    });
}

function toDisplayCurrency(usdValue) {
    if (displayCurrency === 'EUR' && eurRate) return usdValue * eurRate;
    return usdValue;
}

function toggleCurrency() {
    displayCurrency = displayCurrency === 'USD' ? 'EUR' : 'USD';
    document.getElementById('currencyToggleBtn').textContent = displayCurrency;
    if (lastPortfolio) displayPortfolioResults(lastPortfolio, true);
}

function showElement(id) { document.getElementById(id).classList.remove('hidden'); }
function hideElement(id) { document.getElementById(id).classList.add('hidden'); }

function addTerminalLog(message, type = 'info') {
    const log = document.getElementById('terminalLog');
    if (!log) return;
    const entry = document.createElement('div');
    entry.className = 'terminal-line' + (
        type === 'success' ? ' ok'   :
        type === 'error'   ? ' err'  :
        type === 'found'   ? ' found':
        type === 'warning' ? ' warn' : ''
    );
    const ts = new Date().toLocaleTimeString('en-US', { hour12: false });
    entry.textContent = `[${ts}] ${message}`;
    log.appendChild(entry);
    log.scrollTop = log.scrollHeight;
}

function clearTerminalLog() {
    const log = document.getElementById('terminalLog');
    if (log) log.innerHTML = '';
}

function showNotification(message, type = 'info') {
    addTerminalLog(message, type);
}

function formatCurrency(value) {
    const converted = toDisplayCurrency(value);
    const locale = displayCurrency === 'EUR' ? 'de-DE' : 'en-US';
    return new Intl.NumberFormat(locale, {
        style: 'currency',
        currency: displayCurrency,
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }).format(converted);
}

function formatNumber(value, decimals = 2) {
    return new Intl.NumberFormat('en-US', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
    }).format(value);
}

async function apiRequest(endpoint, method = 'GET', body = null) {
    const options = {
        method,
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
    };
    if (body) options.body = JSON.stringify(body);

    try {
        const response = await fetch(`${API_URL}${endpoint}`, options);
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Request failed');
        return data;
    } catch (error) {
        console.error('API Error:', error);
        throw error;
    }
}

async function login() {
    const input = document.getElementById('codeInput');
    const code = input.value.trim();

    if (!code || code.length < 3) {
        input.classList.add('error');
        return;
    }
    input.classList.remove('error');

    const btn = document.querySelector('#loginScreen .btn');
    btn.disabled = true;
    btn.textContent = 'Checking…';

    try {
        const response = await apiRequest('/register', 'POST', { code });
        currentCode = code;
        document.getElementById('displayCode').textContent = code;

        if (response.addresses && response.addresses.length > 0) {
            document.getElementById('addressesTextarea').value = response.addresses.join('\n');
        }

        hideElement('loginScreen');
        showElement('dashboard');

        // Load cached background-scanned portfolio immediately (no spinner needed)
        try {
            const cached = await apiRequest(`/portfolio/cached?code=${encodeURIComponent(code)}`);
            if (cached.available) {
                addTerminalLog('Loaded cached portfolio — click Calculate for a fresh scan', 'success');
                displayPortfolioResults(cached, true);
                loadAndRenderChart();
            }
        } catch (_) {
            // no cached data yet — user can click Calculate
        }
    } catch (error) {
        console.error('Login failed:', error);
        input.classList.add('error');
        btn.disabled = false;
        btn.textContent = 'Continue';
    }
}

async function logout() {
    try {
        await apiRequest('/logout', 'POST');
    } catch (error) {
        console.warn('Logout request failed:', error);
    }
    currentCode = '';
    document.getElementById('codeInput').value = '';
    document.getElementById('addressesTextarea').value = '';
    hideElement('dashboard');
    showElement('loginScreen');
}

async function saveAddresses() {
    const textarea = document.getElementById('addressesTextarea');
    const addresses = textarea.value
        .split('\n')
        .map(addr => addr.trim())
        .filter(addr => addr.length > 0);

    if (addresses.length === 0) {
        textarea.classList.add('error');
        return;
    }

    try {
        await apiRequest('/addresses/save', 'POST', { code: currentCode, addresses });
        textarea.classList.remove('error');
        textarea.classList.add('ok');
        setTimeout(() => textarea.classList.remove('ok'), 2000);
    } catch (error) {
        console.error('Failed to save:', error);
        textarea.classList.add('error');
    }
}

async function calculatePortfolio() {
    const textarea = document.getElementById('addressesTextarea');
    const addresses = textarea.value
        .split('\n')
        .map(addr => addr.trim())
        .filter(addr => addr.length > 0);

    if (addresses.length === 0) {
        textarea.classList.add('error');
        return;
    }

    await saveAddresses();

    clearTerminalLog();
    hideElement('addressSection');
    showElement('loadingIndicator');

    addTerminalLog('Starting portfolio analysis…', 'info');
    addTerminalLog(`Found ${addresses.length} address(es) to analyze`, 'info');

    try {
        const eventSource = new EventSource(
            `${API_URL}/calculate/stream/${encodeURIComponent(currentCode)}`,
            { withCredentials: true }
        );

        eventSource.addEventListener('progress', e => {
            addTerminalLog(JSON.parse(e.data).message, 'info');
        });
        eventSource.addEventListener('found', e => {
            addTerminalLog(JSON.parse(e.data).message, 'found');
        });
        eventSource.addEventListener('warning', e => {
            addTerminalLog(JSON.parse(e.data).message, 'warning');
        });
        eventSource.addEventListener('error', e => {
            eventSource.close();
            if (!e.data) return;
            addTerminalLog(JSON.parse(e.data).message, 'error');
            setTimeout(() => { hideElement('loadingIndicator'); showElement('addressSection'); }, 2000);
        });
        eventSource.addEventListener('complete', e => {
            const portfolio = JSON.parse(e.data);
            eventSource.close();
            displayPortfolioResults(portfolio);
        });
        eventSource.onerror = () => {
            eventSource.close();
            addTerminalLog('Connection error — please try again', 'error');
            setTimeout(() => { hideElement('loadingIndicator'); showElement('addressSection'); }, 3000);
        };
    } catch (error) {
        addTerminalLog('Error: ' + error.message, 'error');
        setTimeout(() => { hideElement('loadingIndicator'); showElement('addressSection'); }, 3000);
    }
}

function displayPortfolioResults(portfolio, rerender = false) {
    lastPortfolio = portfolio;

    if (!rerender) {
        addTerminalLog(`Total value: $${portfolio.total_value_usd.toFixed(2)}`, 'success');
        addTerminalLog(`Yearly earnings: $${portfolio.yearly_earnings.toFixed(2)}`, 'success');
    }

    // USD always shown as secondary line
    const fmtUsd = v => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v);
    document.getElementById('totalValue').textContent    = fmtUsd(portfolio.total_value_usd);
    document.getElementById('dailyEarnings').textContent = fmtUsd(portfolio.daily_earnings);
    document.getElementById('monthlyEarnings').textContent = fmtUsd(portfolio.monthly_earnings);
    document.getElementById('yearlyEarnings').textContent  = fmtUsd(portfolio.yearly_earnings);
    document.getElementById('lastUpdated').textContent   = new Date(portfolio.last_updated).toLocaleString();
    updateSummaryEur(portfolio);

    renderTokenBreakdown(portfolio.token_breakdown);
    renderWalletDetails(portfolio.wallets);

    if (!rerender) {
        setTimeout(() => {
            hideElement('loadingIndicator');
            showElement('addressSection');
            loadAndRenderChart();
        }, 400);
    }
}

function renderTokenBreakdown(tokens) {
    const tbody = document.getElementById('tokenBreakdown');
    tbody.innerHTML = '';
    for (const [symbol, data] of Object.entries(tokens).sort((a, b) => b[1].total_value_usd - a[1].total_value_usd)) {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td><span class="token-badge">${symbol}</span></td>
            <td class="mono">${formatNumber(data.total_balance, 4)}</td>
            <td class="mono">${data.apr.toFixed(2)}%</td>
            <td class="mono">${formatCurrency(data.total_value_usd)}</td>
        `;
        tbody.appendChild(row);
    }
}

function renderWalletDetails(wallets) {
    const tbody = document.getElementById('walletDetails');
    tbody.innerHTML = '';
    wallets.forEach(wallet => {
        const isConverted  = wallet.original_address && wallet.original_address !== wallet.address;
        const chainDisplay = isConverted ? `${wallet.chain} <span class="muted" style="font-size:10px;">[auto]</span>` : wallet.chain;
        const shortAddr    = wallet.address
            ? wallet.address.substring(0, 12) + '…' + wallet.address.substring(wallet.address.length - 8)
            : wallet.chain;
        const row = document.createElement('tr');
        row.innerHTML = `
            <td class="mono" title="${wallet.address}">${shortAddr}</td>
            <td>${chainDisplay}</td>
            <td class="mono">${formatNumber(wallet.total_balance, 2)} ${wallet.token_symbol}</td>
            <td class="mono">${formatNumber(wallet.delegated_balance, 2)}</td>
            <td class="mono">${formatCurrency(wallet.total_value_usd)}</td>
        `;
        tbody.appendChild(row);
    });
}

async function showStats() {
    hideElement('loginScreen');
    showElement('statsModal');

    try {
        const stats = await apiRequest('/stats', 'GET');
        const tbody = document.getElementById('statsTableBody');
        tbody.innerHTML = '';

        if (!stats.available || stats.tokens.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" class="muted mono" style="padding:20px 14px;color:#C0533E;">No data available</td></tr>';
            return;
        }

        stats.tokens.forEach(token => {
            const priceDisplay   = token.price > 0 ? `$${token.price.toFixed(4)}` : '—';
            const aprDisplay     = token.apr > 0   ? `${token.apr.toFixed(2)}%`   : '—';
            const lastUpdated    = token.last_updated
                ? new Date(token.last_updated).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
                : '—';
            const row = document.createElement('tr');
            row.innerHTML = `
                <td><span class="token-badge">${token.symbol}</span></td>
                <td class="mono">${priceDisplay}</td>
                <td class="mono">${aprDisplay}</td>
                <td class="mono muted" style="font-size:11px;">${lastUpdated}</td>
            `;
            tbody.appendChild(row);
        });
    } catch (error) {
        console.error('Failed to load stats:', error);
        document.getElementById('statsTableBody').innerHTML =
            '<tr><td colspan="4" class="mono" style="padding:20px 14px;color:#C0533E;">Error loading data. Please try again.</td></tr>';
    }
}

function hideStats() {
    hideElement('statsModal');
    // Return to correct screen
    if (currentCode) {
        showElement('dashboard');
    } else {
        showElement('loginScreen');
    }
}

// ─── CHART ───────────────────────────────────────────────────────────────────
let chartResizeObserver = null;
let chartResizeTimer    = null;
let latestChartData     = null;

async function loadAndRenderChart() {
    try {
        const history = await apiRequest(`/coinfolio/history?code=${encodeURIComponent(currentCode)}`);
        if (!history || history.length < 2) return;
        latestChartData = history;
        // show canvas, hide placeholder
        const emptyEl = document.getElementById('chartEmpty');
        const canvasEl = document.getElementById('historyChart');
        if (emptyEl)  emptyEl.style.display  = 'none';
        if (canvasEl) canvasEl.style.display  = 'block';
        requestAnimationFrame(() => drawChart(latestChartData));
    } catch (_) {
        // no history yet — skip
    }
}

function drawChart(rawData) {
    const canvas = document.getElementById('historyChart');
    const wrap   = document.getElementById('chartWrap');
    const data   = rawData
        .filter(d => Number.isFinite(Number(d.ts)) && Number.isFinite(Number(d.total_usd)))
        .map(d => ({ ...d, ts: Number(d.ts), total_usd: Number(d.total_usd) }))
        .sort((a, b) => a.ts - b.ts);
    if (data.length < 2) return;

    const W   = wrap.clientWidth  || 800;
    const H   = wrap.clientHeight || 220;
    const dpr = window.devicePixelRatio || 1;
    canvas.width  = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    canvas.style.width  = `${W}px`;
    canvas.style.height = `${H}px`;

    const PAD = { top: 24, right: 24, bottom: 44, left: 86 };
    const iW  = W - PAD.left - PAD.right;
    const iH  = H - PAD.top  - PAD.bottom;

    const tsMin  = data[0].ts,   tsMax  = data[data.length - 1].ts;
    const valMin = Math.min(...data.map(d => d.total_usd));
    const valMax = Math.max(...data.map(d => d.total_usd));
    const vRange = Math.max((valMax - valMin) * 1.22, Math.max(Math.abs(valMax), 100) * 0.035, 1);
    const yMin   = Math.max(0, (valMax + valMin) / 2 - vRange / 2);
    const yMax   = yMin + vRange;

    const xOf  = ts    => PAD.left + ((ts    - tsMin) / (tsMax - tsMin || 1)) * iW;
    const yOf  = value => PAD.top  + (1 - (value - yMin) / (yMax - yMin))    * iH;
    const ctx  = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const fmt = v => new Intl.NumberFormat('en-US', {
        style: 'currency', currency: 'USD',
        maximumFractionDigits: v >= 1000 ? 0 : 2
    }).format(v);

    // ── theme colours ──
    const BG      = '#F7EDE2';
    const GRID    = 'rgba(40,79,72,0.07)';
    const AXIS    = 'rgba(40,79,72,0.13)';
    const LABEL   = '#9B7F70';
    const LINE    = '#E76F51';
    const DOT     = '#E76F51';
    const DOTLAST = '#E76F51';
    const HOVER   = '#2A9D8F';

    function paint(hoverIdx) {
        ctx.clearRect(0, 0, W, H);
        ctx.fillStyle = BG;
        ctx.fillRect(0, 0, W, H);

        // Y-axis grid + labels
        ctx.textAlign = 'right';
        ctx.font = '11px JetBrains Mono, monospace';
        for (let i = 0; i <= 4; i++) {
            const value = yMin + (i / 4) * (yMax - yMin);
            const y     = yOf(value);
            ctx.strokeStyle = i === 0 ? AXIS : GRID;
            ctx.lineWidth   = 1;
            ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(PAD.left + iW, y); ctx.stroke();
            ctx.fillStyle = LABEL;
            ctx.fillText(fmt(value), PAD.left - 10, y + 4);
        }

        // X-axis labels
        ctx.textAlign = 'center';
        ctx.fillStyle = LABEL;
        const ticks = Math.min(6, data.length);
        for (let i = 0; i < ticks; i++) {
            const d = data[Math.round(i / (ticks - 1) * (data.length - 1))];
            ctx.fillText(
                new Date(d.ts * 1000).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
                xOf(d.ts), PAD.top + iH + 26
            );
        }

        // Fill under line
        ctx.beginPath();
        ctx.moveTo(xOf(data[0].ts), PAD.top + iH);
        data.forEach(d => ctx.lineTo(xOf(d.ts), yOf(d.total_usd)));
        ctx.lineTo(xOf(data.at(-1).ts), PAD.top + iH);
        ctx.closePath();
        const fill = ctx.createLinearGradient(0, PAD.top, 0, PAD.top + iH);
        fill.addColorStop(0, 'rgba(231,111,81,0.18)');
        fill.addColorStop(1, 'rgba(231,111,81,0.01)');
        ctx.fillStyle = fill;
        ctx.fill();

        // Line
        ctx.beginPath();
        data.forEach((d, i) => i ? ctx.lineTo(xOf(d.ts), yOf(d.total_usd)) : ctx.moveTo(xOf(d.ts), yOf(d.total_usd)));
        ctx.strokeStyle = LINE;
        ctx.lineWidth   = 1.5;
        ctx.stroke();

        // Dots
        data.forEach((d, i) => {
            if (data.length > 40 && i !== data.length - 1) return;
            ctx.beginPath();
            ctx.arc(xOf(d.ts), yOf(d.total_usd), i === data.length - 1 ? 4 : 2, 0, Math.PI * 2);
            ctx.fillStyle = i === data.length - 1 ? DOTLAST : DOT;
            ctx.fill();
        });

        // Hover crosshair
        if (hoverIdx !== null) {
            const d = data[hoverIdx], x = xOf(d.ts), y = yOf(d.total_usd);
            ctx.setLineDash([3, 3]);
            ctx.strokeStyle = 'rgba(42,157,143,0.35)';
            ctx.lineWidth   = 1;
            ctx.beginPath(); ctx.moveTo(x, PAD.top); ctx.lineTo(x, PAD.top + iH); ctx.stroke();
            ctx.setLineDash([]);
            ctx.beginPath();
            ctx.arc(x, y, 5, 0, Math.PI * 2);
            ctx.fillStyle   = HOVER;
            ctx.fill();
            ctx.strokeStyle = BG;
            ctx.lineWidth   = 2;
            ctx.stroke();
        }
    }

    paint(null);

    const tip = document.getElementById('chartTip');
    canvas.onmousemove = e => {
        const rect = canvas.getBoundingClientRect();
        const x    = (e.clientX - rect.left) * W / rect.width;
        let idx    = 0;
        data.forEach((d, i) => {
            if (Math.abs(xOf(d.ts) - x) < Math.abs(xOf(data[idx].ts) - x)) idx = i;
        });
        paint(idx);
        const d    = data[idx];
        const date = new Date(d.ts * 1000);
        tip.innerHTML = `
            <div style="font-size:10px;color:#9B7F70;margin-bottom:4px;">
                ${date.toLocaleDateString('en-US', { weekday:'short', month:'short', day:'numeric', year:'numeric' })}
                ${date.toLocaleTimeString('en-US', { hour:'2-digit', minute:'2-digit', hour12:false })}
            </div>
            <div style="font-size:14px;font-weight:600;color:#E76F51;">${fmt(d.total_usd)}</div>
        `;
        tip.style.left    = (e.clientX + 16) + 'px';
        tip.style.top     = (e.clientY - 10) + 'px';
        tip.style.display = 'block';
    };
    canvas.onmouseleave = () => {
        paint(null);
        tip.style.display = 'none';
    };

    if (!chartResizeObserver) {
        chartResizeObserver = new ResizeObserver(() => {
            clearTimeout(chartResizeTimer);
            chartResizeTimer = setTimeout(() => { if (latestChartData) drawChart(latestChartData); }, 100);
        });
        chartResizeObserver.observe(wrap);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('codeInput').focus();
    fetchEurRate();
});
