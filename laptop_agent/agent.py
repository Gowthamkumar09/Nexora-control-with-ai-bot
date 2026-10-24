
import asyncio
import difflib
import json
import os
import platform
import secrets
import socket
import subprocess
import time
import webbrowser
from pathlib import Path

import psutil
import pyautogui
import websockets
from websockets.exceptions import ConnectionClosed, InvalidStatus


# ============================================================
# CONFIGURATION
# ============================================================

SERVER_URL = (
    "wss://remote-control-ai-wtuf.onrender.com"
    "/ws/laptop/my-laptop"
)

LAPTOP_ID = "my-laptop"
RECONNECT_DELAY = 5
HEARTBEAT_INTERVAL = 5

TOKEN_PATH = Path.home() / ".nexora" / "remote_token.txt"

# File-search security limits
MAX_SEARCH_RESULTS = 30
MAX_FILES_SCANNED = 15000
FILE_ID_TTL_SECONDS = 300
SEARCH_EXTENSIONS = {
    ".py", ".pyw", ".txt", ".md", ".pdf", ".doc", ".docx",
    ".xls", ".xlsx", ".csv", ".json", ".xml", ".html",
    ".css", ".js", ".ts", ".tsx", ".jsx", ".kt", ".java",
    ".c", ".cpp", ".h", ".cs", ".go", ".rs", ".php",
    ".sql", ".yaml", ".yml", ".toml", ".ini", ".log",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp",
    ".mp3", ".wav", ".mp4", ".mkv", ".zip", ".7z",
    ".ppt", ".pptx", ".odt", ".ods", ".odp",
}

IGNORED_DIRS = {
    ".git", ".svn", "node_modules", "__pycache__",
    ".venv", "venv", "env", ".idea", ".gradle",
    "windows", "program files", "program files (x86)",
    "appdata", "$recycle.bin", "system volume information",
}

battery_history = []

# Opaque file IDs map to files found by this agent.
# The server should send file IDs back, not trust arbitrary paths.
file_index = {}


# ============================================================
# AUTHENTICATION
# ============================================================

def read_auth_token():
    """Read the token without displaying or logging its value."""
    try:
        token = TOKEN_PATH.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(
            f"Cannot read token file at {TOKEN_PATH}: {exc}"
        ) from exc

    if not token:
        raise RuntimeError(f"Token file is empty: {TOKEN_PATH}")

    if "\n" in token or "\r" in token:
        raise RuntimeError("Token file contains unexpected line breaks.")

    return token


# ============================================================
# APPROVED FILE LOCATIONS
# ============================================================

def approved_roots():
    """Return existing user folders in which file search is allowed."""
    home = Path.home()
    candidates = [
        home / "Desktop",
        home / "Documents",
        home / "Downloads",
        home / "Pictures",
        home / "Videos",
        home / "Music",
    ]

    # Also support a redirected Windows Documents/Desktop folder
    # if it exists under the user's profile.
    roots = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            if resolved.is_dir() and resolved not in roots:
                roots.append(resolved)
        except OSError:
            continue

    return roots


def is_within_approved_root(path):
    """Reject paths outside the approved user folders."""
    try:
        resolved = Path(path).resolve(strict=True)
        for root in approved_roots():
            try:
                resolved.relative_to(root)
                return True
            except ValueError:
                continue
    except (OSError, RuntimeError):
        return False

    return False


def cleanup_file_index():
    """Remove expired file IDs."""
    now = time.time()
    expired = [
        file_id
        for file_id, entry in file_index.items()
        if now - entry["created_at"] > FILE_ID_TTL_SECONDS
    ]
    for file_id in expired:
        file_index.pop(file_id, None)


def filename_matches(filename, query):
    """Match names exactly, by substring, or by fuzzy similarity."""
    name = filename.casefold()
    query = query.casefold().strip()

    if not query:
        return False

    if name == query or query in name:
        return True

    # Allow "python" to match "python.py", and vice versa.
    name_stem = Path(name).stem
    query_stem = Path(query).stem

    if query_stem and (
        query_stem == name_stem
        or query_stem in name_stem
        or name_stem in query_stem
    ):
        return True

    return (
        difflib.SequenceMatcher(
            None, query_stem or query, name_stem or name
        ).ratio() >= 0.68
    )


