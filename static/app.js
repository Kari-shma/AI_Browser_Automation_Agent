// State management
let state = {
    flows: [],
    runs: [],
    activeFlowId: null,
    activeRunId: null
};

// Elements
const els = {
    btnSettings: document.getElementById('btn-settings'),
    settingsModal: document.getElementById('settings-modal'),
    closeSettings: document.getElementById('close-settings'),
    saveSettings: document.getElementById('save-settings'),
    settingProvider: document.getElementById('setting-provider'),
    settingApiKey: document.getElementById('setting-api-key'),
    settingBaseUrl: document.getElementById('setting-base-url'),
    
    inputUrl: document.getElementById('input-url'),
    inputGoal: document.getElementById('input-goal'),
    btnDiscover: document.getElementById('btn-discover'),
    flowsList: document.getElementById('flows-list'),
    
    flowEmptyState: document.getElementById('flow-empty-state'),
    flowDetailCard: document.getElementById('flow-detail-card'),
    detailFlowName: document.getElementById('detail-flow-name'),
    detailFrameworkBadge: document.getElementById('detail-framework-badge'),
    detailUrl: document.getElementById('detail-url'),
    detailCreated: document.getElementById('detail-created'),
    stepsContainer: document.getElementById('steps-container'),
    
    tabBtnScript: document.getElementById('tab-btn-script'),
    codeEditorBlock: document.getElementById('code-editor-block'),
    btnSaveScript: document.getElementById('btn-save-script'),
    btnGenerateScript: document.getElementById('btn-generate-script'),
    btnRunFlow: document.getElementById('btn-run-flow'),
    
    runsList: document.getElementById('runs-list'),
    runEmptyState: document.getElementById('run-empty-state'),
    runDetailCard: document.getElementById('run-detail-card'),
    runStatusBadge: document.getElementById('run-status-badge'),
    runMetaInfo: document.getElementById('run-meta-info'),
    linkLog: document.getElementById('link-log'),
    linkDom: document.getElementById('link-dom'),
    
    visualRegressionSection: document.getElementById('visual-regression-section'),
    btnPromoteBaseline: document.getElementById('btn-promote-baseline'),
    btnViewDiff: document.getElementById('btn-view-diff'),
    
    diagnosisPanel: document.getElementById('diagnosis-panel'),
    diagErrorType: document.getElementById('diag-error-type'),
    diagStep: document.getElementById('diag-step'),
    diagDesc: document.getElementById('diag-desc'),
    diagAlternatives: document.getElementById('diag-alternatives'),
    
    diffModal: document.getElementById('diff-modal'),
    closeDiff: document.getElementById('close-diff'),
    imgBaseline: document.getElementById('img-baseline'),
    imgCurrent: document.getElementById('img-current'),
    imgDiff: document.getElementById('img-diff'),
    
    loadingOverlay: document.getElementById('loading-overlay'),
    loadingText: document.getElementById('loading-text'),

    watchLive: document.getElementById('chk-watch-live')
};

// Init app
document.addEventListener('DOMContentLoaded', () => {
    loadSettings();
    bindEvents();
    fetchFlows();
    fetchRuns();
});

// Load Settings from LocalStorage
function loadSettings() {
    els.settingProvider.value = localStorage.getItem('provider') || 'openai';
    els.settingApiKey.value = localStorage.getItem('apiKey') || '';
    els.settingBaseUrl.value = localStorage.getItem('baseUrl') || '';
    toggleBaseUrlField();
    updateHeaderStatus();
}

function updateHeaderStatus() {
    const apiKey = localStorage.getItem('apiKey');
    const provider = localStorage.getItem('provider') || 'openai';
    const el = document.getElementById('header-status');
    const textEl = document.getElementById('header-status-text');
    if (apiKey) {
        el.className = 'header-status-indicator configured';
        textEl.textContent = `${provider} connected`;
    } else {
        el.className = 'header-status-indicator unconfigured';
        textEl.textContent = 'No API key';
    }
}

function toggleBaseUrlField() {
    const isOpenRouter = els.settingProvider.value === 'openrouter';
    document.getElementById('group-base-url').style.display = isOpenRouter ? 'block' : 'none';
    if (isOpenRouter && !els.settingBaseUrl.value) {
        els.settingBaseUrl.value = 'https://openrouter.ai/api/v1';
    }
}

