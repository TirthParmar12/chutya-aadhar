/* ============================================================
   e-Aadhaar Web Portal - Frontend Client JavaScript
   ============================================================ */

// Global State
const state = {
  userId: sessionStorage.getItem('aadhaar_user_id') || '',
  password: sessionStorage.getItem('aadhaar_password') || '',
  allUsersData: {}, // To store raw users list for admin searching
  mobileFlow: {
    mobile: '',
    name: '',
    captcha1TxnId: '',
    txnId1: '',
    otp1TxnId: '',
    eid: '',
    verifiedName: '',
    captcha2TxnId: '',
    txnId2: '',
    pdfOtpTxnId: ''
  },
  aadhaarFlow: {
    eid: '',
    name: '',
    captchaTxnId: '',
    txnId: '',
    otpTxnId: ''
  }
};

// Initialize app on DOM ready
document.addEventListener('DOMContentLoaded', () => {
  // If user is referred, store the ref link query param
  const urlParams = new URLSearchParams(window.location.search);
  const ref = urlParams.get('ref');
  if (ref) {
    localStorage.setItem('aadhaar_referrer', ref);
  }

  // Set bot link inside login box dynamically
  const botLink = document.getElementById('bot-login-link-btn');
  if (botLink) {
    botLink.href = 'https://t.me/UR_IMAGE';
  }

  checkAuthState();
});

function checkAuthState() {
  const loginScreen = document.getElementById('login-screen');
  const portalScreen = document.getElementById('portal-screen');

  if (state.userId && state.password) {
    if (loginScreen) loginScreen.style.display = 'none';
    if (portalScreen) portalScreen.style.display = 'flex';

    // Hide Admin Console tab button if not Owner
    const adminTabs = Array.from(document.querySelectorAll('.tab-btn'));
    const adminTabBtn = adminTabs.find(btn => btn.innerText.includes('Admin'));
    if (adminTabBtn) {
      if (state.userId === '7759665144') {
        adminTabBtn.style.display = 'flex';
      } else {
        adminTabBtn.style.display = 'none';
      }
    }

    fetchUserStatus();
    loadCaptcha('m-captcha-box-1', 'm-captcha-1');
    loadCaptcha('a-captcha-box', 'a-captcha');
    fetchPlans();
    
    if (state.userId === '7759665144') {
      fetchAdminStats();
    }
  } else {
    if (loginScreen) loginScreen.style.display = 'flex';
    if (portalScreen) portalScreen.style.display = 'none';
  }
}

async function handleLogin() {
  const uid = document.getElementById('login-uid').value.trim();
  const pass = document.getElementById('login-password').value.trim();

  if (!uid || !pass) {
    return showToast('User ID and Password are required', 'error');
  }

  showToast('Signing in...', 'info');

  try {
    const res = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: uid, password: pass })
    });
    const data = await res.json();
    if (data.success) {
      sessionStorage.setItem('aadhaar_user_id', uid);
      sessionStorage.setItem('aadhaar_password', pass);
      state.userId = uid;
      state.password = pass;
      showToast('Login successful!', 'success');
      checkAuthState();
    } else {
      showToast(data.message || 'Invalid User ID or Password', 'error');
    }
  } catch (err) {
    showToast('Failed to connect to authentication service', 'error');
  }
}

function handleLogout() {
  sessionStorage.removeItem('aadhaar_user_id');
  sessionStorage.removeItem('aadhaar_password');
  state.userId = '';
  state.password = '';
  showToast('Logged out successfully', 'success');
  window.location.reload();
}

// Toast notification helper
function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `
    <span>${message}</span>
  `;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}

// Fetch User Credits & Status
async function fetchUserStatus() {
  try {
    const referrer = localStorage.getItem('aadhaar_referrer') || '';
    const res = await fetch(`/api/user/status?user_id=${state.userId}&password=${state.password}&ref=${referrer}`);
    const data = await res.json();
    if (res.status === 401) {
      showToast('Session expired or invalid credentials.', 'error');
      handleLogout();
      return;
    }
    const navCredit = document.getElementById('nav-credit-count');
    if (navCredit) {
      navCredit.innerText = `${data.credits}`;
    }
    // Set referral link in input
    const refUrl = `${window.location.origin}${window.location.pathname}?ref=${state.userId}`;
    const refInput = document.getElementById('ref-link-val');
    if (refInput) refInput.value = refUrl;
  } catch (err) {
    console.error('Failed to fetch user status:', err);
  }
}

