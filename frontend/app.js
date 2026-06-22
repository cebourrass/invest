// API base URL configuration (empty for relative paths since frontend is served by FastAPI)
const API_URL = "";

// Global State
let accounts = [];
let holdings = [];
let portfolioSummary = null;
let portfolioHistory = [];
let currentPeriod = "1m";
let deposits = [];
let depositHistory = [];

// Chart instances
let historyChart = null;
let accountAllocationChart = null;
let categoryAllocationChart = null;
let confirmAction = null;

// DOM Elements
const panes = document.querySelectorAll(".tab-pane");
const navBtns = document.querySelectorAll(".nav-btn");
const currentDateSpan = document.getElementById("current-date");
const refreshBtn = document.getElementById("refresh-btn");
const refreshIcon = document.getElementById("refresh-icon");

// --- UTILS ---
function formatCurrency(val) {
    if (val === undefined || val === null) val = 0;
    return new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' }).format(val);
}

function formatPercent(val) {
    if (val === undefined || val === null) val = 0;
    const sign = val >= 0 ? '+' : '';
    return `${sign}${val.toFixed(2)}%`;
}

function calculateAnnualizedReturn(gainPct, creationDateStr) {
    if (!creationDateStr) return null;
    const creationDate = new Date(creationDateStr);
    const today = new Date();
    // Normalize to dates only to ignore hours/minutes/seconds
    creationDate.setHours(0,0,0,0);
    today.setHours(0,0,0,0);
    
    const diffTime = today - creationDate;
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
    
    // Ignore if creation date is in the future
    if (diffDays <= 0) return null;
    
    // Annualized return (CAGR) formula:
    // CAGR = (1 + R)^(365 / diffDays) - 1
    // If diffDays < 30, display "-" to avoid astronomical percentages for new accounts
    if (diffDays < 30) return null;
    
    const R = gainPct / 100;
    if (R <= -1) return -100;
    
    const annualizedR = Math.pow(1 + R, 365 / diffDays) - 1;
    return annualizedR * 100;
}

function getAccountBadgeClass(type) {
    switch (type.toLowerCase()) {
        case 'pea': return 'pea';
        case 'per': return 'per';
        case 'assurance vie': return 'assurance-vie';
        case 'compte-titres': return 'compte-titres';
        case 'crypto wallet': return 'crypto-wallet';
        default: return 'autre';
    }
}

function getCategoryBadgeClass(category) {
    switch (category.toLowerCase()) {
        case 'etf': return 'etf';
        case 'opcvm': return 'opcvm';
        case 'actions': return 'actions';
        case 'immobilier': return 'immobilier';
        case 'fonds euros': return 'fonds-euros';
        case 'crypto': return 'crypto';
        case 'cash': return 'cash';
        default: return 'autre';
    }
}

// --- INIT & NAVIGATION ---
document.addEventListener("DOMContentLoaded", () => {
    // Set Current Date
    const today = new Date();
    currentDateSpan.textContent = today.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' });

    // Initialize Lucide Icons
    lucide.createIcons();

    // Tab Switching Navigation
    navBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            const targetTab = btn.getAttribute("data-tab");
            
            navBtns.forEach(b => b.classList.remove("active"));
            panes.forEach(p => p.classList.remove("active"));

            btn.classList.add("active");
            document.getElementById(`pane-${targetTab}`).classList.add("active");
            
            // Re-render layout specific things if needed (e.g. redraw charts)
            if (targetTab === 'dashboard') {
                updateCharts();
            } else if (targetTab === 'settings') {
                fetchSettings();
            } else if (targetTab === 'deposits') {
                fetchDepositsData();
            }
        });
    });

    // Refresh Price Button
    refreshBtn.addEventListener("click", handleRefreshPrices);

    // Period Selectors for History Chart
    const periodBtns = document.querySelectorAll(".period-btn");
    periodBtns.forEach(btn => {
        btn.addEventListener("click", async () => {
            periodBtns.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            const period = btn.getAttribute("data-period");
            await fetchHistory(period);
        });
    });

    // Filter holdings by account
    const filterSelect = document.getElementById("filter-holding-account");
    if (filterSelect) {
        filterSelect.addEventListener("change", () => {
            renderHoldingsTable();
        });
    }

    // Initial load
    initApp();
});

async function initApp() {
    await fetchAllData();
    await fetchSettings();
    setupModals();
    setupSettingsForm();
    setupDepositForm();
    setupMaintenance();
}

async function fetchHistory(period) {
    currentPeriod = period;
    try {
        const response = await fetch(`${API_URL}/api/portfolio/history?period=${period}`);
        if (response.ok) {
            portfolioHistory = await response.json();
            updateCharts();
        }
    } catch (err) {
        console.error("Erreur lors de la récupération de l'historique:", err);
    }
}

async function fetchAllData() {
    try {
        const [accountsRes, holdingsRes, summaryRes, historyRes] = await Promise.all([
            fetch(`${API_URL}/api/accounts`),
            fetch(`${API_URL}/api/holdings`),
            fetch(`${API_URL}/api/portfolio/summary`),
            fetch(`${API_URL}/api/portfolio/history?period=${currentPeriod}`)
        ]);

        accounts = await accountsRes.json();
        holdings = await holdingsRes.json();
        portfolioSummary = await summaryRes.json();
        portfolioHistory = await historyRes.json();

        // Render everything
        renderDashboard();
        updateAccountSelectDropdowns();
        updateFilterDropdown();
        renderHoldingsTable();
        renderAccountsList();
        
        // Refresh icons
        lucide.createIcons();
    } catch (error) {
        console.error("Erreur lors de la récupération des données:", error);
    }
}

// --- REFRESH ACTION ---
async function handleRefreshPrices() {
    refreshIcon.classList.add("spin");
    refreshBtn.disabled = true;
    try {
        const response = await fetch(`${API_URL}/api/portfolio/refresh`, { method: "POST" });
        if (response.ok) {
            await fetchAllData();
        } else {
            alert("Erreur lors de la mise à jour automatique des cours.");
        }
    } catch (err) {
        console.error(err);
        alert("Impossible de contacter le serveur pour mettre à jour les cours.");
    } finally {
        refreshIcon.classList.remove("spin");
        refreshBtn.disabled = false;
    }
}

