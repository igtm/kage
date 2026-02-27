from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

import uvicorn
import sqlite3
import webbrowser
import threading
import time
from pathlib import Path
from .config import KAGE_DB_PATH, get_global_config

app = FastAPI(title="kage UI")

INDEX_HTML = """
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>kage Dashboard</title>
    <style>
        :root {
            --bg-color: #0d1117;
            --text-color: #c9d1d9;
            --card-bg: #161b22;
            --border-color: #30363d;
            --accent-color: #58a6ff;
            --success-color: #2ea043;
            --error-color: #f85149;
            --secondary-text: #8b949e;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-color);
            margin: 0;
            padding: 20px;
            display: flex;
            flex-direction: column;
            align-items: center;
        }
        .header {
            width: 100%;
            max-width: 1000px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2rem;
        }
        .header-right {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .github-link {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 36px;
            height: 36px;
            border: 1px solid var(--border-color);
            border-radius: 999px;
            color: var(--text-color);
            transition: border-color 0.2s, color 0.2s, background-color 0.2s;
            text-decoration: none;
        }
        .github-link:hover {
            color: var(--accent-color);
            border-color: var(--accent-color);
            background-color: rgba(88, 166, 255, 0.08);
        }
        .github-link svg {
            width: 18px;
            height: 18px;
            fill: currentColor;
        }
        h1 {
            color: var(--accent-color);
            margin: 0;
            font-weight: 600;
        }
        .tabs {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            width: 100%;
            max-width: 1000px;
            border-bottom: 1px solid var(--border-color);
        }
        .tab {
            padding: 10px 20px;
            cursor: pointer;
            border-bottom: 2px solid transparent;
            color: var(--secondary-text);
            font-weight: bold;
        }
        .tab.active {
            color: var(--accent-color);
            border-bottom: 2px solid var(--accent-color);
        }
        .container {
            width: 100%;
            max-width: 1000px;
        }
        .section {
            display: none;
        }
        .section.active {
            display: block;
        }
        .task-card, .config-card, .task-list-item {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .task-list-item.inactive {
            opacity: 0.6;
        }
        .task-list-item h3 { margin-top: 0; color: var(--accent-color); }
        .task-list-head {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 12px;
        }
        .task-list-head h3 { margin: 0; color: var(--accent-color); }
        .task-controls {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .task-run-button {
            background-color: var(--success-color);
            color: white;
            border: none;
            border-radius: 6px;
            padding: 6px 12px;
            font-size: 0.85rem;
            font-weight: bold;
            cursor: pointer;
            transition: opacity 0.2s;
            white-space: nowrap;
        }
        .task-run-button:hover { opacity: 0.85; }
        .task-run-button:disabled {
            background-color: var(--border-color);
            color: var(--secondary-text);
            cursor: not-allowed;
        }
        /* Toggle Switch */
        .switch {
            position: relative;
            display: inline-block;
            width: 44px;
            height: 22px;
        }
        .switch input { opacity: 0; width: 0; height: 0; }
        .slider {
            position: absolute;
            cursor: pointer;
            top: 0; left: 0; right: 0; bottom: 0;
            background-color: var(--border-color);
            transition: .4s;
            border-radius: 22px;
        }
        .slider:before {
            position: absolute;
            content: "";
            height: 16px; width: 16px;
            left: 3px; bottom: 3px;
            background-color: white;
            transition: .4s;
            border-radius: 50%;
        }
        input:checked + .slider { background-color: var(--accent-color); }
        input:checked + .slider:before { transform: translateX(22px); }

        .task-run-message {
            margin-top: 10px;
            font-size: 0.85rem;
            color: var(--secondary-text);
        }
        .task-run-message.error { color: var(--error-color); }
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 10px;
            margin-bottom: 10px;
        }
        .task-name { font-size: 1.25rem; font-weight: bold; }
        .status {
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 0.85rem;
            font-weight: bold;
        }
        .status.SUCCESS { background-color: rgba(46, 160, 67, 0.2); color: var(--success-color); }
        .status.FAILED, .status.ERROR { background-color: rgba(248, 81, 73, 0.2); color: var(--error-color); }
        .details { font-size: 0.9rem; color: var(--secondary-text); margin-bottom: 10px; }
        pre {
            background-color: #010409;
            padding: 10px;
            border-radius: 6px;
            overflow-x: auto;
            color: #e6edf3;
            font-size: 0.85rem;
            max-height: 300px;
        }
        .config-label { color: var(--accent-color); font-weight: bold; margin-bottom: 5px; display: block; }

        /* Chat UI Styles */
        #chat-section {
            display: none;
            flex-direction: column;
            height: 70vh;
        }
        #chat-section.active {
            display: flex;
        }
        #chat-history {
            flex-grow: 1;
            overflow-y: auto;
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
            display: flex;
            flex-direction: column;
            gap: 15px;
        }
        .message {
            max-width: 85%;
            padding: 12px 16px;
            border-radius: 8px;
            line-height: 1.5;
        }
        .message.user {
            align-self: flex-end;
            background-color: var(--accent-color);
            color: #0d1117;
            border-bottom-right-radius: 0;
        }
        .message.assistant {
            align-self: flex-start;
            background-color: #21262d;
            border: 1px solid var(--border-color);
            border-bottom-left-radius: 0;
        }
        .message.error {
            background-color: rgba(248, 81, 73, 0.2);
            color: var(--error-color);
            border: 1px solid var(--error-color);
        }
        .message pre {
            background-color: #0d1117;
            margin-top: 10px;
            max-height: 500px;
        }
        .chat-input-container {
            display: flex;
            gap: 10px;
        }
        #chat-input {
            flex-grow: 1;
            background-color: #0d1117;
            color: var(--text-color);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 12px;
            font-family: inherit;
            resize: none;
            height: 50px;
        }
        #chat-input:focus {
            outline: none;
            border-color: var(--accent-color);
        }
        #chat-submit {
            background-color: var(--success-color);
            color: white;
            border: none;
            border-radius: 6px;
            padding: 0 20px;
            font-weight: bold;
            cursor: pointer;
            transition: opacity 0.2s;
        }
        #chat-submit:hover {
            opacity: 0.8;
        }
        #chat-submit:disabled {
            background-color: var(--border-color);
            color: var(--secondary-text);
            cursor: not-allowed;
        }
        .loading-dots:after {
            content: '.';
            animation: dots 1.5s steps(5, end) infinite;
        }
        @keyframes dots {
            0%, 20% { color: rgba(0,0,0,0); text-shadow: .25em 0 0 rgba(0,0,0,0), .5em 0 0 rgba(0,0,0,0);}
            40% { color: inherit; text-shadow: .25em 0 0 rgba(0,0,0,0), .5em 0 0 rgba(0,0,0,0);}
            60% { text-shadow: .25em 0 0 inherit, .5em 0 0 rgba(0,0,0,0);}
            80%, 100% { text-shadow: .25em 0 0 inherit, .5em 0 0 inherit;}
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>kage Dashboard 🌑</h1>
        <div class="header-right">
            <a class="github-link" href="https://github.com/igtm/kage" target="_blank" rel="noopener noreferrer" aria-label="kage GitHub repository" title="GitHub">
                <svg viewBox="0 0 16 16" aria-hidden="true">
                    <path d="M8 0C3.58 0 0 3.67 0 8.2c0 3.63 2.29 6.71 5.47 7.8.4.08.55-.18.55-.39 0-.19-.01-.83-.01-1.5-2.01.38-2.53-.5-2.69-.96-.09-.23-.48-.96-.82-1.16-.28-.15-.68-.54-.01-.55.63-.01 1.08.59 1.23.84.72 1.24 1.87.89 2.33.68.07-.54.28-.89.5-1.1-1.78-.21-3.64-.92-3.64-4.08 0-.9.31-1.64.82-2.22-.08-.21-.36-1.04.08-2.16 0 0 .67-.22 2.2.85.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.07 2.2-.85 2.2-.85.44 1.12.16 1.95.08 2.16.51.58.82 1.31.82 2.22 0 3.17-1.87 3.87-3.65 4.08.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.47.55.39A8.24 8.24 0 0 0 16 8.2C16 3.67 12.42 0 8 0z"/>
                </svg>
            </a>
        </div>
    </div>
    
    <div class="tabs">
        <div class="tab active" data-section="logs">Execution Logs</div>
        <div class="tab" data-section="config">Settings & Task List</div>
        <div class="tab" data-section="chat">AI Chat</div>
    </div>

    <div class="container">
        <div id="logs-section" class="section active">
            <div id="logs-container">Loading logs...</div>
        </div>
        
        <div id="config-section" class="section">
            <div id="config-container">Loading configuration...</div>
        </div>
        
        <div id="chat-section" class="section">
            <div id="chat-history">
                <div class="message assistant">
                    Hi! I'm the kage AI assistant. I can help you configure tasks, explain logs, or execute commands using your default AI engine. What would you like to do?
                </div>
            </div>
            <div class="chat-input-container">
                <textarea id="chat-input" placeholder="Ask AI to create a task or check config... (Shift+Enter for new line, Enter to send)"></textarea>
                <button id="chat-submit">Send</button>
            </div>
        </div>
    </div>

    <script>
        let lastLogsSignature = null;

        function escapeHtml(text) {
            return String(text)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;');
        }

        document.querySelectorAll('.tab').forEach(tab => {
            tab.addEventListener('click', () => {
                const sectionName = tab.getAttribute('data-section');
                showSection(sectionName, tab);
            });
        });

        function showSection(name, tabElement) {
            document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            
            document.getElementById(name + '-section').classList.add('active');
            tabElement.classList.add('active');
            
            if (name === 'config') fetchConfig();
            if (name === 'logs') fetchLogs();
        }

        async function fetchLogs() {
            try {
                const response = await fetch('/api/logs');
                const logs = await response.json();
                const signature = JSON.stringify(logs);
                if (signature === lastLogsSignature) {
                    return;
                }
                lastLogsSignature = signature;
                const container = document.getElementById('logs-container');
                container.innerHTML = '';
                
                if (logs.length === 0) {
                    container.innerHTML = '<p>No execution logs found.</p>';
                    return;
                }

                logs.forEach(log => {
                    const card = document.createElement('div');
                    card.className = 'task-card';
                    const time = new Date(log.run_at).toLocaleString();
                    const statusClass = log.status || 'ERROR';

                    let outputHtml = '';
                    if (log.stdout) outputHtml += `<strong>stdout:</strong><pre>${escapeHtml(log.stdout)}</pre>`;
                    if (log.stderr) outputHtml += `<strong>stderr:</strong><pre>${escapeHtml(log.stderr)}</pre>`;

                    card.innerHTML = `
                        <div class="card-header">
                            <span class="task-name">${escapeHtml(log.task_name)}</span>
                            <span class="status ${statusClass}">${escapeHtml(log.status)}</span>
                        </div>
                        <div class="details">
                            <div><strong>Project:</strong> ${escapeHtml(log.project_path)}</div>
                            <div><strong>Run At:</strong> ${time}</div>
                        </div>
                        ${outputHtml}
                    `;
                    container.appendChild(card);
                });
            } catch (error) {
                document.getElementById('logs-container').innerHTML = '<p style="color:red">Failed to load logs.</p>';
            }
        }

        async function fetchConfig() {
            try {
                const response = await fetch('/api/config');
                const config = await response.json();
                const container = document.getElementById('config-container');
                
                let tasksHtml = '<span class="config-label">Registered Tasks</span>';
                if (config.tasks && config.tasks.length > 0) {
                    config.tasks.forEach(task => {
                        tasksHtml += `
                            <div class="task-list-item ${task.active ? '' : 'inactive'}">
                                <div class="task-list-head">
                                    <h3>${escapeHtml(task.name)}</h3>
                                    <div class="task-controls">
                                        <label class="switch" title="Enable/Disable task">
                                            <input type="checkbox" class="task-toggle" 
                                                data-project-path="${escapeHtml(task.project_path)}"
                                                data-task-name="${escapeHtml(task.name)}"
                                                data-file="${escapeHtml(task.file || '')}"
                                                ${task.active ? 'checked' : ''}>
                                            <span class="slider"></span>
                                        </label>
                                        <button
                                            class="task-run-button"
                                            data-project-path="${escapeHtml(task.project_path)}"
                                            data-task-name="${escapeHtml(task.name)}"
                                            data-file="${escapeHtml(task.file || '')}"
                                            ${task.active ? '' : 'disabled'}
                                        >
                                            Run now
                                        </button>
                                    </div>
                                </div>
                                <div class="details">
                                    <div><strong>Project:</strong> ${escapeHtml(task.project_path)}</div>
                                    <div><strong>Schedule:</strong> <code>${escapeHtml(task.cron)}</code> (Next: ${escapeHtml(task.next_run)})</div>
                                    ${task.prompt ? `<div><strong>AI Prompt:</strong> ${escapeHtml(task.prompt)}</div>` : ''}
                                    ${task.command ? `<div><strong>Command:</strong> <code>${escapeHtml(task.command)}</code></div>` : ''}
                                    ${task.provider ? `<div><strong>Provider:</strong> ${escapeHtml(task.provider)}</div>` : ''}
                                </div>
                                <div class="task-run-message"></div>
                            </div>
                        `;
                    });
                } else {
                    tasksHtml += '<p>No tasks registered. Use <code>kage init</code> in your project.</p>';
                }

                container.innerHTML = `
                    <div class="config-card">
                        <span class="config-label">Global Settings</span>
                        <div class="details">
                            <div><strong>Default AI Engine:</strong> ${config.default_ai_engine || 'None'}</div>
                            <div><strong>Log Level:</strong> ${config.log_level}</div>
                            <div><strong>UI Port:</strong> ${config.ui_port}</div>
                            <div><strong>Timezone:</strong> ${config.timezone}</div>
                        </div>
                    </div>
                    ${tasksHtml}
                `;
                wireRunButtons();
            } catch (error) {
                document.getElementById('config-container').innerHTML = '<p style="color:red">Failed to load configuration.</p>';
            }
        }

        function wireRunButtons() {
            document.querySelectorAll('.task-run-button').forEach(button => {
                button.addEventListener('click', async () => {
                    const projectPath = button.getAttribute('data-project-path') || '';
                    const taskName = button.getAttribute('data-task-name') || '';
                    const file = button.getAttribute('data-file') || '';
                    const messageEl = button.closest('.task-list-item')?.querySelector('.task-run-message');

                    button.disabled = true;
                    if (messageEl) {
                        messageEl.textContent = 'Starting...';
                        messageEl.classList.remove('error');
                    }

                    try {
                        const response = await fetch('/api/tasks/run', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                project_path: projectPath,
                                task_name: taskName,
                                file: file || null
                            })
                        });
                        const result = await response.json();
                        if (!response.ok) {
                            throw new Error(result.error || 'Failed to start task');
                        }
                        if (messageEl) {
                            messageEl.textContent = result.message || 'Task started';
                        }
                        fetchLogs();
                    } catch (error) {
                        if (messageEl) {
                            messageEl.textContent = error.message || 'Failed to start task';
                            messageEl.classList.add('error');
                        }
                    } finally {
                        button.disabled = false;
                    }
                });
            });

            document.querySelectorAll('.task-toggle').forEach(toggle => {
                toggle.addEventListener('change', async () => {
                    const projectPath = toggle.getAttribute('data-project-path') || '';
                    const taskName = toggle.getAttribute('data-task-name') || '';
                    const file = toggle.getAttribute('data-file') || '';
                    const active = toggle.checked;
                    const card = toggle.closest('.task-list-item');
                    const runBtn = card?.querySelector('.task-run-button');

                    try {
                        const response = await fetch('/api/tasks/toggle', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                project_path: projectPath,
                                task_name: taskName,
                                file: file || null,
                                active: active
                            })
                        });
                        if (!response.ok) {
                            throw new Error('Failed to toggle task');
                        }
                        
                        if (card) {
                            if (active) card.classList.remove('inactive');
                            else card.classList.add('inactive');
                        }
                        if (runBtn) {
                            runBtn.disabled = !active;
                        }
                    } catch (error) {
                        alert(error.message);
                        toggle.checked = !active;
                    }
                });
            });
        }

        fetchLogs();
        setInterval(() => {
            if (document.getElementById('logs-section').classList.contains('active')) {
                fetchLogs();
            }
        }, 5000);

        // Chat Logic
        const chatInput = document.getElementById('chat-input');
        const chatSubmit = document.getElementById('chat-submit');
        const chatHistory = document.getElementById('chat-history');

        function appendMessage(role, content, isHtml=false) {
            const msgDiv = document.createElement('div');
            msgDiv.className = `message ${role}`;
            if (isHtml) {
                msgDiv.innerHTML = content;
            } else {
                msgDiv.textContent = content;
            }
            chatHistory.appendChild(msgDiv);
            chatHistory.scrollTop = chatHistory.scrollHeight;
            return msgDiv;
        }

        async function sendChatMessage() {
            const text = chatInput.value.trim();
            if (!text) return;

            chatInput.value = '';
            chatInput.disabled = true;
            chatSubmit.disabled = true;
            appendMessage('user', text);

            const loadingMsg = appendMessage('assistant', '<span class="loading-dots">Thinking</span>', true);

            try {
                const response = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: text })
                });

                const result = await response.json();
                chatHistory.removeChild(loadingMsg);
                
                if (response.ok) {
                    let htmlRes = '';
                    if (result.stdout) htmlRes += `<pre>${result.stdout.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</pre>`;
                    if (result.stderr) htmlRes += `<pre style="color:var(--error-color)">${result.stderr.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</pre>`;
                    if (!result.stdout && !result.stderr) htmlRes = "Done with empty output.";
                    appendMessage('assistant', htmlRes, true);
                } else {
                    appendMessage('error', result.error || "Unknown error occurred.");
                }

            } catch (err) {
                chatHistory.removeChild(loadingMsg);
                appendMessage('error', "Network error or server down.");
            } finally {
                chatInput.disabled = false;
                chatSubmit.disabled = false;
                chatInput.focus();
            }
        }

        chatSubmit.addEventListener('click', sendChatMessage);
        chatInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendChatMessage();
            }
        });

    </script>
</body>
</html>
"""