// Tab Switching
function switchTab(tabId) {
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  
  const targetTab = document.getElementById(tabId);
  if (targetTab) targetTab.classList.add('active');
  
  const btn = Array.from(document.querySelectorAll('.tab-btn')).find(b => b.getAttribute('onclick').includes(tabId));
  if (btn) btn.classList.add('active');
}

// Captcha Generator Helper
async function loadCaptcha(containerId, flowKey) {
  const box = document.getElementById(containerId);
  if (box) {
    box.innerHTML = '<span style="color:#64748b; font-size:12px;">Generating Captcha...</span>';
  }

  try {
    const res = await fetch('/api/captcha', { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      if (box) {
        box.innerHTML = `<img src="${data.captcha_image}" alt="Captcha Image">`;
      }
      if (flowKey === 'm-captcha-1') {
        state.mobileFlow.captcha1TxnId = data.captcha_txn_id;
        state.mobileFlow.txnId1 = data.transaction_id;
      } else if (flowKey === 'm-captcha-2') {
        state.mobileFlow.captcha2TxnId = data.captcha_txn_id;
        state.mobileFlow.txnId2 = data.transaction_id;
      } else if (flowKey === 'a-captcha') {
        state.aadhaarFlow.captchaTxnId = data.captcha_txn_id;
        state.aadhaarFlow.txnId = data.transaction_id;
      }
    } else {
      if (box) box.innerHTML = '<span style="color:#ef4444; font-size:12px;">Failed to load</span>';
      showToast(data.message || 'Captcha generation failed', 'error');
    }
  } catch (err) {
    if (box) box.innerHTML = '<span style="color:#ef4444; font-size:12px;">Error connecting</span>';
    showToast('Could not reach backend captcha service', 'error');
  }
}

// ------------------------------------------------------------------
// MOBILE WIZARD FLOW
// ------------------------------------------------------------------

function updateMobileProgress(stepNumber) {
  const line = document.getElementById('m-progress-line');
  const widths = ['0%', '33%', '66%', '100%'];
  if (line) line.style.width = widths[stepNumber - 1];

  for (let i = 1; i <= 4; i++) {
    const node = document.getElementById(`m-step-${i}-node`);
    if (node) {
      if (i < stepNumber) {
        node.className = 'step-node completed';
      } else if (i === stepNumber) {
        node.className = 'step-node active';
      } else {
        node.className = 'step-node';
      }
    }
  }
}

async function handleMobileStep1() {
  const mobile = document.getElementById('m-mobile').value.trim();
  const name = document.getElementById('m-name').value.trim() || 'MR';
  const captchaCode = document.getElementById('m-captcha-code-1').value.trim();

  if (!/^\d{10}$/.test(mobile)) {
    return showToast('Enter a valid 10-digit mobile number', 'error');
  }
  if (!captchaCode) {
    return showToast('Please enter the captcha characters', 'error');
  }

  showToast('Sending OTP via UIDAI...', 'info');

  try {
    const res = await fetch('/api/mobile/send-otp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: state.userId,
        password: state.password,
        mobile: mobile,
        name: name,
        captcha_code: captchaCode,
        captcha_txn_id: state.mobileFlow.captcha1TxnId,
        transaction_id: state.mobileFlow.txnId1
      })
    });
    const data = await res.json();
    if (data.success) {
      state.mobileFlow.mobile = mobile;
      state.mobileFlow.name = name;
      state.mobileFlow.otp1TxnId = data.otp_txn_id;

      document.getElementById('m-step-1').style.display = 'none';
      document.getElementById('m-step-2').style.display = 'block';
      updateMobileProgress(2);
      showToast('OTP sent successfully to your mobile!', 'success');
    } else {
      showToast(data.message || 'OTP generation failed', 'error');
      loadCaptcha('m-captcha-box-1', 'm-captcha-1');
    }
  } catch (err) {
    showToast('Failed to connect to backend', 'error');
  }
}

async function handleMobileStep2() {
  const otp = document.getElementById('m-otp-1').value.trim();
  if (!/^\d{6}$/.test(otp)) {
    return showToast('Enter valid 6-digit OTP', 'error');
  }

  showToast('Verifying OTP with UIDAI...', 'info');

  try {
    const res = await fetch('/api/mobile/verify-otp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: state.userId,
        password: state.password,
        mobile: state.mobileFlow.mobile,
        name: state.mobileFlow.name,
        otp: otp,
        otp_txn_id: state.mobileFlow.otp1TxnId,
        captcha_txn_id: state.mobileFlow.captcha1TxnId,
        captcha_code: document.getElementById('m-captcha-code-1').value.trim()
      })
    });
    const data = await res.json();
    if (data.success) {
      state.mobileFlow.eid = data.eid_number;
      state.mobileFlow.verifiedName = data.verified_name;

      document.getElementById('m-verified-info').innerText = `Name: ${data.verified_name} | EID: ${data.eid_number}`;
      document.getElementById('m-step-2').style.display = 'none';
      document.getElementById('m-step-3').style.display = 'block';
      updateMobileProgress(3);

      loadCaptcha('m-captcha-box-2', 'm-captcha-2');
      showToast('Identity verified successfully!', 'success');
    } else {
      showToast(data.message || 'OTP Verification failed', 'error');
    }
  } catch (err) {
    showToast('Failed to connect to backend', 'error');
  }
}

