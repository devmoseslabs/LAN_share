# LAN Share System

A lightweight LAN-based file and text sharing system that works entirely offline between devices on the same network.

No accounts. No cloud. No external services.

---

## Overview

This application allows one device to host a temporary session where multiple devices can connect through a local network URL or QR code.

Inside a session, users can:
- Upload and download files
- Send and receive text messages
- Share data instantly across devices

All session data is temporary and is deleted automatically when the session ends.

---

## Features

### File Sharing
- Upload files to a shared session
- Download files from any connected device
- Unique file IDs to prevent conflicts
- Session-based isolated storage

### Text Sharing
- Send messages in real time within a session
- Copy messages with one click
- Lightweight chat-like communication layer

### Session System
- Unique session ID generation
- QR code session sharing
- Multi-device support over LAN
- Automatic session cleanup after timeout or shutdown

### Privacy
- No authentication required
- No database storage
- No persistent data after session ends

---

## How It Works

1. Start the server on a host device
2. Create a session
3. Share the generated link or QR code
4. Other devices join the session via browser
5. Share files or text instantly
6. End session → all data is permanently deleted

---

## Installation

```bash
git clone https://github.com/devmoseslabs/LAN_share.git
cd LAN_share

Install dependencies:

pip install fastapi uvicorn python-multipart qrcode
Running the Server
python main.py

or

uvicorn main:app --host 0.0.0.0 --port 8000
Access

Open in browser:

http://<local-ip>:8000

Example:

http://10.42.0.1:8000
Project Structure
main.py              Core FastAPI application
Session Manager      Handles sessions and lifecycle
File System          Temporary file storage per session
Message System       In-memory text message handling
QR Generator         Session sharing via QR code
Design Principles
Offline first (LAN only)
Ephemeral sessions (nothing persists)
No external dependencies
Fast local communication
Minimal system overhead
Security Model

This system is designed for trusted local networks only.

No encryption layer by default
No authentication system
Not intended for public internet exposure
Future Improvements
WebSocket real-time updates
Device auto-discovery
End-to-end encryption per session
Mobile PWA interface
Persistent optional mode (toggle storage)
License

MIT 