// --- RENDER KPI & CHARTS (DASHBOARD) ---
function renderDashboard() {
    if (!portfolioSummary) return;

    // KPI Values
    document.getElementById("kpi-total-val").textContent = formatCurrency(portfolioSummary.total_value);
    const valSubEl = document.getElementById("kpi-total-val-subtext");
    if (valSubEl) {
        valSubEl.textContent = `Coût d'achat : ${formatCurrency(portfolioSummary.total_cost)} (${formatPercent(portfolioSummary.total_gain_pct)} latent)`;
    }
    
    // Gain Global KPI
    const gainValue = portfolioSummary.total_invested_gain;
    const gainPct = portfolioSummary.total_invested_gain_pct;
    const gainEl = document.getElementById("kpi-total-gain");
    const gainPctEl = document.getElementById("kpi-total-gain-pct");
    const gainIconEl = document.getElementById("kpi-total-gain-icon");
    
    if (gainEl) {
        gainEl.textContent = `${gainValue >= 0 ? '+' : ''}${formatCurrency(gainValue)}`;
        gainEl.className = `kpi-value ${gainValue >= 0 ? 'positive' : 'negative'}`;
    }
    if (gainPctEl) {
        gainPctEl.textContent = `${formatPercent(gainPct)} vs Argent Investi`;
        gainPctEl.className = `kpi-subtext ${gainValue >= 0 ? 'positive' : 'negative'}`;
    }
    if (gainIconEl) {
        if (gainValue >= 0) {
            gainIconEl.className = "kpi-icon gain";
            gainIconEl.innerHTML = `<i data-lucide="trending-up"></i>`;
        } else {
            gainIconEl.className = "kpi-icon loss-icon";
            gainIconEl.innerHTML = `<i data-lucide="trending-down"></i>`;
        }
    }

    // Invested KPI
    document.getElementById("kpi-total-invested").textContent = formatCurrency(portfolioSummary.total_invested);
    const investedSubEl = document.getElementById("kpi-total-invested-subtext");
    if (investedSubEl) {
        investedSubEl.textContent = "Total net des versements externes";
    }

    document.getElementById("kpi-accounts-count").textContent = accounts.length;

    // Render Temporal Profitability Table
    const tempBody = document.getElementById("temporal-profitability-body");
    if (tempBody) {
        tempBody.innerHTML = "";
        
        const periodLabels = {
            "1d": "1 Jour",
            "1w": "1 Semaine",
            "1m": "1 Mois",
            "5m": "5 Mois",
            "1y": "1 An",
            "global": "Global"
        };
        
        Object.keys(periodLabels).forEach(key => {
            const periodData = portfolioSummary.profitability_periods[key];
            if (periodData) {
                const tr = document.createElement("tr");
                
                const portClass = periodData.portfolio_return_abs >= 0 ? "positive" : "negative";
                const invClass = periodData.invested_return_abs >= 0 ? "positive" : "negative";
                
                const portStr = `${formatCurrency(periodData.portfolio_return_abs)} (${formatPercent(periodData.portfolio_return_pct)})`;
                const invStr = `${formatCurrency(periodData.invested_return_abs)} (${formatPercent(periodData.invested_return_pct)})`;
                
                const dateText = periodData.date ? ` <span style="font-size: 10px; color: var(--text-muted);">(${periodData.date})</span>` : "";
                
                tr.innerHTML = `
                    <td style="font-weight: 500;">${periodLabels[key]}${dateText}</td>
                    <td><span class="gain-status ${portClass}">${portStr}</span></td>
                    <td><span class="gain-status ${invClass}">${invStr}</span></td>
                `;
                tempBody.appendChild(tr);
            }
        });
    }

    // Render Accounts Performance Table
    const dbAccountsBody = document.getElementById("dashboard-accounts-body");
    if (dbAccountsBody) {
        dbAccountsBody.innerHTML = "";
        
        if (accounts.length === 0) {
            dbAccountsBody.innerHTML = `
                <tr>
                    <td colspan="6" style="text-align: center; color: var(--text-muted); padding: 20px;">
                        Aucun compte support configuré.
                    </td>
                </tr>
            `;
        } else {
            // Sort by current value descending
            const sortedAccounts = [...accounts].map(acc => {
                const accHoldings = holdings.filter(h => h.account_id === acc.id);
                const cost = accHoldings.reduce((sum, h) => sum + h.total_cost, 0) + (acc.cash_balance || 0);
                const val = accHoldings.reduce((sum, h) => sum + h.total_value, 0) + (acc.cash_balance || 0);
                const gain = val - cost;
                const gainPct = cost > 0 ? (gain / cost * 100) : 0.0;
                
                const gainInvested = val - (acc.invested_amount || 0);
                const gainInvestedPct = (acc.invested_amount || 0) > 0 ? (gainInvested / acc.invested_amount * 100) : 0.0;
                
                return { ...acc, cost, val, gain, gainPct, gainInvested, gainInvestedPct };
            }).sort((a, b) => b.val - a.val);

            sortedAccounts.forEach(acc => {
                const tr = document.createElement("tr");
                const gainClass = acc.gain >= 0 ? "positive" : "negative";
                const gainInvestedClass = acc.gainInvested >= 0 ? "positive" : "negative";

                tr.innerHTML = `
                    <td>
                        <span class="badge ${getAccountBadgeClass(acc.type)}">${acc.name}</span>
                    </td>
                    <td><code>${acc.type}</code></td>
                    <td>${formatCurrency(acc.invested_amount || 0)}</td>
                    <td>${formatCurrency(acc.cost)}</td>
                    <td>${formatCurrency(acc.cash_balance || 0)}</td>
                    <td><strong>${formatCurrency(acc.val)}</strong></td>
                    <td>
                        <span class="gain-status ${gainClass}">
                            ${formatPercent(acc.gainPct)}
                        </span>
                    </td>
                    <td>
                        <span class="gain-status ${gainInvestedClass}">
                            ${formatPercent(acc.gainInvestedPct)}
                        </span>
                    </td>
                `;
                dbAccountsBody.appendChild(tr);
            });
        }
    }
    
    // Draw Charts
    updateCharts();
}