async function handleMobileStep3() {
  const captchaCode = document.getElementById('m-captcha-code-2').value.trim();
  if (!captchaCode) {
    return showToast('Enter PDF Captcha code', 'error');
  }

  showToast('Generating PDF Download OTP...', 'info');

  try {
    const res = await fetch('/api/aadhaar/send-otp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: state.userId,
        password: state.password,
        eid: state.mobileFlow.eid,
        captcha_code: captchaCode,
        captcha_txn_id: state.mobileFlow.captcha2TxnId,
        transaction_id: state.mobileFlow.txnId2
      })
    });
    const data = await res.json();
    if (data.success) {
      state.mobileFlow.pdfOtpTxnId = data.otp_txn_id;
      document.getElementById('m-step-3').style.display = 'none';
      document.getElementById('m-step-4').style.display = 'block';
      updateMobileProgress(4);
      showToast('Download OTP sent to your mobile!', 'success');
    } else {
      showToast(data.message || 'Failed to send Download OTP', 'error');
      loadCaptcha('m-captcha-box-2', 'm-captcha-2');
    }
  } catch (err) {
    showToast('Failed to connect to backend', 'error');
  }
}

async function handleMobileStep4() {
  const otp = document.getElementById('m-pdf-otp').value.trim();
  if (!/^\d{6}$/.test(otp)) {
    return showToast('Enter valid 6-digit Download OTP', 'error');
  }

  showToast('Downloading & decrypting PDF...', 'info');

  try {
    const res = await fetch('/api/aadhaar/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: state.userId,
        password: state.password,
        eid: state.mobileFlow.eid,
        otp: otp,
        otp_txn_id: state.mobileFlow.pdfOtpTxnId,
        transaction_id: state.mobileFlow.txnId2,
        verified_name: state.mobileFlow.verifiedName
      })
    });
    const data = await res.json();
    if (data.success) {
      displayPdfResult('m-result-box', data);
      document.getElementById('m-step-4').style.display = 'none';
      fetchUserStatus();
      showToast('PDF Downloaded successfully!', 'success');
    } else {
      showToast(data.message || 'PDF Download failed', 'error');
    }
  } catch (err) {
    showToast('Failed to connect to backend', 'error');
  }
}

function resetMobileWizard() {
  document.getElementById('m-step-1').style.display = 'block';
  document.getElementById('m-step-2').style.display = 'none';
  document.getElementById('m-step-3').style.display = 'none';
  document.getElementById('m-step-4').style.display = 'none';
  document.getElementById('m-result-box').style.display = 'none';
  updateMobileProgress(1);
  loadCaptcha('m-captcha-box-1', 'm-captcha-1');
}

// ------------------------------------------------------------------
// AADHAAR DIRECT SEARCH FLOW
// ------------------------------------------------------------------

async function handleAadhaarStep1() {
  const eid = document.getElementById('a-eid').value.trim().replace(/\s+/g, '');
  const name = document.getElementById('a-name').value.trim() || 'MR';
  const captchaCode = document.getElementById('a-captcha-code').value.trim();

  if (eid.length < 10) {
    return showToast('Enter valid Aadhaar or EID number', 'error');
  }
  if (!captchaCode) {
    return showToast('Enter Captcha code', 'error');
  }

  showToast('Sending Download OTP...', 'info');

  try {
    const res = await fetch('/api/aadhaar/send-otp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: state.userId,
        password: state.password,
        eid: eid,
        captcha_code: captchaCode,
        captcha_txn_id: state.aadhaarFlow.captchaTxnId,
        transaction_id: state.aadhaarFlow.txnId
      })
    });
    const data = await res.json();
    if (data.success) {
      state.aadhaarFlow.eid = eid;
      state.aadhaarFlow.name = name;
      state.aadhaarFlow.otpTxnId = data.otp_txn_id;

      document.getElementById('a-step-1').style.display = 'none';
      document.getElementById('a-step-2').style.display = 'block';
      showToast('OTP sent to your registered mobile!', 'success');
    } else {
      showToast(data.message || 'OTP Generation failed', 'error');
      loadCaptcha('a-captcha-box', 'a-captcha');
    }
  } catch (err) {
    showToast('Failed to connect to backend', 'error');
  }
}

