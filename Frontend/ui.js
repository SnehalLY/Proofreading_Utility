let questions = [];
let allQBs = [];
let currentUser = null;


function showLoader() {
    document.getElementById("globalLoader").classList.remove("hidden");
}

function hideLoader() {
    document.getElementById("globalLoader").classList.add("hidden");
}

// =====================================================
// HELPER: DISPLAY CHANGES
// =====================================================
function renderChangesSection(changes) {
    if (!changes || Object.keys(changes).length === 0) {
        return '';
    }
    
    let changesHTML = `
    <div class="bg-yellow-50 p-3 rounded mb-3 border-l-4 border-yellow-400">
        <div class="font-semibold text-yellow-800 mb-2">📝 Changes Made:</div>
        <div class="space-y-2 text-sm">
    `;
    
    Object.entries(changes).forEach(([field, change]) => {
        const original = change.original || '[Not provided]';
        const modified = change.modified || '[Not provided]';
        
        // Truncate long values for readability
        const truncateValue = (val, limit = 100) => {
            const str = String(val).trim();
            return str.length > limit ? str.substring(0, limit) + '...' : str;
        };
        
        changesHTML += `
            <div class="bg-white p-2 rounded border border-yellow-200">
                <div class="font-semibold text-gray-700">${escapeHTML(field)}:</div>
                <div class="text-red-600 line-through text-xs mt-1">
                    <span class="font-semibold">Was:</span> ${escapeHTML(truncateValue(original))}
                </div>
                <div class="text-green-600 text-xs mt-1">
                    <span class="font-semibold">Now:</span> ${escapeHTML(truncateValue(modified))}
                </div>
            </div>
        `;
    });
    
    changesHTML += `
        </div>
    </div>
    `;
    
    return changesHTML;
}

// =====================================================
// AUTHENTICATION CHECK
// =====================================================
async function checkAuthentication() {
    try {
        const user = localStorage.getItem('user');
        if (!user) {
            window.location.href = 'login.html';
            return;
        }
        
        currentUser = JSON.parse(user);
        
        // Display user info in header
        document.getElementById('userDisplay').textContent = currentUser.username;
        const roleEl = document.getElementById('roleDisplay');
        const _roleBadgeColors = { 'Admin': 'bg-red-100 text-red-700', 'Senior Editor': 'bg-purple-100 text-purple-700', 'Editor': 'bg-blue-100 text-blue-700' };
        roleEl.innerHTML = `<span class="inline-block px-2 py-0.5 rounded-full text-xs font-semibold ${_roleBadgeColors[currentUser.role] || 'bg-gray-100 text-gray-600'}">${currentUser.role}</span>`;

        // Show pending requests button only for Admins
        try {
            const pendingBtn = document.getElementById('pendingReqBtn');
            if (pendingBtn) {
                if (currentUser.role === 'Admin') pendingBtn.classList.remove('hidden');
                else pendingBtn.classList.add('hidden');
            }
        } catch (e) {
            console.warn('pendingReqBtn not found in DOM');
        }

        // Show backfill button only for Admins
        try {
            const backfillBtn = document.getElementById('btnBackfillAudit');
            if (backfillBtn) {
                if (currentUser.role === 'Admin') backfillBtn.classList.remove('hidden');
                else backfillBtn.classList.add('hidden');
            }
        } catch (e) {
            console.warn('btnBackfillAudit not found in DOM');
        }

        // Show batch push button for Admin only
        try {
            const batchPushBtn = document.getElementById('batchPushBtn');
            if (batchPushBtn) {
                if (currentUser.role === 'Admin') batchPushBtn.classList.remove('hidden');
                else batchPushBtn.classList.add('hidden');
            }
        } catch (e) {
            console.warn('batchPushBtn not found in DOM');
        }

        // Show overall History button for all authenticated users
        try {
            const activityLogBtn = document.getElementById('activityLogBtn');
            if (activityLogBtn) {
                activityLogBtn.classList.remove('hidden');
            }
        } catch (e) {
            console.warn('activityLogBtn not found in DOM');
        }
        
    } catch (err) {
        console.error("Auth check error:", err);
        window.location.href = 'login.html';
    }
}

function isProtectedPage() {
    const currentPage = window.location.pathname.split('/').pop() || 'index.html';
    return !currentPage.includes('login') && !currentPage.includes('signup');
}

function enforceAuthentication() {
    if (isProtectedPage()) {
        const user = localStorage.getItem('user');
        if (!user) {
            window.location.href = 'login.html';
            return false;
        }
        return true;
    }
    return true;
}

async function logoutAndRedirect() {
    try {
        // try to clear server session (best-effort)
        await logoutUser();
    } catch (err) {
        console.warn('Server logout failed or not reachable, continuing locally');
    }
    localStorage.removeItem('user');
    window.location.href = 'login.html';
}