// Get API Request Headers
function getHeaders() {
    const headers = {
        'Content-Type': 'application/json',
        'X-API-Key': localStorage.getItem('apiKey') || ''
    };
    const provider = localStorage.getItem('provider');
    if (provider) headers['X-API-Provider'] = provider;
    
    const baseUrl = localStorage.getItem('baseUrl');
    if (baseUrl) headers['X-API-Base-Url'] = baseUrl;
    
    return headers;
}

// Bind UI events
function bindEvents() {
    // Settings modal
    els.btnSettings.addEventListener('click', () => els.settingsModal.style.display = 'flex');
    els.closeSettings.addEventListener('click', () => els.settingsModal.style.display = 'none');
    els.saveSettings.addEventListener('click', () => {
        localStorage.setItem('provider', els.settingProvider.value);
        localStorage.setItem('apiKey', els.settingApiKey.value);
        localStorage.setItem('baseUrl', els.settingBaseUrl.value);
        els.settingsModal.style.display = 'none';
        showToast('Settings saved.', 'success');
        updateHeaderStatus();
    });
    els.settingProvider.addEventListener('change', toggleBaseUrlField);
    
    // Discovery
    els.btnDiscover.addEventListener('click', triggerDiscovery);
    
    // Tab switching
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.style.display = 'none');
            
            btn.classList.add('active');
            const tabId = btn.getAttribute('data-tab');
            document.getElementById(tabId).style.display = 'flex';
            
            if (tabId === 'tab-script') {
                loadScript(state.activeFlowId);
            }
        });
    });
    
    // Script & execution actions
    els.btnGenerateScript.addEventListener('click', generateScript);
    els.btnSaveScript.addEventListener('click', saveScriptChanges);
    els.btnRunFlow.addEventListener('click', executeFlow);
    
    // Baseline & visual diff modal
    els.btnPromoteBaseline.addEventListener('click', setBaseline);
    els.btnViewDiff.addEventListener('click', openDiffModal);
    els.closeDiff.addEventListener('click', () => els.diffModal.style.display = 'none');
}

// Loading Spinner Helpers
function showLoading(text) {
    els.loadingText.textContent = text;
    els.loadingOverlay.style.display = 'flex';
}

function hideLoading() {
    els.loadingOverlay.style.display = 'none';
}

// Show non-blocking toast notifications
function showToast(msg, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = msg;
    container.appendChild(toast);

    setTimeout(() => {
        toast.classList.add('toast-out');
        toast.addEventListener('animationend', () => toast.remove(), { once: true });
    }, 3500);
}

// Fetch Flows List
async function fetchFlows() {
    try {
        const res = await fetch('/api/flows');
        state.flows = await res.json();
        renderFlows();
    } catch (e) {
        console.error('Error fetching flows:', e);
    }
}

// Fetch Runs List
async function fetchRuns() {
    try {
        const res = await fetch('/api/runs');
        state.runs = await res.json();
        renderRuns();
    } catch (e) {
        console.error('Error fetching runs:', e);
    }
}

// Render Flows to DOM
function renderFlows() {
    if (state.flows.length === 0) {
        els.flowsList.innerHTML = `
            <div class="empty-state">
                <i class="fa-solid fa-folder-open"></i>
                <p>No flows discovered yet.</p>
            </div>`;
        return;
    }
    
    els.flowsList.innerHTML = state.flows.map(flow => `
        <div class="flow-item ${state.activeFlowId === flow.flow_id ? 'active' : ''}" onclick="selectFlow('${flow.flow_id}')">
            <h3>${flow.flow_name}</h3>
            <p>${flow.url}</p>
        </div>
    `).join('');
}

// Render Runs to DOM
function renderRuns() {
    if (state.runs.length === 0) {
        els.runsList.innerHTML = `
            <div class="empty-state">
                <i class="fa-solid fa-history"></i>
                <p>No runs recorded yet.</p>
            </div>`;
        return;
    }
    
    els.runsList.innerHTML = state.runs.map(run => {
        const date = new Date(run.timestamp).toLocaleTimeString();
        let badgeClass = run.status;
        return `
            <div class="run-item ${state.activeRunId === run.run_id ? 'active' : ''}" onclick="selectRun('${run.run_id}')">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <h3>Run #${run.run_id.substring(0, 8)}</h3>
                    <span class="status-badge ${badgeClass}">${run.status}</span>
                </div>
                <p>Flow: ${state.flows.find(f => f.flow_id === run.flow_id)?.flow_name || 'Unknown'}</p>
                <p style="display:flex; justify-content:space-between;">
                    <span>Duration: ${(run.duration_ms / 1000).toFixed(1)}s</span>
                    <span>${date}</span>
                </p>
            </div>
        `;
    }).join('');
}