async function handleAadhaarStep2() {
  const otp = document.getElementById('a-otp').value.trim();
  if (!/^\d{6}$/.test(otp)) {
    return showToast('Enter valid 6-digit OTP', 'error');
  }

  showToast('Downloading & unlocking e-Aadhaar PDF...', 'info');

  try {
    const res = await fetch('/api/aadhaar/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: state.userId,
        password: state.password,
        eid: state.aadhaarFlow.eid,
        otp: otp,
        otp_txn_id: state.aadhaarFlow.otpTxnId,
        transaction_id: state.aadhaarFlow.txnId,
        verified_name: state.aadhaarFlow.name
      })
    });
    const data = await res.json();
    if (data.success) {
      displayPdfResult('a-result-box', data);
      document.getElementById('a-step-2').style.display = 'none';
      fetchUserStatus();
      showToast('PDF Downloaded successfully!', 'success');
    } else {
      showToast(data.message || 'Download failed', 'error');
    }
  } catch (err) {
    showToast('Failed to connect to backend', 'error');
  }
}

function resetAadhaarDirect() {
  document.getElementById('a-step-1').style.display = 'block';
  document.getElementById('a-step-2').style.display = 'none';
  document.getElementById('a-result-box').style.display = 'none';
  loadCaptcha('a-captcha-box', 'a-captcha');
}

// ------------------------------------------------------------------
// STANDALONE PDF UNLOCKER
// ------------------------------------------------------------------

function updateFileName(input) {
  const label = document.getElementById('dropzone-label');
  if (input.files && input.files[0]) {
    label.innerText = `Selected: ${input.files[0].name}`;
  }
}

async function handleUnlockFile(e) {
  e.preventDefault();
  const fileInput = document.getElementById('pdf-file-input');
  const nameInput = document.getElementById('u-name').value.trim();

  if (!fileInput.files || !fileInput.files[0]) {
    return showToast('Please select a PDF file first', 'error');
  }
  if (!nameInput) {
    return showToast('Enter name for password cracking', 'error');
  }

  const formData = new FormData();
  formData.append('pdf', fileInput.files[0]);
  formData.append('name', nameInput);
  formData.append('user_id', state.userId);
  formData.append('password', state.password);

  showToast('Decrypting e-Aadhaar PDF file...', 'info');

  try {
    const res = await fetch('/api/pdf/unlock-file', {
      method: 'POST',
      body: formData
    });
    const data = await res.json();
    if (data.success) {
      displayPdfResult('u-result-box', data);
      fetchUserStatus();
      showToast('PDF Unlocked successfully!', 'success');
    } else {
      showToast(data.message || 'Cracking failed. Check name pattern.', 'error');
    }
  } catch (err) {
    showToast('Failed to unlock PDF file', 'error');
  }
}

// ------------------------------------------------------------------
// RESULT PRESENTATION & DOWNLOAD HELPER
// ------------------------------------------------------------------

function displayPdfResult(containerId, data) {
  const box = document.getElementById(containerId);
  if (!box) return;

  const isUnlocked = data.unlocked;
  const pwdText = isUnlocked ? `<p style="color:var(--accent-emerald); font-weight:700; margin-top:8px;">Decrypted Password: <code>${data.password}</code></p>` : `<p style="color:var(--text-muted); margin-top:8px;">Note: PDF is password protected. Format: First 4 Name letters + Birth Year</p>`;

  box.innerHTML = `
    <div class="result-card">
      <div class="result-icon">✓</div>
      <h3 style="font-family:'Outfit'; font-size:22px; color:#fff;">${isUnlocked ? 'Document Ready & Unlocked!' : 'e-Aadhaar PDF Ready!'}</h3>
      ${pwdText}
      <div style="margin-top:20px;">
        <a href="${data.pdf_base64}" download="${data.filename}" class="btn-primary" style="text-decoration:none; display:inline-flex; width:auto; padding:14px 32px;">
          ⬇ Download e-Aadhaar PDF
        </a>
      </div>
    </div>
  `;
  box.style.display = 'block';
}

// ------------------------------------------------------------------
// PLANS & PRICING & REFERRAL
// ------------------------------------------------------------------