function updateCharts() {
    if (!portfolioSummary) return;

    // 1. Account Allocation Chart
    const accCanvas = document.getElementById("account-allocation-chart");
    if (accCanvas) {
        if (accountAllocationChart) accountAllocationChart.destroy();
        
        const labels = Object.keys(portfolioSummary.allocation_by_account);
        const data = Object.values(portfolioSummary.allocation_by_account);

        if (labels.length === 0) {
            labels.push("Aucun actif");
            data.push(1);
        }

        accountAllocationChart = new Chart(accCanvas, {
            type: 'doughnut',
            data: {
                labels: labels,
                datasets: [{
                    data: data,
                    backgroundColor: [
                        '#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#6b7280'
                    ],
                    borderWidth: 2,
                    borderColor: '#18181b'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: { color: '#a1a1aa', font: { family: 'Inter' }, boxWidth: 12 }
                    }
                }
            }
        });
    }

    // 2. Category Allocation Chart
    const catCanvas = document.getElementById("category-allocation-chart");
    if (catCanvas) {
        if (categoryAllocationChart) categoryAllocationChart.destroy();
        
        const labels = Object.keys(portfolioSummary.allocation_by_category);
        const data = Object.values(portfolioSummary.allocation_by_category);

        if (labels.length === 0) {
            labels.push("Aucun actif");
            data.push(1);
        }

        categoryAllocationChart = new Chart(catCanvas, {
            type: 'doughnut',
            data: {
                labels: labels,
                datasets: [{
                    data: data,
                    backgroundColor: [
                        '#06b6d4', '#8b5cf6', '#6366f1', '#fb7185', '#fbbf24', '#f472b6', '#34d399', '#a1a1aa'
                    ],
                    borderWidth: 2,
                    borderColor: '#18181b'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: { color: '#a1a1aa', font: { family: 'Inter' }, boxWidth: 12 }
                    }
                }
            }
        });
    }

    // 3. Historical Line Chart
    const histCanvas = document.getElementById("history-chart");
    if (histCanvas) {
        if (historyChart) historyChart.destroy();

        // Sort history chronological
        const sortedHistory = [...portfolioHistory].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
        
        const labels = sortedHistory.map(h => {
            const d = new Date(h.timestamp);
            if (currentPeriod === "1d") {
                return d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
            }
            return d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: '2-digit' });
        });
        const values = sortedHistory.map(h => h.total_value);
        const costs = sortedHistory.map(h => h.total_cost);
        const invested = sortedHistory.map(h => h.total_invested || h.total_cost);

        historyChart = new Chart(histCanvas, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Valeur du Portefeuille',
                        data: values,
                        borderColor: '#6366f1',
                        backgroundColor: 'rgba(99, 102, 241, 0.05)',
                        fill: true,
                        tension: 0.3,
                        borderWidth: 3
                    },
                    {
                        label: 'Coût d\'acquisition',
                        data: costs,
                        borderColor: '#71717a',
                        borderDash: [5, 5],
                        backgroundColor: 'transparent',
                        fill: false,
                        tension: 0.1,
                        borderWidth: 2
                    },
                    {
                        label: 'Argent Investi',
                        data: invested,
                        borderColor: '#10b981',
                        borderDash: [2, 2],
                        backgroundColor: 'transparent',
                        fill: false,
                        tension: 0.1,
                        borderWidth: 2
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        labels: { color: '#a1a1aa', font: { family: 'Inter' } }
                    }
                },
                scales: {
                    y: {
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        ticks: { color: '#a1a1aa', font: { family: 'Inter' } }
                    },
                    x: {
                        grid: { display: false },
                        ticks: { color: '#a1a1aa', font: { family: 'Inter' } }
                    }
                }
            }
        });
    }
}

// --- RENDER PLACEMENTS / HOLDINGS TABLE ---
function renderHoldingsTable() {
    const tbody = document.getElementById("holdings-table-body");
    tbody.innerHTML = "";

    if (holdings.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="10" style="text-align: center; color: var(--text-muted); padding: 40px;">
                    Aucun placement enregistré. Cliquez sur "Nouveau Placement" pour commencer !
                </td>
            </tr>
        `;
        return;
    }

    const filterSelect = document.getElementById("filter-holding-account");
    const selectedAccountId = filterSelect ? filterSelect.value : "all";

    // Sort by Account Support name, then by Holding name
    const sortedHoldings = [...holdings].sort((a, b) => {
        const accA = getAccountName(a.account_id).toLowerCase();
        const accB = getAccountName(b.account_id).toLowerCase();
        if (accA !== accB) return accA.localeCompare(accB);
        return a.name.localeCompare(b.name);
    });

    const filteredHoldings = sortedHoldings.filter(h => {
        if (selectedAccountId === "all") return true;
        return h.account_id === parseInt(selectedAccountId);
    });

    if (filteredHoldings.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="10" style="text-align: center; color: var(--text-muted); padding: 40px;">
                    Aucun placement enregistré pour ce compte support.
                </td>
            </tr>
        `;
        return;
    }

    filteredHoldings.forEach(h => {
        const tr = document.createElement("tr");
        
        const accName = getAccountName(h.account_id);
        const accType = getAccountType(h.account_id);
        const gainClass = h.gain_loss >= 0 ? "positive" : "negative";

        tr.innerHTML = `
            <td>
                <span class="badge ${getAccountBadgeClass(accType)}">${accName}</span>
            </td>
            <td><strong>${h.name}</strong></td>
            <td><code>${h.isin_or_symbol || 'Manuel'}</code></td>
            <td><span class="badge ${getCategoryBadgeClass(h.category)}">${h.category}</span></td>
            <td>${h.quantity}</td>
            <td>${formatCurrency(h.buy_price)}</td>
            <td>${formatCurrency(h.current_price || h.manual_price)}</td>
            <td><strong>${formatCurrency(h.total_value)}</strong></td>
            <td>
                <span class="gain-status ${gainClass}">
                    ${formatCurrency(h.gain_loss)} (${formatPercent(h.gain_loss_pct)})
                </span>
            </td>
            <td class="actions-cell">
                <button class="table-action-btn edit" onclick="openHoldingEditModal(${h.id})" title="Modifier">
                    <i data-lucide="edit-3"></i>
                </button>
                <button class="table-action-btn delete" onclick="deleteHolding(${h.id})" title="Supprimer">
                    <i data-lucide="trash-2"></i>
                </button>
            </td>
        `;

        tbody.appendChild(tr);
    });

    // Re-initialize Lucide icons for the newly rendered rows
    lucide.createIcons();
}

function getAccountName(id) {
    const acc = accounts.find(a => a.id === id);
    return acc ? acc.name : "Inconnu";
}

function getAccountType(id) {
    const acc = accounts.find(a => a.id === id);
    return acc ? acc.type : "Autre";
}

