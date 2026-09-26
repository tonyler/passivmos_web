// PassivMOS Webapp - Frontend JavaScript

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
        ['totalValueEur',    portfolio.total_value_usd],
        ['dailyEarningsEur', portfolio.daily_earnings],
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
    document.getElementById('currencyToggleBtn').textContent =
        displayCurrency === 'USD' ? '[ Switch to EUR ]' : '[ Switch to USD ]';
    if (lastPortfolio) displayPortfolioResults(lastPortfolio, true);
}

function showElement(id) {
    document.getElementById(id).classList.remove('hidden');
}

function hideElement(id) {
    document.getElementById(id).classList.add('hidden');
}

function addTerminalLog(message, type = 'info') {
    const terminalLog = document.getElementById('terminalLog');
    if (!terminalLog) return;

    const entry = document.createElement('div');
    entry.className = 'terminal-line';

    // Simple prefix based on type
    let prefix = '>';
    switch(type) {
        case 'success': prefix = '[OK]'; break;
        case 'error': prefix = '[ERR]'; break;
        case 'warning': prefix = '[WARN]'; break;
        case 'found': prefix = '[FOUND]'; break;
        case 'skip': prefix = '[SKIP]'; break;
    }

    const timestamp = new Date().toLocaleTimeString('en-US', { hour12: false });
    entry.textContent = `[${timestamp}] ${prefix} ${message}`;

    terminalLog.appendChild(entry);

    // Auto-scroll to bottom
    terminalLog.scrollTop = terminalLog.scrollHeight;
}

function clearTerminalLog() {
    const terminalLog = document.getElementById('terminalLog');
    if (terminalLog) {
        terminalLog.innerHTML = '';
    }
}

function showNotification(message, type = 'info') {
    // No popups - use terminal logs instead
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
        headers: {
            'Content-Type': 'application/json',
        }
    };

    if (body) {
        options.body = JSON.stringify(body);
    }

    try {
        const response = await fetch(`${API_URL}${endpoint}`, options);
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || 'Request failed');
        }

        return data;
    } catch (error) {
        console.error('API Error:', error);
        throw error;
    }
}