// -------------------------------
// HTML Escaping Utility
// -------------------------------
function escapeHTML(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// -------------------------------
// Load Question Banks
// -------------------------------
async function loadQBs() {
    try {
        const qbs = await fetchQBs();

        // Trim names to remove leading/trailing spaces
        allQBs = qbs.map(qb => ({
            id: qb.id,
            name: qb.name.trim()
        }));

        const datalist = document.getElementById("qbList");
        datalist.innerHTML = "";

        allQBs.forEach(qb => {
            const option = document.createElement("option");
            option.value = qb.name;   // cleaned name
            datalist.appendChild(option);
        });

    } catch (err) {
        console.error("Error loading QBs:", err);
    }
}

// -------------------------------
// Load Questions by QB
// -------------------------------
async function loadQuestionsByQB() {
    try {
        const input = document.getElementById("qbInput");
        const typedValue = input.value.trim().toLowerCase();

        if (!typedValue) {
            alert("Please enter a Question Bank name.");
            return;
        }

        // ✅ Allow partial match instead of exact match
        const matchedQB = allQBs.find(qb =>
            qb.name.toLowerCase().includes(typedValue)
        );

        if (!matchedQB) {
            alert(allQBs.length === 0
                ? 'Question Banks not loaded yet. Please refresh the page and try again.'
                : 'No matching Question Bank found.');
            return;
        }

        // Show feedback — QB with many questions can take ~30s on Azure SQL
        const btn = document.querySelector('button[onclick="loadQuestionsByQB()"]');
        const origText = btn ? btn.textContent : '';
        if (btn) btn.textContent = 'Loading...';

        try {
            // Show inline loading feedback while waiting for the server
            document.getElementById('fullQuestionView').innerHTML = '<div class="flex flex-col items-center justify-center py-20 text-gray-400 gap-3"><div class="w-10 h-10 border-4 border-[#FF6B00] border-t-transparent rounded-full animate-spin"></div><span class="text-sm">Loading questions…</span></div>';
            document.getElementById('resultsList').innerHTML = '<div class="text-center text-gray-400 text-sm py-4">Loading…</div>';
            document.getElementById('resultCount').textContent = '…';
            const raw = await fetchQuestionsByQB(matchedQB.id);

            if (!Array.isArray(raw) || raw.length === 0) {
                renderQuestionList([]);
                return;
            }

            questions = raw.map(q => ({
                id: q.id,
                displayId: `QID-${q.id}`,
                bank: matchedQB.name,
                qbId: q.qb_id || matchedQB.id || null,
                question: q.questionText,
                difficulty: q.difficultyLevel || "Easy",
                status: q.reviewStatus === 'Reviewed' ? 'Completed' : (q.reviewStatus || "Pending"),
                reviewedBy: q.ReviewedByName || q.ReviewedBy || null,
                reviewedOn: q.ReviewedOn || null,
                isEdited: q.isEdited || false,
                source: q.source || 'rtu',
                lastModifiedBy: q.lastModifiedBy || null,
                lastModifiedDate: q.lastModifiedDate || null,
                isSynced: q.isSynced || false,
                lastSyncedByName: q.lastSyncedByName || null,
                lastSyncedDate: q.lastSyncedDate || null,
                changes: q.changes || {},
                options: {
                    A: q.optionA || "",
                    B: q.optionB || "",
                    C: q.optionC || "",
                    D: q.optionD || ""
                },
                answer: q.correctAnswer || "A",
                explanation: q.answerExplanation || ""
            }));

            renderQuestionList(questions);
            const ctxEl = document.getElementById('resultContext');
            if (ctxEl) ctxEl.textContent = matchedQB.name;

        } catch (fetchErr) {
            console.error('QB fetch error:', fetchErr);
            alert('Failed to load questions: ' + (fetchErr.name === 'AbortError' ? 'Request timed out (60s). The server may be slow, please try again.' : fetchErr.message));
        } finally {
            if (btn) btn.textContent = origText;
        }

    } catch (err) {
        console.error("Error loading questions:", err);
    }
}
// -------------------------------
// Search by QID
// -------------------------------
async function searchByQID() {
    showLoader();
    try {
        const input = document.getElementById("searchInput");
        let qid = input.value.trim();

        if (!qid) {
            alert("Please enter a QID (e.g. QID-268)");
            return;
        }

        const result = await fetchQuestionByQID(qid);

        if (!result || !result.id) {
            renderQuestionList([]);
            return;
        }

        // Extract first correct answer if multiple (e.g., "A,B,C" -> "A")
        const correctAnswerValue = result.correctAnswer 
            ? result.correctAnswer.split(',')[0].trim()
            : "A";

        // Normalize the data - VALIDATE EACH FIELD
       const normalizedQuestion = {
            id: result.id,
            displayId: result.id ? `QID-${result.id}` : "QID-UNKNOWN",
            bank: result.skill ? String(result.skill).trim() : "Unknown Bank",
            qbId: result.qb_id || null,
            question: result.questionText ? String(result.questionText).trim() : "No question text",
            difficulty: result.difficultyLevel ? String(result.difficultyLevel).trim() : "Easy",
            status: result.reviewStatus === 'Reviewed' ? 'Completed' : (result.reviewStatus || "Pending"),
            reviewedBy: result.ReviewedByName || result.ReviewedBy || null,
            reviewedOn: result.ReviewedOn || null,
            isEdited: result.isEdited || false,
            source: result.source || 'rtu',
            lastModifiedBy: result.lastModifiedBy || null,
            lastModifiedDate: result.lastModifiedDate || null,
            isSynced: result.isSynced || false,
            lastSyncedByName: result.lastSyncedByName || null,
            lastSyncedDate: result.lastSyncedDate || null,
            changes: result.changes || {},
            options: {
                A: result.optionA !== null && result.optionA !== undefined ? String(result.optionA).trim() || "[No Option A]" : "[No Option A]",
                B: result.optionB !== null && result.optionB !== undefined ? String(result.optionB).trim() || "[No Option B]" : "[No Option B]",
                C: result.optionC !== null && result.optionC !== undefined ? String(result.optionC).trim() || "[No Option C]" : "[No Option C]",
                D: result.optionD !== null && result.optionD !== undefined ? String(result.optionD).trim() || "[No Option D]" : "[No Option D]"
            },
            answer: correctAnswerValue,
            explanation: result.answerExplanation ? String(result.answerExplanation).trim() : "No explanation"
        };

        questions = [normalizedQuestion];
        renderQuestionList(questions);
        const ctxEl2 = document.getElementById('resultContext');
        if (ctxEl2) ctxEl2.textContent = 'QID search';

    } catch (err) {
        console.error("🔴 ERROR in searchByQID:", err);
        alert('Failed to load question: ' + err.message);
    } finally {
        hideLoader();
    }
}
// -------------------------------
// Render Results
// -------------------------------
function renderQuestionList(questionArray) {

    const resultList = document.getElementById("resultsList");
    const fullView = document.getElementById("fullQuestionView");
    const countSpan = document.getElementById("resultCount");

    resultList.innerHTML = "";
    fullView.innerHTML = "";
    
    // Handle both single question and array of questions
    const questionsToRender = Array.isArray(questionArray) ? questionArray : [questionArray];
    countSpan.textContent = questionsToRender.length;

    if (!questionsToRender || questionsToRender.length === 0) {
        resultList.innerHTML = `<div class="text-gray-400 text-sm">No results</div>`;
        fullView.innerHTML = `<div class="text-gray-400 text-sm">No questions found</div>`;
        return;
    }

    questionsToRender.forEach((question, index) => {
        // LEFT SIDE SIMPLE LIST
        const listItem = document.createElement('div');
        listItem.className = 'p-2 border rounded cursor-pointer hover:bg-gray-50 text-sm font-medium';
        listItem.textContent = question.displayId;
        listItem.onclick = () => scrollToQuestion(question.id);
        resultList.appendChild(listItem);

        // STATUS BADGE
        let statusBadge = '';

if (question.status === "Completed") {
    statusBadge = `
        <div class="text-green-600 font-semibold">
            Completed
            ${question.reviewedBy ? `
                <div class="text-xs text-gray-500">
                    by ${escapeHTML(question.reviewedBy)}
                    ${question.reviewedOn ? `on ${new Date(question.reviewedOn).toLocaleString()}` : ''}
                </div>
            ` : ''}
        </div>
    `;
} else {
    statusBadge = `<span class="text-red-500 font-semibold">Pending</span>`;
}

        // RIGHT SIDE FULL VIEW - Create elements
        const questionCard = document.createElement('div');
        questionCard.id = `question-${question.displayId}`;
        questionCard.className = 'border rounded-lg p-5 bg-white';
        
        questionCard.innerHTML = `
            <div class="flex justify-between items-start mb-3">
                <div>
                    <div class="flex items-center gap-2">
                        <span class="font-bold text-lg">QID: ${escapeHTML(question.displayId.replace('QID-', ''))}</span>
                        <span class="text-gray-300 font-light">|</span>
                        <span class="text-sm text-gray-500">QB Name: ${escapeHTML(question.bank)}</span>
                    </div>
                    ${question.status === 'Completed' ? `<div class="text-xs bg-green-100 text-green-700 px-2 py-1 rounded mt-1 inline-block">Completed</div>` : question.isEdited ? `<div class="text-xs bg-red-100 text-red-700 px-2 py-1 rounded mt-1 inline-block">Edited</div>` : ''}
                </div>

                <button class="edit-btn bg-[#FF6B00] hover:bg-[#E66000] text-white text-xs font-semibold px-3 py-1.5 rounded-md transition" data-qid="${escapeHTML(question.displayId)}">
                    Edit
                </button>
            </div>

            <div class="mb-3 font-medium">
                Q: ${escapeHTML(question.question)}
            </div>

            <div class="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-3">
                <div>A) ${escapeHTML(question.options.A)}</div>
                <div>B) ${escapeHTML(question.options.B)}</div>
                <div>C) ${escapeHTML(question.options.C)}</div>
                <div>D) ${escapeHTML(question.options.D)}</div>
            </div>

            <div class="bg-gray-50 p-3 rounded text-sm mb-3">
                <strong>Explanation:</strong> ${escapeHTML(question.explanation)}
            </div>

            ${question.isEdited && Object.keys(question.changes).length > 0 ? renderChangesSection(question.changes) : ''}

            <div class="flex justify-between items-center text-sm border-t pt-3 mb-3">
                <div>
                    <strong>Difficulty:</strong> ${escapeHTML(question.difficulty)}
                </div>
                <div>
                    <strong>Status:</strong> ${statusBadge}
                </div>
            </div>

            ${question.isSynced ? `
            <div class="text-sm border-t pt-3 mb-3">
                <strong>Pushed to RTU:</strong>
                <div class="text-green-600 font-semibold mt-1">
                    Pushed
                    <div class="text-xs text-gray-500">
                        by ${question.lastSyncedByName || 'Unknown'}
                        ${question.lastSyncedDate ? `on ${new Date(question.lastSyncedDate).toLocaleString()}` : ''}
                    </div>
                </div>
            </div>
            ` : ''}
            
            ${question.isEdited ? `
            <div class="bg-blue-50 p-2 rounded text-xs text-gray-700 mb-2 border-l-4 border-blue-400">
                <strong>📝 Last Modified:</strong> ${question.lastModifiedBy || 'Unknown'} on ${question.lastModifiedDate ? new Date(question.lastModifiedDate).toLocaleString() : 'Unknown date'}
            </div>
            ` : ''}
            
            <div class="flex gap-2 mt-1">
                <button class="track-versions-btn text-xs bg-indigo-100 hover:bg-indigo-200 text-indigo-800 font-semibold px-3 py-1 rounded" onclick="trackVersions(${question.id})">Track Versions</button>
                <button class="text-xs bg-gray-100 hover:bg-gray-200 text-gray-700 font-semibold px-3 py-1 rounded" onclick="showQuestionHistory(${question.id})">History</button>
            </div>
        `;
        
        // Add event listener for Edit button
        const editBtn = questionCard.querySelector('.edit-btn');
        editBtn.addEventListener('click', () => selectQuestion(question.id));
        
        fullView.appendChild(questionCard);
    });
}


// -------------------------------
function selectQuestion(id) {
    const q = questions.find(item => item.id === id);
    if (!q) return;


    
    document.getElementById("mainEditor").classList.remove("hidden");

    document.getElementById("displayQid").innerText = 'QID: ' + q.displayId.replace('QID-', '');
    document.getElementById("displayBank").innerText = q.bank || '';

    document.getElementById("fieldQuestion").value = q.question;
    document.getElementById("fieldOptA").value = q.options.A;
    document.getElementById("fieldOptB").value = q.options.B;
    document.getElementById("fieldOptC").value = q.options.C;
    document.getElementById("fieldOptD").value = q.options.D;

    document.getElementById("fieldAnswer").value = q.answer;
    document.getElementById("fieldDifficulty").value = q.difficulty;
    document.getElementById("fieldExplanation").value = q.explanation;

    // Snapshot original values so Save can detect whether anything actually changed
    window.originalFormValues = {
        question:    q.question,
        optionA:     q.options.A,
        optionB:     q.options.B,
        optionC:     q.options.C,
        optionD:     q.options.D,
        explanation: q.explanation
    };

    // Store current question ID + QB info for actions
    window.currentQuestionId = id;
    window.currentQBId   = q.qbId   || null;
    window.currentQBName = q.bank   || null;
    
    // Set read-only based on role (Editor, Senior Editor and Admin can edit)
    const canEdit = currentUser && (currentUser.role === 'Editor' || currentUser.role === 'Senior Editor' || currentUser.role === 'Admin');
    setReadOnlyMode(!canEdit);
    
    // Show/hide action buttons based on role
    const btnSave = document.getElementById('btnSave');
    const btnReview = document.getElementById('btnReview');
    const btnPushRTU = document.getElementById('btnPushRTU');
    
    // Hide all buttons first
    btnSave.classList.add('hidden');
    btnReview.classList.add('hidden');
    btnPushRTU.classList.add('hidden');
    
    // Show save button for Editor, Senior Editor and Admin
    if (currentUser.role === 'Editor' || currentUser.role === 'Senior Editor' || currentUser.role === 'Admin') {
        btnSave.classList.remove('hidden');
    }
    
    // Show review and push buttons for Admin, Senior Editor, and Editor
    if (currentUser.role === 'Admin' || currentUser.role === 'Senior Editor' || currentUser.role === 'Editor') {
        btnReview.classList.remove('hidden');
        btnPushRTU.classList.remove('hidden');
    }
}


// -------------------------------
function setReadOnlyMode(isReadOnly) {
    // Editable fields: question text, options, explanation
    ["fieldQuestion","fieldOptA","fieldOptB","fieldOptC","fieldOptD","fieldExplanation"]
        .forEach(id => {
            const el = document.getElementById(id);
            if (el) el.readOnly = isReadOnly;
        });

    // Correct Answer is NEVER editable - always stays disabled
    const answerEl = document.getElementById('fieldAnswer');
    if (answerEl) answerEl.disabled = true;

    // Difficulty is NEVER editable - always stays disabled
    const difficultyEl = document.getElementById('fieldDifficulty');
    if (difficultyEl) difficultyEl.disabled = true;
}

function scrollToQuestion(qid) {
    const element = document.getElementById(`question-${qid}`);
    if (element) {
        element.scrollIntoView({ behavior: "smooth", block: "start" });
    }
}

// =====================================================
// HISTORY FUNCTIONS
// =====================================================

async function showQuestionHistory(questionId) {
    try {
        const data = await getQuestionHistory(questionId);

        const modal   = document.getElementById('questionHistoryModal');
        const content = document.getElementById('historyContent');
        const history = data.history || [];

        if (!history.length) {
            content.innerHTML = '<div class="text-center text-gray-400 py-6">No history available for this question</div>';
            modal.classList.remove('hidden');
            return;
        }

        const fmt = iso => {
            if (!iso) return 'N/A';
            try { return new Date(iso).toLocaleString(); } catch { return iso; }
        };

        // Badge colours per action type
        const actionBadge = {
            'Review':          'bg-yellow-100 text-yellow-700',
            'PushToRTU':       'bg-green-100  text-green-700',
            'RTU ProofRead':   'bg-purple-100 text-purple-700',
        };
        // Source pill colours
        const sourcePill = {
            'versions':  'bg-blue-100   text-blue-600',
            'audit_log': 'bg-orange-100 text-orange-600',
            'rtu':       'bg-purple-100 text-purple-600',
        };
        const sourceLabel = { 'versions': 'Save', 'audit_log': 'Utility', 'rtu': 'RTU' };

        const rows = history.map(e => {
            // Save (V2) entries → blue; others look up table
            const isSave = e.source === 'versions';
            const badge  = isSave
                ? 'bg-blue-100 text-blue-700'
                : (actionBadge[e.action_type] || 'bg-gray-100 text-gray-700');
            const pill   = sourcePill[e.source]  || 'bg-gray-100 text-gray-600';
            const src    = sourceLabel[e.source] || e.source;

            return `<div class="flex items-start justify-between gap-3 border rounded px-3 py-2 mb-1.5 bg-gray-50 hover:bg-white text-xs">
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-1.5 flex-wrap">
                        <span class="px-2 py-0.5 rounded font-semibold ${badge}">${escapeHTML(e.action_type || 'Edit')}</span>
                        <span class="px-1.5 py-0.5 rounded ${pill}">${src}</span>
                        ${e.status ? `<span class="text-gray-500">${escapeHTML(e.status)}</span>` : ''}
                    </div>
                    <div class="mt-1 text-gray-700">
                        <span class="font-medium">${escapeHTML(e.performed_by_name || 'N/A')}</span>
                        ${e.performed_by_role ? `<span class="text-gray-400 ml-1">(${escapeHTML(e.performed_by_role)})</span>` : ''}
                    </div>
                    ${e.details ? `<div class="text-gray-400 mt-0.5 truncate">${escapeHTML(e.details)}</div>` : ''}
                </div>
                <div class="text-gray-400 whitespace-nowrap mt-0.5">${fmt(e.action_date)}</div>
            </div>`;
        }).join('');

        content.innerHTML =
            `<div class="text-xs text-gray-400 mb-3">${history.length} event${history.length !== 1 ? 's' : ''} — newest first</div>` +
            rows;

        modal.classList.remove('hidden');
    } catch (err) {
        console.error("Error loading history:", err);
        alert("Failed to load history: " + err.message);
    }
}

// Activity Log (Global history - called from header button)
// Pagination state
let globalHistoryOffset = 0;
let globalHistoryLimit = 50000; // Set high limit to fetch all records at once, adjust if needed
let globalHistoryHasMore = false;

async function showActivityLog() {
    globalHistoryOffset = 0;
    await loadGlobalHistory();
}

async function loadGlobalHistory() {
    try {
        const response = await getHighLevelHistory(globalHistoryLimit, globalHistoryOffset);
        
        const modal = document.getElementById('highLevelHistoryModal');
        const content = document.getElementById('highLevelHistoryContent');
        
        if (!response || !response.history || response.history.length === 0) {
            if (globalHistoryOffset === 0) {
                content.innerHTML = '<div class="text-center text-gray-400 py-8">No activity history available</div>';
            }
        } else {
            const totalHtml = '<div class="flex justify-between items-center mb-3 text-sm text-gray-500"><div>Total Records: ' + (response.total_records || response.history.length) + '</div></div>';
            
            const historyHtml = response.history.map(entry => {
                const actionColors = {
                    'Save': 'bg-blue-100 text-blue-800',
                    'Edit': 'bg-blue-100 text-blue-800',
                    'Review': 'bg-yellow-100 text-yellow-800',
                    'PushToRTU': 'bg-green-100 text-green-800',
                    'ProofRead': 'bg-purple-100 text-purple-800'
                };
                const badgeClass = actionColors[entry.action_type] || 'bg-gray-100 text-gray-800';
                const sourceBadgeClass = entry.source === 'mongo' ? 'bg-orange-100 text-orange-800' : 'bg-blue-100 text-blue-800';
                
                let dateStr = 'N/A';
                if (entry.action_date) {
                    try { dateStr = new Date(entry.action_date).toLocaleString(); }
                    catch(e) { dateStr = entry.action_date; }
                }
                
                return '<div class="border rounded p-3 bg-gray-50 hover:bg-gray-100 mb-2"><div class="flex justify-between items-start gap-4"><div class="flex-grow"><div class="font-semibold">QID-' + (entry.que_id || 'N/A') + '</div><div class="text-sm text-gray-600">Action: <strong>' + (entry.action_type || 'N/A') + '</strong></div></div><div><span class="inline-block px-2 py-1 rounded text-xs font-semibold ' + badgeClass + '">' + (entry.action_type || 'N/A') + '</span><span class="inline-block px-1 py-0.5 text-xs rounded ' + sourceBadgeClass + ' ml-1">' + (entry.source === 'mongo' ? 'Utility' : 'RTU') + '</span></div><div class="text-right text-xs text-gray-500 whitespace-nowrap"><div>' + dateStr + '</div><div>By: ' + (entry.performed_by_name || entry.performed_by || 'N/A') + '</div></div></div></div>';
            }).join('');
            
            const paginationHtml = '<div class="flex justify-center gap-2 mt-4"><button onclick="prevPage()" class="px-4 py-2 bg-gray-200 rounded ' + (globalHistoryOffset === 0 ? 'opacity-50' : 'hover:bg-gray-300') + '" ' + (globalHistoryOffset === 0 ? 'disabled' : '') + '>Previous</button><span class="px-4 py-2 text-sm text-gray-600">Page ' + (Math.floor(globalHistoryOffset / globalHistoryLimit) + 1) + '</span><button onclick="nextPage()" class="px-4 py-2 bg-gray-200 rounded ' + (!response.has_more ? 'opacity-50' : 'hover:bg-gray-300') + '" ' + (!response.has_more ? 'disabled' : '') + '>Next</button></div>';
            
            content.innerHTML = totalHtml + historyHtml + paginationHtml;
            globalHistoryHasMore = response.has_more;
        }
        
        modal.classList.remove('hidden');
    } catch (err) {
        console.error("Error loading activity log:", err);
        alert("Failed to load activity history");
    }
}

async function nextPage() {
    if (globalHistoryHasMore) {
        globalHistoryOffset += globalHistoryLimit;
        await loadGlobalHistory();
    }
}

async function prevPage() {
    if (globalHistoryOffset > 0) {
        globalHistoryOffset = Math.max(0, globalHistoryOffset - globalHistoryLimit);
        await loadGlobalHistory();
    }
}

// =====================================================
// REVIEW QUEUE
// =====================================================
async function loadReviewQueueCount() {
    if (!currentUser || (currentUser.role !== 'Admin' && currentUser.role !== 'Senior Editor')) return;
    try {
        const queue = await fetchReviewQueue();
        const count = Array.isArray(queue) ? queue.length : 0;
        const countEl = document.getElementById('reviewQueueCount');
        if (countEl) {
            if (count > 0) {
                countEl.textContent = count;
                countEl.classList.remove('hidden');
            } else {
                countEl.classList.add('hidden');
            }
        }
    } catch (err) {
        console.warn('Could not load review queue count:', err);
    }
}

async function showReviewQueue() {
    if (!currentUser || (currentUser.role !== 'Admin' && currentUser.role !== 'Senior Editor')) {
        alert('Access denied');
        return;
    }
    const modal   = document.getElementById('reviewQueueModal');
    const content = document.getElementById('reviewQueueContent');
    modal.classList.remove('hidden');
    content.innerHTML = '<div class="text-center text-gray-400 py-8">Loading...</div>';

    try {
        const queue = await fetchReviewQueue();
        if (!Array.isArray(queue) || queue.length === 0) {
            content.innerHTML = '<div class="text-center text-gray-400 py-12 text-lg">✅ All caught up — no questions pending review</div>';
        } else {
            content.innerHTML = queue.map(q => {
                const qid    = q.que_id;
                const date   = q.last_modified_date ? new Date(q.last_modified_date).toLocaleString() : '—';
                const qb     = escapeHTML(q.qb_name  || (q.qb_id ? `QB-${q.qb_id}` : 'Unknown QB'));
                const editor = escapeHTML(q.last_modified_by_name || '?');
                const role   = escapeHTML(q.last_modified_role    || '?');
                const v = k => escapeHTML(q[k] || '');
                return `
                <div class="border rounded-lg bg-white shadow-sm" id="rq-row-${qid}">
                    <!-- Card header -->
                    <div class="flex items-center justify-between px-5 py-3 bg-orange-50 rounded-t-lg border-b">
                        <div>
                            <span class="font-bold text-gray-900 text-base">QID-${qid}</span>
                            <span class="ml-3 text-sm text-gray-500">📚 ${qb}</span>
                        </div>
                        <div class="text-xs text-gray-400 text-right">
                            <div>✏️ <strong>${editor}</strong> &middot; ${role}</div>
                            <div>🕐 ${date}</div>
                        </div>
                    </div>
                    <!-- Editable fields -->
                    <div class="p-5 space-y-4">
                        <div>
                            <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Question</label>
                            <textarea id="rq_${qid}_question" class="w-full border rounded p-2 text-sm focus:border-orange-400 focus:outline-none" rows="4">${v('question')}</textarea>
                        </div>
                        <div class="grid grid-cols-2 gap-3">
                            <div>
                                <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Option A</label>
                                <input id="rq_${qid}_optionA" type="text" value="${v('optionA')}" class="w-full border rounded p-2 text-sm focus:border-orange-400 focus:outline-none" />
                            </div>
                            <div>
                                <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Option B</label>
                                <input id="rq_${qid}_optionB" type="text" value="${v('optionB')}" class="w-full border rounded p-2 text-sm focus:border-orange-400 focus:outline-none" />
                            </div>
                            <div>
                                <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Option C</label>
                                <input id="rq_${qid}_optionC" type="text" value="${v('optionC')}" class="w-full border rounded p-2 text-sm focus:border-orange-400 focus:outline-none" />
                            </div>
                            <div>
                                <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Option D</label>
                                <input id="rq_${qid}_optionD" type="text" value="${v('optionD')}" class="w-full border rounded p-2 text-sm focus:border-orange-400 focus:outline-none" />
                            </div>
                        </div>
                        <div>
                            <label class="block text-xs font-bold text-gray-500 uppercase mb-1">Explanation</label>
                            <textarea id="rq_${qid}_explanation" class="w-full border rounded p-2 text-sm focus:border-orange-400 focus:outline-none" rows="3">${v('explanation')}</textarea>
                        </div>
                        <!-- Inline status message -->
                        <div id="rq_${qid}_status" class="text-xs hidden"></div>
                        <!-- Action buttons -->
                        <div class="flex justify-end gap-3 pt-2 border-t">
                            <button
                                id="rq_${qid}_saveBtn"
                                class="orange-button px-4 py-2 rounded-md text-sm font-semibold"
                                onclick="saveFromQueue(${qid}, ${q.qb_id || 'null'}, '${escapeHTML(q.qb_name || '')}')">
                                Save Changes
                            </button>
                            <button
                                id="rq_${qid}_pushBtn"
                                class="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-md text-sm font-semibold transition"
                                onclick="pushFromQueue(${qid}, this)">
                                🚀 Push to RTU
                            </button>
                            <button
                                id="rq_${qid}_completeBtn"
                                class="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded-md text-sm font-semibold transition"
                                onclick="markCompleteFromQueue(${qid}, this)">
                                ✅ Mark Complete
                            </button>
                        </div>
                    </div>
                </div>`;
            }).join('');
        }
        await loadReviewQueueCount();
    } catch (err) {
        content.innerHTML = '<div class="text-center text-red-400 py-8">Failed to load review queue</div>';
        console.error('showReviewQueue error:', err);
    }
}

async function saveFromQueue(queId, qbId, qbName) {
    const get = id => (document.getElementById(id) || {}).value || '';
    const btn = document.getElementById(`rq_${queId}_saveBtn`);
    const statusEl = document.getElementById(`rq_${queId}_status`);
    if (btn) { btn.disabled = true; btn.textContent = 'Saving...'; }
    try {
        await saveQuestion(queId, {
            question:    get(`rq_${queId}_question`),
            optionA:     get(`rq_${queId}_optionA`),
            optionB:     get(`rq_${queId}_optionB`),
            optionC:     get(`rq_${queId}_optionC`),
            optionD:     get(`rq_${queId}_optionD`),
            explanation: get(`rq_${queId}_explanation`),
            qb_id:   qbId,
            qb_name: qbName
        });
        if (statusEl) {
            statusEl.textContent = '✅ Saved successfully';
            statusEl.className = 'text-xs text-green-600';
            statusEl.classList.remove('hidden');
            setTimeout(() => statusEl.classList.add('hidden'), 3000);
        }
        // sync back to main list if question is open
        const q = questions.find(x => x.id === queId);
        if (q) {
            q.question = get(`rq_${queId}_question`);
            reRenderSingleQuestion(q);
        }
    } catch (err) {
        if (statusEl) {
            statusEl.textContent = '❌ Save failed: ' + (err.message || err);
            statusEl.className = 'text-xs text-red-500';
            statusEl.classList.remove('hidden');
        }
        console.error('saveFromQueue error:', err);
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = 'Save Changes'; }
    }
}