// --- RENDER ACCOUNTS ---
function renderAccountsList() {
    const container = document.getElementById("accounts-list-container");
    container.innerHTML = "";

    if (accounts.length === 0) {
        container.innerHTML = `
            <div style="grid-column: 1 / -1; text-align: center; color: var(--text-muted); padding: 40px;" class="glass">
                Aucun compte support configuré. Cliquez sur "Ajouter un compte" !
            </div>
        `;
        return;
    }

    accounts.forEach(acc => {
        // Calculate account stats
        const accHoldings = holdings.filter(h => h.account_id === acc.id);
        const cost = accHoldings.reduce((sum, h) => sum + h.total_cost, 0) + (acc.cash_balance || 0);
        const val = accHoldings.reduce((sum, h) => sum + h.total_value, 0) + (acc.cash_balance || 0);
        const gain = val - cost;
        const gainPct = cost > 0 ? (gain / cost * 100) : 0.0;
        const gainClass = gain >= 0 ? "positive" : "negative";

        const gainInvested = val - (acc.invested_amount || 0);
        const gainInvestedPct = (acc.invested_amount || 0) > 0 ? (gainInvested / acc.invested_amount * 100) : 0.0;
        const gainInvestedClass = gainInvested >= 0 ? "positive" : "negative";

        const annReturn = calculateAnnualizedReturn(gainPct, acc.creation_date);
        const annReturnStr = annReturn !== null ? formatPercent(annReturn) : "-";
        const annReturnClass = annReturn !== null ? (annReturn >= 0 ? "positive" : "negative") : "";

        const annReturnInvested = calculateAnnualizedReturn(gainInvestedPct, acc.creation_date);
        const annReturnInvestedStr = annReturnInvested !== null ? formatPercent(annReturnInvested) : "-";
        const annReturnInvestedClass = annReturnInvested !== null ? (annReturnInvested >= 0 ? "positive" : "negative") : "";

        // Format creation date nicely
        let creationDateFormatted = "Non renseignée";
        if (acc.creation_date) {
            const dateObj = new Date(acc.creation_date);
            creationDateFormatted = dateObj.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' });
        }

        const card = document.createElement("div");
        card.className = `account-card glass ${getAccountBadgeClass(acc.type)}`;
        
        card.innerHTML = `
            <div class="account-card-header">
                <div>
                    <span class="badge ${getAccountBadgeClass(acc.type)}" style="margin-bottom: 8px;">${acc.type}</span>
                    <h3>${acc.name}</h3>
                </div>
                <div style="display: flex; gap: 8px;">
                    <button class="table-action-btn edit edit-account-btn" data-id="${acc.id}" title="Modifier ce compte support">
                        <i data-lucide="edit-3"></i>
                    </button>
                    <button class="table-action-btn delete delete-account-btn" data-id="${acc.id}" title="Supprimer ce compte support">
                        <i data-lucide="trash-2"></i>
                    </button>
                </div>
            </div>
            <div class="account-card-body">
                <div class="account-value-row">
                    <span class="label">Date de création</span>
                    <span class="val">${creationDateFormatted}</span>
                </div>
                <div class="account-value-row">
                    <span class="label">Argent investi</span>
                    <span class="val">${formatCurrency(acc.invested_amount || 0)}</span>
                </div>
                <div class="account-value-row">
                    <span class="label">Liquidités</span>
                    <span class="val">${formatCurrency(acc.cash_balance || 0)}</span>
                </div>
                <div class="account-value-row">
                    <span class="label">Coût d'achat</span>
                    <span class="val">${formatCurrency(cost)}</span>
                </div>
                <div class="account-value-row">
                    <span class="label">Gain / Coût</span>
                    <span class="val gain-status ${gainClass}">${formatCurrency(gain)} (${formatPercent(gainPct)})</span>
                </div>
                <div class="account-value-row">
                    <span class="label">Gain / Investi</span>
                    <span class="val gain-status ${gainInvestedClass}">${formatCurrency(gainInvested)} (${formatPercent(gainInvestedPct)})</span>
                </div>
                <div class="account-value-row">
                    <span class="label">Rentabilité p.a. (Coût)</span>
                    <span class="val gain-status ${annReturnClass}">${annReturnStr}</span>
                </div>
                <div class="account-value-row">
                    <span class="label">Rentabilité p.a. (Investi)</span>
                    <span class="val gain-status ${annReturnInvestedClass}">${annReturnInvestedStr}</span>
                </div>
                <div class="account-value-row grand-total">
                    <span class="label">Valeur actuelle</span>
                    <span class="val">${formatCurrency(val)}</span>
                </div>
            </div>
        `;

        container.appendChild(card);
    });

    // Add click listeners to account delete buttons
    document.querySelectorAll(".delete-account-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            const accId = parseInt(btn.getAttribute("data-id"));
            deleteAccount(accId);
        });
    });

    // Add click listeners to account edit buttons
    document.querySelectorAll(".edit-account-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            const accId = parseInt(btn.getAttribute("data-id"));
            openAccountEditModal(accId);
        });
    });
}

// --- POPULATE FORMS DROPDOWNS ---
function updateAccountSelectDropdowns() {
    const select = document.getElementById("holding-account");
    select.innerHTML = "";
    
    if (accounts.length === 0) {
        select.innerHTML = `<option value="">-- Veuillez créer un compte support d'abord --</option>`;
        return;
    }

    accounts.forEach(acc => {
        const opt = document.createElement("option");
        opt.value = acc.id;
        opt.textContent = `${acc.name} (${acc.type})`;
        select.appendChild(opt);
    });
}

function updateFilterDropdown() {
    const filterSelect = document.getElementById("filter-holding-account");
    if (!filterSelect) return;
    
    const currentValue = filterSelect.value;
    filterSelect.innerHTML = `<option value="all">Tous les comptes</option>`;
    
    accounts.forEach(acc => {
        const opt = document.createElement("option");
        opt.value = acc.id;
        opt.textContent = `${acc.name} (${acc.type})`;
        filterSelect.appendChild(opt);
    });
    
    // Restore selection if it still exists
    if (currentValue && [...filterSelect.options].some(opt => opt.value === currentValue)) {
        filterSelect.value = currentValue;
    } else {
        filterSelect.value = "all";
    }
}

// --- MODALS CODE & HANDLERS ---
function setupModals() {
    const holdingModal = document.getElementById("holding-modal");
    const accountModal = document.getElementById("account-modal");
    
    // Add Buttons
    document.getElementById("open-holding-modal").addEventListener("click", () => {
        openHoldingAddModal();
    });
    
    document.getElementById("open-account-modal").addEventListener("click", () => {
        openAccountAddModal();
    });

    // Close buttons holding
    document.getElementById("close-holding-modal").addEventListener("click", () => holdingModal.classList.remove("active"));
    document.getElementById("cancel-holding-form").addEventListener("click", () => holdingModal.classList.remove("active"));

    // Close buttons accounts
    document.getElementById("close-account-modal").addEventListener("click", () => accountModal.classList.remove("active"));
    document.getElementById("cancel-account-form").addEventListener("click", () => accountModal.classList.remove("active"));

    // Toggle manual price vs ISIN inputs in holding modal
    const priceModeSelect = document.getElementById("holding-pricing-mode");
    const isinField = document.getElementById("isin-field-container");
    const isinInput = document.getElementById("holding-isin");
    const manualPriceField = document.getElementById("manual-price-field-container");
    
    priceModeSelect.addEventListener("change", () => {
        if (priceModeSelect.value === 'manual') {
            isinField.style.display = "none";
            isinInput.required = false;
            manualPriceField.style.display = "flex";
        } else {
            isinField.style.display = "flex";
            manualPriceField.style.display = "none";
        }
    });

    // Forms Submissions
    document.getElementById("holding-form").addEventListener("submit", handleHoldingFormSubmit);
    document.getElementById("account-form").addEventListener("submit", handleAccountFormSubmit);

    // Close confirm modal
    document.getElementById("confirm-cancel-btn").addEventListener("click", () => {
        document.getElementById("confirm-modal").classList.remove("active");
    });
    
    // Execute confirm action
    document.getElementById("confirm-delete-btn").addEventListener("click", async () => {
        if (confirmAction) {
            await confirmAction();
        }
        document.getElementById("confirm-modal").classList.remove("active");
        confirmAction = null;
    });
}

function openHoldingAddModal() {
    const modal = document.getElementById("holding-modal");
    document.getElementById("holding-modal-title").textContent = "Nouveau Placement";
    document.getElementById("holding-form").reset();
    document.getElementById("holding-id").value = "";
    
    // Trigger reset layout for fields
    document.getElementById("holding-pricing-mode").value = "auto";
    document.getElementById("isin-field-container").style.display = "flex";
    document.getElementById("manual-price-field-container").style.display = "none";
    
    modal.classList.add("active");
}

