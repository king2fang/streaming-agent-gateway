"""S6b: overwrite app.js with modern interaction logic."""
import sys
from pathlib import Path

FILES = {

"app/static/app.js": r'''let currentRunId = null;
let abortController = null;
let lastEventId = 0;
let isReasoning = false;

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

function setConnStatus(txt, color = "#111827") {
    el("st-conn").textContent = txt;
    el("st-conn").style.color = color;
}

function setRunStatus(txt, turn = null) {
    if (turn !== null) el("st-run").textContent = `${txt} / ${turn}`;
    else el("st-run").textContent = txt;
}

function updateUIButtons(state) {
    el("btn-create").disabled = (state !== "idle");
    el("btn-disconnect").disabled = (state !== "connected");
    el("btn-reconnect").disabled = !(state === "disconnected" && currentRunId);
    el("btn-cancel").disabled = (state === "idle" || state === "terminal");
}

function clearUI() {
    if (abortController) abortController.abort();
    currentRunId = null; lastEventId = 0; isReasoning = false;
    el("st-runid").textContent = "-";
    setConnStatus("未连接", "#6b7280");
    setRunStatus("Idle / 0");
    el("st-tokens").textContent = "0";
    el("text-output").innerHTML = '<div class="empty-state">等待模型输出...</div>';
    el("terminal-log").innerHTML = "等待事件...";
    updateUIButtons("idle");
}

async function createRun() {
    const model = el("model-select").value;
    const prompt = el("prompt-input").value.trim();
    if (!prompt) return alert("请输入提示词");

    clearUI();
    updateUIButtons("busy");
    setConnStatus("Creating...", "#4f46e5");
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
        setRunStatus("pending");
        
        connectSSE();

    } catch (e) {
        log(`[Error] ${e.message}`, "err");
        setConnStatus("Error", "#ef4444");
        updateUIButtons("idle");
    }
}

async function connectSSE() {
    if (!currentRunId) return;
    abortController = new AbortController();
    setConnStatus("Connected (SSE)", "#10b981");
    updateUIButtons("connected");
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
            buffer = parts.pop(); // 留下最后一个不完整的包

            for (const part of parts) {
                if (part.trim()) parseSSE(part);
            }
        }
        
        // 自然结束
        setConnStatus("Closed by Server", "#6b7280");
        updateUIButtons("terminal");
        log("[Client] Stream closed by server.", "meta");

    } catch (e) {
        if (e.name === "AbortError") {
            log("[Client] Connection manually aborted.", "warn");
        } else {
            log(`[Client Error] ${e.message}`, "err");
            setConnStatus("Error", "#ef4444");
        }
        updateUIButtons("disconnected");
    }
}

function disconnectSSE() {
    if (abortController) abortController.abort();
    setConnStatus("Disconnected", "#f59e0b");
    log("[Client] Disconnected. Run continues on server.", "warn");
    updateUIButtons("disconnected");
}

function reconnectSSE() {
    if (!currentRunId) return;
    log(`[Client] Reconnecting... (resume from seq: ${lastEventId})`, "warn");
    connectSSE();
}

async function cancelRun() {
    if (!currentRunId) return;
    log("[Client] Sending cancel request...", "err");
    disconnectSSE();
    try {
        await fetch(`/v1/runs/${currentRunId}/cancel`, { method: "POST" });
        setRunStatus("cancelled");
        updateUIButtons("terminal");
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
        setConnStatus("Completed", "#6b7280");
        updateUIButtons("terminal");
        return;
    }

    if (!data) return;

    try {
        const parsed = JSON.parse(data);
        
        if (event === "message.delta" || event === "reasoning.delta") {
            const isReason = event === "reasoning.delta";
            const delta = isReason ? parsed.choices[0]?.delta?.reasoning_content : parsed.choices[0]?.delta?.content;
            
            if (delta) {
                renderText(delta, isReason);
            }
        } else if (event === "run.started") {
            setRunStatus("running", 1);
        } else if (event === "model.request.started") {
            setRunStatus("running", parsed.attempt);
        } else if (event === "message.completed" || event === "run.completed") {
            if (parsed.usage) el("st-tokens").textContent = parsed.usage.total_tokens;
            if (event === "run.completed") setRunStatus("completed");
        } else if (event === "error") {
            log(`[Server Error] ${parsed.error.message}`, "err");
            setRunStatus("failed");
            setConnStatus("Failed", "#ef4444");
        } else if (event === "cancelled") {
            setRunStatus("cancelled");
            setConnStatus("Cancelled", "#ef4444");
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
''',

}


def main():
    root = Path.cwd()
    if not (root / "pyproject.toml").exists():
        if (root / "streaming-agent-gateway").exists():
            root = root / "streaming-agent-gateway"
        else:
            sys.exit(f"not a gateway project: {root}")
    for rel, content in FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8", newline="\n")
        print(f"  = {rel:28s} {content.count(chr(10)):3d} lines")
    print("\nDone. Next: pytest -v")


if __name__ == "__main__":
    main()