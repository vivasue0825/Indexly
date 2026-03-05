// --- Constants & Config ---
const NICKNAME_KEY = 'indexly_nickname';
const MAX_NICKNAME_LENGTH = 10;
const UPDATE_INTERVAL_MS = 60 * 1000; // 1 minute
const FLASH_DURATION_MS = 500;

// --- Dummy Data ---
// In a real app, this would come from an API.
// We keep 'id' for DOM tracking, 'currentPrice', 'change', 'changePercent'.
const INITIAL_DATA = [
  { id: 'usdkrw', name: 'USD/KRW', symbol: '환율', price: 1332.50, change: 4.20, changePercent: 0.32 },
  { id: 'jpykrw', name: 'JPY/KRW', symbol: '환율', price: 890.12, change: -2.45, changePercent: -0.27 },
  { id: 'gold', name: 'Gold', symbol: '국제 금', price: 2024.30, change: 12.50, changePercent: 0.62 },
  { id: 'silver', name: 'Silver', symbol: '국제 은', price: 22.85, change: -0.15, changePercent: -0.65 },
  { id: 'copper', name: 'Copper', symbol: '국제 구리', price: 3.84, change: 0.02, changePercent: 0.52 },
];

let marketData = JSON.parse(JSON.stringify(INITIAL_DATA)); // Deep copy

// --- DOM Elements ---
const dom = {
  nicknameContainer: document.getElementById('nickname-container'),
  nicknameDisplay: document.getElementById('nickname-display'),
  nicknameInput: document.getElementById('nickname-input'),
  editIcon: document.querySelector('.edit-icon'),
  settingsBtn: document.getElementById('settings-btn'),
  indexList: document.getElementById('index-list')
};

// --- Utilities ---
function formatNumber(num, decimals = 2) {
  return new Intl.NumberFormat('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals
  }).format(num);
}

function getStatusClass(change) {
  if (change > 0) return 'status-up';
  if (change < 0) return 'status-down';
  return 'status-neutral';
}

function getArrow(change) {
  if (change > 0) return '▲';
  if (change < 0) return '▼';
  return '-';
}

// --- Logic: Nickname ---
function initNickname() {
  let nickname = localStorage.getItem(NICKNAME_KEY);
  if (!nickname) {
    const randomNum = Math.floor(1000 + Math.random() * 9000); // 1000 ~ 9999
    nickname = `Indexly_${randomNum}`;
    localStorage.setItem(NICKNAME_KEY, nickname);
  }
  dom.nicknameDisplay.textContent = nickname;
}

function enableNicknameEdit() {
  const currentNav = dom.nicknameDisplay.textContent;
  dom.nicknameDisplay.hidden = true;
  dom.editIcon.hidden = true;
  dom.nicknameInput.hidden = false;
  
  dom.nicknameInput.value = currentNav;
  dom.nicknameInput.focus();
  // Move cursor to end
  dom.nicknameInput.setSelectionRange(currentNav.length, currentNav.length);
}

function saveNickname() {
  const newVal = dom.nicknameInput.value.trim();
  const currentVal = dom.nicknameDisplay.textContent;

  // Validation: Not empty
  if (newVal.length > 0) {
    // Limits handled by maxlength attribute, but double check
    const finalVal = newVal.substring(0, MAX_NICKNAME_LENGTH);
    localStorage.setItem(NICKNAME_KEY, finalVal);
    dom.nicknameDisplay.textContent = finalVal;
  } else {
    // Revert to current if empty
    dom.nicknameDisplay.textContent = currentVal;
  }

  dom.nicknameInput.hidden = true;
  dom.nicknameDisplay.hidden = false;
  dom.editIcon.hidden = false;
}

// Event Listeners for Nickname
dom.nicknameContainer.addEventListener('click', (e) => {
  if (dom.nicknameInput.hidden) {
    enableNicknameEdit();
  }
});

dom.nicknameInput.addEventListener('click', (e) => {
  e.stopPropagation(); // Prevent container click when already interacting with input
});

dom.nicknameInput.addEventListener('blur', saveNickname);

dom.nicknameInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    dom.nicknameInput.blur(); // Triggers blur event which calls saveNickname
  }
  if (e.key === 'Escape') {
      // Cancel edit
      dom.nicknameInput.value = dom.nicknameDisplay.textContent;
      dom.nicknameInput.blur();
  }
});


// --- Logic: List Rendering & Updates ---