function openHoldingEditModal(id) {
    const h = holdings.find(item => item.id === id);
    if (!h) return;

    const modal = document.getElementById("holding-modal");
    document.getElementById("holding-modal-title").textContent = "Modifier le Placement";
    
    document.getElementById("holding-id").value = h.id;
    document.getElementById("holding-account").value = h.account_id;
    document.getElementById("holding-name").value = h.name;
    document.getElementById("holding-category").value = h.category;
    document.getElementById("holding-qty").value = h.quantity;
    document.getElementById("holding-buy-price").value = h.buy_price;
    
    const priceMode = h.is_manual ? "manual" : "auto";
    document.getElementById("holding-pricing-mode").value = priceMode;
    document.getElementById("holding-isin").value = h.isin_or_symbol || "";
    document.getElementById("holding-manual-price").value = h.manual_price || 0.0;

    const isinField = document.getElementById("isin-field-container");
    const manualPriceField = document.getElementById("manual-price-field-container");

    if (priceMode === 'manual') {
        isinField.style.display = "none";
        manualPriceField.style.display = "flex";
    } else {
        isinField.style.display = "flex";
        manualPriceField.style.display = "none";
    }

    modal.classList.add("active");
}

// --- CRUD API ACTIONS ---

async function handleHoldingFormSubmit(e) {
    e.preventDefault();
    const id = document.getElementById("holding-id").value;
    const account_id = parseInt(document.getElementById("holding-account").value);
    
    if (!account_id) {
        alert("Veuillez sélectionner ou créer un compte support d'abord.");
        return;
    }

    const payload = {
        account_id: account_id,
        name: document.getElementById("holding-name").value,
        category: document.getElementById("holding-category").value,
        quantity: parseFloat(document.getElementById("holding-qty").value),
        buy_price: parseFloat(document.getElementById("holding-buy-price").value),
        is_manual: document.getElementById("holding-pricing-mode").value === 'manual',
        isin_or_symbol: document.getElementById("holding-isin").value,
        manual_price: parseFloat(document.getElementById("holding-manual-price").value) || 0.0
    };

    try {
        let response;
        if (id) {
            // Edit PUT
            response = await fetch(`${API_URL}/api/holdings/${id}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
        } else {
            // New POST
            response = await fetch(`${API_URL}/api/holdings`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
        }

        if (response.ok) {
            document.getElementById("holding-modal").classList.remove("active");
            await fetchAllData();
        } else {
            const err = await response.json();
            alert(`Erreur : ${err.detail || "Erreur de validation"}`);
        }
    } catch (error) {
        console.error(error);
        alert("Une erreur s'est produite lors de l'enregistrement.");
    }
}

function openAccountAddModal() {
    const modal = document.getElementById("account-modal");
    document.getElementById("account-modal-title").textContent = "Ajouter un Compte Support";
    document.getElementById("account-form").reset();
    document.getElementById("account-id").value = "";
    document.getElementById("account-invested").value = "";
    document.getElementById("account-cash").value = "";
    document.getElementById("account-submit-btn").textContent = "Créer";
    modal.classList.add("active");
}

function openAccountEditModal(id) {
    const acc = accounts.find(item => item.id === id);
    if (!acc) return;
    
    const modal = document.getElementById("account-modal");
    document.getElementById("account-modal-title").textContent = "Modifier le Compte Support";
    
    document.getElementById("account-id").value = acc.id;
    document.getElementById("account-name").value = acc.name;
    document.getElementById("account-type").value = acc.type;
    document.getElementById("account-creation-date").value = acc.creation_date || "";
    document.getElementById("account-invested").value = acc.invested_amount || 0;
    document.getElementById("account-cash").value = acc.cash_balance || 0;
    document.getElementById("account-submit-btn").textContent = "Sauvegarder";
    
    modal.classList.add("active");
}

async function handleAccountFormSubmit(e) {
    e.preventDefault();
    const id = document.getElementById("account-id").value;
    const creationDateValue = document.getElementById("account-creation-date").value;
    const investedValue = parseFloat(document.getElementById("account-invested").value) || 0.0;
    const cashValue = parseFloat(document.getElementById("account-cash").value) || 0.0;
    
    const payload = {
        name: document.getElementById("account-name").value,
        type: document.getElementById("account-type").value,
        creation_date: creationDateValue ? creationDateValue : null,
        invested_amount: investedValue,
        cash_balance: cashValue
    };

    try {
        let response;
        if (id) {
            // Edit PUT
            response = await fetch(`${API_URL}/api/accounts/${id}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
        } else {
            // Create POST
            response = await fetch(`${API_URL}/api/accounts`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
        }

        if (response.ok) {
            document.getElementById("account-modal").classList.remove("active");
            await fetchAllData();
        } else {
            const err = await response.json();
            alert(`Erreur: ${err.detail || "Erreur de validation"}`);
        }
    } catch (error) {
        console.error(error);
        alert("Une erreur s'est produite lors de l'enregistrement du compte.");
    }
}

function showConfirmModal(title, text, action) {
    document.getElementById("confirm-modal-title").textContent = title;
    document.getElementById("confirm-modal-text").textContent = text;
    confirmAction = action;
    document.getElementById("confirm-modal").classList.add("active");
    lucide.createIcons();
}

function deleteHolding(id) {
    showConfirmModal(
        "Supprimer le placement ?",
        "Voulez-vous vraiment supprimer ce placement ? Cette action est irréversible.",
        async () => {
            try {
                const response = await fetch(`${API_URL}/api/holdings/${id}`, { method: "DELETE" });
                if (response.ok) {
                    await fetchAllData();
                } else {
                    alert("Impossible de supprimer le placement.");
                }
            } catch (err) {
                console.error(err);
            }
        }
    );
}

function deleteAccount(id) {
    const acc = accounts.find(a => a.id === id);
    const accName = acc ? acc.name : "ce compte";
    const accountHoldings = holdings.filter(h => h.account_id === id);
    let msg = `Voulez-vous vraiment supprimer le compte "${accName}" ?`;
    if (accountHoldings.length > 0) {
        msg = `ATTENTION : Le compte "${accName}" contient ${accountHoldings.length} placement(s). Supprimer ce compte supprimera également tous les placements associés de manière définitive.`;
    }
    
    showConfirmModal(
        "Supprimer le compte support ?",
        msg,
        async () => {
            try {
                const response = await fetch(`${API_URL}/api/accounts/${id}`, { method: "DELETE" });
                if (response.ok) {
                    await fetchAllData();
                } else {
                    alert("Impossible de supprimer le compte support.");
                }
            } catch (err) {
                console.error(err);
            }
        }
    );
}

// --- SETTINGS VIEW ACTIONS ---
let systemSettings = {};

async function fetchSettings() {
    try {
        const response = await fetch(`${API_URL}/api/settings`);
        if (response.ok) {
            systemSettings = await response.json();
            updateSettingsUI();
        }
    } catch (err) {
        console.error("Erreur lors de la récupération des réglages:", err);
    }
}

function updateSettingsUI() {
    const hourInput = document.getElementById("settings-hour");
    const minuteInput = document.getElementById("settings-minute");
    const statusText = document.getElementById("settings-status-text");

    const peaSelect = document.getElementById("settings-freq-pea");
    const perSelect = document.getElementById("settings-freq-per");
    const avSelect = document.getElementById("settings-freq-av");
    const ctSelect = document.getElementById("settings-freq-ct");
    const cwSelect = document.getElementById("settings-freq-cw");
    const autreSelect = document.getElementById("settings-freq-autre");

    if (!hourInput || !minuteInput || !statusText) return;

    if (systemSettings.update_hour) hourInput.value = parseInt(systemSettings.update_hour);
    if (systemSettings.update_minute) minuteInput.value = parseInt(systemSettings.update_minute);

    if (peaSelect && systemSettings.refresh_freq_PEA) peaSelect.value = systemSettings.refresh_freq_PEA;
    if (perSelect && systemSettings.refresh_freq_PER) perSelect.value = systemSettings.refresh_freq_PER;
    if (avSelect && systemSettings["refresh_freq_Assurance Vie"]) avSelect.value = systemSettings["refresh_freq_Assurance Vie"];
    if (ctSelect && systemSettings["refresh_freq_Compte-Titres"]) ctSelect.value = systemSettings["refresh_freq_Compte-Titres"];
    if (cwSelect && systemSettings["refresh_freq_Crypto Wallet"]) cwSelect.value = systemSettings["refresh_freq_Crypto Wallet"];
    if (autreSelect && systemSettings.refresh_freq_Autre) autreSelect.value = systemSettings.refresh_freq_Autre;

    const formattedHour = String(hourInput.value || 20).padStart(2, '0');
    const formattedMinute = String(minuteInput.value || 0).padStart(2, '0');
    
    statusText.textContent = `Planification personnalisée active (mise à jour quotidienne à ${formattedHour}:${formattedMinute})`;
}

function setupSettingsForm() {
    const form = document.getElementById("settings-form");
    if (form) {
        form.addEventListener("submit", async (e) => {
            e.preventDefault();
            const payload = {
                update_hour: parseInt(document.getElementById("settings-hour").value),
                update_minute: parseInt(document.getElementById("settings-minute").value),
                refresh_freq_PEA: document.getElementById("settings-freq-pea").value,
                refresh_freq_PER: document.getElementById("settings-freq-per").value,
                "refresh_freq_Assurance Vie": document.getElementById("settings-freq-av").value,
                "refresh_freq_Compte-Titres": document.getElementById("settings-freq-ct").value,
                "refresh_freq_Crypto Wallet": document.getElementById("settings-freq-cw").value,
                refresh_freq_Autre: document.getElementById("settings-freq-autre").value
            };

            try {
                const response = await fetch(`${API_URL}/api/settings`, {
                    method: "PUT",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });

                if (response.ok) {
                    alert("Réglages enregistrés et planificateur mis à jour avec succès !");
                    await fetchSettings();
                } else {
                    const err = await response.json();
                    alert(`Erreur: ${err.detail || "Erreur de validation"}`);
                }
            } catch (err) {
                console.error(err);
                alert("Une erreur s'est produite lors de l'enregistrement.");
            }
        });
    }
}

function setupMaintenance() {
    const cleanPortfolioBtn = document.getElementById("btn-clean-portfolio-history");
    const cleanDepositsBtn = document.getElementById("btn-clean-deposits-history");

    if (cleanPortfolioBtn) {
        cleanPortfolioBtn.addEventListener("click", () => {
            const periodSelect = document.getElementById("maintenance-history-period");
            const periodValue = periodSelect.value;
            
            let url = `${API_URL}/api/portfolio/history`;
            let confirmMessage = "Voulez-vous vraiment supprimer tout l'historique du portefeuille ?\nUn cliché de l'état actuel sera créé pour éviter un graphique vide.";
            
            if (periodValue !== "all") {
                url += `?keep_days=${periodValue}`;
                confirmMessage = `Voulez-vous vraiment supprimer l'historique du portefeuille datant de plus de ${periodValue} jours ?`;
            }
            
            showConfirmModal(
                "Confirmer le nettoyage de l'historique",
                confirmMessage,
                async () => {
                    try {
                        const response = await fetch(url, { method: "DELETE" });
                        if (response.ok) {
                            const res = await response.json();
                            alert(res.message || "Nettoyage effectué.");
                            // Refresh dashboard & history chart
                            await fetchAllData();
                        } else {
                            const err = await response.json();
                            alert(`Erreur: ${err.detail || "Le nettoyage a échoué."}`);
                        }
                    } catch (error) {
                        console.error(error);
                        alert("Erreur réseau lors de la tentative de nettoyage.");
                    }
                }
            );
        });
    }

    if (cleanDepositsBtn) {
        cleanDepositsBtn.addEventListener("click", () => {
            const periodSelect = document.getElementById("maintenance-deposits-period");
            const periodValue = periodSelect.value;
            
            let url = `${API_URL}/api/deposits/history`;
            let confirmMessage = "Voulez-vous vraiment supprimer tout l'historique d'exécution des versements ?";
            
            if (periodValue !== "all") {
                url += `?keep_days=${periodValue}`;
                confirmMessage = `Voulez-vous vraiment supprimer l'historique d'exécution des versements datant de plus de ${periodValue} jours ?`;
            }
            
            showConfirmModal(
                "Confirmer le nettoyage des versements",
                confirmMessage,
                async () => {
                    try {
                        const response = await fetch(url, { method: "DELETE" });
                        if (response.ok) {
                            const res = await response.json();
                            alert(res.message || "Nettoyage effectué.");
                            // Refresh deposits data & history
                            await fetchDepositsData();
                        } else {
                            const err = await response.json();
                            alert(`Erreur: ${err.detail || "Le nettoyage a échoué."}`);
                        }
                    } catch (error) {
                        console.error(error);
                        alert("Erreur réseau lors de la tentative de nettoyage.");
                    }
                }
            );
        });
    }
}

// --- RECURRING DEPOSITS FRONTEND LOGIC ---

async function fetchDepositsData() {
    try {
        const [depositsRes, historyRes] = await Promise.all([
            fetch(`${API_URL}/api/deposits`),
            fetch(`${API_URL}/api/deposits/history`)
        ]);
        if (depositsRes.ok && historyRes.ok) {
            deposits = await depositsRes.json();
            depositHistory = await historyRes.json();
            renderDeposits();
        }
    } catch (err) {
        console.error("Erreur lors de la récupération des versements réguliers:", err);
    }
}

function renderDeposits() {
    // 1. Calculate Monthly savings KPI
    let monthlyTotal = 0;
    let activeCount = 0;
    
    deposits.forEach(dep => {
        if (dep.is_active) {
            activeCount++;
            if (dep.frequency === 'daily') {
                monthlyTotal += dep.amount * 30;
            } else if (dep.frequency === 'weekly') {
                monthlyTotal += dep.amount * 4.33;
            } else if (dep.frequency === 'monthly') {
                monthlyTotal += dep.amount;
            }
        }
    });

    document.getElementById("kpi-deposit-monthly-total").textContent = formatCurrency(monthlyTotal);
    document.getElementById("kpi-deposit-active-count").textContent = activeCount;
    document.getElementById("kpi-deposit-total-count").textContent = `${deposits.length} plan(s) programmé(s) au total`;

    // Next scheduled KPI
    const activeDeposits = deposits.filter(d => d.is_active);
    const nextAmountEl = document.getElementById("kpi-deposit-next-amount");
    const nextDateEl = document.getElementById("kpi-deposit-next-date");

    if (activeDeposits.length > 0) {
        // Sort by next execution date
        activeDeposits.sort((a, b) => new Date(a.next_execution_date) - new Date(b.next_execution_date));
        const soonest = activeDeposits[0];
        nextAmountEl.textContent = formatCurrency(soonest.amount);
        
        const nextDt = new Date(soonest.next_execution_date);
        const formattedDate = nextDt.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' });
        nextDateEl.textContent = `${soonest.name} le ${formattedDate}`;
    } else {
        nextAmountEl.textContent = "0,00 €";
        nextDateEl.textContent = "Aucun plan actif";
    }

    // 2. Render Scheduled Deposits Table
    const tbody = document.getElementById("deposits-table-body");
    tbody.innerHTML = "";

    if (deposits.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="9" style="text-align: center; color: var(--text-muted); padding: 40px;">
                    Aucun versement régulier planifié. Cliquez sur "Planifier un versement" pour commencer !
                </td>
            </tr>
        `;
    } else {
        deposits.forEach(dep => {
            const tr = document.createElement("tr");
            
            // Format schedule description
            let scheduleDesc = "";
            let freqLabel = "";
            if (dep.frequency === 'daily') {
                freqLabel = "Quotidien";
                scheduleDesc = "Chaque jour";
            } else if (dep.frequency === 'weekly') {
                freqLabel = "Hebdomadaire";
                const days = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"];
                const dayName = days[dep.day_of_period] || "Jour inconnu";
                scheduleDesc = `Chaque ${dayName}`;
            } else if (dep.frequency === 'monthly') {
                freqLabel = "Mensuel";
                scheduleDesc = `Le ${dep.day_of_period} du mois`;
            }

            const holdingLabel = dep.holding_name ? 
                `<span class="badge etf">${dep.holding_name}</span>` : 
                `<span class="badge autre" style="color: var(--text-muted);">Liquidités / Cash</span>`;

            const nextExecutionFormatted = dep.next_execution_date ? 
                new Date(dep.next_execution_date).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' }) : 
                "-";

            tr.innerHTML = `
                <td><strong>${dep.name}</strong></td>
                <td><span class="badge ${getAccountBadgeClass(dep.account_name.split(' ')[0] || 'Autre')}">${dep.account_name}</span></td>
                <td>${holdingLabel}</td>
                <td><strong>${formatCurrency(dep.amount)}</strong></td>
                <td><code>${freqLabel}</code></td>
                <td style="color: var(--text-secondary); font-size: 13px;">${scheduleDesc}</td>
                <td>${nextExecutionFormatted}</td>
                <td>
                    <label class="switch">
                        <input type="checkbox" ${dep.is_active ? 'checked' : ''} onchange="toggleDepositActive(${dep.id}, this.checked)">
                        <span class="slider-toggle"></span>
                    </label>
                </td>
                <td class="actions-cell">
                    <button class="table-action-btn edit" onclick="triggerDepositNow(${dep.id})" title="Exécuter maintenant" style="color: var(--color-success);">
                        <i data-lucide="play"></i>
                    </button>
                    <button class="table-action-btn edit" onclick="openDepositEditModal(${dep.id})" title="Modifier">
                        <i data-lucide="edit-3"></i>
                    </button>
                    <button class="table-action-btn delete" onclick="deleteDeposit(${dep.id})" title="Supprimer">
                        <i data-lucide="trash-2"></i>
                    </button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    }

    // 3. Render Execution History Table
    const histBody = document.getElementById("deposit-history-table-body");
    histBody.innerHTML = "";

    if (depositHistory.length === 0) {
        histBody.innerHTML = `
            <tr>
                <td colspan="6" style="text-align: center; color: var(--text-muted); padding: 20px;">
                    Aucun historique de versement disponible.
                </td>
            </tr>
        `;
    } else {
        depositHistory.forEach(rec => {
            const tr = document.createElement("tr");
            
            const execDate = new Date(rec.execution_date);
            const formattedTime = execDate.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' }) + 
                ' ' + execDate.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });

            const statusClass = rec.status === 'success' ? 'success' : 'failed';
            const statusLabel = rec.status === 'success' ? 'Succès' : 'Échec';

            tr.innerHTML = `
                <td style="color: var(--text-secondary); font-size: 13px;">${formattedTime}</td>
                <td><strong>${rec.deposit_name}</strong></td>
                <td><span class="badge ${getAccountBadgeClass(rec.account_name.split(' ')[0] || 'Autre')}">${rec.account_name}</span></td>
                <td><strong>${formatCurrency(rec.amount)}</strong></td>
                <td><span class="badge ${statusClass}">${statusLabel}</span></td>
                <td style="color: var(--text-secondary); font-size: 13px; font-style: italic;">${rec.details || "-"}</td>
            `;
            histBody.appendChild(tr);
        });
    }

    lucide.createIcons();
}

