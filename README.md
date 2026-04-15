📁 LAN Temporary File & Text Sharing System

A lightweight offline LAN-based sharing system that allows devices to share files and text messages instantly within a temporary session.
No accounts. No cloud. No internet dependency.

🚀 Features
📂 File Sharing
Upload and download files instantly
Unique file IDs (no collisions)
Session-isolated storage
Automatic cleanup after session ends
📝 Text Sharing
Send text messages inside a session
Instant visibility across connected devices
One-click copy to clipboard
Temporary storage (deleted after session ends)
🔗 Session System
Create temporary sessions with unique IDs
Join via URL or QR code
Multiple devices supported (LAN)
🔒 Privacy & Ephemeral Design
No user accounts
No database required
Everything is deleted when session ends
Fully offline capable
🏗️ Architecture
Backend: FastAPI
Server: Uvicorn
Storage: Temporary filesystem (/tmp)
State: In-memory session manager
QR Codes: Python qrcode
📡 How It Works
Start the server on one device
Create a session
Share QR code or session link
Other devices join via browser
Share files or text instantly
Close session → everything is deleted
⚙️ Installation
1. Clone repo
git clone https://github.com/your-username/lan-share.git
cd lan-share
2. Create virtual environment (optional but recommended)
python -m venv venv
source venv/bin/activate  # Linux/macOS
3. Install dependencies
pip install fastapi uvicorn python-multipart qrcode
▶️ Run the server
python main.py

or

uvicorn main:app --host 0.0.0.0 --port 8000
🌐 Access

Open in browser:

http://<your-local-ip>:8000

Example:

http://10.42.0.1:8000
📱 Creating a Session
Click Create Session
Set optional timeout
Scan QR code or share link
Start sharing files and text instantly
🧹 Session Cleanup

Sessions are automatically destroyed when:

Timeout is reached
Server is stopped
Session is manually deleted

All files and messages are permanently removed.

📦 Project Structure
.
├── main.py            # FastAPI application
├── sessions.py        # Session manager logic
├── files.py           # File handling logic
├── messages.py       # Text messaging system
├── templates/        # HTML UI (if separated)
└── /tmp/             # Temporary session storage
⚡ Key Design Principles
Offline-first (no internet dependency)
Ephemeral data (nothing is permanent)
LAN optimized
Minimal dependencies
Fast and lightweight
No authentication overhead
🧠 Why this exists

This project is built to replace:

cloud file sharing tools
slow USB transfers
paid messaging/file apps on LAN

It turns any device into a temporary collaboration node.

🔮 Future Improvements
WebSocket real-time sync
Drag-and-drop UI upgrade
Mobile PWA support
Encryption per session
Device discovery (auto LAN detection)
⚠️ Disclaimer

This tool is designed for local network use only.
Do not expose it to the public internet without adding security layers.

👨‍💻 Author

Built for fast, offline, peer-to-peer style sharing on LAN.
