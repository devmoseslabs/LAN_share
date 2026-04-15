"""
Unified Offline Session-Based Communication System
LAN-based temporary collaboration with file sharing and text messaging
Run with: python main.py
"""

import os
import shutil
import uuid
import tempfile
import asyncio
import socket
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
import qrcode
from io import BytesIO
import base64

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_local_ip() -> str:
    """Auto-detect the local LAN IP address"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def generate_qr_code_base64(url: str) -> str:
    """Generate QR code as base64 string"""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode()


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class FileMetadata:
    file_id: str
    filename: str
    original_filename: str
    size: int
    upload_timestamp: str
    storage_path: str
    owner_client_id: str
    
    def to_dict(self) -> dict:
        return {
            "file_id": self.file_id,
            "filename": self.filename,
            "original_filename": self.original_filename,
            "size": self.size,
            "upload_timestamp": self.upload_timestamp,
            "owner_client_id": self.owner_client_id
        }


@dataclass
class Message:
    message_id: str
    content: str
    timestamp: str
    owner_client_id: str
    
    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "content": self.content,
            "timestamp": self.timestamp,
            "owner_client_id": self.owner_client_id
        }


@dataclass
class ClientInfo:
    client_id: str
    ip_address: str
    joined_at: str
    last_seen: str


class Session:
    def __init__(self, session_id: str, host_ip: str, timeout_minutes: int = 60):
        self.session_id = session_id
        self.host_ip = host_ip
        self.created_at = datetime.now()
        self.timeout_minutes = timeout_minutes
        self.last_activity = datetime.now()
        
        self.files: Dict[str, FileMetadata] = {}
        self.messages: List[Message] = []
        self.clients: Dict[str, ClientInfo] = {}
        
        self._files_lock = asyncio.Lock()
        self._messages_lock = asyncio.Lock()
        self._clients_lock = asyncio.Lock()
        
        self.storage_path = Path(tempfile.gettempdir()) / f"session_{session_id}"
        self.storage_path.mkdir(parents=True, exist_ok=True)
    
    @property
    def is_expired(self) -> bool:
        return datetime.now() - self.last_activity > timedelta(minutes=self.timeout_minutes)
    
    def update_activity(self):
        self.last_activity = datetime.now()
    
    async def add_file(self, file_id: str, filename: str, original_filename: str, 
                       size: int, storage_path: Path, owner_client_id: str) -> FileMetadata:
        async with self._files_lock:
            metadata = FileMetadata(
                file_id=file_id,
                filename=filename,
                original_filename=original_filename,
                size=size,
                upload_timestamp=datetime.now().isoformat(),
                storage_path=str(storage_path),
                owner_client_id=owner_client_id
            )
            self.files[file_id] = metadata
            self.update_activity()
            return metadata
    
    async def get_file(self, file_id: str) -> Optional[FileMetadata]:
        async with self._files_lock:
            return self.files.get(file_id)
    
    async def remove_file(self, file_id: str, client_id: str) -> bool:
        async with self._files_lock:
            if file_id in self.files:
                if self.files[file_id].owner_client_id != client_id:
                    return False
                file_path = Path(self.files[file_id].storage_path)
                if file_path.exists():
                    file_path.unlink()
                del self.files[file_id]
                self.update_activity()
                return True
            return False
    
    async def add_message(self, content: str, owner_client_id: str) -> Message:
        async with self._messages_lock:
            message = Message(
                message_id=str(uuid.uuid4())[:8],
                content=content,
                timestamp=datetime.now().isoformat(),
                owner_client_id=owner_client_id
            )
            self.messages.append(message)
            self.update_activity()
            return message
    
    async def delete_message(self, message_id: str, client_id: str) -> bool:
        async with self._messages_lock:
            for i, msg in enumerate(self.messages):
                if msg.message_id == message_id:
                    if msg.owner_client_id == client_id:
                        self.messages.pop(i)
                        self.update_activity()
                        return True
                    return False
            return False
    
    async def get_messages(self, limit: int = 100) -> List[Message]:
        async with self._messages_lock:
            return self.messages[-limit:] if limit else self.messages.copy()
    
    async def add_client(self, client_id: str, ip_address: str) -> ClientInfo:
        async with self._clients_lock:
            client = ClientInfo(
                client_id=client_id,
                ip_address=ip_address,
                joined_at=datetime.now().isoformat(),
                last_seen=datetime.now().isoformat()
            )
            self.clients[client_id] = client
            self.update_activity()
            return client
    
    async def get_clients_list(self) -> List[dict]:
        async with self._clients_lock:
            return [client.__dict__ for client in self.clients.values()]
    
    async def get_files_list(self) -> Dict[str, dict]:
        async with self._files_lock:
            return {fid: meta.to_dict() for fid, meta in self.files.items()}
    
    async def destroy(self):
        async with self._files_lock:
            for file_meta in self.files.values():
                file_path = Path(file_meta.storage_path)
                if file_path.exists():
                    file_path.unlink()
            self.files.clear()
        
        async with self._messages_lock:
            self.messages.clear()
        
        async with self._clients_lock:
            self.clients.clear()
        
        if self.storage_path.exists():
            shutil.rmtree(self.storage_path)
    
    def to_summary(self) -> dict:
        return {
            "session_id": self.session_id,
            "host_ip": self.host_ip,
            "created_at": self.created_at.isoformat(),
            "timeout_minutes": self.timeout_minutes,
            "file_count": len(self.files),
            "message_count": len(self.messages),
            "client_count": len(self.clients),
            "last_activity": self.last_activity.isoformat()
        }


class SessionManager:
    def __init__(self, default_timeout: int = 60):
        self.sessions: Dict[str, Session] = {}
        self._sessions_lock = asyncio.Lock()
        self.default_timeout = default_timeout
    
    async def create_session(self, host_ip: str, timeout_minutes: int = None) -> Session:
        session_id = str(uuid.uuid4())[:8]
        timeout = timeout_minutes or self.default_timeout
        
        async with self._sessions_lock:
            session = Session(session_id, host_ip, timeout)
            self.sessions[session_id] = session
            return session
    
    async def get_session(self, session_id: str) -> Optional[Session]:
        async with self._sessions_lock:
            session = self.sessions.get(session_id)
        
        if session:
            if session.is_expired:
                await self.destroy_session(session_id)
                return None
            session.update_activity()
        
        return session
    
    async def destroy_session(self, session_id: str) -> bool:
        async with self._sessions_lock:
            if session_id in self.sessions:
                session = self.sessions[session_id]
                await session.destroy()
                del self.sessions[session_id]
                return True
            return False
    
    async def cleanup_expired_sessions(self):
        async with self._sessions_lock:
            expired = [sid for sid, sess in self.sessions.items() if sess.is_expired]
        
        for sid in expired:
            await self.destroy_session(sid)
    
    async def start_cleanup_worker(self, interval_seconds: int = 30):
        while True:
            await asyncio.sleep(interval_seconds)
            await self.cleanup_expired_sessions()


# ============================================================================
# FASTAPI APPLICATION
# ============================================================================

session_manager = SessionManager(default_timeout=60)

@asynccontextmanager
async def lifespan(app: FastAPI):
    cleanup_task = asyncio.create_task(session_manager.start_cleanup_worker())
    local_ip = get_local_ip()
    print(f"""
    ================================================================
    LAN Collaboration System - Professional Edition
    ================================================================
    
    Server Configuration:
    - Local IP: {local_ip}
    - Port: 8000
    - LAN URL: http://{local_ip}:8000
    
    Features:
    - File sharing with ownership
    - Text messaging with delete
    - Session isolation with auto-cleanup
    
    Access from any device on your local network:
    http://{local_ip}:8000
    
    ================================================================
    """)
    yield
    cleanup_task.cancel()
    for session_id in list(session_manager.sessions.keys()):
        await session_manager.destroy_session(session_id)
    print("[System] Shutdown complete")

app = FastAPI(title="LAN Collaboration System", lifespan=lifespan)


# ============================================================================
# HOME PAGE
# ============================================================================

HOME_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LAN Collaboration System</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            background: #F9FAFB;
            min-height: 100vh;
            padding: 48px 24px;
        }
        
        .container {
            max-width: 900px;
            margin: 0 auto;
        }
        
        .header {
            text-align: center;
            margin-bottom: 48px;
        }
        
        .header h1 {
            font-size: 28px;
            font-weight: 600;
            color: #111827;
            margin-bottom: 8px;
        }
        
        .header p {
            color: #6B7280;
            font-size: 14px;
        }
        
        .card {
            background: #FFFFFF;
            border-radius: 12px;
            padding: 28px;
            margin-bottom: 24px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05), 0 1px 2px rgba(0,0,0,0.03);
            border: 1px solid #E5E7EB;
        }
        
        .card h2 {
            font-size: 18px;
            font-weight: 600;
            color: #111827;
            margin-bottom: 20px;
            padding-bottom: 12px;
            border-bottom: 1px solid #E5E7EB;
        }
        
        .form-group {
            margin-bottom: 20px;
        }
        
        label {
            display: block;
            font-size: 14px;
            font-weight: 500;
            color: #374151;
            margin-bottom: 8px;
        }
        
        input {
            width: 100%;
            padding: 10px 12px;
            border: 1px solid #D1D5DB;
            border-radius: 8px;
            font-size: 14px;
            font-family: inherit;
            transition: all 0.2s;
        }
        
        input:focus {
            outline: none;
            border-color: #2563EB;
            box-shadow: 0 0 0 3px rgba(37,99,235,0.1);
        }
        
        button {
            background: #2563EB;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            transition: background 0.2s;
        }
        
        button:hover {
            background: #1D4ED8;
        }
        
        .info-box {
            background: #F9FAFB;
            border-left: 3px solid #2563EB;
            padding: 16px;
            font-size: 13px;
            color: #6B7280;
            border-radius: 8px;
        }
        
        .session-result {
            margin-top: 24px;
            padding: 20px;
            background: #F9FAFB;
            border-radius: 8px;
            border: 1px solid #E5E7EB;
        }
        
        .session-url {
            font-family: monospace;
            background: #FFFFFF;
            padding: 10px;
            border: 1px solid #E5E7EB;
            border-radius: 8px;
            word-break: break-all;
            font-size: 13px;
            margin: 12px 0;
            color: #111827;
        }
        
        .qr-container {
            text-align: center;
            margin: 20px 0;
        }
        
        .qr-container img {
            max-width: 160px;
            height: auto;
            border: 1px solid #E5E7EB;
            border-radius: 8px;
        }
        
        .hidden {
            display: none;
        }
        
        .badge {
            display: inline-block;
            background: #2563EB;
            color: white;
            font-size: 11px;
            padding: 2px 8px;
            border-radius: 4px;
            margin-left: 8px;
            font-weight: 500;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>LAN Collaboration System</h1>
            <p>Private offline session-based file sharing and messaging</p>
        </div>
        
        <div class="card">
            <h2>Create New Session</h2>
            <form id="createForm">
                <div class="form-group">
                    <label for="timeout">Session Timeout (minutes)</label>
                    <input type="number" id="timeout" value="60" min="5" max="480">
                </div>
                <button type="submit">Create Session</button>
            </form>
            <div id="createResult" class="hidden"></div>
        </div>
        
        <div class="card">
            <h2>Join Existing Session</h2>
            <form id="joinForm">
                <div class="form-group">
                    <label for="sessionId">Session ID</label>
                    <input type="text" id="sessionId" placeholder="Enter 8-character session ID" required>
                </div>
                <button type="submit">Join Session</button>
            </form>
        </div>
        
        <div class="info-box">
            <strong>How it works</strong><br>
            Each device generates a unique client ID. You can only delete content you own. All data is automatically deleted when the session expires.
        </div>
    </div>
    
    <script>
        const createForm = document.getElementById('createForm');
        const joinForm = document.getElementById('joinForm');
        
        createForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const timeout = document.getElementById('timeout').value;
            
            const response = await fetch('/api/session/create', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({timeout_minutes: parseInt(timeout)})
            });
            
            const data = await response.json();
            const joinUrl = data.join_url;
            
            const resultDiv = document.getElementById('createResult');
            resultDiv.innerHTML = `
                <div class="session-result">
                    <strong>Session Created Successfully</strong>
                    <div style="margin-top: 16px;">
                        <div style="font-size: 13px; font-weight: 500; color: #374151; margin-bottom: 8px;">
                            Network URL <span class="badge">Share with other devices</span>
                        </div>
                        <div class="session-url">${joinUrl}</div>
                    </div>
                    <div class="qr-container">
                        <img src="data:image/png;base64,${data.qr_code}" alt="QR Code">
                        <div style="font-size: 12px; color: #6B7280; margin-top: 8px;">
                            Scan with other devices to join
                        </div>
                    </div>
                    <button onclick="window.location.href='${joinUrl}'">Open Session</button>
                </div>
            `;
            resultDiv.classList.remove('hidden');
        });
        
        joinForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const sessionId = document.getElementById('sessionId').value.trim();
            if (sessionId) {
                window.location.href = '/session/' + sessionId;
            }
        });
    </script>
</body>
</html>"""