function updateDepositHoldingsDropdown(selectedAccountId, targetSelectId, selectedHoldingId = null) {
    const holdingSelect = document.getElementById(targetSelectId);
    holdingSelect.innerHTML = `<option value="">-- Conserver en Liquidités (Non investi) --</option>`;
    
    if (!selectedAccountId) return;

    const filteredHoldings = holdings.filter(h => h.account_id === parseInt(selectedAccountId));
    filteredHoldings.forEach(h => {
        const opt = document.createElement("option");
        opt.value = h.id;
        opt.textContent = `${h.name} (${h.category} - ISIN: ${h.isin_or_symbol || 'Manuel'})`;
        if (selectedHoldingId && h.id === parseInt(selectedHoldingId)) {
            opt.selected = true;
        }
        holdingSelect.appendChild(opt);
    });
}

function setupDepositForm() {
    // Populate holdings when account changes in modal
    const accountSelect = document.getElementById("deposit-account");
    accountSelect.addEventListener("change", (e) => {
        updateDepositHoldingsDropdown(e.target.value, "deposit-holding");
    });

    // Update label and limits based on frequency selection
    const freqSelect = document.getElementById("deposit-frequency");
    const dayLabel = document.getElementById("deposit-day-label");
    const dayInput = document.getElementById("deposit-day-of-period");

    freqSelect.addEventListener("change", () => {
        if (freqSelect.value === 'daily') {
            dayLabel.textContent = "Jour (Sans objet)";
            dayInput.value = 1;
            dayInput.disabled = true;
            dayInput.required = false;
        } else if (freqSelect.value === 'weekly') {
            dayLabel.textContent = "Jour de la semaine (0=Lundi, 6=Dimanche)";
            dayInput.value = 0;
            dayInput.min = 0;
            dayInput.max = 6;
            dayInput.disabled = false;
            dayInput.required = true;
        } else if (freqSelect.value === 'monthly') {
            dayLabel.textContent = "Jour du mois (1 - 31)";
            dayInput.value = 5;
            dayInput.min = 1;
            dayInput.max = 31;
            dayInput.disabled = false;
            dayInput.required = true;
        }
    });

    // Open button
    document.getElementById("open-deposit-modal").addEventListener("click", () => {
        openDepositAddModal();
    });

    // Close buttons
    const depositModal = document.getElementById("deposit-modal");
    document.getElementById("close-deposit-modal").addEventListener("click", () => depositModal.classList.remove("active"));
    document.getElementById("cancel-deposit-form").addEventListener("click", () => depositModal.classList.remove("active"));

    // Form submit
    document.getElementById("deposit-form").addEventListener("submit", handleDepositFormSubmit);
}