async function pushFromQueue(queId, btn) {
    if (!confirm(`Push QID-${queId} edits to RTU (source database)?\n\nThis will overwrite question text, options, and explanation in RTU with the saved MongoDB values.`)) return;
    if (btn) { btn.disabled = true; btn.textContent = 'Pushing...'; }
    const statusEl = document.getElementById(`rq_${queId}_status`);
    try {
        const response = await pushToRTU(queId);
        const fields = response.fields_updated?.join(', ') || 'none';
        if (statusEl) {
            statusEl.textContent = `🚀 Pushed to RTU — fields updated: ${fields}`;
            statusEl.className = 'text-xs text-blue-600';
            statusEl.classList.remove('hidden');
            setTimeout(() => statusEl.classList.add('hidden'), 5000);
        }
    } catch (err) {
        console.error('pushFromQueue error:', err);
        const msg = err.status === 404
            ? 'No saved data found — save edits first before pushing.'
            : (err.message || 'Push failed');
        if (statusEl) {
            statusEl.textContent = '❌ ' + msg;
            statusEl.className = 'text-xs text-red-500';
            statusEl.classList.remove('hidden');
        } else {
            alert('Push to RTU failed: ' + msg);
        }
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = '🚀 Push to RTU'; }
    }
}

async function markCompleteFromQueue(queId, btn) {
    if (!confirm(`Mark QID-${queId} as Complete?`)) return;
    if (btn) { btn.disabled = true; btn.textContent = 'Marking...'; }
    try {
        await reviewQuestion(queId);
        // Fade-remove the row
        const row = document.getElementById(`rq-row-${queId}`);
        if (row) {
            row.style.transition = 'opacity 0.3s';
            row.style.opacity = '0';
            setTimeout(() => row.remove(), 310);
        }
        // Refresh count badge
        await loadReviewQueueCount();
        // If this question is open in the editor, update its status live
        if (window.currentQuestionId === queId) {
            const q = questions.find(x => x.id === queId);
            if (q) { q.status = 'Completed'; reRenderSingleQuestion(q); }
        }
    } catch (err) {
        console.error('markCompleteFromQueue error:', err);
        alert('Failed to mark as complete: ' + (err.message || err));
        if (btn) { btn.disabled = false; btn.textContent = '✅ Mark Complete'; }
    }
}

