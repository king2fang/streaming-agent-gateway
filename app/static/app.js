let currentRunId = null;
let abortController = null;
let lastEventId = 0;

// 拆分两个独立状态
let currentRunStatus = "idle"; 
let currentConnState = "idle"; 

function el(id) { return document.getElementById(id); }

function log(msg, type = "normal") {
    const term = el("terminal-log");
    if (term.innerHTML === "等待事件...") term.innerHTML = "";
    const div = document.createElement("div");
    div.className = "log-line";
    if (type === "meta") div.innerHTML = `<span class="log-meta">${msg}</span>`;
    else if (type === "data") div.innerHTML = `<span class="log-data">${msg}</span>`;
    else if (type === "warn") div.innerHTML = `<span class="log-warn">${msg}</span>`;
    else if (type === "err") div.innerHTML = `<span class="log-err">${msg}</span>`;
    else div.textContent = msg;
    term.appendChild(div);
    term.scrollTop = term.scrollHeight;
}

function updateConn(txt, color, state) {
    el("st-conn").textContent = txt;
    el("st-conn").style.color = color;
    currentConnState = state;
    updateUIButtons();
}

function updateRun(txt, turn = null) {
    currentRunStatus = txt;
    if (turn !== null) el("st-run").textContent = `${txt} / ${turn}`;
    else el("st-run").textContent = txt;
    updateUIButtons();
}

function updateUIButtons() {
    const isTerminal = ["completed", "failed", "cancelled"].includes(currentRunStatus);
    
    // 创建按钮：只有在完全空闲（非运行、非连接）时可用
    el("btn-create").disabled = (currentConnState !== "idle");
    
    // 断开按钮：只有在已连接且未结束时可用
    el("btn-disconnect").disabled = (currentConnState !== "connected" || isTerminal);
    
    // 重连按钮：只有在已断开、有RunID、且未结束时可用
    el("btn-reconnect").disabled = !(currentConnState === "disconnected" && currentRunId && !isTerminal);
    
    // 取消按钮：只要有RunID且未结束时可用
    el("btn-cancel").disabled = (currentConnState === "idle" || isTerminal);
}

function clearUI() {
    if (abortController) abortController.abort();
    currentRunId = null; 
    lastEventId = 0;
    el("st-runid").textContent = "-";
    updateConn("未连接", "#6b7280", "idle");
    updateRun("Idle");
    el("st-tokens").textContent = "0";
    el("text-output").innerHTML = '<div class="empty-state">等待模型输出...</div>';
    el("terminal-log").innerHTML = "等待事件...";
}

async function createRun() {
    const model = el("model-select").value;
    const prompt = el("prompt-input").value.trim();
    if (!prompt) return alert("请输入提示词");

    clearUI();
    el("btn-create").disabled = true; // 防止双击
    updateConn("Creating...", "#4f46e5", "creating");
    updateRun("pending");
    log(`[Client] Creating run for model: ${model}`, "meta");

    try {
        const res = await fetch("/v1/runs", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ model, messages: [{ role: "user", content: prompt }] })
        });
        if (!res.ok) throw new Error(await res.text());
        
        const data = await res.json();
        currentRunId = data.run_id;
        el("st-runid").textContent = currentRunId;
        
        connectSSE();

    } catch (e) {
        log(`[Error] ${e.message}`, "err");
        updateConn("Error", "#ef4444", "idle");
        updateRun("failed");
    }
}

async function connectSSE() {
    if (!currentRunId) return;
    abortController = new AbortController();
    updateConn("Connected (SSE)", "#10b981", "connected");
    log(`[Client] Subscribing to stream (Last-Event-ID: ${lastEventId})...`, "meta");

    try {
        const res = await fetch(`/v1/runs/${currentRunId}/stream`, {
            method: "GET",
            headers: { "Last-Event-ID": lastEventId.toString() },
            signal: abortController.signal
        });

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            let parts = buffer.split("\n\n");
            buffer = parts.pop();

            for (const part of parts) {
                if (part.trim()) parseSSE(part);
            }
        }
        
        updateConn("Closed", "#6b7280", "disconnected");

    } catch (e) {
        if (e.name === "AbortError") {
            log("[Client] Connection manually aborted.", "warn");
        } else {
            log(`[Client Error] ${e.message}`, "err");
            updateConn("Error", "#ef4444", "disconnected");
        }
    }
}