function populateDepositAccountsDropdown(selectedAccountId = null) {
    const select = document.getElementById("deposit-account");
    select.innerHTML = "";
    
    if (accounts.length === 0) {
        select.innerHTML = `<option value="">-- Veuillez créer un compte support d'abord --</option>`;
        return;
    }

    accounts.forEach(acc => {
        const opt = document.createElement("option");
        opt.value = acc.id;
        opt.textContent = `${acc.name} (${acc.type})`;
        if (selectedAccountId && acc.id === parseInt(selectedAccountId)) {
            opt.selected = true;
        }
        select.appendChild(opt);
    });
}

function openDepositAddModal() {
    const modal = document.getElementById("deposit-modal");
    document.getElementById("deposit-modal-title").textContent = "Planifier un Versement";
    document.getElementById("deposit-form").reset();
    document.getElementById("deposit-id").value = "";
    
    populateDepositAccountsDropdown();
    
    // Set default day input constraints and next execution date to tomorrow
    const dayInput = document.getElementById("deposit-day-of-period");
    dayInput.disabled = false;
    dayInput.required = true;
    dayInput.value = 5;
    document.getElementById("deposit-day-label").textContent = "Jour du mois (1 - 31)";
    
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    document.getElementById("deposit-next-date").value = tomorrow.toISOString().split('T')[0];

    // Trigger holdings loading for first account
    if (accounts.length > 0) {
        updateDepositHoldingsDropdown(accounts[0].id, "deposit-holding");
    }

    modal.classList.add("active");
    lucide.createIcons();
}