// =====================================================
// ADMIN: Show pending signup requests (modal)
// =====================================================
async function showPendingRequests() {
    if (!currentUser || currentUser.role !== 'Admin') {
        alert('Only Admins can view pending requests');
        return;
    }

    try {
        const pending = await getPendingSignups();
        const modal = document.getElementById('pendingRequestsModal');
        const content = document.getElementById('pendingRequestsContent');

        if (!Array.isArray(pending) || pending.length === 0) {
            content.innerHTML = '<div class="text-center text-gray-400 py-8">No pending signup requests</div>';
        } else {
            content.innerHTML = pending.map(u => `
                <div class="flex items-center justify-between border rounded p-3 bg-gray-50">
                    <div>
                        <div class="font-semibold">${escapeHTML(u.username)}</div>
                        <div class="text-xs text-gray-600">${escapeHTML(u.email)}</div>
                        <div class="text-xs text-gray-400">${new Date(u.created_at).toLocaleString()}</div>
                    </div>
                    <div class="flex items-center gap-2">
                        <select id="role_${u.id}" class="border border-gray-300 rounded text-sm px-2 py-1 focus:outline-none focus:border-orange-500">
                            <option value="">— Assign Role —</option>
                            <option value="Editor">Editor</option>
                            <option value="Senior Editor">Senior Editor</option>
                            <option value="Admin">Admin</option>
                        </select>
                        <button class="px-3 py-1 bg-green-100 text-green-800 rounded text-sm font-semibold" onclick="handleApproveRequest('${u.id}')">Approve</button>
                        <button class="px-3 py-1 bg-red-100 text-red-800 rounded text-sm font-semibold" onclick="handleRejectRequest('${u.id}')">Reject</button>
                    </div>
                </div>
            `).join('');
        }

        modal.classList.remove('hidden');
    } catch (err) {
        console.error('Error loading pending requests:', err);
        alert('Failed to load pending requests');
    }
}