def search_user_files(query):
    """Search approved user folders and return selectable file records."""
    cleanup_file_index()

    if not isinstance(query, str):
        return []

    query = query.strip().strip('"').strip("'")
    if not query or len(query) > 200:
        return []

    # Support common natural-language requests such as "open python.py".
    for prefix in ("open ", "find ", "search for ", "search "):
        if query.casefold().startswith(prefix):
            query = query[len(prefix):].strip()
            break

    query = query.strip().strip('"').strip("'")
    if not query:
        return []

    matches = []
    scanned = 0

    for root in approved_roots():
        for current, dirs, files in os.walk(root, followlinks=False):
            # Do not traverse common system, cache, or dependency folders.
            dirs[:] = [
                dirname for dirname in dirs
                if dirname.casefold() not in IGNORED_DIRS
            ]

            for filename in files:
                scanned += 1
                if scanned > MAX_FILES_SCANNED:
                    break

                path = Path(current) / filename

                # Keep search focused on common user files.
                if path.suffix.casefold() not in SEARCH_EXTENSIONS:
                    continue

                if filename_matches(filename, query):
                    try:
                        resolved = path.resolve(strict=True)
                        if not resolved.is_file():
                            continue
                        if not is_within_approved_root(resolved):
                            continue
                    except (OSError, RuntimeError):
                        continue

                    name_lower = filename.casefold()
                    query_lower = query.casefold()
                    if name_lower == query_lower:
                        score = 1.0
                    elif query_lower in name_lower:
                        score = 0.95
                    else:
                        score = difflib.SequenceMatcher(
                            None,
                            Path(query_lower).stem,
                            Path(name_lower).stem,
                        ).ratio()

                    matches.append((score, resolved))

            if scanned > MAX_FILES_SCANNED:
                break

        if scanned > MAX_FILES_SCANNED:
            break

    matches.sort(key=lambda item: (-item[0], item[1].name.casefold()))

    results = []
    for score, path in matches[:MAX_SEARCH_RESULTS]:
        file_id = secrets.token_urlsafe(18)
        file_index[file_id] = {
            "path": str(path),
            "created_at": time.time(),
        }

        results.append({
            "file_id": file_id,
            "name": path.name,
            "path": str(path),
            "extension": path.suffix.lower(),
            "is_directory": False,
        })

    return results


def open_selected_file(file_id):
    """Open a previously indexed file without executing scripts."""
    cleanup_file_index()

    if not isinstance(file_id, str) or not file_id:
        return "Invalid file selection."

    entry = file_index.pop(file_id, None)
    if entry is None:
        return "This file selection expired or is invalid. Search again."

    path = Path(entry["path"])

    if not is_within_approved_root(path):
        return "Opening blocked: file is outside approved folders."

    try:
        path = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return "The selected file no longer exists."

    if not path.is_file():
        return "The selected item is not a file."

    try:
        if path.suffix.casefold() in {".py", ".pyw"}:
            # Never launch a Python script for execution.
            # Open its source as text in Notepad instead.
            subprocess.Popen(["notepad.exe", str(path)], shell=False)
        else:
            # Use the normal Windows file association for other file types.
            os.startfile(str(path))

        return f"Opened: {path.name}"
    except Exception as exc:
        print(f"File open error ({type(exc).__name__}): {exc}")
        return "Could not open the selected file."


# ============================================================
# BATTERY ESTIMATION
# ============================================================

def get_battery_time_estimate(battery):
    """Estimate minutes remaining or until fully charged."""
    global battery_history

    if battery is None:
        battery_history.clear()
        return None

    now = time.time()
    battery_history.append((now, battery.percent))
    cutoff = now - 600
    battery_history = [
        reading for reading in battery_history if reading[0] >= cutoff
    ]

    if len(battery_history) < 2:
        return None

    old_time, old_percent = battery_history[0]
    elapsed_hours = (now - old_time) / 3600
    if elapsed_hours <= 0:
        return None

    percent_per_hour = (battery.percent - old_percent) / elapsed_hours

    if battery.power_plugged:
        if percent_per_hour <= 0:
            return None
        hours_remaining = (100 - battery.percent) / percent_per_hour
    else:
        if percent_per_hour >= 0:
            return None
        discharge_rate = abs(percent_per_hour)
        if discharge_rate <= 0:
            return None
        hours_remaining = battery.percent / discharge_rate

    minutes = int(hours_remaining * 60)
    if not 0 <= minutes <= 24 * 60:
        return None

    return minutes


# ============================================================
# LAPTOP INFORMATION
# ============================================================

