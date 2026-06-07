// API base URL configuration (empty for relative paths since frontend is served by FastAPI)
const API_URL = "";

// Global State
let accounts = [];
let holdings = [];
let portfolioSummary = null;
let portfolioHistory = [];

// Chart instances
let historyChart = null;
let accountAllocationChart = null;
let categoryAllocationChart = null;

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
            }
        });
    });

    // Refresh Price Button
    refreshBtn.addEventListener("click", handleRefreshPrices);

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
}

async function fetchAllData() {
    try {
        const [accountsRes, holdingsRes, summaryRes, historyRes] = await Promise.all([
            fetch(`${API_URL}/api/accounts`),
            fetch(`${API_URL}/api/holdings`),
            fetch(`${API_URL}/api/portfolio/summary`),
            fetch(`${API_URL}/api/portfolio/history`)
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
    document.getElementById("kpi-total-cost").textContent = `Coût d'achat total : ${formatCurrency(portfolioSummary.total_cost)}`;

    const gainEl = document.getElementById("kpi-total-gain");
    const gainPctEl = document.getElementById("kpi-total-gain-pct");
    const gainValue = portfolioSummary.total_gain;
    const gainPct = portfolioSummary.total_gain_pct;

    gainEl.textContent = formatCurrency(gainValue);
    gainPctEl.textContent = `${formatPercent(gainPct)} de performance globale`;

    if (gainValue >= 0) {
        gainEl.className = "kpi-value gain-status positive";
        gainPctEl.className = "kpi-subtext positive";
    } else {
        gainEl.className = "kpi-value gain-status negative";
        gainPctEl.className = "kpi-subtext negative";
    }

    document.getElementById("kpi-accounts-count").textContent = accounts.length;

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
                const cost = accHoldings.reduce((sum, h) => sum + h.total_cost, 0);
                const val = accHoldings.reduce((sum, h) => sum + h.total_value, 0);
                const gain = val - cost;
                const gainPct = cost > 0 ? (gain / cost * 100) : 0.0;
                return { ...acc, cost, val, gain, gainPct };
            }).sort((a, b) => b.val - a.val);

            sortedAccounts.forEach(acc => {
                const tr = document.createElement("tr");
                const gainClass = acc.gain >= 0 ? "positive" : "negative";
                
                tr.innerHTML = `
                    <td>
                        <span class="badge ${getAccountBadgeClass(acc.type)}">${acc.name}</span>
                    </td>
                    <td><code>${acc.type}</code></td>
                    <td>${formatCurrency(acc.cost)}</td>
                    <td><strong>${formatCurrency(acc.val)}</strong></td>
                    <td>
                        <span class="gain-status ${gainClass}">
                            ${formatCurrency(acc.gain)}
                        </span>
                    </td>
                    <td>
                        <span class="gain-status ${gainClass}">
                            ${formatPercent(acc.gainPct)}
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
            return d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: '2-digit' });
        });
        const values = sortedHistory.map(h => h.total_value);
        const costs = sortedHistory.map(h => h.total_cost);

        historyChart = new Chart(histCanvas, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Valeur du Portefeuille',
                        data: values,
                        borderColor: '#6366f1',
                        backgroundColor: 'rgba(99, 102, 241, 0.1)',
                        fill: true,
                        tension: 0.3,
                        borderWidth: 3
                    },
                    {
                        label: 'Coût d\'acquisition',
                        data: costs,
                        borderColor: '#4b5563',
                        borderDash: [5, 5],
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
                <button class="table-action-btn edit" data-id="${h.id}" title="Modifier">
                    <i data-lucide="edit-3"></i>
                </button>
                <button class="table-action-btn delete" data-id="${h.id}" title="Supprimer">
                    <i data-lucide="trash-2"></i>
                </button>
            </td>
        `;

        tbody.appendChild(tr);
    });

    // Attach Event Listeners on newly rendered actions buttons
    document.querySelectorAll(".table-action-btn.edit").forEach(btn => {
        btn.addEventListener("click", (e) => {
            const hId = parseInt(btn.getAttribute("data-id"));
            openHoldingEditModal(hId);
        });
    });

    document.querySelectorAll(".table-action-btn.delete").forEach(btn => {
        btn.addEventListener("click", (e) => {
            const hId = parseInt(btn.getAttribute("data-id"));
            deleteHolding(hId);
        });
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
        const cost = accHoldings.reduce((sum, h) => sum + h.total_cost, 0);
        const val = accHoldings.reduce((sum, h) => sum + h.total_value, 0);
        const gain = val - cost;
        const gainPct = cost > 0 ? (gain / cost * 100) : 0.0;
        const gainClass = gain >= 0 ? "positive" : "negative";

        const card = document.createElement("div");
        card.className = `account-card glass ${getAccountBadgeClass(acc.type)}`;
        
        card.innerHTML = `
            <div class="account-card-header">
                <div>
                    <span class="badge ${getAccountBadgeClass(acc.type)}" style="margin-bottom: 8px;">${acc.type}</span>
                    <h3>${acc.name}</h3>
                </div>
                <button class="table-action-btn delete delete-account-btn" data-id="${acc.id}" title="Supprimer ce compte support">
                    <i data-lucide="trash-2"></i>
                </button>
            </div>
            <div class="account-card-body">
                <div class="account-value-row">
                    <span class="label">Coût d'achat</span>
                    <span class="val">${formatCurrency(cost)}</span>
                </div>
                <div class="account-value-row">
                    <span class="label">Gain / Perte</span>
                    <span class="val gain-status ${gainClass}">${formatCurrency(gain)} (${formatPercent(gainPct)})</span>
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
        document.getElementById("account-form").reset();
        accountModal.classList.add("active");
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

async function handleAccountFormSubmit(e) {
    e.preventDefault();
    const payload = {
        name: document.getElementById("account-name").value,
        type: document.getElementById("account-type").value
    };

    try {
        const response = await fetch(`${API_URL}/api/accounts`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        if (response.ok) {
            document.getElementById("account-modal").classList.remove("active");
            await fetchAllData();
        } else {
            const err = await response.json();
            alert(`Erreur: ${err.detail}`);
        }
    } catch (error) {
        console.error(error);
        alert("Une erreur s'est produite lors de la création du compte.");
    }
}

async function deleteHolding(id) {
    if (!confirm("Voulez-vous vraiment supprimer ce placement ?")) return;
    
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

async function deleteAccount(id) {
    const accountHoldings = holdings.filter(h => h.account_id === id);
    let msg = "Voulez-vous vraiment supprimer ce compte support ?";
    if (accountHoldings.length > 0) {
        msg = `ATTENTION: Ce compte contient ${accountHoldings.length} placement(s). Supprimer ce compte supprimera également tous les placements associés. Continuer ?`;
    }
    
    if (!confirm(msg)) return;

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
    const intervalSelect = document.getElementById("settings-interval");
    const hourInput = document.getElementById("settings-hour");
    const minuteInput = document.getElementById("settings-minute");
    const statusText = document.getElementById("settings-status-text");

    if (!intervalSelect || !hourInput || !minuteInput || !statusText) return;

    if (systemSettings.update_interval) intervalSelect.value = systemSettings.update_interval;
    if (systemSettings.update_hour) hourInput.value = parseInt(systemSettings.update_hour);
    if (systemSettings.update_minute) minuteInput.value = parseInt(systemSettings.update_minute);

    const intervalLabel = intervalSelect.value === 'daily' ? 'quotidienne (chaque jour)' : 'hebdomadaire (le lundi)';
    const formattedHour = String(hourInput.value || 20).padStart(2, '0');
    const formattedMinute = String(minuteInput.value || 0).padStart(2, '0');
    
    statusText.textContent = `Planification active : ${intervalLabel} à ${formattedHour}:${formattedMinute}`;
}

function setupSettingsForm() {
    const form = document.getElementById("settings-form");
    if (form) {
        form.addEventListener("submit", async (e) => {
            e.preventDefault();
            const payload = {
                update_interval: document.getElementById("settings-interval").value,
                update_hour: parseInt(document.getElementById("settings-hour").value),
                update_minute: parseInt(document.getElementById("settings-minute").value)
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