async function fetchPlans() {
  try {
    const res = await fetch('/api/plans');
    const data = await res.json();
    const container = document.getElementById('plans-container');
    if (!container) return;

    container.innerHTML = data.plans.map(p => `
      <div class="price-card ${p.popular ? 'popular' : ''}">
        ${p.popular ? '<div class="popular-badge">Most Popular</div>' : ''}
        <h4 style="font-size:18px; color:var(--text-main);">${p.name}</h4>
        <div class="price-val">${p.price}</div>
        <div class="price-credits">${typeof p.credits === 'number' ? p.credits + ' Downloads' : p.credits}</div>
        <a href="https://t.me/${data.owner_telegram.replace('@', '')}" target="_blank" class="btn-secondary" style="text-decoration:none; display:block; text-align:center;">
          Buy via Telegram
        </a>
      </div>
    `).join('');
  } catch (err) {
    console.error('Failed to fetch pricing plans', err);
  }
}

function copyReferralLink() {
  const input = document.getElementById('ref-link-val');
  if (input) {
    input.select();
    document.execCommand('copy');
    showToast('Referral link copied to clipboard!', 'success');
  }
}

// ------------------------------------------------------------------
// ADMIN CONSOLE
// ------------------------------------------------------------------

async function fetchAdminStats() {
  try {
    const res = await fetch(`/api/admin/stats?admin_id=${state.userId}&password=${state.password}`);
    const data = await res.json();
    if (data.success || res.status === 200) {
      document.getElementById('adm-users').innerText = data.total_users;
      document.getElementById('adm-lifetime').innerText = data.lifetime_users;
      document.getElementById('adm-credits').innerText = data.active_credits;
      
      state.allUsersData = data.users || {};
      renderAdminUsersTable();
    } else {
      showToast(data.message || 'Failed to fetch admin stats', 'error');
    }
  } catch (err) {
    console.error('Failed to fetch admin stats', err);
  }
}

async function handleAdminAddCredits() {
  const uid = document.getElementById('adm-target-user').value.trim();
  const amt = parseInt(document.getElementById('adm-target-amount').value.trim());

  if (!uid) return showToast('Enter user ID', 'error');

  try {
    const res = await fetch('/api/admin/add-credits', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        admin_id: state.userId,
        password: state.password,
        user_id: uid,
        amount: amt
      })
    });
    const data = await res.json();
    if (data.success) {
      showToast(data.message, 'success');
      fetchAdminStats();
      fetchUserStatus();
    } else {
      showToast(data.message || 'Failed to add credits', 'error');
    }
  } catch (err) {
    showToast('Failed to update credits', 'error');
  }
}

function renderAdminUsersTable(usersToRender = state.allUsersData) {
  const tbody = document.getElementById('adm-users-table-body');
  if (!tbody) return;

  tbody.innerHTML = '';

  const entries = Object.entries(usersToRender);
  if (entries.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="padding: 16px; text-align: center; color: var(--text-muted);">No users found</td></tr>`;
    return;
  }

  // Sort users by joined date (descending)
  entries.sort((a, b) => {
    const dateA = new Date(a[1].joined || 0);
    const dateB = new Date(b[1].joined || 0);
    return dateB - dateA;
  });

  tbody.innerHTML = entries.map(([uid, u]) => {
    const typeText = u.lifetime ? '<span style="color:var(--accent-purple); font-weight:700;">Lifetime</span>' : 'Regular';
    const creditsVal = u.lifetime ? '∞' : (u.credits !== undefined ? u.credits : 0);
    const passwordVal = u.password ? `<code>${u.password}</code>` : '<em style="color:var(--text-dim);">none</em>';
    const joinedVal = u.joined ? u.joined.substring(0, 10) : '—';

    return `
      <tr>
        <td style="padding: 12px 16px; font-family: monospace; color:#fff;">${uid}</td>
        <td style="padding: 12px 16px;">${passwordVal}</td>
        <td style="padding: 12px 16px; font-weight: 600; color:var(--primary-cyan);">${creditsVal}</td>
        <td style="padding: 12px 16px;">${typeText}</td>
        <td style="padding: 12px 16px; text-align: center;">${u.referral_count || 0}</td>
        <td style="padding: 12px 16px; color: var(--text-muted);">${joinedVal}</td>
      </tr>
    `;
  }).join('');
}

function filterAdminUsersTable() {
  const query = document.getElementById('adm-user-search').value.trim().toLowerCase();
  if (!query) {
    renderAdminUsersTable(state.allUsersData);
    return;
  }

  const filtered = {};
  for (const [uid, u] of Object.entries(state.allUsersData)) {
    if (uid.toLowerCase().includes(query)) {
      filtered[uid] = u;
    }
  }
  renderAdminUsersTable(filtered);
}