function disconnectSSE() {
    if (abortController) abortController.abort();
    updateConn("Disconnected", "#f59e0b", "disconnected");
    log("[Client] Disconnected. Run continues on server.", "warn");
}

function reconnectSSE() {
    if (!currentRunId) return;
    log(`[Client] Reconnecting... (resume from seq: ${lastEventId})`, "warn");
    connectSSE();
}

async function cancelRun() {
    if (!currentRunId) return;
    log("[Client] Sending cancel request...", "err");
    
    if (abortController) abortController.abort();
    updateConn("Disconnected", "#6b7280", "disconnected");
    updateRun("cancelling"); // 避免用户此时点重连

    try {
        await fetch(`/v1/runs/${currentRunId}/cancel`, { method: "POST" });
    } catch (e) {
        log(`[Cancel Error] ${e.message}`, "err");
    }
}

function parseSSE(rawBlock) {
    const lines = rawBlock.split("\n");
    let id = null, event = "message", data = "";

    for (const line of lines) {
        if (line.startsWith("id: ")) id = line.slice(4);
        else if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data = line.slice(6);
        else if (line.startsWith(": ")) {
            log(`[Ping] ${line.slice(2)}`, "meta");
            continue;
        }
    }

    if (id) {
        lastEventId = parseInt(id, 10);
        log(`[SSE] seq: ${id} | event: ${event}`, "meta");
    }

    if (data === "[DONE]") {
        log("[SSE] Stream Done", "meta");
        updateConn("Completed", "#6b7280", "disconnected");
        return;
    }

    if (!data) return;

    try {
        const parsed = JSON.parse(data);
        
        if (event === "message.delta" || event === "reasoning.delta") {
            const isReason = event === "reasoning.delta";
            const delta = isReason ? parsed.choices[0]?.delta?.reasoning_content : parsed.choices[0]?.delta?.content;
            if (delta) renderText(delta, isReason);
        } else if (event === "run.started") {
            updateRun("running", 1);
        } else if (event === "model.request.started") {
            updateRun("running", parsed.attempt);
        } else if (event === "message.completed" || event === "run.completed") {
            if (parsed.usage) el("st-tokens").textContent = parsed.usage.total_tokens;
            if (event === "run.completed") updateRun("completed");
        } else if (event === "error") {
            log(`[Server Error] ${parsed.error.message}`, "err");
            updateRun("failed");
            updateConn("Failed", "#ef4444", "disconnected");
        } else if (event === "cancelled") {
            updateRun("cancelled");
            updateConn("Cancelled", "#ef4444", "disconnected");
        } else if (event === "gap") {
            log(`[Gap] Missed events! Earliest available: ${parsed.earliest_available_id}`, "err");
        }
    } catch (e) {
        log(`[Parse Error] ${e.message}`, "err");
    }
}

function renderText(text, isReason) {
    const out = el("text-output");
    if (out.innerHTML.includes("empty-state")) out.innerHTML = "";

    let reasonSpan = out.querySelector(".reasoning-text");
    let contentSpan = out.querySelector(".content-text");

    if (isReason) {
        if (!reasonSpan) {
            reasonSpan = document.createElement("span");
            reasonSpan.className = "reasoning-text";
            out.prepend(reasonSpan);
        }
        reasonSpan.textContent += text;
    } else {
        if (!contentSpan) {
            contentSpan = document.createElement("span");
            contentSpan.className = "content-text";
            out.appendChild(contentSpan);
        }
        contentSpan.textContent += text;
    }
    out.scrollTop = out.scrollHeight;
}

document.addEventListener("DOMContentLoaded", () => {
    clearUI();
});