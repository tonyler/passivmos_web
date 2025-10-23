// PassivMOS Webapp - Frontend JavaScript

const API_URL = '/api';
let currentCode = '';

// === UTILITY FUNCTIONS ===

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
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }).format(value);
}

function formatNumber(value, decimals = 2) {
    return new Intl.NumberFormat('en-US', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
    }).format(value);
}

// === API FUNCTIONS ===

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

// === AUTH FUNCTIONS ===

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

function logout() {
    currentCode = '';
    document.getElementById('codeInput').value = '';
    document.getElementById('addressesTextarea').value = '';
    hideElement('dashboard');
    hideElement('portfolioSummary');
    showElement('loginScreen');
}

// === ADDRESS MANAGEMENT ===

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

// === PORTFOLIO CALCULATION ===

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
        const eventSource = new EventSource(`${API_URL}/calculate/stream/${currentCode}`);

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

function displayPortfolioResults(portfolio) {
    // Show summary
    addTerminalLog('---', 'info');
    addTerminalLog(`✅ Total portfolio value: $${portfolio.total_value_usd.toFixed(2)}`, 'success');
    addTerminalLog(`📈 Yearly earnings: $${portfolio.yearly_earnings.toFixed(2)}`, 'success');
    addTerminalLog('📊 Displaying detailed results...', 'info');

    // Update summary boxes
    document.getElementById('totalValue').textContent = formatCurrency(portfolio.total_value_usd);
    document.getElementById('dailyEarnings').textContent = formatCurrency(portfolio.daily_earnings);
    document.getElementById('monthlyEarnings').textContent = formatCurrency(portfolio.monthly_earnings);
    document.getElementById('yearlyEarnings').textContent = formatCurrency(portfolio.yearly_earnings);
    document.getElementById('lastUpdated').textContent = new Date(portfolio.last_updated).toLocaleString();

    // Render token breakdown
    renderTokenBreakdown(portfolio.token_breakdown);

    // Render wallet details
    renderWalletDetails(portfolio.wallets);

    // Show results after a brief delay
    setTimeout(() => {
        hideElement('loadingIndicator');
        showElement('portfolioSummary');
    }, 500);
}

function renderTokenBreakdown(tokens) {
    const tbody = document.getElementById('tokenBreakdown');
    tbody.innerHTML = '';

    for (const [symbol, data] of Object.entries(tokens)) {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td><strong>${symbol}</strong></td>
            <td>${formatNumber(data.total_balance, 2)}</td>
            <td>${data.apr.toFixed(2)}%</td>
            <td>${formatCurrency(data.total_value_usd)}</td>
            <td>${formatCurrency(data.yearly_earnings)}</td>
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

// === STATS DISPLAY ===

async function showStats() {
    hideElement('loginScreen');
    showElement('statsModal');

    try {
        const stats = await apiRequest('/stats', 'GET');

        // Update message and timestamp
        document.getElementById('statsMessage').textContent = stats.message || 'Numia API (Osmosis DEX)';
        document.getElementById('statsLastUpdated').textContent = stats.last_check
            ? new Date(stats.last_check).toLocaleString()
            : '-';

        // Render table
        const tbody = document.getElementById('statsTableBody');
        tbody.innerHTML = '';

        if (!stats.available || stats.tokens.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: #cc0000;">No data available. Please contact @tonyler on Telegram.</td></tr>';
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

// === INITIALIZATION ===

document.addEventListener('DOMContentLoaded', () => {
    console.log('PassivMOS Webapp loaded');
    document.getElementById('codeInput').focus();
});