// Select a Flow
function selectFlow(flowId) {
    state.activeFlowId = flowId;
    renderFlows();
    
    const flow = state.flows.find(f => f.flow_id === flowId);
    if (!flow) return;
    
    els.flowEmptyState.style.display = 'none';
    els.flowDetailCard.style.display = 'flex';
    
    els.detailFlowName.textContent = flow.flow_name;
    els.detailFrameworkBadge.textContent = flow.target_framework || 'playwright';
    els.detailUrl.textContent = flow.url;
    els.detailUrl.href = flow.url;
    els.detailCreated.textContent = `Discovered at: ${new Date(flow.created_at).toLocaleString()}`;
    
    // Render Steps
    els.stepsContainer.innerHTML = flow.steps.map(step => `
        <div class="step-card">
            <div class="step-num">${step.step_id}</div>
            <div class="step-details">
                <h4>${step.action}</h4>
                <p>${step.description || ''}</p>
                ${step.selector ? `<span class="step-selector">${step.selector}</span>` : ''}
                ${step.value ? `<div style="font-size:0.75rem; color:var(--text-primary); margin-top:0.25rem;">Value: <strong>${step.value}</strong></div>` : ''}
            </div>
        </div>
    `).join('');
    
    // Reset tabs
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelector('.tab-btn[data-tab="tab-steps"]').classList.add('active');
    document.getElementById('tab-steps').style.display = 'flex';
    document.getElementById('tab-script').style.display = 'none';
}

// Trigger E2E Flow Discovery
async function triggerDiscovery() {
    const url = els.inputUrl.value.trim();
    const goal = els.inputGoal.value.trim();
    
    if (!url || !goal) {
        showToast('Please enter both Starting URL and Goal description.');
        return;
    }
    
    if (!localStorage.getItem('apiKey')) {
        showToast('Please configure your API Key in the API Settings first.');
        els.settingsModal.style.display = 'flex';
        return;
    }
    
    showLoading('Discovering user flows...');
    
    try {
        const response = await fetch('/api/flows/discover', {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ url, goal })
        });
        
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Failed to discover flow');
        }
        
        const flow = await response.json();
        showToast('Flow discovered successfully!', 'success');
        await fetchFlows();
        selectFlow(flow.flow_id);
    } catch (e) {
        showToast(e.message, 'error');
    } finally {
        hideLoading();
    }
}

// Generate Playwright Script
async function generateScript() {
    if (!state.activeFlowId) return;
    
    showLoading('Generating Playwright script...');
    
    try {
        const res = await fetch(`/api/flows/${state.activeFlowId}/generate`, {
            method: 'POST',
            headers: getHeaders()
        });
        
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Failed to generate script');
        }
        
        showToast('Script generated successfully!', 'success');
        els.tabBtnScript.click(); // switch to script tab
    } catch (e) {
        showToast(e.message, 'error');
    } finally {
        hideLoading();
    }
}

// Load Script Content (reads from disk, does NOT call LLM)
async function loadScript(flowId) {
    if (!flowId) return;
    els.codeEditorBlock.textContent = '# Loading...';
    try {
        const res = await fetch(`/api/flows/${flowId}/script`);
        if (res.status === 404) {
            els.codeEditorBlock.textContent = '# No script generated yet.\n# Click "Generate Script" from the Flow Steps tab.';
            return;
        }
        if (!res.ok) throw new Error('Failed to load script');
        const data = await res.json();
        els.codeEditorBlock.textContent = data.code;
    } catch (e) {
        els.codeEditorBlock.textContent = '# Failed to load script.';
    }
}

// Save Script Changes
async function saveScriptChanges() {
    if (!state.activeFlowId) return;
    const code = els.codeEditorBlock.textContent;
    try {
        const res = await fetch(`/api/flows/${state.activeFlowId}/script`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code })
        });
        if (!res.ok) throw new Error('Save failed');
        showToast('Script saved successfully.', 'success');
    } catch (e) {
        showToast('Failed to save script.', 'error');
    }
}