async function handleApproveRequest(userId) {
    const roleSelect = document.getElementById(`role_${userId}`);
    const role = roleSelect ? roleSelect.value : '';
    if (!role) {
        alert('Please assign a role before approving.');
        return;
    }
    if (!confirm(`Approve this user as ${role}?`)) return;
    try {
        await approveSignup(userId, role);
        alert(`User approved as ${role}`);
        await showPendingRequests();
    } catch (err) {
        console.error('Approve failed:', err);
        alert('Failed to approve user: ' + (err.message || err));
    }
}

async function handleRejectRequest(userId) {
    if (!confirm('Reject this user?')) return;
    try {
        await rejectSignup(userId);
        alert('User rejected');
        await showPendingRequests();
    } catch (err) {
        console.error('Reject failed:', err);
        alert('Failed to reject user: ' + (err.message || err));
    }
}

// =====================================================
// ADMIN: Backfill audit logs (calls backend backfill endpoint)
// =====================================================
async function handleBackfillEdits() {
    if (!currentUser || currentUser.role !== 'Admin') {
        alert('Only Admins can run audit backfill');
        return;
    }

    if (!confirm('Create missing audit-log entries from existing edited documents?')) return;

    try {
        const res = await backfillEdits();
        alert('Backfill complete — ' + (res.created || 0) + ' audit entries created');
        // refresh activity log to show new entries
        await showActivityLog();
    } catch (err) {
        console.error('Backfill failed:', err);
        alert('Backfill failed: ' + (err.message || err));
    }
}

// =====================================================
// ACTION HANDLERS
// =====================================================

// =====================================================
// TOAST NOTIFICATIONS
// =====================================================
function showToast(message, type = 'success') {
    const container = document.getElementById('toastContainer');
    if (!container) { console.warn('[Toast]', message); return; }
    const colors = { success: 'bg-green-600', error: 'bg-red-600', info: 'bg-blue-500', warning: 'bg-yellow-500' };
    const toast  = document.createElement('div');
    const isWarn = type === 'warning';
    toast.className = `flex items-center gap-2 ${colors[type] || colors.success} ${isWarn ? 'text-gray-900' : 'text-white'} text-sm font-medium px-4 py-3 rounded-lg shadow-xl min-w-[220px] max-w-sm opacity-0`;
    toast.innerHTML = `<span>${message}</span>`;
    container.appendChild(toast);
    requestAnimationFrame(() => requestAnimationFrame(() => { toast.style.opacity = '1'; }));
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(8px)';
        setTimeout(() => toast.remove(), 350);
    }, 3500);
}