function openDepositEditModal(id) {
    const dep = deposits.find(item => item.id === id);
    if (!dep) return;

    const modal = document.getElementById("deposit-modal");
    document.getElementById("deposit-modal-title").textContent = "Modifier le Versement";
    
    document.getElementById("deposit-id").value = dep.id;
    document.getElementById("deposit-name").value = dep.name;
    
    populateDepositAccountsDropdown(dep.account_id);
    updateDepositHoldingsDropdown(dep.account_id, "deposit-holding", dep.holding_id);
    
    document.getElementById("deposit-amount").value = dep.amount;
    
    const freqSelect = document.getElementById("deposit-frequency");
    freqSelect.value = dep.frequency;
    
    const dayInput = document.getElementById("deposit-day-of-period");
    const dayLabel = document.getElementById("deposit-day-label");
    
    if (dep.frequency === 'daily') {
        dayLabel.textContent = "Jour (Sans objet)";
        dayInput.value = 1;
        dayInput.disabled = true;
        dayInput.required = false;
    } else if (dep.frequency === 'weekly') {
        dayLabel.textContent = "Jour de la semaine (0=Lundi, 6=Dimanche)";
        dayInput.value = dep.day_of_period;
        dayInput.min = 0;
        dayInput.max = 6;
        dayInput.disabled = false;
        dayInput.required = true;
    } else if (dep.frequency === 'monthly') {
        dayLabel.textContent = "Jour du mois (1 - 31)";
        dayInput.value = dep.day_of_period;
        dayInput.min = 1;
        dayInput.max = 31;
        dayInput.disabled = false;
        dayInput.required = true;
    }

    document.getElementById("deposit-next-date").value = dep.next_execution_date;
    
    modal.classList.add("active");
    lucide.createIcons();
}

async function handleDepositFormSubmit(e) {
    e.preventDefault();
    const id = document.getElementById("deposit-id").value;
    const account_id = parseInt(document.getElementById("deposit-account").value);
    
    if (!account_id) {
        alert("Veuillez sélectionner un compte support.");
        return;
    }

    const holdingVal = document.getElementById("deposit-holding").value;
    const holding_id = holdingVal ? parseInt(holdingVal) : null;

    const payload = {
        account_id: account_id,
        holding_id: holding_id,
        name: document.getElementById("deposit-name").value,
        amount: parseFloat(document.getElementById("deposit-amount").value),
        frequency: document.getElementById("deposit-frequency").value,
        day_of_period: parseInt(document.getElementById("deposit-day-of-period").value) || 1,
        next_execution_date: document.getElementById("deposit-next-date").value,
        is_active: true
    };

    try {
        let response;
        if (id) {
            response = await fetch(`${API_URL}/api/deposits/${id}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
        } else {
            response = await fetch(`${API_URL}/api/deposits`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
        }

        if (response.ok) {
            document.getElementById("deposit-modal").classList.remove("active");
            // Refresh deposits, and also account values and holdings in case of immediate runs/modifications
            await fetchAllData(); 
            await fetchDepositsData();
        } else {
            const err = await response.json();
            alert(`Erreur: ${err.detail || "Validation échouée"}`);
        }
    } catch (error) {
        console.error(error);
        alert("Erreur lors de la sauvegarde du versement.");
    }
}

async function toggleDepositActive(id, isActive) {
    try {
        const response = await fetch(`${API_URL}/api/deposits/${id}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ is_active: isActive })
        });
        if (response.ok) {
            await fetchDepositsData();
        } else {
            alert("Erreur lors du changement de statut.");
        }
    } catch (err) {
        console.error(err);
    }
}

function deleteDeposit(id) {
    const dep = deposits.find(d => d.id === id);
    const depName = dep ? dep.name : "ce versement";
    showConfirmModal(
        "Supprimer la planification ?",
        `Voulez-vous vraiment supprimer la planification du versement "${depName}" ?`,
        async () => {
            try {
                const response = await fetch(`${API_URL}/api/deposits/${id}`, { method: "DELETE" });
                if (response.ok) {
                    await fetchDepositsData();
                } else {
                    alert("Impossible de supprimer la planification.");
                }
            } catch (err) {
                console.error(err);
            }
        }
    );
}

async function triggerDepositNow(id) {
    try {
        const response = await fetch(`${API_URL}/api/deposits/${id}/trigger`, { method: "POST" });
        if (response.ok) {
            const res = await response.json();
            alert(`Succès : ${res.message}\n${res.details}`);
            // Fetch everything again so holdings and dashboard are synchronized
            await fetchAllData();
            await fetchDepositsData();
        } else {
            const err = await response.json();
            alert(`Échec : ${err.detail || "Le versement n'a pas pu être exécuté."}`);
            await fetchDepositsData(); // Refresh history log which might have failure log
        }
    } catch (error) {
        console.error(error);
        alert("Une erreur s'est produite lors de l'exécution.");
    }
}
