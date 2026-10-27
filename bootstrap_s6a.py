"""S6a: overwrite index.html with modern UI."""
import sys
from pathlib import Path

FILES = {

"app/static/index.html": r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Streaming Agent Gateway 演示</title>
    <style>
        :root {
            --bg-color: #f3f4f6;
            --card-bg: #ffffff;
            --text-main: #111827;
            --text-muted: #6b7280;
            --border-color: #e5e7eb;
            --primary: #4f46e5;
            --primary-hover: #4338ca;
            --danger: #ef4444;
            --danger-hover: #dc2626;
            --terminal-bg: #1e1e24;
            --terminal-text: #a9b2c3;
        }
        * { box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-main);
            margin: 0;
            padding: 40px 20px;
            line-height: 1.5;
        }
        .container { max-width: 1200px; margin: 0 auto; display: flex; flex-direction: column; gap: 24px; }
        .card {
            background: var(--card-bg);
            border-radius: 16px;
            padding: 24px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
        }
        h1 { margin: 0 0 8px 0; font-size: 28px; font-weight: 700; letter-spacing: -0.025em; }
        .subtitle { color: var(--text-muted); font-size: 15px; margin: 0 0 24px 0; }
        
        /* Input Area */
        .input-group { margin-bottom: 16px; }
        textarea {
            width: 100%;
            min-height: 120px;
            padding: 16px;
            border: 1px solid var(--border-color);
            border-radius: 12px;
            font-size: 15px;
            font-family: inherit;
            resize: vertical;
            outline: none;
            transition: border-color 0.2s;
        }
        textarea:focus { border-color: var(--primary); }
        .model-select {
            padding: 10px 16px;
            border: 1px solid var(--border-color);
            border-radius: 8px;
            font-size: 14px;
            outline: none;
            background: white;
            cursor: pointer;
            margin-bottom: 16px;
            font-weight: 500;
        }
        
        /* Buttons */
        .controls { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
        button {
            padding: 10px 20px;
            border: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            display: inline-flex;
            align-items: center;
            justify-content: center;
        }
        button:disabled { opacity: 0.5; cursor: not-allowed; }
        .btn-primary { background: var(--primary); color: white; }
        .btn-primary:hover:not(:disabled) { background: var(--primary-hover); }
        .btn-secondary { background: #f3f4f6; color: var(--text-main); border: 1px solid var(--border-color); }
        .btn-secondary:hover:not(:disabled) { background: #e5e7eb; }
        .btn-danger { background: var(--danger); color: white; }
        .btn-danger:hover:not(:disabled) { background: var(--danger-hover); }

        .hint { font-size: 13px; color: var(--text-muted); margin-top: 16px; line-height: 1.6; }

        /* Status Grid */
        .status-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
        .status-card {
            background: #f9fafb;
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 16px;
        }
        .status-label { font-size: 13px; color: var(--text-muted); font-weight: 500; margin-bottom: 6px; }
        .status-value { font-size: 15px; font-weight: 600; font-family: "Courier New", Courier, monospace; word-break: break-all; }

        /* Split View */
        .split-view { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
        @media (max-width: 900px) { .split-view { grid-template-columns: 1fr; } }
        
        .panel-header { font-size: 18px; font-weight: 700; margin: 0 0 16px 0; display: flex; align-items: center; gap: 8px; }
        
        /* Text Output */
        .text-output {
            background: #f9fafb;
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 20px;
            min-height: 300px;
            max-height: 500px;
            overflow-y: auto;
            font-size: 15px;
            line-height: 1.7;
            white-space: pre-wrap;
        }
        .reasoning-text { color: #9ca3af; font-style: italic; display: block; padding-bottom: 8px; margin-bottom: 8px; border-bottom: 1px dashed #e5e7eb; }
        .content-text { color: var(--text-main); }
        .empty-state { color: #9ca3af; text-align: center; margin-top: 100px; font-size: 14px; }
        
        /* Terminal Log */
        .terminal {
            background: var(--terminal-bg);
            color: var(--terminal-text);
            border-radius: 12px;
            padding: 20px;
            font-family: "Fira Code", "Courier New", Courier, monospace;
            font-size: 13px;
            min-height: 300px;
            max-height: 500px;
            overflow-y: auto;
            white-space: pre-wrap;
            box-shadow: inset 0 2px 4px rgba(0,0,0,0.1);
        }
        .log-line { margin-bottom: 6px; }
        .log-meta { color: #6366f1; font-weight: bold; }
        .log-data { color: #10b981; }
        .log-warn { color: #f59e0b; }
        .log-err { color: #ef4444; }
    </style>
</head>
<body>
    <div class="container">
        <!-- 顶部控制区 -->
        <div class="card">
            <h1>Streaming Agent Gateway 浏览器流式演示</h1>
            <p class="subtitle">基于 SSE 协议的真实大模型流式输出，支持断线重连、状态追踪与取消。</p>
            
            <div class="input-group">
                <select id="model-select" class="model-select">
                    <option value="deepseek-chat">DeepSeek Chat</option>
                    <option value="qwen-plus">Qwen Plus</option>
                    <option value="mock">Mock Model (测试用)</option>
                </select>
                <textarea id="prompt-input" placeholder="请输入你的提示词...">请用中文解释 EventSource 为什么适合订阅 SSE</textarea>
            </div>

            <div class="controls">
                <button id="btn-create" class="btn-primary" onclick="createRun()">创建 Run 并开始订阅</button>
                <button id="btn-disconnect" class="btn-secondary" onclick="disconnectSSE()" disabled>断开当前订阅</button>
                <button id="btn-reconnect" class="btn-secondary" onclick="reconnectSSE()" disabled>重连已有 RunID</button>
                <button id="btn-clear" class="btn-secondary" onclick="clearUI()">清除消息</button>
                <button id="btn-cancel" class="btn-danger" onclick="cancelRun()" disabled>取消当前 Run</button>
            </div>

            <p class="hint">
                * 断开当前订阅（模拟网络断开或页面关闭），后台 Agent 会继续运行。<br>
                * 重连已有 RunID 会携带 <code>Last-Event-ID</code> 进行断点续传，浏览器标签页的转圈是 SSE 正常保持长连接的表现。
            </p>
        </div>

        <!-- 状态展示区 -->
        <div class="status-grid">
            <div class="status-card">
                <div class="status-label">当前 Run ID</div>
                <div class="status-value" id="st-runid">-</div>
            </div>
            <div class="status-card">
                <div class="status-label">连接状态</div>
                <div class="status-value" id="st-conn">未连接</div>
            </div>
            <div class="status-card">
                <div class="status-label">运行状态 / 轮次</div>
                <div class="status-value" id="st-run">Idle / 0</div>
            </div>
            <div class="status-card">
                <div class="status-label">Tokens 消耗</div>
                <div class="status-value" id="st-tokens">0</div>
            </div>
        </div>

        <!-- 核心结果区 -->
        <div class="split-view">
            <div class="card">
                <h2 class="panel-header">拼接后的模型文本</h2>
                <div class="text-output" id="text-output">
                    <div class="empty-state">等待模型输出...</div>
                </div>
            </div>
            <div class="card">
                <h2 class="panel-header">SSE 原始事件日志</h2>
                <div class="terminal" id="terminal-log">等待事件...</div>
            </div>
        </div>
    </div>
    <script src="/app.js"></script>
</body>
</html>
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
    print("\nDone. Next: run bootstrap_s6b.py")


if __name__ == "__main__":
    main()