async function handleSaveQuestion() {
    if (!currentUser) { showToast('Please log in.', 'error'); return; }
    
    try {
        const questionId = window.currentQuestionId;
        // Only send fields the user can actually edit
        // correctAnswer (fieldAnswer) and difficulty are non-editable - excluded intentionally
        // qb_id / qb_name are metadata passed for audit log only - not editable fields
        const updatedData = {
            question:     document.getElementById('fieldQuestion').value,
            optionA:      document.getElementById('fieldOptA').value,
            optionB:      document.getElementById('fieldOptB').value,
            optionC:      document.getElementById('fieldOptC').value,
            optionD:      document.getElementById('fieldOptD').value,
            explanation:  document.getElementById('fieldExplanation').value,
            // audit metadata
            qb_id:   window.currentQBId   || null,
            qb_name: window.currentQBName || null
        };
        
        // Dirty check — only save if the user actually changed something
        const orig = window.originalFormValues || {};
        const hasChanges = (
            updatedData.question    !== orig.question    ||
            updatedData.optionA     !== orig.optionA     ||
            updatedData.optionB     !== orig.optionB     ||
            updatedData.optionC     !== orig.optionC     ||
            updatedData.optionD     !== orig.optionD     ||
            updatedData.explanation !== orig.explanation
        );
        if (!hasChanges) {
            showToast('No changes detected — edit the content first.', 'warning');
            return;
        }

        const response = await saveQuestion(questionId, updatedData);
        showToast('Question saved successfully!', 'success');

        // Fetch the updated question from backend (will include changes info)
        const updatedQuestion = await fetchQuestionByQID(`QID-${questionId}`);
        
        // Find and update the question in local array
        const qIndex = questions.findIndex(q => q.id === questionId);
        if (qIndex !== -1 && updatedQuestion) {
            // Normalize the fresh data from backend
            const correctAnswerValue = updatedQuestion.correctAnswer 
                ? updatedQuestion.correctAnswer.split(',')[0].trim()
                : "A";

            const normalizedQuestion = {
                id: updatedQuestion.id,
                displayId: updatedQuestion.id ? `QID-${updatedQuestion.id}` : "QID-UNKNOWN",
                bank: updatedQuestion.skill ? String(updatedQuestion.skill).trim() : "Unknown Bank",
                qbId: updatedQuestion.qb_id || window.currentQBId || null,
                question: updatedQuestion.questionText ? String(updatedQuestion.questionText).trim() : "No question text",
                difficulty: updatedQuestion.difficultyLevel ? String(updatedQuestion.difficultyLevel).trim() : "Easy",
                status: updatedQuestion.reviewStatus === 'Reviewed' ? 'Completed' : (updatedQuestion.reviewStatus || "Pending"),
                reviewedBy: updatedQuestion.ReviewedByName || updatedQuestion.ReviewedBy || null,
                reviewedOn: updatedQuestion.ReviewedOn || null,
                isEdited: updatedQuestion.isEdited || false,
                source: updatedQuestion.source || 'rtu',
                lastModifiedBy: updatedQuestion.lastModifiedBy || null,
                lastModifiedDate: updatedQuestion.lastModifiedDate || null,
                isSynced: updatedQuestion.isSynced || false,
                lastSyncedByName: updatedQuestion.lastSyncedByName || null,
                lastSyncedDate: updatedQuestion.lastSyncedDate || null,
                changes: updatedQuestion.changes || {},
                options: {
                    A: updatedQuestion.optionA !== null && updatedQuestion.optionA !== undefined ? String(updatedQuestion.optionA).trim() || "[No Option A]" : "[No Option A]",
                    B: updatedQuestion.optionB !== null && updatedQuestion.optionB !== undefined ? String(updatedQuestion.optionB).trim() || "[No Option B]" : "[No Option B]",
                    C: updatedQuestion.optionC !== null && updatedQuestion.optionC !== undefined ? String(updatedQuestion.optionC).trim() || "[No Option C]" : "[No Option C]",
                    D: updatedQuestion.optionD !== null && updatedQuestion.optionD !== undefined ? String(updatedQuestion.optionD).trim() || "[No Option D]" : "[No Option D]"
                },
                answer: correctAnswerValue,
                explanation: updatedQuestion.answerExplanation ? String(updatedQuestion.answerExplanation).trim() : "No explanation"
            };
            
            // Update in local array
            questions[qIndex] = normalizedQuestion;

            // Re-render just this question card
            reRenderSingleQuestion(normalizedQuestion);

            // Close editor after successful save
            setTimeout(() => {
                document.getElementById('mainEditor').classList.add('hidden');
            }, 500);
        }
    } catch (err) {
        console.error('Error saving question:', err);
        if (err.status === 403) {
            showToast('You do not have permission to save questions.', 'error');
        } else {
            showToast('Error saving: ' + (err.message || 'Unknown error'), 'error');
        }
    }
}

// Helper function to re-render a single question card without full reload
function reRenderSingleQuestion(question) {
    const questionCard = document.getElementById(`question-${question.displayId}`);
    if (!questionCard) {
        console.warn('Question card not found, skipping re-render');
        return;
    }

    // STATUS BADGE
    let statusBadge = '';
    if (question.status === "Completed") {
        statusBadge = `
            <div class="text-green-600 font-semibold">
                Completed
                ${question.reviewedBy ? `
                    <div class="text-xs text-gray-500">
                        by ${escapeHTML(question.reviewedBy)}
                        ${question.reviewedOn ? `on ${new Date(question.reviewedOn).toLocaleString()}` : ''}
                    </div>
                ` : ''}
            </div>
        `;
    } else {
        statusBadge = `<span class="text-red-500 font-semibold">Pending</span>`;
    }

    // Update the card HTML
    questionCard.innerHTML = `
        <div class="flex justify-between items-start mb-3">
            <div>
                <div class="font-bold text-lg">${escapeHTML(question.displayId)}</div>
                <div class="text-sm text-gray-500">${escapeHTML(question.bank)}</div>
                ${question.status === 'Completed' ? `<div class="text-xs bg-green-100 text-green-700 px-2 py-1 rounded mt-1 inline-block">Completed</div>` : question.isEdited ? `<div class="text-xs bg-red-100 text-red-700 px-2 py-1 rounded mt-1 inline-block">Edited</div>` : ''}
            </div>

            <button class="edit-btn text-[#FF6B00] text-sm font-semibold hover:underline" data-qid="${escapeHTML(question.displayId)}">
                Edit
            </button>
        </div>

        <div class="mb-3 font-medium">
            Q: ${escapeHTML(question.question)}
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-3">
            <div>A) ${escapeHTML(question.options.A)}</div>
            <div>B) ${escapeHTML(question.options.B)}</div>
            <div>C) ${escapeHTML(question.options.C)}</div>
            <div>D) ${escapeHTML(question.options.D)}</div>
        </div>

        <div class="bg-gray-50 p-3 rounded text-sm mb-3">
            <strong>Explanation:</strong> ${escapeHTML(question.explanation)}
        </div>

        ${question.isEdited && Object.keys(question.changes).length > 0 ? renderChangesSection(question.changes) : ''}

        <div class="flex justify-between items-center text-sm border-t pt-3 mb-3">
            <div>
                <strong>Difficulty:</strong> ${escapeHTML(question.difficulty)}
            </div>
            <div>
                <strong>Status:</strong> ${statusBadge}
            </div>
        </div>

        ${question.isSynced ? `
        <div class="text-sm border-t pt-3 mb-3">
            <strong>Pushed to RTU:</strong>
            <div class="text-green-600 font-semibold mt-1">
                Pushed
                <div class="text-xs text-gray-500">
                    by ${question.lastSyncedByName || 'Unknown'}
                    ${question.lastSyncedDate ? `on ${new Date(question.lastSyncedDate).toLocaleString()}` : ''}
                </div>
            </div>
        </div>
        ` : ''}
        
        ${question.isEdited ? `
        <div class="bg-blue-50 p-2 rounded text-xs text-gray-700 mb-2 border-l-4 border-blue-400">
            <strong>📝 Last Modified:</strong> ${question.lastModifiedBy || 'Unknown'} on ${question.lastModifiedDate ? new Date(question.lastModifiedDate).toLocaleString() : 'Unknown date'}
        </div>
        ` : ''}
        
        <div class="flex gap-2 mt-1">
            <button class="track-versions-btn text-xs bg-indigo-100 hover:bg-indigo-200 text-indigo-800 font-semibold px-3 py-1 rounded" onclick="trackVersions(${question.id})">Track Versions</button>
            <button class="text-xs bg-gray-100 hover:bg-gray-200 text-gray-700 font-semibold px-3 py-1 rounded" onclick="showQuestionHistory(${question.id})">History</button>
        </div>
    `;

    // Re-add event listener for Edit button
    const editBtn = questionCard.querySelector('.edit-btn');
    editBtn.addEventListener('click', () => selectQuestion(question.id));
}