def get_laptop_info():
    battery = psutil.sensors_battery()
    return {
        "battery": battery.percent if battery else None,
        "charging": battery.power_plugged if battery else None,
        "battery_time_minutes": get_battery_time_estimate(battery),
        "cpu_usage": psutil.cpu_percent(interval=0.5),
        "ram_usage": psutil.virtual_memory().percent,
        "hostname": socket.gethostname(),
        "windows_version": platform.platform(),
    }


def format_minutes(minutes):
    if minutes is None:
        return "Calculating..."
    hours, remaining_minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {remaining_minutes}m"
    return f"{remaining_minutes}m"


# ============================================================
# COMMAND EXECUTION
# ============================================================

async def execute_command(command):
    print(f"Executing command: {command}")

    try:
        if command == "lock":
            subprocess.run(
                ["rundll32.exe", "user32.dll,LockWorkStation"],
                check=False,
            )
            return "Laptop lock requested."

        elif command == "sleep":
            subprocess.run(
                ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
                check=False,
            )
            return "Sleep requested."

        elif command == "restart":
            subprocess.run(["shutdown", "/r", "/t", "10"], check=False)
            return "Laptop will restart in 10 seconds."

        elif command == "shutdown":
            subprocess.run(["shutdown", "/s", "/t", "10"], check=False)
            return "Laptop will shut down in 10 seconds."

        elif command == "open_chrome":
            chrome_path = (
                Path(os.environ["LOCALAPPDATA"])
                / "Google"
                / "Chrome"
                / "Application"
                / "chrome.exe"
            )

            if not chrome_path.is_file():
                return "Chrome executable was not found."

            subprocess.Popen([str(chrome_path)])
            return "Chrome launch requested."

        elif command == "open_notepad":
            subprocess.Popen(["notepad.exe"])
            return "Notepad opened."

        elif command == "open_calculator":
            subprocess.Popen(["calc.exe"])
            return "Calculator opened."

        elif command == "open_youtube":
            webbrowser.open("https://www.youtube.com")
            return "YouTube opened."

        elif command == "open_google":
            webbrowser.open("https://www.google.com")
            return "Google opened."

        elif command == "open_downloads":
            folder = Path.home() / "Downloads"
            if not folder.is_dir():
                return "Downloads folder was not found."
            os.startfile(str(folder))
            return "Downloads folder opened."

        elif command == "open_documents":
            folder = Path.home() / "Documents"
            if not folder.is_dir():
                return "Documents folder was not found."
            os.startfile(str(folder))
            return "Documents folder opened."

        elif command == "take_screenshot":
            pictures = Path.home() / "Pictures"
            pictures.mkdir(parents=True, exist_ok=True)
            screenshot_path = pictures / "remote_screenshot.png"
            screenshot = pyautogui.screenshot()
            screenshot.save(str(screenshot_path))
            return f"Screenshot saved to {screenshot_path}"

        elif command == "volume_up":
            for _ in range(5):
                pyautogui.press("volumeup")
            return "Volume increased."

        elif command == "volume_down":
            for _ in range(5):
                pyautogui.press("volumedown")
            return "Volume decreased."

        elif command == "mute":
            pyautogui.press("volumemute")
            return "Volume muted."

        elif command == "play_pause":
            pyautogui.press("playpause")
            return "Media playback toggled."

        elif command == "get_status":
            info = get_laptop_info()
            return (
                f"Battery: {info['battery']}%. "
                f"Charging: {info['charging']}. "
                f"Battery time: "
                f"{format_minutes(info['battery_time_minutes'])}. "
                f"CPU: {info['cpu_usage']}%. "
                f"RAM: {info['ram_usage']}%."
            )

        elif command == "close_chrome":
            subprocess.run(
                ["taskkill", "/IM", "chrome.exe", "/T"],
                check=False,
                capture_output=True,
            )
            return "Chrome close requested."

        elif command == "close_notepad":
            subprocess.run(
                ["taskkill", "/IM", "notepad.exe", "/T"],
                check=False,
                capture_output=True,
            )
            return "Notepad close requested."

        elif command == "close_calculator":
            subprocess.run(
                ["taskkill", "/IM", "CalculatorApp.exe", "/T"],
                check=False,
                capture_output=True,
            )
            return "Calculator close requested."

        elif command == "minimize_window":
            pyautogui.hotkey("win", "down")
            return "Minimize requested."

        elif command == "maximize_window":
            pyautogui.hotkey("win", "up")
            return "Maximize requested."

        elif command == "restore_window":
            pyautogui.hotkey("win", "shift", "down")
            return "Restore requested."

        elif command == "switch_window":
            pyautogui.hotkey("alt", "tab")
            return "Window switch requested."

        elif command == "show_desktop":
            pyautogui.hotkey("win", "d")
            return "Show desktop requested."

        else:
            return f"Unknown command: {command}"

    except Exception as exc:
        print(f"Command execution error ({type(exc).__name__}): {exc}")
        return f"Command failed: {exc}"


