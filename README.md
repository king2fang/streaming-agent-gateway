# Streaming Agent Gateway

一个基于 FastAPI 构建的单进程 Agent 运行网关。它接收用户请求，驱动底层 LLM 生成流式输出，并通过标准的 Server-Sent Events (SSE) 将状态推送给前端。完美兼容 OpenAI 的 `chat.completion.chunk` 协议，提供 Web 与 CLI 双端体验。

## ✨ 核心特性

- 🚀 **标准化协议**：对外输出严格对齐 OpenAI Chunk 格式，可直接被标准 SDK 消费。
- 🔄 **断线续传与缺口处理**：利用内存热缓冲与 `Last-Event-ID`，支持客户端断网重连后补齐丢失的事件，并显式发送 `event: gap` 预警。
- 🧠 **多模型接入**：内置 `OpenAICompatibleAdapter`，支持接入真实大模型（DeepSeek、通义千问），并支持自定义 Mock 模型。
- 🛑 **生命周期控制**：支持精准的取消机制、网络超时控制、以及模型断流的异常兜底。
- 🛠️ **Tool Call 与 Loop 调度**：原生支持解析流式 Tool Call 参数，自动执行内置工具（如计算器）并回传结果形成多轮对话。
- 💻 **双端可视化**：提供原生 HTML/JS 的高颜值 Web UI 与基于 `rich` 库的终端 CLI (`sag`)。

## 🛠️ 技术栈
- **Python**: 3.11+
- **Web Framework**: FastAPI + Uvicorn
- **Network**: httpx (HTTP/SSE 客户端)
- **CLI**: rich
- **Testing**: pytest + pytest-asyncio

## 🚀 快速开始（Windows + VSCode 环境）

请确保你的系统已安装 **Python 3.11** 或更高版本。

### 1. 克隆仓库与安装依赖

```powershell
git clone <你的Github仓库链接>
cd streaming-agent-gateway

# 创建并激活虚拟环境
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 以可编辑模式安装项目（包含依赖包及 sag CLI 命令注册）
pip install -e ".[dev]"