class ChatRequest(BaseModel):
    message: str

class RunTaskRequest(BaseModel):
    project_path: str
    task_name: str
    file: str | None = None

class ToggleTaskRequest(BaseModel):
    project_path: str
    task_name: str
    active: bool
    file: str | None = None

@app.get("/", response_class=HTMLResponse)
def root():
    return INDEX_HTML

@app.get("/api/logs")
def get_logs():
    if not KAGE_DB_PATH.exists():
        return []
    conn = sqlite3.connect(KAGE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT id, project_path, task_name, run_at, status, stdout, stderr FROM executions ORDER BY run_at DESC LIMIT 50')
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "project_path": r[1], "task_name": r[2], "run_at": r[3], "status": r[4], "stdout": r[5], "stderr": r[6]} for r in rows]

@app.get("/api/config")
def get_config_api():
    from .scheduler import get_projects
    from .parser import load_project_tasks
    from datetime import datetime, timezone as dt_timezone
    import zoneinfo
    from croniter import croniter
    
    config = get_global_config()
    projects = get_projects()
    
    # Setup timezone for calculating next run
    tz_name = config.timezone
    try:
        tz = zoneinfo.ZoneInfo(tz_name)
    except Exception:
        tz = dt_timezone.utc
    now = datetime.now(tz)
    
    all_tasks = []
    for proj_dir in projects:
        tasks = load_project_tasks(proj_dir)
        for toml_path, task_def in tasks:
            t = task_def.task
            
            next_run_str = ""
            try:
                itr = croniter(t.cron, now)
                next_dt = itr.get_next(datetime)
                next_run_str = next_dt.strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                next_run_str = "Invalid cron"

            all_tasks.append({
                "name": t.name,
                "cron": t.cron,
                "active": t.active,
                "next_run": next_run_str,
                "prompt": t.prompt,
                "command": t.command,
                "provider": t.provider or (t.ai.engine if (t.ai and t.ai.engine) else None),
                "project_path": str(proj_dir),
                "file": str(toml_path)
            })

    return {
        "default_ai_engine": config.default_ai_engine,
        "log_level": config.log_level,
        "ui_port": config.ui_port,
        "timezone": config.timezone,
        "tasks": all_tasks
    }

