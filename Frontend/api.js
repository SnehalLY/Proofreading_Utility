const API_BASE = window.location.origin + "/api";
console.log("✅ api.js loaded, API_BASE:", API_BASE);

// =====================================================
// AUTHENTICATION APIS
// =====================================================
async function loginUser(userId) {
    try {
        const res = await fetch(`${API_BASE}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ user_id: userId })
        });
        return await res.json();
    } catch (err) {
        console.error("loginUser() error:", err);
        throw err;
    }
}

async function logoutUser() {
    try {
        const res = await fetch(`${API_BASE}/auth/logout`, {
            method: 'POST',
            credentials: 'include'
        });
        return await res.json();
    } catch (err) {
        console.error("logoutUser() error:", err);
        throw err;
    }
}

async function getCurrentUser() {
    try {
        const res = await fetch(`${API_BASE}/auth/me`, {
            credentials: 'include'
        });
        return await res.json();
    } catch (err) {
        console.error("getCurrentUser() error:", err);
        throw err;
    }
}

// =====================================================
// QUESTION APIS
// =====================================================
async function fetchQBs() {
    try {
        const res = await fetch(`${API_BASE}/question-banks`);
        return await res.json();
    } catch (err) {
        console.error("fetchQBs() error:", err);
        throw err;
    }
}

async function fetchQuestionsByQB(qbId) {
    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 60000); // 60s timeout
        const res = await fetch(`${API_BASE}/questions/${qbId}`, { signal: controller.signal });
        clearTimeout(timeoutId);
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || data.detail || `HTTP ${res.status}`);
        return data;
    } catch (err) {
        console.error("fetchQuestionsByQB() error:", err);
        throw err;
    }
}

async function fetchQuestionByQID(qid) {
    try {
        const cleanId = qid.replace("QID-", "");
        // Uses /api/question/ (singular) to avoid conflict with /api/questions/<qb_id>
        const url = `${API_BASE}/question/${cleanId}`;
        
        // Add timeout to prevent hanging
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 30000); // 30s timeout
        
        const res = await fetch(url, { 
            signal: controller.signal,
            credentials: 'include'
        });
        clearTimeout(timeoutId);
        
        if (!res.ok) {
            throw new Error(`HTTP error! status: ${res.status}`);
        }
        
        const data = await res.json();
        return data;
    } catch (err) {
        console.error("fetchQuestionByQID() error:", err);
        if (err.name === 'AbortError') {
            throw new Error('Request timed out after 30s. The server is too slow — try again or check backend logs.');
        }
        throw err;
    }
}

// =====================================================
// QUESTION ACTION APIS (Save, Review, Push to RTU)
// =====================================================
async function saveQuestion(questionId, questionData) {
    try {
        const storedUser = JSON.parse(localStorage.getItem('user') || 'null');
        const res = await fetch(`${API_BASE}/questions/${questionId}/save`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(storedUser?.id ? { 'X-User-Id': storedUser.id } : {})
            },
            credentials: 'include',
            body: JSON.stringify(questionData)
        });
        
        if (!res.ok) {
            const error = new Error(`HTTP error! status: ${res.status}`);
            error.status = res.status;
            throw error;
        }
        
        return await res.json();
    } catch (err) {
        console.error("saveQuestion() error:", err);
        throw err;
    }
}

async function reviewQuestion(questionId, comment = '') {
    try {
        const storedUser = JSON.parse(localStorage.getItem('user') || 'null');
        const res = await fetch(`${API_BASE}/questions/${questionId}/review`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(storedUser?.id ? { 'X-User-Id': storedUser.id } : {})
            },
            credentials: 'include',
            body: JSON.stringify({ reviewComment: comment })
        });
        
        if (!res.ok) {
            const error = new Error(`HTTP error! status: ${res.status}`);
            error.status = res.status;
            throw error;
        }
        
        return await res.json();
    } catch (err) {
        console.error("reviewQuestion() error:", err);
        throw err;
    }
}

async function pushToRTU(questionId) {
    try {
        const storedUser = JSON.parse(localStorage.getItem('user') || 'null');
        const res = await fetch(`${API_BASE}/questions/${questionId}/push-to-rtu`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(storedUser?.id ? { 'X-User-Id': storedUser.id } : {})
            },
            credentials: 'include',
            body: JSON.stringify({})
        });
        
        if (!res.ok) {
            const error = new Error(`HTTP error! status: ${res.status}`);
            error.status = res.status;
            throw error;
        }
        
        return await res.json();
    } catch (err) {
        console.error("pushToRTU() error:", err);
        throw err;
    }
}

async function getQuestionHistory(questionId) {
    try {
        const storedUser = JSON.parse(localStorage.getItem('user') || 'null');
        const res = await fetch(`${API_BASE}/questions/${questionId}/history`, {
            headers: {
                ...(storedUser?.id ? { 'X-User-Id': storedUser.id } : {})
            },
            credentials: 'include'
        });
        
        if (!res.ok) {
            const error = new Error(`HTTP error! status: ${res.status}`);
            error.status = res.status;
            throw error;
        }
        
        return await res.json();
    } catch (err) {
        console.error("getQuestionHistory() error:", err);
        throw err;
    }
}

async function getHighLevelHistory(limit = 100, offset = 0) {
    try {
        const storedUser = JSON.parse(localStorage.getItem('user') || 'null');
        const res = await fetch(`${API_BASE}/history/high-level?limit=${limit}&offset=${offset}`, {
            headers: {
                ...(storedUser?.id ? { 'X-User-Id': storedUser.id } : {})
            },
            credentials: 'include'
        });
        
        if (!res.ok) {
            const error = new Error(`HTTP error! status: ${res.status}`);
            error.status = res.status;
            throw error;
        }
        
        return await res.json();
    } catch (err) {
        console.error("getHighLevelHistory() error:", err);
        throw err;
    }
}

// Backfill audit logs from existing edited documents (Admin only)
async function backfillEdits() {
    try {
        const storedUser = JSON.parse(localStorage.getItem('user') || 'null');
        const res = await fetch(`${API_BASE}/history/backfill-edits`, {
            method: 'POST',
            headers: {
                ...(storedUser?.id ? { 'X-User-Id': storedUser.id } : {})
            },
            credentials: 'include'
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.error || 'Backfill failed');
        }
        return await res.json();
    } catch (err) {
        console.error('backfillEdits() error:', err);
        throw err;
    }
}

async function signupUser(userData) {
    try {
        const res = await fetch(`${API_BASE}/auth/signup`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(userData)
        });

        const data = await res.json();

        if (!res.ok) {
            throw new Error(data.error || 'Signup failed');
        }

        return data;
    } catch (err) {
        console.error("signupUser() error:", err);
        throw err;
    }
}

// =====================================================
// REVIEW QUEUE API
// =====================================================
async function fetchReviewQueue() {
    try {
        const res = await fetch(`${API_BASE}/review-queue`, { credentials: 'include' });
        if (!res.ok) throw new Error('Failed to fetch review queue');
        return await res.json();
    } catch (err) {
        console.error('fetchReviewQueue() error:', err);
        throw err;
    }
}

// =====================================================
// ADMIN: Pending signups API
// =====================================================
async function getPendingSignups() {
    try {
        const res = await fetch(`${API_BASE}/auth/pending-signups`, { credentials: 'include' });
        if (!res.ok) throw new Error('Failed to fetch pending signups');
        return await res.json();
    } catch (err) {
        console.error('getPendingSignups() error:', err);
        throw err;
    }
}

async function approveSignup(userId, role) {
    try {
        const res = await fetch(`${API_BASE}/auth/approve/${userId}`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ role })
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.error || 'Approve failed');
        }
        return await res.json();
    } catch (err) {
        console.error('approveSignup() error:', err);
        throw err;
    }
}

async function fetchUnpushed() {
    try {
        const res = await fetch(`${API_BASE}/questions/unpushed`, { credentials: 'include' });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.error || `HTTP ${res.status}`);
        }
        return await res.json();
    } catch (err) {
        console.error('fetchUnpushed() error:', err);
        throw err;
    }
}

async function batchPushToRTU() {
    try {
        const res = await fetch(`${API_BASE}/questions/batch-push-rtu`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({})
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.error || `HTTP ${res.status}`);
        }
        return await res.json();
    } catch (err) {
        console.error('batchPushToRTU() error:', err);
        throw err;
    }
}

async function rejectSignup(userId) {
    try {
        const res = await fetch(`${API_BASE}/auth/reject/${userId}`, {
            method: 'POST',
            credentials: 'include'
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.error || 'Reject failed');
        }
        return await res.json();
    } catch (err) {
        console.error('rejectSignup() error:', err);
        throw err;
    }
}