async function handleReviewQuestion() {
    if (!currentUser) { showToast('Please log in.', 'error'); return; }

    try {
        const comment = prompt('Enter your review comment (optional):');
        if (comment === null) return;

        const questionId = window.currentQuestionId;
        await reviewQuestion(questionId, comment || '');
        showToast('Question marked as complete!', 'success');

        const q = questions.find(q => q.id === questionId);
        if (q) {
            q.status = 'Completed';
            q.reviewedBy = currentUser.username;
            q.reviewedOn = new Date().toISOString();
            reRenderSingleQuestion(q);
        }

        document.getElementById('mainEditor').classList.add('hidden');
    } catch (err) {
        console.error('Error reviewing question:', err);
        showToast('Error: ' + err.message, 'error');
    }
}

async function handlePushToRTU() {
    if (!currentUser) { showToast('Please log in.', 'error'); return; }

    const questionId = window.currentQuestionId;
    if (!questionId) { showToast('No question selected.', 'warning'); return; }

    if (!confirm(`Push QID-${questionId} edits to RTU (source database)?\n\nThis will overwrite question text, options, and explanation in RTU with the saved MongoDB values.`)) return;

    try {
        const response = await pushToRTU(questionId);
        const fields = response.fields_updated?.join(', ') || 'none';
        showToast(`QID-${questionId} pushed to RTU — fields: ${fields}`, 'success');
    } catch (err) {
        console.error('Push to RTU error:', err);
        if (err.status === 404) {
            showToast('No saved edits found — save the question first.', 'warning');
        } else if (err.status === 403) {
            showToast('You do not have permission to push to RTU.', 'error');
        } else {
            showToast('Push failed: ' + (err.message || 'Unknown error'), 'error');
        }
    }
}

function applyStatusFilter() {
    const filterValue = document.getElementById("statusFilter").value;

    if (filterValue === "all") {
        renderQuestionList(questions);
        return;
    }

    const filtered = questions.filter(q => q.status === filterValue);
    renderQuestionList(filtered);
}

// =====================================================
// Enforce authentication immediately on page load
document.addEventListener('DOMContentLoaded', async () => {
    const isProtected = isProtectedPage();
    
    if (isProtected) {
        const hasAuth = enforceAuthentication();
        if (hasAuth) {
            await checkAuthentication();
            loadQBs();
        }
    }
});