function createItemElement(item) {
  const div = document.createElement('div');
  div.className = 'index-item';
  div.id = `item-${item.id}`;
  
  // Interaction Placeholder
  div.addEventListener('click', () => {
    console.log(`[Navigation] Move to Chart View: ${item.name}`);
    // In a real app: window.location.href = `/chart/${item.id}`;
    
    // Add brief visual feedback
    div.style.transform = 'scale(0.98)';
    setTimeout(() => div.style.transform = '', 150);
  });

  const statusClass = getStatusClass(item.change);
  const sign = item.change > 0 ? '+' : '';

  div.innerHTML = `
    <div class="item-info">
      <div class="item-name">${item.name}</div>
      <div class="item-symbol">${item.symbol}</div>
    </div>
    <div class="item-price-container">
      <div class="item-price ${statusClass}" data-ref="price">${formatNumber(item.price)}</div>
    </div>
    <div class="item-change-container ${statusClass}" data-ref="change-box">
      <div class="item-change">
        <span class="change-arrow">${getArrow(item.change)}</span>
        <span data-ref="change">${formatNumber(Math.abs(item.change))}</span>
      </div>
      <div class="item-change-percent" data-ref="percent">${sign}${formatNumber(item.changePercent)}%</div>
    </div>
  `;
  return div;
}

function renderInitialList() {
  dom.indexList.innerHTML = '';
  marketData.forEach(item => {
    dom.indexList.appendChild(createItemElement(item));
  });
}

function updateItemDOM(oldItem, newItem) {
  const el = document.getElementById(`item-${newItem.id}`);
  if (!el) return;

  const priceEl = el.querySelector('[data-ref="price"]');
  const changeBoxEl = el.querySelector('[data-ref="change-box"]');
  const arrowEl = el.querySelector('.change-arrow');
  const changeEl = el.querySelector('[data-ref="change"]');
  const percentEl = el.querySelector('[data-ref="percent"]');

  const newStatusClass = getStatusClass(newItem.change);
  const oldStatusClass = getStatusClass(oldItem.change);
  const sign = newItem.change > 0 ? '+' : '';

  // Only update DOM if values actually changed to prevent unnecessary reflows
  if (oldItem.price !== newItem.price) {
    priceEl.textContent = formatNumber(newItem.price);
    
    // Update classes
    priceEl.classList.remove(oldStatusClass);
    priceEl.classList.add(newStatusClass);
    
    changeBoxEl.classList.remove(oldStatusClass);
    changeBoxEl.classList.add(newStatusClass);
    
    arrowEl.textContent = getArrow(newItem.change);
    changeEl.textContent = formatNumber(Math.abs(newItem.change));
    percentEl.textContent = `${sign}${formatNumber(newItem.changePercent)}%`;

    // Visual flash effect to indicate update
    el.classList.remove('flash-update');
    // Trigger reflow
    void el.offsetWidth;
    el.classList.add('flash-update');
  }
}

function simulateMarketUpdate() {
  const newMarketData = marketData.map(item => {
    // 50% chance to update an item
    if (Math.random() > 0.5) return { ...item };

    const volatility = item.price * 0.002; // 0.2% max change
    const priceChange = (Math.random() - 0.5) * 2 * volatility;
    
    const newPrice = Math.max(0, item.price + priceChange);
    // Keep cumulative change simple for dummy simulation
    const newChange = item.change + priceChange; 
    const basePrice = item.price - item.change; // Approximate initial price
    const newPercent = (newChange / basePrice) * 100;

    return {
      ...item,
      price: newPrice,
      change: newChange,
      changePercent: newPercent
    };
  });

  // Partially update DOM
  newMarketData.forEach((newItem, index) => {
    const oldItem = marketData[index];
    if (oldItem.price !== newItem.price) {
       updateItemDOM(oldItem, newItem);
    }
  });

  marketData = newMarketData;
  console.log(`[Market Update] Refreshed at ${new Date().toLocaleTimeString()}`);
}

// --- Initialization ---

dom.settingsBtn.addEventListener('click', () => {
  console.log('[Navigation] Move to Index Setting');
});

// App Start
document.addEventListener('DOMContentLoaded', () => {
  initNickname();
  renderInitialList();
  
  // Start 1-minute interval update
  setInterval(simulateMarketUpdate, UPDATE_INTERVAL_MS);
  
  // Note: For debugging/reviewing easily without waiting 1 min, you could expose it:
  window._forceUpdate = simulateMarketUpdate;
});
