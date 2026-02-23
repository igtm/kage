from fastapi import FastAPI
from fastapi.responses import HTMLResponse
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
        .task-list-item h3 { margin-top: 0; color: var(--accent-color); }
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
    </style>
</head>
<body>
    <div class="header">
        <h1>kage Dashboard 🌑</h1>
    </div>
    
    <div class="tabs">
        <div class="tab active" data-section="logs">Execution Logs</div>
        <div class="tab" data-section="config">Settings & Task List</div>
    </div>

    <div class="container">
        <div id="logs-section" class="section active">
            <div id="logs-container">Loading logs...</div>
        </div>
        
        <div id="config-section" class="section">
            <div id="config-container">Loading configuration...</div>
        </div>
    </div>

    <script>
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
                    if (log.stdout) outputHtml += `<strong>stdout:</strong><pre>${log.stdout}</pre>`;
                    if (log.stderr) outputHtml += `<strong>stderr:</strong><pre>${log.stderr}</pre>`;

                    card.innerHTML = `
                        <div class="card-header">
                            <span class="task-name">${log.task_name}</span>
                            <span class="status ${statusClass}">${log.status}</span>
                        </div>
                        <div class="details">
                            <div><strong>Project:</strong> ${log.project_path}</div>
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
                            <div class="task-list-item">
                                <h3>${task.name}</h3>
                                <div class="details">
                                    <div><strong>Project:</strong> ${task.project_path}</div>
                                    <div><strong>Schedule:</strong> <code>${task.cron}</code> (Next: ${task.next_run})</div>
                                    ${task.prompt ? `<div><strong>AI Prompt:</strong> ${task.prompt}</div>` : ''}
                                    ${task.command ? `<div><strong>Command:</strong> <code>${task.command}</code></div>` : ''}
                                    ${task.provider ? `<div><strong>Provider:</strong> ${task.provider}</div>` : ''}
                                </div>
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
            } catch (error) {
                document.getElementById('config-container').innerHTML = '<p style="color:red">Failed to load configuration.</p>';
            }
        }

        fetchLogs();
        setInterval(() => {
            if (document.getElementById('logs-section').classList.contains('active')) {
                fetchLogs();
            }
        }, 5000);
    </script>
</body>
</html>
"""

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

def open_browser(url: str):
    time.sleep(1) # wait for server to start
    webbrowser.open(url)

def start_ui(port: int = 8080):
    url = f"http://127.0.0.1:{port}"
    threading.Thread(target=open_browser, args=(url,), daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=port)