# ============================================================================
# SESSION PAGE WITH PROFESSIONAL UI
# ============================================================================

SESSION_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Session {session_id} - LAN Collaboration</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            background: #F9FAFB;
            height: 100vh;
            display: flex;
            flex-direction: column;
        }}
        
        /* Top Bar */
        .top-bar {{
            background: #FFFFFF;
            border-bottom: 1px solid #E5E7EB;
            padding: 16px 24px;
            box-shadow: 0 1px 2px rgba(0,0,0,0.03);
        }}
        
        .top-bar-content {{
            max-width: 1400px;
            margin: 0 auto;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 16px;
        }}
        
        .session-info {{
            display: flex;
            align-items: center;
            gap: 20px;
            flex-wrap: wrap;
        }}
        
        .session-title {{
            font-size: 16px;
            font-weight: 600;
            color: #111827;
        }}
        
        .session-badge {{
            font-family: monospace;
            background: #F3F4F6;
            padding: 4px 12px;
            border-radius: 6px;
            font-size: 13px;
            color: #6B7280;
            border: 1px solid #E5E7EB;
        }}
        
        .stats {{
            display: flex;
            gap: 20px;
            font-size: 13px;
            color: #6B7280;
        }}
        
        .stat {{
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        
        .stat-value {{
            font-weight: 600;
            color: #111827;
        }}
        
        .nav-buttons {{
            display: flex;
            gap: 10px;
        }}
        
        .button-secondary {{
            background: #F3F4F6;
            color: #374151;
            border: 1px solid #E5E7EB;
            padding: 6px 14px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s;
        }}
        
        .button-secondary:hover {{
            background: #E5E7EB;
        }}
        
        /* Main Layout */
        .main-layout {{
            display: flex;
            flex: 1;
            overflow: hidden;
            max-width: 1400px;
            margin: 0 auto;
            width: 100%;
            gap: 20px;
            padding: 20px;
        }}
        
        .left-panel {{
            flex: 1;
            display: flex;
            flex-direction: column;
            gap: 20px;
        }}
        
        .right-panel {{
            flex: 1;
            display: flex;
            flex-direction: column;
            gap: 20px;
        }}
        
        /* Cards */
        .card {{
            background: #FFFFFF;
            border-radius: 12px;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            border: 1px solid #E5E7EB;
            box-shadow: 0 1px 2px rgba(0,0,0,0.03);
        }}
        
        .card-header {{
            padding: 16px 20px;
            border-bottom: 1px solid #E5E7EB;
            background: #FFFFFF;
        }}
        
        .card-header h2 {{
            font-size: 15px;
            font-weight: 600;
            color: #111827;
        }}
        
        /* Upload Area */
        .upload-area {{
            padding: 24px;
            text-align: center;
            background: #F9FAFB;
            cursor: pointer;
            transition: all 0.2s;
            border-bottom: 1px solid #E5E7EB;
        }}
        
        .upload-area:hover {{
            background: #F3F4F6;
        }}
        
        .upload-icon {{
            display: inline-block;
            margin-bottom: 8px;
        }}
        
        .upload-area input {{
            display: none;
        }}
        
        /* File List */
        .file-list, .message-list {{
            flex: 1;
            overflow-y: auto;
            padding: 8px;
            min-height: 300px;
        }}
        
        .file-item {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 12px;
            border-bottom: 1px solid #F3F4F6;
            transition: background 0.2s;
        }}
        
        .file-item:hover {{
            background: #F9FAFB;
        }}
        
        .file-info {{
            flex: 1;
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        
        .file-icon {{
            flex-shrink: 0;
        }}
        
        .file-details {{
            flex: 1;
        }}
        
        .file-name {{
            font-size: 14px;
            font-weight: 500;
            color: #111827;
            word-break: break-all;
        }}
        
        .file-meta {{
            font-size: 12px;
            color: #6B7280;
            margin-top: 2px;
        }}
        
        .file-actions {{
            display: flex;
            gap: 8px;
        }}
        
        /* Message Item */
        .message-item {{
            padding: 12px;
            border-bottom: 1px solid #F3F4F6;
            transition: background 0.2s;
        }}
        
        .message-item:hover {{
            background: #F9FAFB;
        }}
        
        .message-content {{
            font-size: 14px;
            color: #111827;
            word-wrap: break-word;
            line-height: 1.5;
            margin-bottom: 8px;
        }}
        
        .message-meta {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 11px;
            color: #9CA3AF;
        }}
        
        .message-actions {{
            display: flex;
            gap: 8px;
        }}
        
        /* Buttons */
        .btn-icon {{
            background: none;
            border: none;
            padding: 6px;
            cursor: pointer;
            border-radius: 6px;
            transition: all 0.2s;
            display: inline-flex;
            align-items: center;
            justify-content: center;
        }}
        
        .btn-icon:hover {{
            background: #F3F4F6;
        }}
        
        .btn-download {{
            color: #2563EB;
        }}
        
        .btn-delete {{
            color: #DC2626;
        }}
        
        .btn-copy {{
            color: #6B7280;
        }}
        
        .btn-primary {{
            background: #2563EB;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 500;
            cursor: pointer;
            transition: background 0.2s;
        }}
        
        .btn-primary:hover {{
            background: #1D4ED8;
        }}
        
        /* Message Input */
        .message-input-area {{
            padding: 16px;
            border-top: 1px solid #E5E7EB;
            background: #FFFFFF;
        }}
        
        .message-form {{
            display: flex;
            gap: 12px;
        }}
        
        .message-input {{
            flex: 1;
            padding: 10px 12px;
            border: 1px solid #D1D5DB;
            border-radius: 8px;
            font-size: 14px;
            font-family: inherit;
            resize: vertical;
            transition: all 0.2s;
        }}
        
        .message-input:focus {{
            outline: none;
            border-color: #2563EB;
            box-shadow: 0 0 0 3px rgba(37,99,235,0.1);
        }}
        
        /* Progress Bar */
        .progress {{
            width: 100%;
            height: 3px;
            background: #E5E7EB;
            position: relative;
            overflow: hidden;
            display: none;
        }}
        
        .progress-bar {{
            height: 100%;
            background: #2563EB;
            width: 0%;
            transition: width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }}
        
        .empty-state {{
            text-align: center;
            padding: 48px 20px;
            color: #9CA3AF;
            font-size: 13px;
        }}
        
        /* SVG Icons */
        .svg-icon {{
            width: 18px;
            height: 18px;
            stroke-width: 1.5;
            stroke: currentColor;
            fill: none;
        }}
        
        .svg-fill {{
            fill: currentColor;
            stroke: none;
        }}
        
        /* Responsive */
        @media (max-width: 768px) {{
            .main-layout {{
                flex-direction: column;
            }}
            
            .top-bar-content {{
                flex-direction: column;
                align-items: stretch;
            }}
            
            .session-info {{
                justify-content: space-between;
            }}
        }}
    </style>
</head>
<body>
    <div class="top-bar">
        <div class="top-bar-content">
            <div class="session-info">
                <div class="session-title">Collaboration Session</div>
                <div class="session-badge">ID: {session_id}</div>
                <div class="stats">
                    <div class="stat">
                        <svg class="svg-icon svg-fill" viewBox="0 0 20 20" width="14" height="14">
                            <path d="M4 4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4Z"/>
                            <path d="M8 2v4l2-1 2 1V2"/>
                        </svg>
                        <span>Files: <span class="stat-value" id="fileCount">0</span></span>
                    </div>
                    <div class="stat">
                        <svg class="svg-icon svg-fill" viewBox="0 0 20 20" width="14" height="14">
                            <path d="M3 5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-4l-4 4v-4H5a2 2 0 0 1-2-2V5Z"/>
                        </svg>
                        <span>Messages: <span class="stat-value" id="messageCount">0</span></span>
                    </div>
                    <div class="stat">
                        <svg class="svg-icon svg-fill" viewBox="0 0 20 20" width="14" height="14">
                            <path d="M10 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm-7 9a7 7 0 1 1 14 0H3Z"/>
                        </svg>
                        <span>Online: <span class="stat-value" id="clientCount">1</span></span>
                    </div>
                </div>
            </div>
            <div class="nav-buttons">
                <button class="button-secondary" onclick="manualRefresh()">
                    <svg class="svg-icon" viewBox="0 0 20 20" width="14" height="14" style="display: inline-block; margin-right: 4px;">
                        <path d="M16 10a6 6 0 0 1-6 6 6 6 0 0 1-6-6 6 6 0 0 1 6-6 6 6 0 0 1 4.5 2L12 6h5V1l-1.5 1.5A8 8 0 1 0 18 10h-2Z"/>
                    </svg>
                    Refresh
                </button>
                <button class="button-secondary" onclick="window.location.href='/'">
                    <svg class="svg-icon" viewBox="0 0 20 20" width="14" height="14" style="display: inline-block; margin-right: 4px;">
                        <path d="M3 3h14v14H3zM10 3v14"/>
                    </svg>
                    Exit
                </button>
            </div>
        </div>
    </div>
    
    <div class="main-layout">
        <div class="left-panel">
            <div class="card">
                <div class="card-header">
                    <h2>File Sharing</h2>
                </div>
                <div class="upload-area" onclick="document.getElementById('fileInput').click()">
                    <div class="upload-icon">
                        <svg class="svg-icon" viewBox="0 0 20 20" width="24" height="24" style="stroke: #2563EB;">
                            <path d="M10 3v12m-6-6 6-6 6 6"/>
                            <path d="M3 16h14"/>
                        </svg>
                    </div>
                    <div style="font-size: 14px; color: #374151;">Click to upload files</div>
                    <div style="font-size: 12px; color: #6B7280; margin-top: 4px;">Any file type supported</div>
                </div>
                <input type="file" id="fileInput" multiple>
                <div class="progress" id="progress">
                    <div class="progress-bar" id="progressBar"></div>
                </div>
                <div class="file-list" id="fileList">
                    <div class="empty-state">No files shared yet</div>
                </div>
            </div>
            
            <div class="card">
                <div class="card-header">
                    <h2>Send Message</h2>
                </div>
                <div class="message-input-area">
                    <form id="messageForm" class="message-form">
                        <textarea id="messageInput" class="message-input" rows="3" placeholder="Type your message here..."></textarea>
                        <button type="submit" class="btn-primary">Send</button>
                    </form>
                </div>
            </div>
        </div>
        
        <div class="right-panel">
            <div class="card">
                <div class="card-header">
                    <h2>Messages</h2>
                </div>
                <div class="message-list" id="messagesContainer">
                    <div class="empty-state">No messages yet</div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        const sessionId = '{session_id}';
        let clientId = localStorage.getItem('clientId');
        if (!clientId || clientId === 'null' || clientId === 'undefined') {{
            clientId = crypto.randomUUID ? crypto.randomUUID() : 'client_' + Math.random().toString(36).substr(2, 9);
            localStorage.setItem('clientId', clientId);
        }}
        
        let cachedFilesHash = '';
        let cachedMessagesCount = 0;
        
        function getFilesHash(files) {{
            const fileIds = Object.keys(files).sort();
            return fileIds.join(',');
        }}
        
        async function loadFiles() {{
            try {{
                const response = await fetch(`/api/session/${{sessionId}}/files`);
                const data = await response.json();
                const fileList = document.getElementById('fileList');
                const fileCount = document.getElementById('fileCount');
                
                const files = Object.values(data.files || {{}});
                const currentHash = getFilesHash(data.files || {{}});
                
                if (currentHash !== cachedFilesHash) {{
                    cachedFilesHash = currentHash;
                    fileCount.textContent = files.length;
                    
                    if (files.length === 0) {{
                        fileList.innerHTML = '<div class="empty-state">No files shared yet</div>';
                        return;
                    }}
                    
                    fileList.innerHTML = files.map(file => `
                        <div class="file-item">
                            <div class="file-info">
                                <div class="file-icon">
                                    <svg class="svg-icon" viewBox="0 0 20 20" width="20" height="20">
                                        <path d="M4 4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4Z"/>
                                        <path d="M8 2v4l2-1 2 1V2"/>
                                    </svg>
                                </div>
                                <div class="file-details">
                                    <div class="file-name">${{escapeHtml(file.original_filename)}}</div>
                                    <div class="file-meta">${{formatBytes(file.size)}} | Uploaded ${{formatTime(file.upload_timestamp)}}</div>
                                </div>
                            </div>
                            <div class="file-actions">
                                <button class="btn-icon btn-download" onclick="downloadFile('${{file.file_id}}')" title="Download">
                                    <svg class="svg-icon" viewBox="0 0 20 20" width="18" height="18">
                                        <path d="M10 3v12m-6-6 6 6 6-6"/>
                                        <path d="M3 16h14"/>
                                    </svg>
                                </button>
                                ${{file.owner_client_id === clientId ? `
                                    <button class="btn-icon btn-delete" onclick="deleteFile('${{file.file_id}}')" title="Delete">
                                        <svg class="svg-icon" viewBox="0 0 20 20" width="18" height="18">
                                            <path d="M4 5h12M7 5V3h6v2M5 5v10a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2V5"/>
                                            <path d="M9 9v4M11 9v4"/>
                                        </svg>
                                    </button>
                                ` : ''}}
                            </div>
                        </div>
                    `).join('');
                }}
            }} catch (error) {{
                console.error('Error loading files:', error);
            }}
        }}
        
        async function loadMessages() {{
            try {{
                const response = await fetch(`/api/session/${{sessionId}}/messages`);
                const data = await response.json();
                const messagesContainer = document.getElementById('messagesContainer');
                const messageCount = document.getElementById('messageCount');
                
                if (data.messages.length !== cachedMessagesCount) {{
                    cachedMessagesCount = data.messages.length;
                    messageCount.textContent = data.messages.length;
                    
                    if (data.messages.length === 0) {{
                        messagesContainer.innerHTML = '<div class="empty-state">No messages yet</div>';
                        return;
                    }}
                    
                    const wasAtBottom = messagesContainer.scrollHeight - messagesContainer.scrollTop <= messagesContainer.clientHeight + 50;
                    
                    messagesContainer.innerHTML = data.messages.map(msg => `
                        <div class="message-item">
                            <div class="message-content">${{escapeHtml(msg.content)}}</div>
                            <div class="message-meta">
                                <span>${{formatTime(msg.timestamp)}}</span>
                                <div class="message-actions">
                                    <button class="btn-icon btn-copy" onclick="copyToClipboard('${{escapeHtml(msg.content).replace(/'/g, "\\\\'")}}')" title="Copy">
                                        <svg class="svg-icon" viewBox="0 0 20 20" width="14" height="14">
                                            <path d="M8 3h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z"/>
                                            <path d="M4 11H2V5a2 2 0 0 1 2-2h6v2"/>
                                        </svg>
                                    </button>
                                    ${{msg.owner_client_id === clientId ? `
                                        <button class="btn-icon btn-delete" onclick="deleteMessage('${{msg.message_id}}')" title="Delete">
                                            <svg class="svg-icon" viewBox="0 0 20 20" width="14" height="14">
                                                <path d="M4 5h12M7 5V3h6v2M5 5v10a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2V5"/>
                                                <path d="M9 9v4M11 9v4"/>
                                            </svg>
                                        </button>
                                    ` : ''}}
                                </div>
                            </div>
                        </div>
                    `).join('');
                    
                    if (wasAtBottom) {{
                        messagesContainer.scrollTop = messagesContainer.scrollHeight;
                    }}
                }}
            }} catch (error) {{
                console.error('Error loading messages:', error);
            }}
        }}
        
        async function loadStats() {{
            try {{
                const response = await fetch(`/api/session/${{sessionId}}/info`);
                const data = await response.json();
                document.getElementById('clientCount').textContent = data.client_count;
            }} catch (error) {{
                console.error('Error loading stats:', error);
            }}
        }}
        
        async function sendMessage(content) {{
            if (!content.trim()) return;
            
            try {{
                const response = await fetch(`/api/session/${{sessionId}}/message`, {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{content: content, client_id: clientId}})
                }});
                
                if (response.ok) {{
                    document.getElementById('messageInput').value = '';
                    cachedMessagesCount = 0;
                    await loadMessages();
                    const messagesContainer = document.getElementById('messagesContainer');
                    messagesContainer.scrollTop = messagesContainer.scrollHeight;
                }}
            }} catch (error) {{
                console.error('Error sending message:', error);
            }}
        }}
        
        async function deleteMessage(messageId) {{
            if (confirm('Delete this message?')) {{
                const response = await fetch(`/api/session/${{sessionId}}/message/${{messageId}}?client_id=${{clientId}}`, {{method: 'DELETE'}});
                if (response.ok) {{
                    cachedMessagesCount = 0;
                    await loadMessages();
                }} else {{
                    alert('You can only delete your own messages.');
                }}
            }}
        }}
        
        async function uploadFiles(files) {{
            const progress = document.getElementById('progress');
            const progressBar = document.getElementById('progressBar');
            
            for (const file of files) {{
                const formData = new FormData();
                formData.append('file', file);
                formData.append('client_id', clientId);
                
                progress.style.display = 'block';
                
                const xhr = new XMLHttpRequest();
                xhr.upload.onprogress = (e) => {{
                    if (e.lengthComputable) {{
                        const percent = (e.loaded / e.total) * 100;
                        progressBar.style.width = percent + '%';
                    }}
                }};
                
                await new Promise((resolve, reject) => {{
                    xhr.onload = () => {{
                        if (xhr.status === 200) resolve();
                        else reject();
                    }};
                    xhr.onerror = () => reject();
                    xhr.open('POST', `/api/session/${{sessionId}}/upload`);
                    xhr.send(formData);
                }});
            }}
            
            progress.style.display = 'none';
            progressBar.style.width = '0%';
            cachedFilesHash = '';
            await loadFiles();
        }}
        
        async function downloadFile(fileId) {{
            window.open(`/api/session/${{sessionId}}/download/${{fileId}}`, '_blank');
        }}
        
        async function deleteFile(fileId) {{
            if (confirm('Delete this file? Only you can delete your own files.')) {{
                const response = await fetch(`/api/session/${{sessionId}}/file/${{fileId}}?client_id=${{clientId}}`, {{method: 'DELETE'}});
                if (response.ok) {{
                    cachedFilesHash = '';
                    await loadFiles();
                }} else {{
                    alert('You can only delete files you uploaded.');
                }}
            }}
        }}
        
        function copyToClipboard(text) {{
            navigator.clipboard.writeText(text).then(() => {{
                const notification = document.createElement('div');
                notification.textContent = 'Copied to clipboard';
                notification.style.cssText = `
                    position: fixed;
                    bottom: 20px;
                    right: 20px;
                    background: #2563EB;
                    color: white;
                    padding: 8px 16px;
                    border-radius: 8px;
                    font-size: 13px;
                    z-index: 1000;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                `;
                document.body.appendChild(notification);
                setTimeout(() => notification.remove(), 2000);
            }});
        }}
        
        function manualRefresh() {{
            cachedFilesHash = '';
            cachedMessagesCount = 0;
            loadFiles();
            loadMessages();
            loadStats();
        }}
        
        function formatBytes(bytes) {{
            if (bytes === 0) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        }}
        
        function formatTime(timestamp) {{
            if (!timestamp) return 'unknown';
            const date = new Date(timestamp);
            return date.toLocaleTimeString();
        }}
        
        function escapeHtml(text) {{
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }}
        
        document.getElementById('fileInput').onchange = (e) => {{
            if (e.target.files.length > 0) {{
                uploadFiles(Array.from(e.target.files));
                e.target.value = '';
            }}
        }};
        
        document.getElementById('messageForm').onsubmit = (e) => {{
            e.preventDefault();
            const input = document.getElementById('messageInput');
            const content = input.value.trim();
            if (content) {{
                sendMessage(content);
            }}
        }};
        
        loadFiles();
        loadMessages();
        loadStats();
        setInterval(() => {{
            loadFiles();
            loadMessages();
            loadStats();
        }}, 3000);
    </script>