@app.post("/api/tasks/run")
def run_task_now(req: RunTaskRequest):
    from .parser import load_project_tasks
    from .executor import execute_task

    proj_dir = Path(req.project_path).expanduser()
    if not proj_dir.exists():
        return JSONResponse(status_code=404, content={"error": "Project path does not exist."})

    matched_task = None
    for toml_path, local_task in load_project_tasks(proj_dir):
        if local_task.task.name != req.task_name:
            continue
        if req.file and str(toml_path) != req.file:
            continue
        matched_task = local_task.task
        break

    if matched_task is None:
        return JSONResponse(status_code=404, content={"error": "Task not found in the specified project."})

    threading.Thread(
        target=execute_task,
        args=(proj_dir, matched_task),
        daemon=True
    ).start()

    return {"message": f"Task '{req.task_name}' started."}

@app.post("/api/tasks/toggle")
def toggle_task(req: ToggleTaskRequest):
    import tomlkit
    import re
    from pathlib import Path

    task_file = Path(req.file) if req.file else None
    if not task_file or not task_file.exists():
        return JSONResponse(status_code=404, content={"error": "Task file not found."})

    try:
        content = task_file.read_text(encoding="utf-8")
        if task_file.suffix == ".md":
            new_val = "true" if req.active else "false"
            if "active:" in content:
                content = re.sub(r"active:\s*(true|false)", f"active: {new_val}", content)
            else:
                content = re.sub(r"(cron:.*?\n)", rf"\1active: {new_val}\n", content)
        else:
            doc = tomlkit.load(content)
            if "task" in doc:
                doc["task"]["active"] = req.active
            else:
                for k, v in doc.items():
                    if k.startswith("task") and isinstance(v, dict):
                        if v.get("name") == req.task_name:
                            v["active"] = req.active
            content = tomlkit.dumps(doc)
            
        task_file.write_text(content, encoding="utf-8")
        return {"message": f"Task '{req.task_name}' {'enabled' if req.active else 'disabled'}."}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/chat")