async function login() {
    const code = document.getElementById('codeInput').value.trim();

    if (!code || code.length < 3) {
        // Show error inline
        document.getElementById('codeInput').style.borderColor = 'red';
        return;
    }

    try {
        const response = await apiRequest('/register', 'POST', { code });

        currentCode = code;
        document.getElementById('displayCode').textContent = code;

        // Load addresses
        if (response.addresses && response.addresses.length > 0) {
            document.getElementById('addressesTextarea').value = response.addresses.join('\n');
        }

        // Show dashboard
        hideElement('loginScreen');
        showElement('dashboard');

    } catch (error) {
        console.error('Login failed:', error);
        document.getElementById('codeInput').style.borderColor = 'red';
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
    hideElement('portfolioSummary');
    showElement('loginScreen');
}

async function saveAddresses() {
    const textarea = document.getElementById('addressesTextarea');
    const addresses = textarea.value
        .split('\n')
        .map(addr => addr.trim())
        .filter(addr => addr.length > 0);

    if (addresses.length === 0) {
        textarea.style.borderColor = 'red';
        return;
    }

    try {
        const response = await apiRequest('/addresses/save', 'POST', {
            code: currentCode,
            addresses: addresses
        });

        // Show success briefly with border color
        textarea.style.borderColor = 'green';
        setTimeout(() => {
            textarea.style.borderColor = '#333';
        }, 2000);

    } catch (error) {
        console.error('Failed to save:', error);
        textarea.style.borderColor = 'red';
    }
}

async function calculatePortfolio() {
    const textarea = document.getElementById('addressesTextarea');
    const addresses = textarea.value
        .split('\n')
        .map(addr => addr.trim())
        .filter(addr => addr.length > 0);

    if (addresses.length === 0) {
        textarea.style.borderColor = 'red';
        return;
    }

    // First save addresses
    await saveAddresses();

    // Show loading and clear previous logs
    hideElement('portfolioSummary');
    clearTerminalLog();
    showElement('loadingIndicator');

    // Add initial log
    addTerminalLog('🚀 Starting portfolio analysis...', 'info');
    addTerminalLog(`Found ${addresses.length} address(es) to analyze`, 'info');

    try {
        // Use EventSource for real-time progress updates
        const eventSource = new EventSource(`${API_URL}/calculate/stream/${encodeURIComponent(currentCode)}`);

        let portfolio = null;

        eventSource.addEventListener('progress', (event) => {
            const data = JSON.parse(event.data);
            addTerminalLog(data.message, 'info');
        });

        eventSource.addEventListener('found', (event) => {
            const data = JSON.parse(event.data);
            addTerminalLog(data.message, 'found');
        });

        eventSource.addEventListener('warning', (event) => {
            const data = JSON.parse(event.data);
            addTerminalLog(data.message, 'warning');
        });

        eventSource.addEventListener('error', (event) => {
            const data = JSON.parse(event.data);
            addTerminalLog(data.message, 'error');
            eventSource.close();
        });

        eventSource.addEventListener('complete', (event) => {
            portfolio = JSON.parse(event.data);
            eventSource.close();

            // Display results
            displayPortfolioResults(portfolio);
        });

        eventSource.onerror = (error) => {
            eventSource.close();
            addTerminalLog('❌ Connection error - please try again', 'error');
            setTimeout(() => hideElement('loadingIndicator'), 3000);
        };

    } catch (error) {
        addTerminalLog('❌ Error: ' + error.message, 'error');
        setTimeout(() => hideElement('loadingIndicator'), 3000);
    }
}

function displayPortfolioResults(portfolio, rerender = false) {
    lastPortfolio = portfolio;

    if (!rerender) {
        addTerminalLog('---', 'info');
        addTerminalLog(`✅ Total portfolio value: $${portfolio.total_value_usd.toFixed(2)}`, 'success');
        addTerminalLog(`📈 Yearly earnings: $${portfolio.yearly_earnings.toFixed(2)}`, 'success');
        addTerminalLog('📊 Displaying detailed results...', 'info');
    }

    // Update summary boxes
    document.getElementById('totalValue').textContent = formatCurrency(portfolio.total_value_usd);
    document.getElementById('dailyEarnings').textContent = formatCurrency(portfolio.daily_earnings);
    document.getElementById('monthlyEarnings').textContent = formatCurrency(portfolio.monthly_earnings);
    document.getElementById('yearlyEarnings').textContent = formatCurrency(portfolio.yearly_earnings);
    document.getElementById('lastUpdated').textContent = new Date(portfolio.last_updated).toLocaleString();
    updateSummaryEur(portfolio);

    // Render token breakdown
    renderTokenBreakdown(portfolio.token_breakdown);

    // Render wallet details
    renderWalletDetails(portfolio.wallets);

    if (!rerender) {
        // Show results after a brief delay, then load chart
        setTimeout(() => {
            hideElement('loadingIndicator');
            showElement('portfolioSummary');
            loadAndRenderChart();
        }, 500);
    }
}

function renderTokenBreakdown(tokens) {
    const tbody = document.getElementById('tokenBreakdown');
    tbody.innerHTML = '';

    for (const [symbol, data] of Object.entries(tokens)) {
        const yearly = data.yearly_earnings;
        const monthly = yearly / 12;
        const daily = yearly / 365;
        const row = document.createElement('tr');
        row.innerHTML = `
            <td><strong>${symbol}</strong></td>
            <td>${formatNumber(data.total_balance, 2)}</td>
            <td>${data.apr.toFixed(2)}%</td>
            <td>${formatCurrency(data.total_value_usd)}</td>
            <td>${formatCurrency(daily)}</td>
            <td>${formatCurrency(monthly)}</td>
            <td>${formatCurrency(yearly)}</td>
        `;
        tbody.appendChild(row);
    }
}

function renderWalletDetails(wallets) {
    const tbody = document.getElementById('walletDetails');
    tbody.innerHTML = '';

    wallets.forEach(wallet => {
        const row = document.createElement('tr');

        // Check if this was converted
        const isConverted = wallet.original_address && wallet.original_address !== wallet.address;
        const chainDisplay = isConverted ? `${wallet.chain} [auto]` : wallet.chain;

        // Shorten address
        const shortAddr = wallet.address.substring(0, 12) + '...' + wallet.address.substring(wallet.address.length - 8);

        row.innerHTML = `
            <td title="${wallet.address}">${shortAddr}</td>
            <td>${chainDisplay}</td>
            <td>${formatNumber(wallet.total_balance, 2)} ${wallet.token_symbol}</td>
            <td>${formatNumber(wallet.delegated_balance, 2)}</td>
            <td>${formatCurrency(wallet.total_value_usd)}</td>
        `;
        tbody.appendChild(row);
    });
}

async function showStats() {
    hideElement('loginScreen');
    showElement('statsModal');

    try {
        const stats = await apiRequest('/stats', 'GET');

        // Render table
        const tbody = document.getElementById('statsTableBody');
        tbody.innerHTML = '';

        if (!stats.available || stats.tokens.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: #cc0000;">No data available</td></tr>';
            return;
        }

        stats.tokens.forEach(token => {
            const row = document.createElement('tr');

            // Format price
            const priceDisplay = token.price > 0
                ? `$${token.price.toFixed(4)}`
                : 'N/A';

            // Format APR
            const aprDisplay = token.apr > 0
                ? `${token.apr.toFixed(2)}%`
                : 'N/A';

            // Format last updated
            const lastUpdated = token.last_updated
                ? new Date(token.last_updated).toLocaleString('en-US', {
                    month: 'short',
                    day: 'numeric',
                    hour: '2-digit',
                    minute: '2-digit'
                })
                : '-';

            row.innerHTML = `
                <td><strong>${token.symbol}</strong></td>
                <td>${priceDisplay}</td>
                <td>${aprDisplay}</td>
                <td style="font-size: 11px;">${lastUpdated}</td>
            `;

            tbody.appendChild(row);
        });

    } catch (error) {
        console.error('Failed to load stats:', error);
        document.getElementById('statsTableBody').innerHTML =
            '<tr><td colspan="4" style="text-align: center; color: #cc0000;">Error loading data. Please try again or contact @tonyler.</td></tr>';
    }
}

function hideStats() {
    hideElement('statsModal');
}

function openChartWindow() {
    document.getElementById('chartSection').style.display = '';
    if (latestChartData) requestAnimationFrame(() => drawChart(latestChartData));
}

function closeChartWindow() {
    document.getElementById('chartSection').style.display = 'none';
}

function initChartDrag() {
    const titlebar = document.getElementById('chartTitlebar');
    const win = document.getElementById('chartSection');

    titlebar.style.cursor = 'move';

    titlebar.addEventListener('pointerdown', e => {
        if (e.target.closest('.win95-btn')) return;
        e.preventDefault();
        const rect = win.getBoundingClientRect();
        // Drop transform so left/top are the sole position
        win.style.transform = 'none';
        win.style.left = rect.left + 'px';
        win.style.top = rect.top + 'px';
        const ox = e.clientX - rect.left;
        const oy = e.clientY - rect.top;
        titlebar.setPointerCapture(e.pointerId);

        function onMove(ev) {
            win.style.left = (ev.clientX - ox) + 'px';
            win.style.top  = (ev.clientY - oy) + 'px';
        }
        function onUp() {
            titlebar.removeEventListener('pointermove', onMove);
            titlebar.removeEventListener('pointerup', onUp);
        }
        titlebar.addEventListener('pointermove', onMove);
        titlebar.addEventListener('pointerup', onUp);
    });
}

async function loadAndRenderChart() {
    try {
        const history = await apiRequest(`/coinfolio/history?code=${encodeURIComponent(currentCode)}`);
        if (!history || history.length < 2) return;
        latestChartData = history;
        document.getElementById('chartBtnSection').style.display = '';
        // Auto-open the window
        openChartWindow();
    } catch (_) {
        // no history yet — skip
    }
}

let chartResizeObserver = null;
let chartResizeTimer = null;
let latestChartData = null;

function drawChart(rawData) {
    const canvas = document.getElementById('historyChart');
    const wrap = document.getElementById('chartWrap');
    const data = rawData.filter(d => Number.isFinite(Number(d.ts)) && Number.isFinite(Number(d.total_usd)))
        .map(d => ({ ...d, ts: Number(d.ts), total_usd: Number(d.total_usd) })).sort((a, b) => a.ts - b.ts);
    if (data.length < 2) return;

    const W = wrap.clientWidth || 700;
    const H = Math.max(310, Math.min(430, Math.round(W * 0.43)));
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr); canvas.style.height = `${H}px`;
    const PAD = { top: 28, right: 26, bottom: 48, left: 88 }, iW = W - PAD.left - PAD.right, iH = H - PAD.top - PAD.bottom;
    const tsMin = data[0].ts, tsMax = data[data.length - 1].ts;
    const valMin = Math.min(...data.map(d => d.total_usd)), valMax = Math.max(...data.map(d => d.total_usd));
    const visualRange = Math.max((valMax - valMin) * 1.22, Math.max(Math.abs(valMax), 100) * .035, 1);
    const yMin = Math.max(0, (valMax + valMin) / 2 - visualRange / 2), yMax = yMin + visualRange;
    const xOf = ts => PAD.left + ((ts - tsMin) / (tsMax - tsMin || 1)) * iW;
    const yOf = value => PAD.top + (1 - (value - yMin) / (yMax - yMin)) * iH;
    const ctx = canvas.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const currency = value => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: value >= 1000 ? 0 : 2 }).format(value);
    const change = data.at(-1).total_usd - data[0].total_usd;
    document.getElementById('chartRange').textContent = `${data.length} snapshots  ·  ${change >= 0 ? '+' : ''}${currency(change)} (${(data[0].total_usd ? change / data[0].total_usd * 100 : 0).toFixed(2)}%)`;

    function paint(hoverIdx) {
        ctx.clearRect(0, 0, W, H);
        ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, W, H);
        ctx.textAlign = 'right'; ctx.font = '11px Courier New'; ctx.fillStyle = '#666';
        for (let i = 0; i <= 5; i++) { const value = yMin + i / 5 * (yMax - yMin), y = yOf(value); ctx.strokeStyle = i === 0 ? '#333' : 'rgba(0,0,0,.08)'; ctx.lineWidth = i === 0 ? 1 : 1; ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(PAD.left + iW, y); ctx.stroke(); ctx.fillText(currency(value), PAD.left - 10, y + 4); }
        ctx.textAlign = 'center'; ctx.fillStyle = '#666';
        for (let i = 0, ticks = Math.min(6, data.length); i < ticks; i++) { const d = data[Math.round(i / (ticks - 1) * (data.length - 1))]; ctx.fillText(new Date(d.ts * 1000).toLocaleDateString('en-US', {month:'short', day:'numeric'}), xOf(d.ts), PAD.top + iH + 28); }
        ctx.beginPath(); ctx.moveTo(xOf(data[0].ts), PAD.top + iH); data.forEach(d => ctx.lineTo(xOf(d.ts), yOf(d.total_usd))); ctx.lineTo(xOf(data.at(-1).ts), PAD.top + iH); ctx.closePath();
        const fill = ctx.createLinearGradient(0, PAD.top, 0, PAD.top + iH); fill.addColorStop(0, 'rgba(0,0,0,.07)'); fill.addColorStop(1, 'rgba(0,0,0,.01)'); ctx.fillStyle = fill; ctx.fill();
        ctx.beginPath(); data.forEach((d,i) => i ? ctx.lineTo(xOf(d.ts), yOf(d.total_usd)) : ctx.moveTo(xOf(d.ts), yOf(d.total_usd))); ctx.strokeStyle = '#333'; ctx.lineWidth = 2; ctx.stroke();
        data.forEach((d,i) => { if (data.length <= 40 || i === data.length - 1) { ctx.beginPath(); ctx.arc(xOf(d.ts), yOf(d.total_usd), i === data.length - 1 ? 4.5 : 2, 0, Math.PI * 2); ctx.fillStyle = i === data.length - 1 ? '#333' : '#666'; ctx.fill(); } });
        if (hoverIdx !== null) { const d = data[hoverIdx], x = xOf(d.ts), y = yOf(d.total_usd); ctx.setLineDash([4,3]); ctx.strokeStyle = '#999'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x,PAD.top); ctx.lineTo(x,PAD.top+iH); ctx.stroke(); ctx.setLineDash([]); ctx.beginPath(); ctx.arc(x,y,5,0,Math.PI*2); ctx.fillStyle='#333'; ctx.fill(); ctx.strokeStyle='#fff'; ctx.lineWidth=2; ctx.stroke(); }
    }
    paint(null);
    const tip = document.getElementById('chartTip');
    canvas.onmousemove = e => { const rect = canvas.getBoundingClientRect(), x = (e.clientX - rect.left) * W / rect.width; let idx = 0; data.forEach((d,i) => { if (Math.abs(xOf(d.ts)-x) < Math.abs(xOf(data[idx].ts)-x)) idx=i; }); paint(idx); const d=data[idx], date=new Date(d.ts*1000); tip.innerHTML=`<div style="color:#666;margin-bottom:3px;">${date.toLocaleDateString('en-US',{weekday:'short',month:'short',day:'numeric',year:'numeric'})} ${date.toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false})}</div><div style="color:#333;font-weight:bold;font-size:13px;">${currency(d.total_usd)}</div>`; tip.style.left=(e.clientX+16)+'px'; tip.style.top=(e.clientY-10)+'px'; tip.style.display='block'; };
    canvas.onmouseleave = () => { paint(null); tip.style.display = 'none'; };
    if (!chartResizeObserver) { chartResizeObserver = new ResizeObserver(() => { clearTimeout(chartResizeTimer); chartResizeTimer = setTimeout(() => drawChart(latestChartData), 100); }); chartResizeObserver.observe(wrap); }
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('codeInput').focus();
    initChartDrag();
    fetchEurRate();
});