</body>
</html>"""


# ============================================================================
# API ROUTES
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def home():
    return HOME_PAGE


@app.get("/session/{session_id}", response_class=HTMLResponse)
async def session_page(session_id: str, request: Request):
    session = await session_manager.get_session(session_id)
    if not session:
        return HTMLResponse("""
            <!DOCTYPE html>
            <html>
            <head><title>Session Not Found</title></head>
            <body style="font-family: sans-serif; text-align: center; padding: 50px;">
                <h1>Session Not Found</h1>
                <p>The session may have expired or does not exist.</p>
                <a href="/">Create a new session</a>
            </body>
            </html>
        """, status_code=404)
    
    client_id = f"client_{uuid.uuid4().hex[:8]}"
    client_ip = request.client.host if request.client else "unknown"
    await session.add_client(client_id, client_ip)
    
    return SESSION_PAGE_TEMPLATE.format(session_id=session_id)


@app.post("/api/session/create")
async def create_session(timeout_minutes: int = 60, request: Request = None):
    local_ip = get_local_ip()
    session = await session_manager.create_session(local_ip, timeout_minutes)
    
    base_url = f"http://{local_ip}:8000"
    join_url = f"{base_url}/session/{session.session_id}"
    qr_code = generate_qr_code_base64(join_url)
    
    return {
        "session_id": session.session_id,
        "join_url": join_url,
        "qr_code": qr_code,
        "timeout_minutes": timeout_minutes
    }


@app.post("/api/session/{session_id}/upload")
async def upload_file(session_id: str, file: UploadFile = File(...), client_id: str = Form(...)):
    session = await session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    
    file_id = str(uuid.uuid4())[:12]
    safe_filename = f"{file_id}_{file.filename.replace('/', '_').replace('\\', '_')}"
    file_path = session.storage_path / safe_filename
    
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)
    
    metadata = await session.add_file(
        file_id=file_id,
        filename=safe_filename,
        original_filename=file.filename,
        size=len(content),
        storage_path=file_path,
        owner_client_id=client_id
    )
    
    return {"message": "File uploaded successfully", "file_id": file_id, "metadata": metadata.to_dict()}


@app.get("/api/session/{session_id}/files")
async def list_files(session_id: str):
    session = await session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    
    files = await session.get_files_list()
    return {"session_id": session_id, "files": files, "file_count": len(files)}


@app.get("/api/session/{session_id}/download/{file_id}")
async def download_file(session_id: str, file_id: str):
    session = await session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    
    file_meta = await session.get_file(file_id)
    if not file_meta:
        raise HTTPException(status_code=404, detail="File not found")
    
    file_path = Path(file_meta.storage_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")
    
    return FileResponse(
        path=file_path,
        filename=file_meta.original_filename,
        media_type="application/octet-stream"
    )


@app.delete("/api/session/{session_id}/file/{file_id}")
async def delete_file(session_id: str, file_id: str, client_id: str):
    session = await session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    
    if await session.remove_file(file_id, client_id):
        return {"message": "File deleted successfully"}
    else:
        raise HTTPException(status_code=403, detail="You can only delete files you uploaded or file not found")


@app.post("/api/session/{session_id}/message")
async def send_message(session_id: str, request: Request):
    session = await session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    
    data = await request.json()
    content = data.get("content", "").strip()
    client_id = data.get("client_id", "")
    
    if not content:
        raise HTTPException(status_code=400, detail="Message content cannot be empty")
    
    if len(content) > 5000:
        raise HTTPException(status_code=400, detail="Message too long (max 5000 characters)")
    
    message = await session.add_message(content, client_id)
    
    return {"message": "Message sent", "message_id": message.message_id}


@app.get("/api/session/{session_id}/messages")
async def get_messages(session_id: str, limit: int = 100):
    session = await session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    
    messages = await session.get_messages(limit)
    return {
        "session_id": session_id,
        "messages": [msg.to_dict() for msg in messages],
        "count": len(messages)
    }


@app.delete("/api/session/{session_id}/message/{message_id}")
async def delete_message(session_id: str, message_id: str, client_id: str):
    session = await session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    
    if await session.delete_message(message_id, client_id):
        return {"message": "Message deleted successfully"}
    else:
        raise HTTPException(status_code=403, detail="You can only delete your own messages or message not found")


@app.delete("/api/session/{session_id}")
async def delete_session(session_id: str):
    if await session_manager.destroy_session(session_id):
        return {"message": "Session deleted successfully"}
    else:
        raise HTTPException(status_code=404, detail="Session not found")


@app.get("/api/session/{session_id}/info")
async def session_info(session_id: str):
    session = await session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    
    info = session.to_summary()
    info["clients"] = await session.get_clients_list()
    return info


@app.get("/api/sessions")
async def list_sessions():
    sessions = await session_manager.get_all_sessions_summary()
    return {"sessions": sessions, "count": len(sessions)}


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