def handle_chat(req: ChatRequest):
    import subprocess
    import os
    from pathlib import Path
    
    config = get_global_config()
    engine_name = config.default_ai_engine
    if not engine_name:
        return JSONResponse(status_code=400, content={"error": "default_ai_engine is not set in global config."})
        
    provider = config.providers.get(engine_name)
    if not provider:
        return JSONResponse(status_code=400, content={"error": f"Provider '{engine_name}' is not defined in providers."})
        
    cmd_def = config.commands.get(provider.command)
    if not cmd_def:
        return JSONResponse(status_code=400, content={"error": f"Command template '{provider.command}' is not defined."})
        
    template = cmd_def.template
    cmd = [part.replace("{prompt}", req.message) for part in template]
    
    # Resolve the executable via env_path if set
    env = os.environ.copy()
    if config.env_path:
        env["PATH"] = config.env_path
        
    import shutil
    if cmd and cmd[0]:
        exe_path = shutil.which(cmd[0], path=env.get("PATH"))
        if exe_path:
            cmd[0] = exe_path
            
    try:
        # Run subprocess blockingly and capture output
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(Path.cwd()),
            env=env
        )
        return {
            "stdout": res.stdout,
            "stderr": res.stderr,
            "returncode": res.returncode
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

def open_browser(url: str):
    time.sleep(1) # wait for server to start
    webbrowser.open(url)

def start_ui(port: int = 8080):
    url = f"http://127.0.0.1:{port}"
    threading.Thread(target=open_browser, args=(url,), daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=port)