// Fallback for window.onload if DOMContentLoaded doesn't trigger
window.onload = async () => {
    const isProtected = isProtectedPage();
    
    if (isProtected) {
        const hasAuth = enforceAuthentication();
        if (hasAuth) {
            await checkAuthentication();
            loadQBs();
        }
    }
};
async function handleSignup(event) {
    event.preventDefault();

    const username = document.getElementById("signupUsername")?.value.trim();
    const email = document.getElementById("signupEmail")?.value.trim();
    const role = document.getElementById("signupRole")?.value;

    if (!username || !email) {
        alert("Please fill all fields");
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/auth/signup`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                username: username,
                email: email,
                role: role
            })
        });

        const data = await res.json();

        if (!res.ok) {
            throw new Error(data.error || "Signup failed");
        }

        alert("Signup successful! Please login.");
        window.location.href = "login.html";

    } catch (err) {
        console.error("Signup error:", err);
        alert("Signup failed: " + err.message);
    }
}

// =====================================================
// BATCH PUSH TO RTU
// =====================================================
async function showBatchPushModal() {
    document.getElementById('batchPushModal').classList.remove('hidden');
    const listEl    = document.getElementById('batchPushList');
    const summaryEl = document.getElementById('batchPushSummary');
    const confirmBtn = document.getElementById('batchPushConfirmBtn');

    listEl.innerHTML = '<div class="text-center text-gray-400 py-8">Loading\u2026</div>';
    summaryEl.textContent = 'Loading unsynced questions\u2026';
    confirmBtn.disabled = true;

    try {
        const docs = await fetchUnpushed();

        if (!docs || docs.length === 0) {
            listEl.innerHTML = '<div class="text-center text-green-600 py-10 text-lg font-semibold">\u2705 All questions are synced with RTU \u2014 nothing to push.</div>';
            summaryEl.textContent = '0 questions to push';
            confirmBtn.disabled = true;
            return;
        }

        const total     = docs.length;
        const completed = docs.filter(d => d.review_status === 'Completed').length;
        const pending   = total - completed;
        summaryEl.textContent = `${total} question${total !== 1 ? 's' : ''} to push \u2014 ${completed} Reviewed, ${pending} Pending review`;

        listEl.innerHTML = docs.map(doc => {
            const statusBadge = doc.review_status === 'Completed'
                ? '<span class="inline-block bg-green-100 text-green-800 text-xs font-bold px-2 py-0.5 rounded-full">\u2705 Reviewed</span>'
                : '<span class="inline-block bg-yellow-100 text-yellow-800 text-xs font-bold px-2 py-0.5 rounded-full">\u23f3 Pending Review</span>';
            const dateStr = doc.last_modified_date
                ? new Date(doc.last_modified_date).toLocaleString('en-IN', { day:'2-digit', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit' })
                : '\u2014';
            return `
            <div id="bprow-${doc.que_id}" class="flex items-center justify-between bg-gray-50 rounded-lg px-4 py-3 border border-gray-200">
                <div class="flex items-center gap-4 flex-wrap">
                    <span class="font-mono text-sm font-bold text-gray-800">QID ${doc.que_id}</span>
                    <span class="text-sm text-gray-600">${doc.qb_name || '\u2014'}</span>
                    ${statusBadge}
                </div>
                <div class="text-right text-xs text-gray-400 whitespace-nowrap">
                    <div>${doc.last_modified_by_name || '\u2014'}</div>
                    <div>${dateStr}</div>
                </div>
            </div>`;
        }).join('');

        confirmBtn.disabled = false;
    } catch (err) {
        listEl.innerHTML = `<div class="text-center text-red-500 py-8">\u274c Failed to load: ${err.message}</div>`;
        summaryEl.textContent = 'Error loading questions';
    }
}

async function handleBatchPush() {
    const confirmBtn = document.getElementById('batchPushConfirmBtn');
    const summaryEl  = document.getElementById('batchPushSummary');

    const confirmed = confirm('Push ALL unsynced questions to RTU now?\n\nThis cannot be undone. Proceed?');
    if (!confirmed) return;

    confirmBtn.disabled = true;
    confirmBtn.textContent = '\u23f3 Pushing\u2026';
    summaryEl.textContent = 'Pushing to RTU\u2026 please wait';

    try {
        const result = await batchPushToRTU();
        const { success_count = 0, error_count = 0, results = [] } = result;

        summaryEl.textContent = `Done \u2014 \u2705 ${success_count} pushed, \u274c ${error_count} failed`;
        confirmBtn.textContent = '\u2705 Done';

        // update each row with its result
        results.forEach(r => {
            const row = document.getElementById(`bprow-${r.que_id}`);
            if (!row) return;
            if (r.status === 'success') {
                const fields = (r.fields_updated || []).join(', ') || 'no fields';
                row.classList.remove('bg-gray-50', 'border-gray-200');
                row.classList.add('bg-green-50', 'border-green-300');
                row.querySelector('.flex.items-center.gap-4')?.insertAdjacentHTML('beforeend',
                    `<span class="inline-block bg-green-600 text-white text-xs font-bold px-2 py-0.5 rounded-full">\u2705 Pushed</span>`
                );
            } else {
                row.classList.remove('bg-gray-50', 'border-gray-200');
                row.classList.add('bg-red-50', 'border-red-300');
                row.querySelector('.flex.items-center.gap-4')?.insertAdjacentHTML('beforeend',
                    `<span class="inline-block bg-red-600 text-white text-xs font-bold px-2 py-0.5 rounded-full" title="${r.error || ''}">\u274c Failed</span>`
                );
            }
        });

    } catch (err) {
        summaryEl.textContent = '\u274c Push failed: ' + err.message;
        confirmBtn.disabled = false;
        confirmBtn.textContent = '\ud83d\ude80 Push All to RTU';
    }
}

// Attach signup form listener if present
document.addEventListener("DOMContentLoaded", () => {
    const signupForm = document.getElementById("signupForm");
    if (signupForm) {
        signupForm.addEventListener("submit", handleSignup);
    }
});


// =====================================================
// TRACK VERSIONS - V1 (RTU) vs V2 (MongoDB) side by side
// =====================================================

async function trackVersions(questionId) {
    const modal = document.getElementById('questionComparisonModal');
    const contentDiv = document.getElementById('comparisonContent');
    const storedUser = JSON.parse(localStorage.getItem('user') || 'null');
    const userId = currentUser?.id || storedUser?.id || '';

    modal.classList.remove('hidden');
    contentDiv.innerHTML = '<div class="text-center text-gray-500 py-8">Loading versions...</div>';

    try {
        const res = await fetch(`${API_BASE}/admin/questions/${questionId}/compare`, {
            credentials: 'include',
            headers: { 'X-User-Id': userId }
        });
        if (!res.ok) throw new Error(`Server returned ${res.status}`);
        const data = await res.json();
        displayQuestionVersions(questionId, data.v1_rtu, data.versions || []);
    } catch (err) {
        console.error('[TRACK_VERSIONS] Error:', err);
        contentDiv.innerHTML = `<div class="text-center text-red-500 py-8">Error loading versions: ${err.message}</div>`;
    }
}

function displayQuestionVersions(questionId, v1, versions) {
    const contentDiv = document.getElementById('comparisonContent');

    const fields = [
        { key: 'question',    label: 'Question Text' },
        { key: 'optionA',     label: 'Option A' },
        { key: 'optionB',     label: 'Option B' },
        { key: 'optionC',     label: 'Option C' },
        { key: 'optionD',     label: 'Option D' },
        { key: 'explanation', label: 'Explanation' },
    ];

    if (!v1) {
        contentDiv.innerHTML = `<div class="text-center text-red-400 py-6 text-sm">Could not load RTU data for QID-${questionId}.</div>`;
        return;
    }

    // Store state so version-picker buttons can call back into renderComparison
    window[`_vtV1_${questionId}`]    = v1;
    window[`_vtList_${questionId}`]  = versions;
    window[`_vtPick_${questionId}`]  = function(versionNum) {
        const selected = versionNum === null
            ? null
            : (window[`_vtList_${questionId}`] || []).find(v => v.version === versionNum) || null;
        renderComparison(selected);
    };

    function renderComparison(v2) {
        // Determine left-side baseline:
        // If v2 has a predecessor in the saved versions list, use that.
        // Only fall back to RTU if v2 is the very first saved version (V2).
        let base = null;       // null = use RTU as baseline
        let baseIsRTU = true;
        if (v2) {
            const idx = versions.findIndex(v => v.version === v2.version);
            if (idx > 0) {
                base = versions[idx - 1];
                baseIsRTU = false;
            }
        }

        const baseData   = baseIsRTU ? v1 : base;
        const baseLabel  = baseIsRTU ? 'V1 — RTU (Original)' : `V${base.version} — Local DB`;
        const baseSuffix = baseIsRTU ? 'RTU' : `V${base.version}`;

        const changedCount = v2
            ? fields.filter(f => (baseData[f.key] || '') !== (v2[f.key] || '')).length
            : 0;

        let html = `
            <div class="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-4 flex items-start justify-between gap-4">
                <div>
                    <div class="font-bold text-blue-900 text-base">QID-${questionId}</div>
                    <div class="text-sm text-blue-700 mt-1">
                        ${ v2
                            ? `${changedCount} field(s) differ from ${baseIsRTU ? 'RTU original' : 'previous version'}`
                            : versions.length > 0
                                ? 'Select a version below to compare'
                                : 'No edits saved yet — showing RTU original'}
                    </div>
                    ${v2 ? `<div class="text-xs text-blue-500 mt-1">Saved by <strong>${escapeHTML(v2.saved_by_name || '')}</strong>${v2.saved_at ? ' on ' + new Date(v2.saved_at).toLocaleString() : ''}</div>` : ''}
                </div>
                <div class="flex gap-3 text-xs font-semibold shrink-0 mt-1">
                    <span class="flex items-center gap-1"><span class="w-3 h-3 rounded bg-gray-200 inline-block"></span>${baseIsRTU ? 'V1 RTU' : `V${base.version} Local DB`}</span>
                    ${v2 ? `<span class="flex items-center gap-1"><span class="w-3 h-3 rounded bg-indigo-200 inline-block"></span>V${v2.version} Local DB</span>` : ''}
                </div>
            </div>`;

        // Version picker bar
        if (versions.length > 0) {
            html += `<div class="flex items-center gap-2 mb-4 flex-wrap">
                <span class="text-xs font-semibold text-gray-500 uppercase tracking-wide mr-1">Versions:</span>
                <button onclick="window['_vtPick_${questionId}'](null)"
                        class="px-3 py-1 rounded text-xs font-semibold border transition
                               ${!v2 ? 'bg-gray-700 text-white border-gray-700' : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'}">
                    V1 — RTU
                </button>`;

            versions.forEach(v => {
                const isSelected = v2 && v2.version === v.version;
                const date = v.saved_at ? new Date(v.saved_at).toLocaleDateString() : '';
                html += `<button onclick="window['_vtPick_${questionId}'](${v.version})"
                        class="px-3 py-1 rounded text-xs font-semibold border transition
                               ${isSelected ? 'bg-indigo-600 text-white border-indigo-600' : 'bg-white text-indigo-600 border-indigo-300 hover:bg-indigo-50'}">
                    V${v.version}${ v.saved_by_name ? ' — ' + escapeHTML(v.saved_by_name) : ''}${date ? ' · ' + date : ''}
                </button>`;
            });

            html += `</div>`;
        }

        if (!v2) {
            // RTU-only view
            html += `<div class="space-y-3">`;
            fields.forEach(({ key, label }) => {
                const val = v1[key] ?? '';
                html += `
                    <div class="border rounded-lg overflow-hidden bg-white border-gray-200">
                        <div class="px-3 py-1.5 border-b border-gray-200 bg-gray-50">
                            <span class="text-xs font-semibold text-gray-700">${label}</span>
                        </div>
                        <div class="p-3 text-sm text-gray-800 break-words whitespace-pre-wrap">${escapeHTML(String(val || '[empty]'))}</div>
                    </div>`;
            });
            html += `</div>`;
        } else {
            // Side-by-side comparison
            html += `
                <div class="grid grid-cols-2 gap-3 mb-2 px-1">
                    <div class="text-xs font-bold text-gray-500 uppercase tracking-wide">${baseLabel}</div>
                    <div class="text-xs font-bold text-indigo-600 uppercase tracking-wide">V${v2.version} — Local DB</div>
                </div>`;

            fields.forEach(({ key, label }) => {
                const leftVal = baseData[key] ?? '';
                const rightVal = v2[key] ?? '';
                const isDiff = (leftVal !== rightVal);
                const rowBg  = isDiff ? 'bg-amber-50 border-amber-300' : 'bg-white border-gray-200';
                const badge  = isDiff ? `<span class="ml-2 text-xs bg-amber-100 text-amber-700 font-semibold px-1.5 py-0.5 rounded">changed</span>` : '';

                html += `
                    <div class="border rounded-lg mb-3 overflow-hidden ${rowBg}">
                        <div class="px-3 py-1.5 border-b border-inherit bg-white/70 flex items-center">
                            <span class="text-xs font-semibold text-gray-700">${label}</span>${badge}
                        </div>
                        <div class="grid grid-cols-2 divide-x divide-inherit">
                            <div class="p-3">
                                <div class="text-xs text-gray-400 font-semibold mb-1">${baseSuffix}</div>
                                <div class="text-sm text-gray-800 break-words whitespace-pre-wrap">${escapeHTML(String(leftVal || '[empty]'))}</div>
                            </div>
                            <div class="p-3 ${isDiff ? 'bg-indigo-50' : ''}">
                                <div class="text-xs text-indigo-400 font-semibold mb-1">V${v2.version}</div>
                                <div class="text-sm ${isDiff ? 'text-indigo-900 font-medium' : 'text-gray-500'} break-words whitespace-pre-wrap">${escapeHTML(String(rightVal || '[empty]'))}</div>
                            </div>
                        </div>
                    </div>`;
            });
        }

        contentDiv.innerHTML = html;
    }

    // Default: show latest version if there are edits, otherwise RTU only
    const latest = versions.length > 0 ? versions[versions.length - 1] : null;
    renderComparison(latest);
}
