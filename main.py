# main.py
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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum

from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
import qrcode
from io import BytesIO
import base64

# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class FileMetadata:
    """Metadata for uploaded files"""
    file_id: str
    filename: str
    original_filename: str
    size: int
    upload_timestamp: str
    storage_path: str
    
    def to_dict(self) -> dict:
        return {
            "file_id": self.file_id,
            "filename": self.filename,
            "original_filename": self.original_filename,
            "size": self.size,
            "upload_timestamp": self.upload_timestamp
        }


@dataclass
class Message:
    """Text message in a session"""
    message_id: str
    content: str
    timestamp: str
    client_ip: str
    
    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "content": self.content,
            "timestamp": self.timestamp,
            "client_ip": self.client_ip
        }


@dataclass
class ClientInfo:
    """Connected client information"""
    client_id: str
    ip_address: str
    joined_at: str
    last_seen: str


class Session:
    """Represents a single collaboration session"""
    
    def __init__(self, session_id: str, host_ip: str, timeout_minutes: int = 60):
        self.session_id = session_id
        self.host_ip = host_ip
        self.created_at = datetime.now()
        self.timeout_minutes = timeout_minutes
        self.last_activity = datetime.now()
        
        # Data stores
        self.files: Dict[str, FileMetadata] = {}  # file_id -> metadata
        self.messages: List[Message] = []  # ordered list of messages
        self.clients: Dict[str, ClientInfo] = {}  # client_id -> info
        
        # Locks for thread safety
        self._files_lock = asyncio.Lock()
        self._messages_lock = asyncio.Lock()
        self._clients_lock = asyncio.Lock()
        
        # Storage directory
        self.storage_path = Path(tempfile.gettempdir()) / f"session_{session_id}"
        self.storage_path.mkdir(parents=True, exist_ok=True)
    
    @property
    def is_expired(self) -> bool:
        """Check if session has exceeded timeout"""
        return datetime.now() - self.last_activity > timedelta(minutes=self.timeout_minutes)
    
    def update_activity(self):
        """Update last activity timestamp"""
        self.last_activity = datetime.now()
    
    async def add_file(self, file_id: str, filename: str, original_filename: str, 
                       size: int, storage_path: Path) -> FileMetadata:
        """Add file metadata to session (thread-safe)"""
        async with self._files_lock:
            metadata = FileMetadata(
                file_id=file_id,
                filename=filename,
                original_filename=original_filename,
                size=size,
                upload_timestamp=datetime.now().isoformat(),
                storage_path=str(storage_path)
            )
            self.files[file_id] = metadata
            self.update_activity()
            return metadata
    
    async def get_file(self, file_id: str) -> Optional[FileMetadata]:
        """Get file metadata by ID (thread-safe)"""
        async with self._files_lock:
            return self.files.get(file_id)
    
    async def remove_file(self, file_id: str) -> bool:
        """Remove file from session and disk (thread-safe)"""
        async with self._files_lock:
            if file_id in self.files:
                file_path = Path(self.files[file_id].storage_path)
                if file_path.exists():
                    file_path.unlink()
                del self.files[file_id]
                self.update_activity()
                return True
            return False
    
    async def add_message(self, content: str, client_ip: str) -> Message:
        """Add text message to session (thread-safe)"""
        async with self._messages_lock:
            message = Message(
                message_id=str(uuid.uuid4())[:8],
                content=content,
                timestamp=datetime.now().isoformat(),
                client_ip=client_ip
            )
            self.messages.append(message)
            self.update_activity()
            return message
    
    async def get_messages(self, limit: int = 100) -> List[Message]:
        """Get recent messages (thread-safe)"""
        async with self._messages_lock:
            return self.messages[-limit:] if limit else self.messages.copy()
    
    async def add_client(self, client_id: str, ip_address: str) -> ClientInfo:
        """Add connected client (thread-safe)"""
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
    
    async def remove_client(self, client_id: str) -> bool:
        """Remove client (thread-safe)"""
        async with self._clients_lock:
            if client_id in self.clients:
                del self.clients[client_id]
                return True
            return False
    
    async def update_client_seen(self, client_id: str):
        """Update client last seen timestamp"""
        async with self._clients_lock:
            if client_id in self.clients:
                self.clients[client_id].last_seen = datetime.now().isoformat()
    
    async def get_files_list(self) -> Dict[str, dict]:
        """Get all files as dict (thread-safe)"""
        async with self._files_lock:
            return {fid: meta.to_dict() for fid, meta in self.files.items()}
    
    async def get_clients_list(self) -> List[dict]:
        """Get all clients as list (thread-safe)"""
        async with self._clients_lock:
            return [client.__dict__ for client in self.clients.values()]
    
    async def destroy(self):
        """Completely destroy session and cleanup all resources"""
        # Delete all files
        async with self._files_lock:
            for file_meta in self.files.values():
                file_path = Path(file_meta.storage_path)
                if file_path.exists():
                    file_path.unlink()
            self.files.clear()
        
        # Clear messages
        async with self._messages_lock:
            self.messages.clear()
        
        # Clear clients
        async with self._clients_lock:
            self.clients.clear()
        
        # Remove storage directory
        if self.storage_path.exists():
            shutil.rmtree(self.storage_path)
    
    def to_summary(self) -> dict:
        """Get session summary"""
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
    """Manages all active sessions with thread-safe operations"""
    
    def __init__(self, default_timeout: int = 60):
        self.sessions: Dict[str, Session] = {}
        self._sessions_lock = asyncio.Lock()
        self.default_timeout = default_timeout
        self.cleanup_task = None
    
    async def create_session(self, host_ip: str, timeout_minutes: int = None) -> Session:
        """Create a new session with unique ID"""
        session_id = str(uuid.uuid4())[:8]
        timeout = timeout_minutes or self.default_timeout
        
        async with self._sessions_lock:
            session = Session(session_id, host_ip, timeout)
            self.sessions[session_id] = session
            return session
    
    async def get_session(self, session_id: str) -> Optional[Session]:
        """Get session if it exists and is not expired"""
        async with self._sessions_lock:
            session = self.sessions.get(session_id)
        
        if session:
            if session.is_expired:
                await self.destroy_session(session_id)
                return None
            session.update_activity()
        
        return session
    
    async def destroy_session(self, session_id: str) -> bool:
        """Destroy a session and clean up resources"""
        async with self._sessions_lock:
            if session_id in self.sessions:
                session = self.sessions[session_id]
                await session.destroy()
                del self.sessions[session_id]
                return True
            return False
    
    async def cleanup_expired_sessions(self):
        """Remove all expired sessions"""
        async with self._sessions_lock:
            expired = [sid for sid, sess in self.sessions.items() if sess.is_expired]
        
        for sid in expired:
            await self.destroy_session(sid)
            if expired:
                print(f"[Cleanup] Removed {len(expired)} expired session(s)")
    
    async def start_cleanup_worker(self, interval_seconds: int = 30):
        """Background task to clean up expired sessions"""
        while True:
            await asyncio.sleep(interval_seconds)
            await self.cleanup_expired_sessions()
    
    async def get_all_sessions_summary(self) -> List[dict]:
        """Get summary of all active sessions"""
        async with self._sessions_lock:
            return [sess.to_summary() for sess in self.sessions.values()]