// Execute Flow Test Run
async function executeFlow() {
    if (!state.activeFlowId) return;

    const watchLive = els.watchLive && els.watchLive.checked;
    const messages = watchLive ? [
        'Opening browser window...',
        'Watch the browser — automation is running...',
        'Waiting for page responses...',
        'Running self-healing checks...',
        'Finalizing run report...'
    ] : [
        'Launching browser...',
        'Executing automation steps...',
        'Waiting for page responses...',
        'Running self-healing checks...',
        'Finalizing run report...'
    ];
    let msgIndex = 0;
    showLoading(messages[0]);
    const intervalId = setInterval(() => {
        msgIndex = (msgIndex + 1) % messages.length;
        if (els.loadingText) els.loadingText.textContent = messages[msgIndex];
    }, 7000);

    try {
        const res = await fetch('/api/runs', {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({
                flow_id: state.activeFlowId,
                browser: 'chromium',
                headless: !watchLive,
                max_repair_attempts: 3
            })
        });
        
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Execution failed');
        }
        
        const report = await res.json();
        showToast(`Execution finished with status: ${report.status}`, report.status === 'pass' ? 'success' : 'error');
        await fetchRuns();
        selectRun(report.run_id);
    } catch (e) {
        showToast(e.message, 'error');
    } finally {
        clearInterval(intervalId);
        hideLoading();
    }
}

// Select a Run from History
async function selectRun(runId) {
    state.activeRunId = runId;
    renderRuns();
    
    const run = state.runs.find(r => r.run_id === runId);
    if (!run) return;
    
    els.runEmptyState.style.display = 'none';
    els.runDetailCard.style.display = 'flex';
    
    els.runStatusBadge.textContent = run.status;
    els.runStatusBadge.className = `status-badge ${run.status}`;
    
    const date = new Date(run.timestamp).toLocaleString();
    els.runMetaInfo.innerHTML = `
        <p><strong>Run ID:</strong> ${run.run_id}</p>
        <p><strong>Browser:</strong> ${run.browser}</p>
        <p><strong>Duration:</strong> ${(run.duration_ms / 1000).toFixed(2)}s</p>
        <p><strong>Timestamp:</strong> ${date}</p>
    `;
    
    // Setup artifact links
    els.linkLog.href = `/artifacts/${runId}/run.log`;
    els.linkDom.href = `/artifacts/${runId}/dom_snapshot.html`;
    
    // Reset displays
    els.diagnosisPanel.style.display = 'none';
    els.visualRegressionSection.style.display = 'none';
    els.btnViewDiff.style.display = 'none';
    
    // Check for baseline screenshot availability
    if (run.artifacts.screenshot) {
        els.visualRegressionSection.style.display = 'block';
        // Verify baseline exists for flow
        checkBaseline(run.flow_id);
    }
    
    // Load diagnosis if failure occurred
    if (run.status === 'fail') {
        fetchDiagnosis(runId);
    }
}

// Fetch Self-Healing Diagnosis
async function fetchDiagnosis(runId) {
    try {
        const res = await fetch(`/api/runs/${runId}/diagnosis`);
        const diag = await res.json();
        if (diag) {
            els.diagnosisPanel.style.display = 'block';
            els.diagErrorType.textContent = diag.error_type;
            els.diagStep.textContent = diag.affected_step;
            els.diagDesc.textContent = diag.explanation;
            els.diagAlternatives.textContent = diag.suggested_alternatives.join('\n') || 'None';
        }
    } catch (e) {
        console.error('Error fetching diagnosis:', e);
    }
}

// Check Baseline
async function checkBaseline(flowId) {
    try {
        const res = await fetch(`/api/regression/${flowId}`);
        const data = await res.json();
        if (data.status === 'active') {
            els.btnViewDiff.style.display = 'inline-flex';
        }
    } catch (e) {
        console.error('Error checking baseline:', e);
    }
}

// Set baseline screenshot
async function setBaseline() {
    if (!state.activeRunId) return;
    const run = state.runs.find(r => r.run_id === state.activeRunId);
    
    try {
        const res = await fetch('/api/regression/baseline', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                flow_id: run.flow_id,
                run_id: run.run_id
            })
        });
        
        if (res.ok) {
            showToast('Baseline screenshot set successfully!', 'success');
            checkBaseline(run.flow_id);
        }
    } catch (e) {
        showToast('Failed to set baseline.', 'error');
    }
}

// Open Visual Diff comparator modal
async function openDiffModal() {
    if (!state.activeRunId) return;
    const run = state.runs.find(r => r.run_id === state.activeRunId);
    
    try {
        const bRes = await fetch(`/api/regression/${run.flow_id}`);
        const baseline = await bRes.json();
        
        els.imgBaseline.src = baseline.baseline_path;
        els.imgCurrent.src = `/artifacts/${run.run_id}/screenshot.png`;
        els.imgDiff.src = `/artifacts/${run.run_id}/visual_diff.png`;
        
        els.diffModal.style.display = 'flex';
    } catch (e) {
        showToast('Error loading visual diff screenshots.', 'error');
    }
}
