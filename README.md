# Nexora — Remote Laptop Control Server

Cloud backend for **Nexora**, an AI-powered remote laptop monitoring and control system.

Nexora connects an Android application to a Windows laptop through a cloud-based FastAPI server and WebSocket communication.

## Overview

Nexora allows a user to remotely monitor and control their Windows laptop from an Android application.

### Features

- Real-time laptop online/offline status
- Battery and charging information
- Battery time estimation
- CPU and RAM monitoring
- Remote laptop commands
- AI-powered laptop assistant
- Secure token-based authentication
- WebSocket communication
- Cloud deployment support

## Architecture
```text
Android App
     |
     | HTTPS
     v
FastAPI Cloud Server
     |
     +--------------> Gemini AI
     |
     | WebSocket
     v
Windows Laptop Agent
```

### Request Flow

```text
User
 |
 v
Nexora Android App
 |
 | HTTPS / REST API
 v
FastAPI Server
 |
 +-- Authentication
 +-- Laptop Monitoring
 +-- AI Processing
 +-- Command Validation
 |
 | WebSocket
 v
Windows Agent
 |
 v
Laptop
```

## Features in Detail

### Laptop Monitoring

The server receives real-time information from the Windows agent, including:

- Online/offline status
- Battery percentage
- Charging status
- Estimated battery time
- CPU usage
- RAM usage
- Hostname
- Windows version

### Remote Control

The server supports validated commands such as:

- Lock laptop
- Sleep
- Restart
- Shutdown
- Open Chrome
- Open Notepad
- Open Calculator
- Open YouTube
- Open Google
- Open Downloads
- Open Documents
- Take screenshot
- Volume up
- Volume down
- Mute
- Play/pause media

Commands are restricted using an allowlist before being sent to the laptop.

### AI Assistant

Nexora integrates Google's Gemini API to understand natural-language requests.

Example requests:

```text
Open Chrome
Lock my laptop
What's my battery level?
How much RAM am I using?
Take a screenshot
```

The AI converts supported requests into structured commands that the server validates before execution.

Restart and shutdown requests require confirmation.

## Technology Stack

### Backend

- Python
- FastAPI
- Uvicorn
- WebSockets

### AI

- Google Gemini API

### Client

- Android
- Kotlin
- Jetpack Compose

### Communication

- REST API
- WebSocket

### Deployment

- Render

## Project Structure

```text

Nexora-control-with-ai-bot/
├── .github/
│   └── workflows/
│       └── tests.yml
├── docs/
│   └── architecture.md
├── laptop_agent/
│   ├── agent.py
│   └── requirements.txt
├── tests/
│   └── test_server.py
├── .env.example
├── .gitignore
├── README.md
├── requirements.txt
└── server.py

```

## Environment Variables

The server uses environment variables for sensitive credentials.

Create a `.env` file based on `.env.example`:

```env
REMOTE_TOKEN=your_secure_token
GEMINI_API_KEY=your_gemini_api_key
```

Never commit real credentials to GitHub.

The `.env.example` file contains placeholders only.

## Running Locally

### 1. Clone the repository

```bash
git clone https://github.com/Gowthamkumar09/Nexora-control-with-ai-bot.git
cd Nexora-control-with-ai-bot
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

Set:

```text
REMOTE_TOKEN
GEMINI_API_KEY
```

### 4. Start the server

```bash
uvicorn server:app --host 0.0.0.0 --port 8000
```

The server will be available at:

```text
http://localhost:8000
```

## API

### Server Status

```http
GET /
```

### Laptop Information

```http
GET /laptops
```

### Send Laptop Command

```http
POST /command/{laptop_id}
```

### AI Assistant

```http
POST /ai/chat
```

### Laptop WebSocket

```text
/ws/laptop/{laptop_id}
```

## Security

Nexora uses several security mechanisms:

- Bearer-token authentication
- Environment-based secrets
- Command allowlisting
- Heartbeat-based laptop availability
- Confirmation for restart/shutdown
- WebSocket communication between the server and laptop agent

Sensitive credentials should never be stored directly in source code.

## AI Command Safety

The AI does not directly execute arbitrary operating-system commands.

Instead:

```text
Natural Language
       |
       v
     Gemini
       |
       v
Structured Command
       |
       v
Allowed Command Check
       |
       v
   WebSocket
       |
       v
 Windows Agent
```

Only commands defined by the server's allowlist can be executed.

## Monitoring

The server maintains the latest laptop telemetry received through WebSocket heartbeats.

The monitored information includes:

- Connection status
- Battery level
- Charging state
- Battery time estimate
- CPU usage
- RAM usage
- Hostname
- Windows version

A laptop is considered offline when heartbeat communication exceeds the configured timeout.

## Cloud Deployment

The backend can be deployed as a cloud service.

The current architecture uses:

```text
Android App
     |
     v
Render
     |
     +-- FastAPI
     +-- WebSocket
     +-- Gemini API
     |
     v
Windows Laptop
```

Sensitive environment variables should be configured through the hosting provider rather than committed to the repository.

## Future Improvements

Planned improvements include:

- Multiple laptop support
- Improved authentication
- Command history
- Audit logging
- Push notifications
- Device management
- Better AI command confirmation
- Role-based access
- Improved monitoring dashboard

**Nexora** is a personal project exploring AI-powered remote device management, cloud communication, intelligent automation, and AI-assisted system control.


## Windows Laptop Agent Setup

The Windows agent connects your laptop to the Nexora cloud backend using
a secure WebSocket connection. Keep the agent running while you want the
laptop to be available for monitoring and remote commands.

### Requirements

- Windows laptop
- Python installed
- Internet connection
- Access to the Nexora Render backend
- The same `REMOTE_TOKEN` configured in Render

### 1. Open the project directory

Open PowerShell and navigate to the cloned repository:

```powershell
cd "$HOME\Documents\Nexora-GitHub"
```

Adjust the path if your repository is stored elsewhere.

### 2. Create and activate a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, you can install dependencies using
the virtual environment's Python executable directly:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
```

### 3. Install the agent dependencies

```powershell
python -m pip install -r .\laptop_agent\requirements.txt
```

### 4. Configure the authentication token

The agent reads its token from:

```text
%USERPROFILE%\.nexora\remote_token.txt
```

Create the directory if it does not exist:

```powershell
New-Item -ItemType Directory -Force "$HOME\.nexora"
```

Create `remote_token.txt` using a trusted local editor and enter the
same token configured as `REMOTE_TOKEN` in the Render environment.

Do not paste the token into source code, commit it to Git, or publish
it in screenshots, logs, or documentation. The token file should remain
excluded from version control.

### 5. Start the Windows agent

From the repository root, run:

```powershell
python .\laptop_agent\agent.py
```

Keep the terminal open while the agent is running.

### Troubleshooting

- **HTTP 403 during WebSocket connection:** Verify that the local token
  matches the `REMOTE_TOKEN` configured in Render. Check the Render logs
  for additional details.
- **Missing dependency:** Activate the virtual environment and reinstall
  `laptop_agent/requirements.txt`.
- **Laptop appears offline:** Check the internet connection and confirm
  that the agent is running and can reach the Render service.

Never share your authentication token when requesting troubleshooting
help.

## Screenshots

### Android Dashboard