# ============================================================================
# QR CODE GENERATOR
# ============================================================================

def generate_qr_code_base64(url: str) -> str:
    """Generate QR code as base64 string (offline, no external deps)"""
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
# FASTAPI APPLICATION
# ============================================================================

# Create session manager
session_manager = SessionManager(default_timeout=60)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Start background cleanup task
    cleanup_task = asyncio.create_task(session_manager.start_cleanup_worker())
    print("[System] Session-based communication system started")
    print("[System] Binding to 0.0.0.0 for LAN access")
    print("[System] Cleanup worker active (30s interval, 60min timeout)")
    yield
    # Cleanup
    cleanup_task.cancel()
    async for session_id in list(session_manager.sessions.keys()):
        await session_manager.destroy_session(session_id)
    print("[System] Shutdown complete")

app = FastAPI(title="LAN Collaboration System", lifespan=lifespan)


# ============================================================================
# HTML TEMPLATES
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
            background: #f5f5f5;
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 800px;
            margin: 0 auto;
        }
        
        .header {
            text-align: center;
            margin-bottom: 30px;
        }
        
        .header h1 {
            font-size: 28px;
            font-weight: 500;
            color: #1a1a1a;
            margin-bottom: 8px;
        }
        
        .header p {
            color: #666;
            font-size: 14px;
        }
        
        .card {
            background: white;
            border-radius: 8px;
            padding: 24px;
            margin-bottom: 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }
        
        .card h2 {
            font-size: 18px;
            font-weight: 500;
            color: #1a1a1a;
            margin-bottom: 16px;
            padding-bottom: 8px;
            border-bottom: 1px solid #e0e0e0;
        }
        
        .form-group {
            margin-bottom: 16px;
        }
        
        label {
            display: block;
            font-size: 14px;
            font-weight: 500;
            color: #333;
            margin-bottom: 6px;
        }
        
        input, select {
            width: 100%;
            padding: 10px;
            border: 1px solid #ccc;
            border-radius: 4px;
            font-size: 14px;
            font-family: inherit;
        }
        
        input:focus, select:focus {
            outline: none;
            border-color: #4a90e2;
        }
        
        button {
            background: #4a90e2;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 4px;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            transition: background 0.2s;
        }
        
        button:hover {
            background: #357abd;
        }
        
        button:active {
            transform: translateY(1px);
        }
        
        .info-box {
            background: #f8f9fa;
            border-left: 3px solid #4a90e2;
            padding: 12px;
            margin-top: 16px;
            font-size: 13px;
            color: #555;
        }
        
        .session-result {
            margin-top: 20px;
            padding: 16px;
            background: #f8f9fa;
            border-radius: 4px;
        }
        
        .session-url {
            font-family: monospace;
            background: white;
            padding: 8px;
            border: 1px solid #ddd;
            border-radius: 4px;
            word-break: break-all;
            font-size: 12px;
            margin: 8px 0;
        }
        
        .qr-container {
            text-align: center;
            margin: 16px 0;
        }
        
        .qr-container img {
            max-width: 180px;
            height: auto;
            border: 1px solid #ddd;
            border-radius: 4px;
        }
        
        .hidden {
            display: none;
        }
        
        .alert {
            padding: 12px;
            border-radius: 4px;
            margin-bottom: 16px;
            font-size: 14px;
        }
        
        .alert-success {
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }
        
        .alert-error {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>LAN Collaboration System</h1>
            <p>Offline session-based file sharing and messaging</p>
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
            <strong>How it works:</strong><br>
            - Create a session to host a collaboration room<br>
            - Share the session URL or QR code with others on your LAN<br>
            - All participants can share files and send messages<br>
            - Session and all data are automatically deleted after timeout
        </div>
    </div>
    
    <script>
        const createForm = document.getElementById('createForm');
        const joinForm = document.getElementById('joinForm');
        
        createForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const timeout = document.getElementById('timeout').value;
            
            try {
                const response = await fetch('/api/session/create', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({timeout_minutes: parseInt(timeout)})
                });
                
                const data = await response.json();
                const joinUrl = window.location.origin + '/session/' + data.session_id;
                
                const resultDiv = document.getElementById('createResult');
                resultDiv.innerHTML = `
                    <div class="session-result">
                        <strong>Session Created Successfully</strong>
                        <div class="session-url">${joinUrl}</div>
                        <div class="qr-container">
                            <img src="data:image/png;base64,${data.qr_code}" alt="QR Code">
                        </div>
                        <button onclick="window.location.href='/session/${data.session_id}'">Open Session</button>
                    </div>
                `;
                resultDiv.classList.remove('hidden');
            } catch (error) {
                console.error('Error:', error);
            }
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
            background: #f5f5f5;
            height: 100vh;
            display: flex;
            flex-direction: column;
        }}
        
        .header {{
            background: white;
            border-bottom: 1px solid #e0e0e0;
            padding: 16px 24px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }}
        
        .header-content {{
            max-width: 1400px;
            margin: 0 auto;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 12px;
        }}
        
        .session-info {{
            display: flex;
            align-items: center;
            gap: 16px;
            flex-wrap: wrap;
        }}
        
        .session-title {{
            font-size: 18px;
            font-weight: 500;
            color: #1a1a1a;
        }}
        
        .session-badge {{
            font-family: monospace;
            background: #f0f0f0;
            padding: 4px 12px;
            border-radius: 4px;
            font-size: 13px;
            color: #555;
        }}
        
        .stats {{
            display: flex;
            gap: 16px;
            font-size: 13px;
            color: #666;
        }}
        
        .stat {{
            display: flex;
            align-items: center;
            gap: 4px;
        }}
        
        .nav-buttons {{
            display: flex;
            gap: 8px;
        }}
        
        .button-secondary {{
            background: #f0f0f0;
            color: #333;
            border: 1px solid #ccc;
            padding: 6px 12px;
            border-radius: 4px;
            font-size: 13px;
            cursor: pointer;
        }}
        
        .button-secondary:hover {{
            background: #e0e0e0;
        }}
        
        .main-container {{
            display: flex;
            flex: 1;
            overflow: hidden;
            max-width: 1400px;
            margin: 0 auto;
            width: 100%;
            gap: 20px;
            padding: 20px;
        }}
        
        .files-section {{
            flex: 1;
            background: white;
            border-radius: 8px;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        
        .messages-section {{
            flex: 1;
            background: white;
            border-radius: 8px;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        
        .section-header {{
            padding: 16px 20px;
            border-bottom: 1px solid #e0e0e0;
            background: #fafafa;
        }}
        
        .section-header h2 {{
            font-size: 16px;
            font-weight: 500;
            color: #1a1a1a;
        }}
        
        .upload-area {{
            padding: 20px;
            border-bottom: 1px solid #e0e0e0;
            text-align: center;
            background: #fafafa;
            cursor: pointer;
            transition: background 0.2s;
        }}
        
        .upload-area:hover {{
            background: #f0f0f0;
        }}
        
        .upload-area input {{
            display: none;
        }}
        
        .file-list {{
            flex: 1;
            overflow-y: auto;
            padding: 12px;
        }}
        
        .file-item {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px;
            border-bottom: 1px solid #f0f0f0;
        }}
        
        .file-item:hover {{
            background: #fafafa;
        }}
        
        .file-info {{
            flex: 1;
        }}
        
        .file-name {{
            font-size: 14px;
            font-weight: 500;
            color: #333;
            word-break: break-all;
        }}
        
        .file-meta {{
            font-size: 11px;
            color: #999;
            margin-top: 4px;
        }}
        
        .file-actions {{
            display: flex;
            gap: 8px;
        }}
        
        .download-btn, .delete-btn {{
            padding: 6px 12px;
            border-radius: 4px;
            font-size: 12px;
            cursor: pointer;
            border: none;
        }}
        
        .download-btn {{
            background: #4a90e2;
            color: white;
        }}
        
        .download-btn:hover {{
            background: #357abd;
        }}
        
        .delete-btn {{
            background: #dc3545;
            color: white;
        }}
        
        .delete-btn:hover {{
            background: #c82333;
        }}
        
        .messages-container {{
            flex: 1;
            overflow-y: auto;
            padding: 16px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }}
        
        .message {{
            padding: 10px 12px;
            background: #f8f9fa;
            border-radius: 6px;
            border-left: 3px solid #4a90e2;
        }}
        
        .message-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 6px;
            font-size: 11px;
            color: #888;
        }}
        
        .message-content {{
            font-size: 14px;
            color: #333;
            word-wrap: break-word;
            line-height: 1.4;
        }}
        
        .copy-btn {{
            background: none;
            border: none;
            color: #4a90e2;
            cursor: pointer;
            font-size: 11px;
            padding: 2px 6px;
            border-radius: 3px;
        }}
        
        .copy-btn:hover {{
            background: #e0e0e0;
        }}
        
        .message-input-area {{
            padding: 16px;
            border-top: 1px solid #e0e0e0;
            background: white;
        }}
        
        .message-form {{
            display: flex;
            gap: 8px;
        }}
        
        .message-input {{
            flex: 1;
            padding: 10px;
            border: 1px solid #ccc;
            border-radius: 4px;
            font-size: 14px;
            font-family: inherit;
            resize: vertical;
        }}
        
        .send-btn {{
            padding: 10px 20px;
            background: #4a90e2;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
        }}
        
        .empty-state {{
            text-align: center;
            padding: 40px;
            color: #999;
            font-size: 14px;
        }}
        
        .progress {{
            width: 100%;
            height: 2px;
            background: #e0e0e0;
            margin-top: 8px;
            display: none;
        }}
        
        .progress-bar {{
            height: 100%;
            background: #4a90e2;
            width: 0%;
            transition: width 0.3s;
        }}
        
        @media (max-width: 768px) {{
            .main-container {{
                flex-direction: column;
            }}
            
            .header-content {{
                flex-direction: column;
                align-items: stretch;
            }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <div class="header-content">
            <div class="session-info">
                <div class="session-title">Collaboration Session</div>
                <div class="session-badge">ID: {session_id}</div>
                <div class="stats">
                    <div class="stat">Files: <span id="fileCount">0</span></div>
                    <div class="stat">Messages: <span id="messageCount">0</span></div>
                    <div class="stat">Clients: <span id="clientCount">1</span></div>
                </div>
            </div>
            <div class="nav-buttons">
                <button class="button-secondary" onclick="refreshAll()">Refresh</button>
                <button class="button-secondary" onclick="window.location.href='/'">Home</button>
            </div>
        </div>
    </div>
    
    <div class="main-container">
        <div class="files-section">
            <div class="section-header">
                <h2>File Sharing</h2>
            </div>
            <div class="upload-area" onclick="document.getElementById('fileInput').click()">
                <div>Click to upload files</div>
                <div style="font-size: 12px; color: #666; margin-top: 4px;">Any file type supported</div>
            </div>
            <input type="file" id="fileInput" multiple>
            <div class="progress" id="progress">
                <div class="progress-bar" id="progressBar"></div>
            </div>
            <div class="file-list" id="fileList">
                <div class="empty-state">No files shared yet</div>
            </div>
        </div>
        
        <div class="messages-section">
            <div class="section-header">
                <h2>Text Messages</h2>
            </div>
            <div class="messages-container" id="messagesContainer">
                <div class="empty-state">No messages yet. Send a message below.</div>
            </div>
            <div class="message-input-area">
                <form id="messageForm" class="message-form">
                    <textarea id="messageInput" class="message-input" rows="2" placeholder="Type your message here..."></textarea>
                    <button type="submit" class="send-btn">Send</button>
                </form>
            </div>
        </div>
    </div>
    
    <script>
        const sessionId = '{session_id}';
        let clientId = localStorage.getItem('clientId');
        if (!clientId) {{
            clientId = 'client_' + Math.random().toString(36).substr(2, 9);
            localStorage.setItem('clientId', clientId);
        }}
        
        async function loadFiles() {{
            try {{
                const response = await fetch(`/api/session/${{sessionId}}/files`);
                const data = await response.json();
                const fileList = document.getElementById('fileList');
                const fileCount = document.getElementById('fileCount');
                
                const files = Object.values(data.files || {{}});
                fileCount.textContent = files.length;
                
                if (files.length === 0) {{
                    fileList.innerHTML = '<div class="empty-state">No files shared yet</div>';
                    return;
                }}
                
                fileList.innerHTML = files.map(file => `
                    <div class="file-item">
                        <div class="file-info">
                            <div class="file-name">${{escapeHtml(file.original_filename)}}</div>
                            <div class="file-meta">${{formatBytes(file.size)}} | Uploaded ${{formatTime(file.upload_timestamp)}}</div>
                        </div>
                        <div class="file-actions">
                            <button class="download-btn" onclick="downloadFile('${{file.file_id}}')">Download</button>
                            <button class="delete-btn" onclick="deleteFile('${{file.file_id}}')">Delete</button>
                        </div>
                    </div>
                `).join('');
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
                
                messageCount.textContent = data.messages.length;
                
                if (data.messages.length === 0) {{
                    messagesContainer.innerHTML = '<div class="empty-state">No messages yet. Send a message below.</div>';
                    return;
                }}
                
                messagesContainer.innerHTML = data.messages.map(msg => `
                    <div class="message">
                        <div class="message-header">
                            <span>From: ${{escapeHtml(msg.client_ip)}}</span>
                            <button class="copy-btn" onclick="copyToClipboard('${{escapeHtml(msg.content).replace(/'/g, "\\'")}}')">Copy</button>
                        </div>
                        <div class="message-content">${{escapeHtml(msg.content)}}</div>
                        <div class="message-header" style="margin-top: 4px;">
                            <span>${{formatTime(msg.timestamp)}}</span>
                        </div>
                    </div>
                `).join('');
                
                messagesContainer.scrollTop = messagesContainer.scrollHeight;
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
            try {{
                const response = await fetch(`/api/session/${{sessionId}}/message`, {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{content: content, client_id: clientId}})
                }});
                
                if (response.ok) {{
                    document.getElementById('messageInput').value = '';
                    await loadMessages();
                }}
            }} catch (error) {{
                console.error('Error sending message:', error);
            }}
        }}
        
        async function uploadFiles(files) {{
            const progress = document.getElementById('progress');
            const progressBar = document.getElementById('progressBar');
            
            for (const file of files) {{
                const formData = new FormData();
                formData.append('file', file);
                
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
            await loadFiles();
        }}
        
        async function downloadFile(fileId) {{
            window.open(`/api/session/${{sessionId}}/download/${{fileId}}`, '_blank');
        }}
        
        async function deleteFile(fileId) {{
            if (confirm('Delete this file?')) {{
                const response = await fetch(`/api/session/${{sessionId}}/file/${{fileId}}`, {{method: 'DELETE'}});
                if (response.ok) {{
                    await loadFiles();
                }}
            }}
        }}
        
        function copyToClipboard(text) {{
            navigator.clipboard.writeText(text).then(() => {{
                alert('Message copied to clipboard');
            }});
        }}
        
        function refreshAll() {{
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
        setInterval(refreshAll, 3000);
    </script>
</body>
</html>"""


# ============================================================================
# API ROUTES
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def home():
    """Home page"""
    return HOME_PAGE


@app.get("/session/{session_id}", response_class=HTMLResponse)
async def session_page(session_id: str, request: Request):
    """Session page"""
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
    
    # Register client
    client_id = f"client_{uuid.uuid4().hex[:8]}"
    client_ip = request.client.host if request.client else "unknown"
    await session.add_client(client_id, client_ip)
    
    return SESSION_PAGE_TEMPLATE.format(session_id=session_id)


@app.post("/api/session/create")
async def create_session(timeout_minutes: int = 60, request: Request = None):
    """Create a new session"""
    client_ip = request.client.host if request else "unknown"
    session = await session_manager.create_session(client_ip, timeout_minutes)
    
    base_url = str(request.base_url).rstrip('/')
    join_url = f"{base_url}/session/{session.session_id}"
    qr_code = generate_qr_code_base64(join_url)
    
    return {
        "session_id": session.session_id,
        "join_url": join_url,
        "qr_code": qr_code,
        "timeout_minutes": timeout_minutes
    }


@app.post("/api/session/{session_id}/upload")
async def upload_file(session_id: str, file: UploadFile = File(...)):
    """Upload a file to a session"""
    session = await session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    
    # Generate unique file ID and safe filename
    file_id = str(uuid.uuid4())[:12]
    safe_filename = f"{file_id}_{file.filename.replace('/', '_').replace('\\', '_')}"
    file_path = session.storage_path / safe_filename
    
    # Save file with streaming
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)
    
    # Add metadata
    metadata = await session.add_file(
        file_id=file_id,
        filename=safe_filename,
        original_filename=file.filename,
        size=len(content),
        storage_path=file_path
    )
    
    return {"message": "File uploaded successfully", "file_id": file_id, "metadata": metadata.to_dict()}


@app.get("/api/session/{session_id}/files")
async def list_files(session_id: str):
    """List all files in a session"""
    session = await session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    
    files = await session.get_files_list()
    return {"session_id": session_id, "files": files, "file_count": len(files)}


@app.get("/api/session/{session_id}/download/{file_id}")
async def download_file(session_id: str, file_id: str):
    """Download a file by its ID"""
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
async def delete_file(session_id: str, file_id: str):
    """Delete a file from a session"""
    session = await session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    
    if await session.remove_file(file_id):
        return {"message": "File deleted successfully"}
    else:
        raise HTTPException(status_code=404, detail="File not found")


@app.post("/api/session/{session_id}/message")
async def send_message(session_id: str, request: Request):
    """Send a text message to a session"""
    session = await session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    
    data = await request.json()
    content = data.get("content", "").strip()
    
    if not content:
        raise HTTPException(status_code=400, detail="Message content cannot be empty")
    
    if len(content) > 5000:
        raise HTTPException(status_code=400, detail="Message too long (max 5000 characters)")
    
    client_ip = request.client.host if request.client else "unknown"
    message = await session.add_message(content, client_ip)
    
    return {"message": "Message sent", "message_id": message.message_id}


@app.get("/api/session/{session_id}/messages")
async def get_messages(session_id: str, limit: int = 100):
    """Get messages from a session"""
    session = await session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    
    messages = await session.get_messages(limit)
    return {
        "session_id": session_id,
        "messages": [msg.to_dict() for msg in messages],
        "count": len(messages)
    }


@app.delete("/api/session/{session_id}")
async def delete_session(session_id: str):
    """Delete an entire session"""
    if await session_manager.destroy_session(session_id):
        return {"message": "Session deleted successfully"}
    else:
        raise HTTPException(status_code=404, detail="Session not found")


@app.get("/api/session/{session_id}/info")
async def session_info(session_id: str):
    """Get session information"""
    session = await session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    
    info = session.to_summary()
    info["clients"] = await session.get_clients_list()
    return info


@app.get("/api/sessions")
async def list_sessions():
    """List all active sessions (admin)"""
    sessions = await session_manager.get_all_sessions_summary()
    return {"sessions": sessions, "count": len(sessions)}


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    print("""
    ================================================================
    LAN Collaboration System - Offline Session-Based Communication
    ================================================================
    
    Features:
    - File sharing with unique file IDs
    - Text messaging with copy functionality
    - Session-based temporary rooms
    - Automatic cleanup after timeout
    - No external dependencies or CDNs
    
    Server running on: http://0.0.0.0:8000
    Access from any device on your local network
    
    Press Ctrl+C to stop the server
    ================================================================
    """)
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
