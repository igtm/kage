from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

import uvicorn
import sqlite3
import webbrowser
import threading
import time
from pathlib import Path
from .config import KAGE_DB_PATH, get_global_config
from .ai.chat import generate_chat_reply, clean_ai_reply

app = FastAPI(title="kage UI")

INDEX_HTML = """
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>kage Dashboard</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root {
            /* Dark Theme (Default) */
            --bg-base: #0d1117;
            --bg-sidebar: #161b22;
            --bg-card: #161b22;
            --bg-card-hover: #1c2128;
            --bg-input: #010409;
            --bg-terminal: #010409;
            
            --text-primary: #c9d1d9;
            --text-secondary: #8b949e;
            --text-dim: #484f58;
            
            --border-base: #30363d;
            --border-hover: #444c56;
            
            --accent: #58a6ff;
            --accent-muted: rgba(88, 166, 255, 0.1);
            
            --success: #238636;
            --success-text: #3fb950;
            --error: #da3633;
            --error-text: #f85149;
            --warning: #9e6a03;
            --warning-text: #d29922;
            
            --sidebar-width: 260px;
            --sidebar-collapsed-width: 68px;
            --header-height: 64px;
            --transition: 0.2s cubic-bezier(0.4, 0, 0.2, 1);
        }

        @media (prefers-color-scheme: light) {
            :root {
                --bg-base: #f6f8fa;
                --bg-sidebar: #ffffff;
                --bg-card: #ffffff;
                --bg-card-hover: #fcfcfc;
                --bg-input: #ffffff;
                --bg-terminal: #0d1117; /* Keep terminal dark-ish */
                
                --text-primary: #1f2328;
                --text-secondary: #636c76;
                --text-dim: #8c959f;
                
                --border-base: #d0d7de;
                --border-hover: #afb8c1;
                
                --accent: #0969da;
                --accent-muted: rgba(9, 105, 218, 0.1);
                
                --success: #1a7f37;
                --success-text: #1a7f37;
                --error: #cf222e;
                --error-text: #cf222e;
                --warning: #9a6700;
                --warning-text: #9a6700;
            }
        }

        * {
            box-sizing: border-box;
            -webkit-font-smoothing: antialiased;
        }

        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
            background-color: var(--bg-base);
            color: var(--text-primary);
            margin: 0;
            padding: 0;
            display: flex;
            height: 100vh;
            overflow: hidden;
        }

        /* Sidebar */
        .sidebar {
            width: var(--sidebar-width);
            background-color: var(--bg-sidebar);
            border-right: 1px solid var(--border-base);
            display: flex;
            flex-direction: column;
            z-index: 100;
            transition: width var(--transition);
            position: relative;
        }

        .sidebar.collapsed {
            width: var(--sidebar-collapsed-width);
        }

        .sidebar-header {
            padding: 16px 24px;
            height: var(--header-height);
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid var(--border-base);
        }

        .sidebar.collapsed .sidebar-header {
            padding: 16px 0;
            justify-content: center;
        }

        #sidebar-toggle {
            background: none;
            border: none;
            color: var(--text-secondary);
            cursor: pointer;
            display: flex;
            align-items: center;
            padding: 6px;
            border-radius: 6px;
            transition: all var(--transition);
        }

        #sidebar-toggle:hover {
            background-color: var(--accent-muted);
            color: var(--accent);
        }

        .sidebar.collapsed #sidebar-toggle {
            transform: rotate(0deg);
        }

        .logo {
            font-size: 1.25rem;
            font-weight: 700;
            color: var(--accent);
            letter-spacing: -0.5px;
            text-decoration: none;
            white-space: nowrap;
            overflow: hidden;
            transition: opacity var(--transition);
        }

        .sidebar.collapsed .logo-text {
            display: none;
        }

        .nav-list {
            padding: 16px 12px;
            flex-grow: 1;
            list-style: none;
            margin: 0;
        }

        .nav-item {
            padding: 10px 12px;
            border-radius: 6px;
            color: var(--text-secondary);
            text-decoration: none;
            display: flex;
            align-items: center;
            gap: 10px;
            font-weight: 500;
            margin-bottom: 4px;
            cursor: pointer;
            transition: all var(--transition);
            white-space: nowrap;
            position: relative;
        }

        .sidebar.collapsed .nav-item {
            justify-content: center;
            padding: 10px 0;
            gap: 0;
        }

        .nav-text {
            transition: opacity var(--transition);
        }

        .sidebar.collapsed .nav-text {
            display: none;
        }

        /* Hover Label for Collapsed Sidebar */
        .nav-item::after {
            content: attr(data-label);
            position: absolute;
            left: calc(100% + 12px);
            background-color: var(--bg-sidebar);
            color: var(--text-primary);
            padding: 6px 12px;
            border-radius: 4px;
            font-size: 0.8rem;
            border: 1px solid var(--border-base);
            box-shadow: 0 4px 12px rgba(0,0,0,0.2);
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.1s ease;
            z-index: 1000;
        }

        .sidebar.collapsed .nav-item:hover::after {
            opacity: 1;
        }

        .nav-item:hover {
            background-color: var(--accent-muted);
            color: var(--accent);
        }

        .nav-item.active {
            background-color: var(--accent);
            color: white;
        }

        .sidebar-footer {
            padding: 16px;
            border-top: 1px solid var(--border-base);
            font-size: 0.8rem;
            color: var(--text-dim);
            white-space: nowrap;
            overflow: hidden;
        }

        .sidebar.collapsed .sidebar-footer {
            display: none;
        }

        /* Main Content */
        .main {
            flex-grow: 1;
            display: flex;
            flex-direction: column;
            height: 100vh;
            overflow: hidden;
            position: relative;
        }

        .header {
            height: var(--header-height);
            padding: 0 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            background-color: var(--bg-base);
            border-bottom: 1px solid var(--border-base);
            flex-shrink: 0;
        }

        .header-title {
            font-size: 1rem;
            font-weight: 600;
        }

        .header-actions {
            display: flex;
            align-items: center;
            gap: 16px;
        }

        .github-link {
            display: flex;
            align-items: center;
            color: var(--text-secondary);
            text-decoration: none;
            transition: color var(--transition);
        }

        .github-link:hover {
            color: var(--accent);
        }

        .github-link svg {
            width: 20px;
            height: 20px;
            fill: currentColor;
        }

        .content-area {
            flex-grow: 1;
            overflow-y: auto;
            padding: 24px;
            scrollbar-width: thin;
        }

        .section {
            display: none;
            max-width: 1200px;
            margin: 0 auto;
        }

        .section.active {
            display: block;
        }

        /* Log Features */
        .toolbar {
            display: flex;
            gap: 12px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }

        .search-container {
            flex-grow: 1;
            position: relative;
        }

        .search-input {
            width: 100%;
            background-color: var(--bg-input);
            border: 1px solid var(--border-base);
            border-radius: 6px;
            padding: 8px 12px;
            color: var(--text-primary);
            font-family: inherit;
        }

        .search-input:focus {
            outline: none;
            border-color: var(--accent);
            box-shadow: 0 0 0 3px var(--accent-muted);
        }

        .filter-select {
            background-color: var(--bg-input);
            border: 1px solid var(--border-base);
            border-radius: 6px;
            padding: 8px 12px;
            color: var(--text-primary);
            cursor: pointer;
        }

        .log-card {
            background-color: var(--bg-card);
            border: 1px solid var(--border-base);
            border-radius: 8px;
            margin-bottom: 16px;
            overflow: hidden;
            transition: border-color var(--transition);
        }

        .log-card:hover {
            border-color: var(--border-hover);
        }

        .log-header {
            padding: 12px 16px;
            background-color: rgba(0,0,0,0.02);
            display: flex;
            justify-content: space-between;
            align-items: center;
            cursor: pointer;
            user-select: none;
        }

        .log-info {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .log-name {
            font-weight: 600;
        }

        .status-badge {
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
        }

        .status-badge.SUCCESS { background: rgba(35, 134, 54, 0.15); color: var(--success-text); }
        .status-badge.FAILED, .status-badge.ERROR { background: rgba(218, 54, 51, 0.15); color: var(--error-text); }
        .status-badge.RUNNING { background: rgba(184, 115, 51, 0.15); color: var(--warning-text); }
        .status-badge.TIMEOUT { background: rgba(218, 54, 51, 0.1); color: var(--text-dim); }

        .log-meta {
            display: flex;
            align-items: center;
            gap: 16px;
            font-size: 0.85rem;
            color: var(--text-secondary);
        }

        .log-body {
            display: none;
            padding: 0;
            border-top: 1px solid var(--border-base);
        }

        .log-card.expanded .log-body {
            display: block;
        }

        .terminal-header {
            padding: 8px 16px;
            background-color: var(--bg-sidebar);
            font-size: 0.75rem;
            color: var(--text-dim);
            display: flex;
            justify-content: space-between;
        }

        .terminal {
            background-color: var(--bg-terminal);
            color: #d1d5db;
            padding: 16px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.85rem;
            line-height: 1.5;
            overflow-x: auto;
            max-height: 500px;
            position: relative;
        }

        .line-numbers {
            display: inline-block;
            color: var(--text-dim);
            text-align: right;
            padding-right: 12px;
            margin-right: 12px;
            border-right: 1px solid var(--text-dim);
            user-select: none;
        }

        /* Config Cards */
        .config-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
            gap: 20px;
        }

        .card {
            background-color: var(--bg-card);
            border: 1px solid var(--border-base);
            border-radius: 8px;
            padding: 20px;
        }

        .card-title {
            font-size: 1.1rem;
            font-weight: 600;
            margin: 0 0 16px 0;
            color: var(--accent);
        }

        .kv-row {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid var(--border-base);
        }

        .kv-row:last-child { border-bottom: none; }
        .kv-key { color: var(--text-secondary); font-size: 0.9rem; }
        .kv-val { font-weight: 500; font-size: 0.9rem; }

        /* Buttons & Controls */
        .btn {
            background-color: var(--accent);
            color: white;
            border: none;
            border-radius: 6px;
            padding: 8px 16px;
            font-weight: 600;
            cursor: pointer;
            transition: opacity 0.2s;
        }

        .btn:hover { opacity: 0.9; }
        .btn:disabled { background-color: var(--border-base); cursor: not-allowed; }

        /* Animation */
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(4px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .task-card, .log-card {
            animation: fadeIn 0.3s ease-out forwards;
        }

        /* Toggle Switch */
        .switch {
            position: relative;
            display: inline-block;
            width: 36px;
            height: 20px;
        }

        .switch input {
            opacity: 0;
            width: 0;
            height: 0;
        }

        .slider {
            position: absolute;
            cursor: pointer;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: var(--border-base);
            transition: .4s;
            border-radius: 20px;
        }

        .slider:before {
            position: absolute;
            content: "";
            height: 14px;
            width: 14px;
            left: 3px;
            bottom: 3px;
            background-color: white;
            transition: .4s;
            border-radius: 50%;
        }
        
        .switch input:checked + .slider { background-color: var(--accent); }
        .switch input:checked + .slider:before { transform: translateX(16px); }

        /* Task Details Expansion */
        .task-details-toggle {
            width: 100%;
            padding: 8px;
            margin-top: 12px;
            background: none;
            border: 1px dashed var(--border-base);
            border-radius: 6px;
            color: var(--text-secondary);
            font-size: 0.8rem;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            transition: background var(--transition);
        }

        .task-details-toggle:hover {
            background-color: var(--accent-muted);
            border-color: var(--accent);
            color: var(--accent);
        }

        .task-details-content {
            display: none;
            margin-top: 12px;
            padding-top: 12px;
            border-top: 1px solid var(--border-base);
            animation: fadeIn 0.2s ease-out;
        }

        .card.expanded .task-details-content {
            display: block;
        }

        .card.expanded .details-icon {
            transform: rotate(180deg);
        }

        .details-icon {
            transition: transform var(--transition);
        }

        .prompt-container {
            margin-top: 12px;
        }

        .prompt-label {
            font-size: 0.75rem;
            color: var(--text-dim);
            margin-bottom: 4px;
            display: block;
            font-weight: 600;
            text-transform: uppercase;
        }

        .prompt-code {
            background-color: var(--bg-terminal);
            color: #d1d5db;
            padding: 12px;
            border-radius: 6px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.85rem;
            white-space: pre-wrap;
            word-break: break-all;
            border: 1px solid var(--border-base);
            max-height: 300px;
            overflow-y: auto;
        }

        .card.inactive {
            opacity: 0.6;
            filter: grayscale(0.5);
        }

        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 12px;
        }

        /* Chat Styles */
        .chat-container {
            height: 60vh;
            background: var(--bg-card);
            border: 1px solid var(--border-base);
            border-radius: 8px;
            padding: 20px;
            overflow-y: auto;
            margin-bottom: 20px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .chat-provider-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 12px;
            background: var(--accent-muted);
            border: 1px solid var(--accent);
            border-radius: 20px;
            font-size: 0.75rem;
            color: var(--accent);
            font-weight: 600;
            margin-bottom: 8px;
        }

        .chat-input-area {
            display: flex;
            gap: 12px;
        }

        .chat-input-area textarea {
            flex-grow: 1;
            background: var(--bg-input);
            border: 1px solid var(--border-base);
            border-radius: 8px;
            padding: 12px;
            color: var(--text-primary);
            font-family: inherit;
            resize: none;
            height: 60px;
        }

        .chat-input-area textarea:focus {
            outline: none;
            border-color: var(--accent);
            box-shadow: 0 0 0 3px var(--accent-muted);
        }

        .message {
            padding: 12px;
            border-radius: 8px;
            max-width: 80%;
            word-wrap: break-word;
            overflow-wrap: break-word;
            white-space: pre-wrap;
        }

        .message.user {
            align-self: flex-end;
            background: var(--accent);
            color: white;
        }

        .message.assistant {
            background: var(--bg-sidebar);
            border: 1px solid var(--border-base);
        }

        .message.assistant pre {
            margin: 0;
            white-space: pre-wrap;
            word-break: break-word;
            overflow-wrap: break-word;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.85rem;
        }

        /* Typing Indicator */
        .typing-indicator {
            display: flex;
            align-items: center;
            gap: 4px;
            padding: 12px 16px;
            background: var(--bg-sidebar);
            border: 1px solid var(--border-base);
            border-radius: 8px;
            max-width: 80px;
        }

        .typing-indicator span {
            display: inline-block;
            width: 8px;
            height: 8px;
            background: var(--text-dim);
            border-radius: 50%;
            animation: typingBounce 1.4s infinite ease-in-out;
        }

        .typing-indicator span:nth-child(1) { animation-delay: 0s; }
        .typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
        .typing-indicator span:nth-child(3) { animation-delay: 0.4s; }

        @keyframes typingBounce {
            0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
            40% { transform: scale(1); opacity: 1; }
        }
        /* Modal */
        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0,0,0,0.5);
            align-items: center;
            justify-content: center;
            opacity: 0;
            transition: opacity 0.2s;
        }
        .modal.active {
            display: flex;
            opacity: 1;
        }
        .modal-content {
            background-color: var(--bg-card);
            border: 1px solid var(--border-base);
            border-radius: 12px;
            width: 90%;
            max-width: 600px;
            max-height: 80vh;
            overflow-y: auto;
            position: relative;
            box-shadow: 0 8px 32px rgba(0,0,0,0.4);
            animation: modalIn 0.3s ease-out;
        }
        @keyframes modalIn {
            from { transform: scale(0.95); opacity: 0; }
            to { transform: scale(1); opacity: 1; }
        }
        .modal-header {
            padding: 16px 20px;
            border-bottom: 1px solid var(--border-base);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .modal-body {
            padding: 20px;
            line-height: 1.6;
        }
        .close-modal {
            background: none;
            border: none;
            color: var(--text-secondary);
            cursor: pointer;
            font-size: 1.5rem;
            display: flex;
            align-items: center;
            justify-content: center;
        }
    </style>
</head>
<body>
    <aside class="sidebar" id="sidebar">
        <div class="sidebar-header">
            <a href="/" class="logo">🌑<span class="logo-text" style="margin-left:8px">kage</span></a>
            <button id="sidebar-toggle" title="Toggle Sidebar">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="6" x2="21" y2="6"></line><line x1="3" y1="18" x2="21" y2="18"></line></svg>
            </button>
        </div>
        <nav class="nav-list">
            <div class="nav-item active" data-section="logs" id="nav-logs" data-label="Execution Logs">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
                <span class="nav-text">Execution Logs</span>
            </div>
            <div class="nav-item" data-section="config" id="nav-config" data-label="Settings & Tasks">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
                <span class="nav-text">Settings & Tasks</span>
            </div>
            <div class="nav-item" data-section="chat" id="nav-chat" data-label="AI Chat">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.1a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>
                <span class="nav-text">AI Chat</span>
            </div>
            <div class="nav-item" data-section="connectors" id="nav-connectors" data-label="Connectors">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 2v4"/><path d="M16 2v4"/><rect x="4" y="8" width="16" height="12" rx="2"/></svg>
                <span class="nav-text">Connectors</span>
            </div>
        </nav>
        <div class="sidebar-footer">
            v0.1.10 - Autonomous Exec layer
        </div>
    </aside>

    <main class="main">
        <header class="header">
            <div class="header-title" id="page-title">Execution Logs</div>
            <div class="header-actions">
                <a class="github-link" href="https://github.com/igtm/kage" target="_blank" title="GitHub">
                    <svg viewBox="0 0 16 16"><path d="M8 0C3.58 0 0 3.67 0 8.2c0 3.63 2.29 6.71 5.47 7.8.4.08.55-.18.55-.39 0-.19-.01-.83-.01-1.5-2.01.38-2.53-.5-2.69-.96-.09-.23-.48-.96-.82-1.16-.28-.15-.68-.54-.01-.55.63-.01 1.08.59 1.23.84.72 1.24 1.87.89 2.33.68.07-.54.28-.89.5-1.1-1.78-.21-3.64-.92-3.64-4.08 0-.9.31-1.64.82-2.22-.08-.21-.36-1.04.08-2.16 0 0 .67-.22 2.2.85.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.07 2.2-.85 2.2-.85.44 1.12.16 1.95.08 2.16.51.58.82 1.31.82 2.22 0 3.17-1.87 3.87-3.65 4.08.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.47.55.39A8.24 8.24 0 0 0 16 8.2C16 3.67 12.42 0 8 0z"/></svg>
                </a>
            </div>
        </header>

        <section class="content-area">
            <!-- Logs Section -->
            <div id="logs-section" class="section active">
                <div class="toolbar">
                    <div class="search-container">
                        <input type="text" id="log-search" class="search-input" placeholder="Search logs (task name, project, output)...">
                    </div>
                    <select id="log-filter-project" class="filter-select">
                        <option value="ALL">All Projects</option>
                    </select>
                    <select id="log-filter-task" class="filter-select">
                        <option value="ALL">All Tasks</option>
                    </select>
                    <select id="log-filter-status" class="filter-select">
                        <option value="ALL">All Status</option>
                        <option value="SUCCESS">Success</option>
                        <option value="FAILED">Failed</option>
                        <option value="RUNNING">Running</option>
                        <option value="ERROR">Error</option>
                    </select>
                </div>
                <div id="logs-container">Loading...</div>
            </div>

            <!-- Config Section -->
            <div id="config-section" class="section">
                <div class="toolbar">
                    <select id="config-filter-project" class="filter-select">
                        <option value="ALL">All Projects</option>
                    </select>
                </div>
                <div id="config-container">Loading...</div>
            </div>

            <!-- Chat Section -->
            <div id="chat-section" class="section">
                <div id="chat-provider-info"></div>
                <div id="chat-history" class="chat-container">
                    <div class="message assistant">Hi! I'm the kage AI assistant. I can help you configure tasks, explain logs, or execute commands.</div>
                </div>
                <div class="chat-input-area">
                    <textarea id="chat-input" placeholder="Type a message..."></textarea>
                    <button id="chat-submit" class="btn" style="height: 60px; padding: 0 24px;">Send</button>
                </div>
            </div>

            <!-- Connectors Section -->
            <div id="connectors-section" class="section">
                <div class="toolbar">
                    <button class="btn" onclick="fetchConnectors()">Refresh</button>
                    <select id="connector-select" class="filter-select" style="margin-left: 10px;" onchange="selectConnector()">
                        <option value="">Select a Connector...</option>
                    </select>
                    <button class="btn" style="margin-left:auto; background:var(--accent-muted); border:1px solid var(--accent); color:var(--accent); font-size:0.85rem;" onclick="showConnectorHelp()">Setup Help</button>
                </div>
                <div id="connectors-container" style="display: flex; gap: 20px; padding: 20px; height: calc(100% - 60px);">
                    <div style="flex: 1; max-width: 400px; display: flex; flex-direction: column;">
                        <div class="card" id="connector-config-card" style="flex-grow: 1; overflow-y: auto;">
                            Select a connector to view details.
                        </div>
                    </div>
                    <div style="flex: 2; display: flex; flex-direction: column; background: var(--bg-card); border: 1px solid var(--border-base); border-radius: 8px;">
                        <h3 style="margin: 0; padding: 12px 16px; border-bottom: 1px solid var(--border-base); font-size: 1rem;">Message History</h3>
                        <div id="connector-history" class="chat-container" style="flex-grow: 1; overflow-y: auto;">
                        </div>
                    </div>
                </div>
            </div>
        </section>
    </main>

    <!-- Modal -->
    <div id="help-modal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h3 id="modal-title" style="margin:0;">Setup Help</h3>
                <button class="close-modal" onclick="closeModal()">&times;</button>
            </div>
            <div id="modal-body" class="modal-body">
            </div>
        </div>
    </div>

    <script>
        let lastLogsSignature = null;
        let allLogsData = [];
        let allConfigData = null;
        let allConnectorsData = [];
        let autoScrollEnabled = true;

        // Helper: Get project short name (last directory)
        function getProjectShortName(path) {
            if (!path) return "Unknown";
            const parts = path.split('/');
            return parts[parts.length - 1] || path;
        }

        function escapeHtml(text) {
            if (!text) return "";
            return String(text)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;');
        }

        // Navigation
        function navigateTo(section, push = true) {
            document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
            document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
            
            const targetContent = document.getElementById(section + '-section');
            const targetNav = document.getElementById('nav-' + section);
            
            if (targetContent && targetNav) {
                targetContent.classList.add('active');
                targetNav.classList.add('active');
                document.getElementById('page-title').textContent = targetNav.querySelector('.nav-text') ? targetNav.querySelector('.nav-text').textContent.trim() : targetNav.textContent.trim();
                
                if (section === 'config') fetchConfig();
                if (section === 'logs') fetchLogs();
                if (section === 'chat') fetchChatProviderInfo();
                if (section === 'connectors') fetchConnectors();
                
                if (push) {
                    const path = section === 'logs' ? '/' : '/' + section;
                    history.pushState({ section }, '', path);
                }
            }
        }

        document.querySelectorAll('.nav-item').forEach(item => {
            item.addEventListener('click', () => {
                const sectionName = item.getAttribute('data-section');
                navigateTo(sectionName);
            });
        });

        window.onpopstate = (event) => {
            if (event.state && event.state.section) {
                navigateTo(event.state.section, false);
            } else {
                // Default to logs if no state
                navigateTo('logs', false);
            }
        };

        // Initial landing
        document.addEventListener('DOMContentLoaded', () => {
            const path = window.location.pathname.substring(1);
            const validSections = ['logs', 'config', 'chat', 'connectors'];
            const section = validSections.includes(path) ? path : 'logs';
            
            // Sidebar state
            const isCollapsed = localStorage.getItem('sidebarCollapsed') === 'true';
            if (isCollapsed) {
                document.getElementById('sidebar').classList.add('collapsed');
            }

            // Set initial state for the landing page so back button works
            history.replaceState({ section }, '', window.location.pathname);
            navigateTo(section, false);
        });

        document.getElementById('sidebar-toggle').addEventListener('click', () => {
            const sidebar = document.getElementById('sidebar');
            sidebar.classList.toggle('collapsed');
            localStorage.setItem('sidebarCollapsed', sidebar.classList.contains('collapsed'));
        });

        function formatDuration(ms) {
            if (ms < 0) ms = 0;
            const sec = Math.floor(ms / 1000);
            const min = Math.floor(sec / 60);
            
            if (min > 0) return `${min}m ${sec % 60}s`;
            return `${sec}s`;
        }

        function updateTimers() {
            document.querySelectorAll('.log-card[data-status="RUNNING"]').forEach(card => {
                const startedAt = new Date(card.getAttribute('data-run-at')).getTime();
                const now = new Date().getTime();
                const durationEl = card.querySelector('.duration-value');
                if (durationEl) {
                    durationEl.textContent = formatDuration(now - startedAt);
                }
            });
        }
        setInterval(updateTimers, 1000);

        async function fetchLogs() {
            try {
                const response = await fetch('/api/logs');
                allLogsData = await response.json();
                updateTaskFilterOptions();
                renderLogs();
            } catch (error) {
                document.getElementById('logs-container').innerHTML = '<p style="color:red">Failed to load logs.</p>';
            }
        }

        function renderLogs() {
            const searchTerm = document.getElementById('log-search').value.toLowerCase();
            const statusFilter = document.getElementById('log-filter-status').value;
            const taskFilter = document.getElementById('log-filter-task').value;
            const projectFilter = document.getElementById('log-filter-project').value;
            const container = document.getElementById('logs-container');
            
            const filtered = allLogsData.filter(log => {
                const matchesSearch = !searchTerm || 
                    log.task_name.toLowerCase().includes(searchTerm) ||
                    log.project_path.toLowerCase().includes(searchTerm) ||
                    (log.stdout && log.stdout.toLowerCase().includes(searchTerm)) ||
                    (log.stderr && log.stderr.toLowerCase().includes(searchTerm));
                
                const matchesStatus = statusFilter === 'ALL' || log.status === statusFilter;
                const matchesTask = taskFilter === 'ALL' || log.task_name === taskFilter;
                const matchesProject = projectFilter === 'ALL' || log.project_path === projectFilter;
                
                return matchesSearch && matchesStatus && matchesTask && matchesProject;
            });

            const signature = JSON.stringify(filtered);
            if (signature === lastLogsSignature) return;
            lastLogsSignature = signature;

            if (filtered.length === 0) {
                container.innerHTML = '<p style="padding: 20px; color: var(--text-dim);">No logs match your filter.</p>';
                return;
            }

            container.innerHTML = '';
            filtered.forEach(log => {
                const card = document.createElement('div');
                card.className = 'log-card';
                card.id = `log-${log.id}`;
                card.setAttribute('data-status', log.status);
                card.setAttribute('data-run-at', log.run_at);

                const start = new Date(log.run_at);
                const end = log.finished_at ? new Date(log.finished_at) : null;
                const duration = end ? (end.getTime() - start.getTime()) : (new Date().getTime() - start.getTime());
                
                const hasOutput = !!(log.stdout || log.stderr);
                const lineCount = log.stdout ? log.stdout.split('\\n').length : 0;

                card.innerHTML = `
                    <div class="log-header" onclick="toggleLogBody('${log.id}')">
                        <div class="log-info">
                            <span class="status-badge ${log.status}">${log.status}</span>
                            <span class="log-name">${escapeHtml(log.task_name)}</span>
                            <span class="log-meta">${start.toLocaleTimeString()} · ${escapeHtml(getProjectShortName(log.project_path))}</span>
                        </div>
                        <div class="log-meta">
                            <span class="duration-value">${formatDuration(duration)}</span>
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
                        </div>
                    </div>
                    <div class="log-body" id="body-${log.id}">
                        <div class="terminal-header">
                            <span>OUTPUT (${lineCount} lines)</span>
                            <span>ID: ${log.id.substring(0,8)}</span>
                        </div>
                        <div class="terminal" id="term-${log.id}">
                            ${hasOutput ? formatTerminalOutput(log.stdout, log.stderr) : '<p style="margin:0; color:var(--text-dim)">No output recorded.</p>'}
                        </div>
                    </div>
                `;
                container.appendChild(card);
            });
        }

        function formatTerminalOutput(stdout, stderr) {
            let out = "";
            if (stdout) {
                const lines = stdout.trim().split('\\n');
                out += `<div class="lines">` + lines.map((l, i) => `<div><span class="line-numbers">${i+1}</span>${escapeHtml(l)}</div>`).join('') + `</div>`;
            }
            if (stderr) {
                out += `<div style="color:var(--error-text); margin-top: 12px; border-top: 1px solid var(--text-dim); padding-top: 8px;">[STDERR]</div>`;
                out += `<div style="color:var(--error-text)">${escapeHtml(stderr)}</div>`;
            }
            return out;
        }

        function toggleLogBody(id) {
            const card = document.getElementById(`log-${id}`);
            card.classList.toggle('expanded');
        }

        function updateTaskFilterOptions() {
            const taskFilter = document.getElementById('log-filter-task');
            const projFilter = document.getElementById('log-filter-project');
            const currentTask = taskFilter.value;
            const currentProj = projFilter.value;
            
            const tasks = [...new Set(allLogsData.map(l => l.task_name))].sort();
            const projects = [...new Set(allLogsData.map(l => l.project_path))].sort();
            
            let tHtml = '<option value="ALL">All Tasks</option>';
            tasks.forEach(t => {
                tHtml += `<option value="${escapeHtml(t)}" ${t === currentTask ? 'selected' : ''}>${escapeHtml(t)}</option>`;
            });
            taskFilter.innerHTML = tHtml;

            let pHtml = '<option value="ALL">All Projects</option>';
            projects.forEach(p => {
                pHtml += `<option value="${escapeHtml(p)}" ${p === currentProj ? 'selected' : ''}>${escapeHtml(getProjectShortName(p))}</option>`;
            });
            projFilter.innerHTML = pHtml;
        }

        document.getElementById('log-search').addEventListener('input', renderLogs);
        document.getElementById('log-filter-status').addEventListener('change', renderLogs);
        document.getElementById('log-filter-task').addEventListener('change', renderLogs);
        document.getElementById('log-filter-project').addEventListener('change', renderLogs);
        document.getElementById('config-filter-project').addEventListener('change', renderConfig);

        // Config & Chat (Simplified for current overhaul focus)
        async function fetchConfig() {
            const response = await fetch('/api/config');
            allConfigData = await response.json();
            
            // Populate config project filter
            const projFilter = document.getElementById('config-filter-project');
            const currentProj = projFilter.value;
            const projects = [...new Set(allConfigData.tasks.map(t => t.project_path))].sort();
            
            let pHtml = '<option value="ALL">All Projects</option>';
            projects.forEach(p => {
                pHtml += `<option value="${escapeHtml(p)}" ${p === currentProj ? 'selected' : ''}>${escapeHtml(getProjectShortName(p))}</option>`;
            });
            projFilter.innerHTML = pHtml;
            
            renderConfig();
        }

        function renderConfig() {
            if (!allConfigData) return;
            const config = allConfigData;
            const container = document.getElementById('config-container');
            const projFilter = document.getElementById('config-filter-project').value;
            
            let tasksHtml = '';
            
            const filteredTasks = config.tasks.filter(t => projFilter === 'ALL' || t.project_path === projFilter);
            
            filteredTasks.forEach(task => {
                let nextRunDisplay = 'Not scheduled';
                if (task.next_run && task.active) {
                    try {
                        const d = new Date(task.next_run);
                        if (!isNaN(d.getTime())) {
                            nextRunDisplay = d.toLocaleString(undefined, {
                                year: 'numeric', month: '2-digit', day: '2-digit',
                                hour: '2-digit', minute: '2-digit', second: '2-digit',
                                timeZoneName: 'short'
                            });
                        } else {
                            nextRunDisplay = task.next_run; // Fallback to raw string
                        }
                    } catch (e) {
                        nextRunDisplay = task.next_run;
                    }
                } else if (!task.active) {
                    nextRunDisplay = 'Task disabled';
                }

                let detailsHtml = '';
                const fields = [
                    { key: 'Mode', val: task.mode },
                    { key: 'Concurrency', val: task.concurrency_policy },
                    { key: 'Timeout', val: task.timeout_minutes ? task.timeout_minutes + ' min' : null },
                    { key: 'Allowed Hours', val: task.allowed_hours },
                    { key: 'Denied Hours', val: task.denied_hours },
                    { key: 'Shell', val: task.shell },
                    { key: 'Command', val: task.command },
                    { key: 'AI Engine', val: task.provider }
                ];

                fields.forEach(f => {
                    if (f.val) {
                        detailsHtml += `<div class="kv-row"><span class="kv-key">${f.key}</span><span class="kv-val">${escapeHtml(String(f.val))}</span></div>`;
                    }
                });

                let promptHtml = '';
                if (task.prompt) {
                    promptHtml = `
                        <div class="prompt-container">
                            <span class="prompt-label">Prompt</span>
                            <div class="prompt-code"><code>${escapeHtml(task.prompt)}</code></div>
                        </div>
                    `;
                }

                tasksHtml += `
                    <div class="card ${task.active ? '' : 'inactive'}" style="margin-bottom: 16px;" id="task-${escapeHtml(task.name)}">
                        <div class="card-header">
                            <h4 style="margin:0; font-size: 1rem;">${escapeHtml(task.name)}</h4>
                            <label class="switch" title="Enable/Disable task">
                                <input type="checkbox" class="task-toggle" 
                                    data-project-path="${escapeHtml(task.project_path)}"
                                    data-task-name="${escapeHtml(task.name)}"
                                    data-file="${escapeHtml(task.file || '')}"
                                    ${task.active ? 'checked' : ''}>
                                <span class="slider"></span>
                            </label>
                        </div>
                        <div class="kv-row"><span class="kv-key">Schedule</span><span class="kv-val"><code>${escapeHtml(task.cron)}</code> <small style="color: var(--text-dim); margin-left: 4px;">(${escapeHtml(task.task_timezone)})</small></span></div>
                        <div class="kv-row"><span class="kv-key">Next Run</span><span class="kv-val">${escapeHtml(nextRunDisplay)}</span></div>
                        <div class="kv-row"><span class="kv-key">Project</span><span class="kv-val">${escapeHtml(getProjectShortName(task.project_path))}</span></div>
                        
                        <div class="task-details-content">
                             ${detailsHtml}
                             ${promptHtml}
                        </div>

                        <button class="task-details-toggle" onclick="this.closest('.card').classList.toggle('expanded')">
                            <span class="details-icon">▼</span> Details
                        </button>

                        <button class="btn" onclick="runTaskNow('${task.project_path}', '${task.name}', '${task.file}')" style="margin-top: 12px; width: 100%; font-size: 0.8rem;" ${task.active ? '' : 'disabled'}>Run Now</button>
                    </div>
                `;
            });

            container.innerHTML = `
                <div class="card" style="margin-bottom: 24px;">
                    <h3 class="card-title">Global Configuration</h3>
                    <div class="kv-row"><span class="kv-key">Default Engine</span><span class="kv-val">${config.default_ai_engine || 'None'}</span></div>
                    <div class="kv-row"><span class="kv-key">Timezone</span><span class="kv-val">${config.timezone}</span></div>
                    <div class="kv-row"><span class="kv-key">UI Port</span><span class="kv-val">${config.ui_port}</span></div>
                </div>
                <h3 class="card-title">Registered Tasks</h3>
                <div class="config-grid">${tasksHtml}</div>
            `;
            wireToggleButtons();
        }

        function wireToggleButtons() {
            document.querySelectorAll('.task-toggle').forEach(toggle => {
                toggle.addEventListener('change', async () => {
                    const projectPath = toggle.getAttribute('data-project-path');
                    const taskName = toggle.getAttribute('data-task-name');
                    const file = toggle.getAttribute('data-file');
                    const active = toggle.checked;

                    const card = toggle.closest('.card');
                    const runBtn = card.querySelector('.btn');

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
                        if (!response.ok) throw new Error('Failed to toggle task');

                        if (active) card.classList.remove('inactive');
                        else card.classList.add('inactive');
                        
                        if (runBtn) runBtn.disabled = !active;

                    } catch (error) {
                        alert(error.message);
                        toggle.checked = !active;
                    }
                });
            });
        }

        async function runTaskNow(path, name, file) {
            await fetch('/api/tasks/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ project_path: path, task_name: name, file: file })
            });
            // Switch to logs and fetch
            document.getElementById('nav-logs').click();
            setTimeout(fetchLogs, 500);
        }

        // Initialize Chat Script (adapted from original)
        const chatInput = document.getElementById('chat-input');
        const chatSubmit = document.getElementById('chat-submit');
        const chatHistory = document.getElementById('chat-history');

        async function fetchChatProviderInfo() {
            try {
                const resp = await fetch('/api/config');
                const config = await resp.json();
                const providerEl = document.getElementById('chat-provider-info');
                if (config.default_ai_engine) {
                    providerEl.innerHTML = `<div class="chat-provider-badge"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm0 18a8 8 0 1 1 8-8 8 8 0 0 1-8 8z"/><circle cx="12" cy="12" r="3"/></svg>Provider: ${escapeHtml(config.default_ai_engine)}</div>`;
                    chatSubmit.disabled = false;
                    chatInput.disabled = false;
                    chatInput.placeholder = 'Type a message...';
                } else {
                    providerEl.innerHTML = `<div class="chat-provider-badge" style="color:var(--error-text); border-color:var(--error); background:rgba(218,54,51,0.08);">⚠ No AI provider configured</div>
<div style="background:var(--bg-card); border:1px solid var(--border-base); border-radius:8px; padding:16px; margin-top:8px; font-size:0.85rem; color:var(--text-secondary);">
    <p style="margin:0 0 12px 0; font-weight:600; color:var(--text-primary);">Setup Guide</p>
    <p style="margin:0 0 8px 0;">Set <code style="background:var(--bg-terminal); padding:2px 6px; border-radius:4px; font-family:'JetBrains Mono',monospace; font-size:0.8rem;">default_ai_engine</code> in <code style="background:var(--bg-terminal); padding:2px 6px; border-radius:4px; font-family:'JetBrains Mono',monospace; font-size:0.8rem;">~/.kage/config.toml</code>:</p>
    <div style="display:flex; flex-direction:column; gap:8px;">
        <div style="background:var(--bg-terminal); padding:10px 12px; border-radius:6px; font-family:'JetBrains Mono',monospace; font-size:0.8rem; color:#d1d5db;">
            <div style="color:var(--text-dim); margin-bottom:4px;"># Claude Code</div>
            <div>default_ai_engine = <span style="color:var(--success-text);">"claude"</span></div>
            <div style="color:var(--text-dim); margin-top:4px;"># Install: npm install -g @anthropic-ai/claude-code</div>
        </div>
        <div style="background:var(--bg-terminal); padding:10px 12px; border-radius:6px; font-family:'JetBrains Mono',monospace; font-size:0.8rem; color:#d1d5db;">
            <div style="color:var(--text-dim); margin-bottom:4px;"># Gemini CLI</div>
            <div>default_ai_engine = <span style="color:var(--success-text);">"gemini"</span></div>
            <div style="color:var(--text-dim); margin-top:4px;"># Install: npm install -g @anthropic-ai/gemini-cli</div>
        </div>
        <div style="background:var(--bg-terminal); padding:10px 12px; border-radius:6px; font-family:'JetBrains Mono',monospace; font-size:0.8rem; color:#d1d5db;">
            <div style="color:var(--text-dim); margin-bottom:4px;"># OpenAI Codex</div>
            <div>default_ai_engine = <span style="color:var(--success-text);">"codex"</span></div>
            <div style="color:var(--text-dim); margin-top:4px;"># Install: npm install -g @openai/codex</div>
        </div>
    </div>
</div>`;
                    chatSubmit.disabled = true;
                    chatInput.disabled = true;
                    chatInput.placeholder = 'Configure a provider to start chatting...';
                }
            } catch(e) {
                console.error('Failed to fetch provider info:', e);
            }
        }
        // Lightweight Markdown renderer
        function renderMarkdown(text) {
            let html = escapeHtml(text);

            // Code blocks (triple backtick)
            html = html.replace(new RegExp('```[a-zA-Z]*\\n([\\s\\S]*?)```', 'g'), function(m, code) {
                return '<pre style="background:var(--bg-terminal); padding:12px; border-radius:6px; border:1px solid var(--border-base); margin:8px 0; overflow-x:auto;"><code>' + code.trim() + '</code></pre>';
            });

            // Inline code
            html = html.replace(/`([^`]+)`/g, '<code style="background:var(--bg-terminal); padding:2px 6px; border-radius:4px; font-size:0.85em;">$1</code>');

            // Headers
            html = html.replace(/^### (.+)$/gm, '<strong style="font-size:1rem; display:block; margin:12px 0 4px;">$1</strong>');
            html = html.replace(/^## (.+)$/gm, '<strong style="font-size:1.1rem; display:block; margin:12px 0 4px;">$1</strong>');
            html = html.replace(/^# (.+)$/gm, '<strong style="font-size:1.2rem; display:block; margin:12px 0 4px;">$1</strong>');

            // Bold and italic
            html = html.replace(/[*][*](.+?)[*][*]/g, '<strong>$1</strong>');
            html = html.replace(/[*](.+?)[*]/g, '<em>$1</em>');

            // Unordered list items
            html = html.replace(/^[-] (.+)$/gm, '<div style="padding-left:16px;">&#8226; $1</div>');

            // Ordered list items
            html = html.replace(/^([0-9]+)[.] (.+)$/gm, '<div style="padding-left:16px;">$1. $2</div>');

            // Line breaks
            html = html.replace(new RegExp('\\n\\n', 'g'), '<br><br>');
            html = html.replace(new RegExp('\\n', 'g'), '<br>');

            return html;
        }

        chatSubmit.onclick = async () => {
            const text = chatInput.value.trim();
            if (!text) return;
            chatInput.value = '';
            chatSubmit.disabled = true;

            const userMsg = document.createElement('div');
            userMsg.className = 'message user';
            userMsg.textContent = text;
            chatHistory.appendChild(userMsg);

            // Show typing indicator
            const typing = document.createElement('div');
            typing.className = 'typing-indicator';
            typing.innerHTML = '<span></span><span></span><span></span>';
            chatHistory.appendChild(typing);
            chatHistory.scrollTop = chatHistory.scrollHeight;

            try {
                const response = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: text })
                });
                const result = await response.json();

                // Remove typing indicator
                typing.remove();

                const botMsg = document.createElement('div');
                botMsg.className = 'message assistant';
                if (result.error) {
                    botMsg.innerHTML = `<span style="color:var(--error-text)">Error: ${escapeHtml(result.error)}</span>`;
                } else if (result.stdout) {
                    botMsg.innerHTML = renderMarkdown(result.stdout);
                } else {
                    botMsg.textContent = 'Command executed (no output).';
                }
                chatHistory.appendChild(botMsg);
            } catch (e) {
                typing.remove();
                const errMsg = document.createElement('div');
                errMsg.className = 'message assistant';
                errMsg.innerHTML = `<span style="color:var(--error-text)">Network error: ${escapeHtml(e.message)}</span>`;
                chatHistory.appendChild(errMsg);
            }

            chatSubmit.disabled = false;
            chatHistory.scrollTop = chatHistory.scrollHeight;
        };

        chatInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                chatSubmit.click();
            }
        });

        // Polling
        fetchLogs();
        setInterval(() => {
            if (document.getElementById('logs-section').classList.contains('active')) {
                fetchLogs();
            }
        }, 5000);
        async function fetchConnectors() {
            try {
                const res = await fetch('/api/connectors');
                allConnectorsData = await res.json();
                renderConnectorsSelect();
            } catch (err) {
                console.error("Failed to load connectors", err);
            }
        }

        function closeModal() {
            document.getElementById('help-modal').classList.remove('active');
        }

        const SETUP_GUIDES = {
            discord: `
# Discord Setup Guide
1. **Developer Portal**: Create app at [discord.com/developers](https://discord.com/developers/applications).
2. **Bot Token**: Reset Token in **Bot** tab. Enable **Message Content Intent**.
3. **OAuth2**: URL Generator -> \`bot\` -> \`Send Messages\`, \`Read Message History\`.
4. **Channel ID**: Enable Developer Mode in Discord, right-click channel -> **Copy Channel ID**.
5. **Config**:
\`\`\`toml
[connectors.my_discord]
type = "discord"
bot_token = "..."
channel_id = "..."
\`\`\`
`,
            slack: `
# Slack Setup Guide
1. **Slack API**: Create app at [api.slack.com/apps](https://api.slack.com/apps) (From scratch).
2. **Scopes**: OAuth & Permissions -> \`channels:history\`, \`chat:write\`.
3. **Install**: Install to Workspace, copy **Bot User OAuth Token** (\`xoxb-...\`).
4. **Channel ID**: Channel details -> find ID at bottom (starts with \`C\`).
5. **Invite**: Type \`/invite @YourBotName\` in the channel.
6. **Config**:
\`\`\`toml
[connectors.my_slack]
type = "slack"
bot_token = "xoxb-..."
channel_id = "..."
\`\`\`
`
        };

        function showConnectorHelp() {
            const select = document.getElementById('connector-select');
            const name = select.value;
            let type = 'discord';
            
            if (name) {
                const c = allConnectorsData.find(x => x.name === name);
                if (c) type = c.config.type;
            }
            
            const modal = document.getElementById('help-modal');
            const body = document.getElementById('modal-body');
            const title = document.getElementById('modal-title');
            
            const guide = SETUP_GUIDES[type] || "# Guide not available\\nAvailable types: discord, slack";
            title.textContent = "Setup Help: " + type.charAt(0).toUpperCase() + type.slice(1);
            body.innerHTML = renderMarkdown(guide);
            modal.classList.add('active');
        }

        function renderConnectorsSelect() {
            const select = document.getElementById('connector-select');
            const currentVal = select.value;
            let html = '<option value="">Select a Connector...</option>';
            allConnectorsData.forEach(c => {
                html += `<option value="${escapeHtml(c.name)}">${escapeHtml(c.name)} (${escapeHtml(c.config.type)})</option>`;
            });
            select.innerHTML = html;
            if (currentVal && allConnectorsData.some(c => c.name === currentVal)) {
                select.value = currentVal;
            } else if (allConnectorsData.length > 0) {
                select.value = allConnectorsData[0].name;
            }
            selectConnector();
        }

        async function selectConnector() {
            const name = document.getElementById('connector-select').value;
            const configCard = document.getElementById('connector-config-card');
            const historyContainer = document.getElementById('connector-history');
            
            if (!name) {
                configCard.innerHTML = 'Select a connector to view details.';
                historyContainer.innerHTML = '';
                return;
            }
            
            const connector = allConnectorsData.find(c => c.name === name);
            if (!connector) return;
            
            // Render Config
            let confHtml = `<h3 style="margin:0 0 10px 0;">${escapeHtml(connector.name)}</h3>`;
            Object.entries(connector.config).forEach(([k, v]) => {
                confHtml += `<div class="kv-row"><span class="kv-key">${escapeHtml(k)}</span><span class="kv-val">${escapeHtml(String(v))}</span></div>`;
            });
            configCard.innerHTML = confHtml;
            
            // Render History
            historyContainer.innerHTML = 'Loading history...';
            try {
                const res = await fetch(`/api/connectors/${encodeURIComponent(name)}/history`);
                const history = await res.json();
                
                if (history.length === 0) {
                    historyContainer.innerHTML = '<div style="padding:16px; color:var(--text-dim);">No history found.</div>';
                    return;
                }
                
                let hHtml = '';
                history.forEach(entry => {
                    const date = new Date(entry.timestamp * 1000).toLocaleString();
                    const isAssistant = entry.role.toLowerCase() === 'assistant';
                    const roleClass = isAssistant ? 'assistant' : 'user';
                    hHtml += `
                        <div style="margin-bottom: 4px; font-size: 0.8rem; color: var(--text-dim); text-align: ${isAssistant ? 'left' : 'right'}">
                            ${escapeHtml(entry.role)} · ${date}
                        </div>
                        <div class="message ${roleClass}">${renderMarkdown(entry.content)}</div>
                    `;
                });
                historyContainer.innerHTML = hHtml;
                historyContainer.scrollTop = historyContainer.scrollHeight;
            } catch (err) {
                historyContainer.innerHTML = '<div style="color:var(--error-text);">Failed to load history</div>';
            }
        }
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
@app.get("/logs", response_class=HTMLResponse)
@app.get("/config", response_class=HTMLResponse)
@app.get("/chat", response_class=HTMLResponse)
def root():
    return INDEX_HTML


@app.get("/api/logs")
def get_logs():
    if not KAGE_DB_PATH.exists():
        return []
    conn = sqlite3.connect(KAGE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, project_path, task_name, run_at, status, stdout, stderr, finished_at FROM executions ORDER BY run_at DESC LIMIT 50"
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "project_path": r[1],
            "task_name": r[2],
            "run_at": r[3],
            "status": r[4],
            "stdout": r[5],
            "stderr": r[6],
            "finished_at": r[7],
        }
        for r in rows
    ]


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

            # Use task-specific timezone if defined, otherwise fallback to global
            task_tz = tz
            if t.timezone:
                try:
                    task_tz = zoneinfo.ZoneInfo(t.timezone)
                except Exception:
                    pass
            
            task_now = datetime.now(task_tz)
            next_run_str = ""
            try:
                itr = croniter(t.cron, task_now)
                next_dt = itr.get_next(datetime)
                # Return ISO format for frontend to parse in browser timezone
                next_run_str = next_dt.isoformat()
            except Exception:
                next_run_str = "Invalid cron"

            all_tasks.append(
                {
                    "name": t.name,
                    "cron": t.cron,
                    "active": t.active,
                    "next_run": next_run_str,
                    "prompt": t.prompt,
                    "command": t.command,
                    "shell": t.shell,
                    "mode": t.mode,
                    "concurrency_policy": t.concurrency_policy,
                    "timeout_minutes": t.timeout_minutes,
                    "allowed_hours": t.allowed_hours,
                    "denied_hours": t.denied_hours,
                    "provider": t.provider
                    or (t.ai.engine if (t.ai and t.ai.engine) else None),
                    "project_path": str(proj_dir),
                    "file": str(toml_path),
                    "task_timezone": str(task_tz),
                }
            )

    return {
        "default_ai_engine": config.default_ai_engine,
        "log_level": config.log_level,
        "ui_port": config.ui_port,
        "timezone": config.timezone,
        "tasks": all_tasks,
    }


@app.post("/api/tasks/run")
def run_task_now(req: RunTaskRequest):
    from .parser import load_project_tasks
    from .executor import execute_task

    proj_dir = Path(req.project_path).expanduser()
    if not proj_dir.exists():
        return JSONResponse(
            status_code=404, content={"error": "Project path does not exist."}
        )

    matched_task = None
    for toml_path, local_task in load_project_tasks(proj_dir):
        if local_task.task.name != req.task_name:
            continue
        if req.file and str(toml_path) != req.file:
            continue
        matched_task = local_task.task
        break

    if matched_task is None:
        return JSONResponse(
            status_code=404,
            content={"error": "Task not found in the specified project."},
        )

    threading.Thread(
        target=execute_task, args=(proj_dir, matched_task), daemon=True
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
                content = re.sub(
                    r"active:\s*(true|false)", f"active: {new_val}", content
                )
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
        return {
            "message": f"Task '{req.task_name}' {'enabled' if req.active else 'disabled'}."
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/chat")
def handle_chat(req: ChatRequest):
    from .ai.chat import generate_chat_reply, clean_ai_reply
    from fastapi.responses import JSONResponse
    
    try:
        reply_data = generate_chat_reply(req.message)
        # Clean thinking tags for the UI too
        reply_data["stdout"] = clean_ai_reply(reply_data.get("stdout", ""))
        return reply_data
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


def open_browser(url: str):
    time.sleep(1)  # wait for server to start
    webbrowser.open(url)


def start_ui(port: int = 8080):
    url = f"http://127.0.0.1:{port}"
    threading.Thread(target=open_browser, args=(url,), daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=port)

@app.get("/api/connectors")
def get_connectors():
    config = get_global_config()
    res = []
    for name, c in config.connectors.items():
        masked_c = dict(c)
        if "bot_token" in masked_c and masked_c["bot_token"]:
            masked_c["bot_token"] = "***" + masked_c["bot_token"][-4:]
        res.append({"name": name, "config": masked_c})
    return res

@app.get("/api/connectors/{name}/history")
def get_connector_history(name: str):
    import json
    history_file = Path.home() / ".kage" / "connectors" / f"{name}_history.jsonl"
    if not history_file.exists():
        return []
    
    entries = []
    try:
        with history_file.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except Exception as e:
        print(f"Error reading history for {name}: {e}")
    # Return last 50 messages
    return entries[-50:]