# ============================================================
# HEARTBEATS
# ============================================================

async def send_heartbeats(websocket):
    while True:
        info = get_laptop_info()
        payload = {"type": "heartbeat", **info}
        await websocket.send(json.dumps(payload))

        print(
            "Heartbeat sent | "
            f"Battery: {info['battery']}% | "
            f"Charging: {info['charging']} | "
            f"Battery time: "
            f"{format_minutes(info['battery_time_minutes'])} | "
            f"CPU: {info['cpu_usage']}% | "
            f"RAM: {info['ram_usage']}%"
        )

        await asyncio.sleep(HEARTBEAT_INTERVAL)


# ============================================================
# RECEIVE REMOTE COMMANDS AND FILE REQUESTS
# ============================================================

async def receive_commands(websocket):
    async for message in websocket:
        try:
            data = json.loads(message)
            message_type = data.get("type")

            if message_type == "file_search":
                request_id = data.get("request_id")
                query = data.get("query")

                if not isinstance(request_id, str) or not isinstance(query, str):
                    print("Ignored invalid file-search request.")
                    continue

                # Run filesystem scanning outside the event loop.
                results = await asyncio.to_thread(search_user_files, query)

                await websocket.send(json.dumps({
                    "type": "file_search_result",
                    "request_id": request_id,
                    "results": results,
                }))

                print(f"File search completed: {len(results)} result(s).")
                continue

            if message_type == "file_open":
                request_id = data.get("request_id")
                file_id = data.get("file_id")

                if not isinstance(request_id, str) or not isinstance(file_id, str):
                    print("Ignored invalid file-open request.")
                    continue

                result = await asyncio.to_thread(open_selected_file, file_id)

                await websocket.send(json.dumps({
                    "type": "file_open_result",
                    "request_id": request_id,
                    "result": result,
                }))

                print(f"File open result: {result}")
                continue

            if message_type != "command":
                continue

            command = data.get("command")
            if not isinstance(command, str) or not command:
                print("Ignored invalid command message.")
                continue

            result = await execute_command(command)

            await websocket.send(json.dumps({
                "type": "command_result",
                "command": command,
                "result": result,
            }))

            print(f"Command result: {result}")

        except json.JSONDecodeError:
            print("Received invalid JSON from server.")

        except ConnectionClosed:
            raise

        except Exception as exc:
            print(
                f"Command receiving error "
                f"({type(exc).__name__}): {exc}"
            )


# ============================================================
# CONNECT TO SERVER
# ============================================================

async def connect_to_server():
    print(f"Connecting laptop ID: {LAPTOP_ID}")
    print(f"Server endpoint: {SERVER_URL}")

    token = read_auth_token()

    try:
        async with websockets.connect(
            SERVER_URL,
            additional_headers={"Authorization": f"Bearer {token}"},
            ping_interval=20,
            ping_timeout=20,
            open_timeout=30,
        ) as websocket:
            print("Connected to server successfully.")
            del token

            await asyncio.gather(
                send_heartbeats(websocket),
                receive_commands(websocket),
            )

    except InvalidStatus as exc:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)

        if status_code == 403:
            raise RuntimeError(
                "Server rejected the WebSocket handshake (403). "
                "Check that the token file contains exactly the "
                "same token as Render's REMOTE_TOKEN, with no "
                "extra spaces or quotation marks."
            ) from exc

        if status_code is not None:
            raise RuntimeError(
                f"WebSocket handshake rejected: HTTP {status_code}."
            ) from exc

        raise RuntimeError(
            "WebSocket handshake was rejected. Check the Render logs."
        ) from exc


# ============================================================
# RECONNECT LOOP
# ============================================================

async def main():
    print("Remote Control AI Windows Agent")
    print(f"Laptop ID: {LAPTOP_ID}")
    print(f"Token file: {TOKEN_PATH}")
    print("Token value will never be printed.")

    while True:
        try:
            await connect_to_server()

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            print(
                f"Connection failed ({type(exc).__name__}): {exc}"
            )
            print(f"Retrying in {RECONNECT_DELAY} seconds...")
            await asyncio.sleep(RECONNECT_DELAY)


# ============================================================
# START AGENT
# ============================================================

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nRemote Control AI agent stopped.")
