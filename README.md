# Strat Trade

Pocket Option API backend for trading and strategies. Built with FastAPI and [BinaryOptionsTools-v2](https://github.com/ChipaDevTeam/BinaryOptionsTools-v2).

---

## How to run the project (step by step)

### 1. Prerequisites

- Python 3.9+
- Git (optional, for cloning)

### 2. Open the project and create a virtual environment

```bash
cd /path/to/strat_trade

python3 -m venv .venv
source .venv/bin/activate
```

On Windows:

```bash
.venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -e ".[dev]"
```

Optional: install the latest BinaryOptionsTools-v2 from source:

```bash
pip install "git+https://github.com/ChipaDevTeam/BinaryOptionsTools-v2.git#subdirectory=BinaryOptionsToolsV2"
pip install -e ".[dev]"
```

### 4. Get Pocket Option SSID

The app needs the **full Socket.IO auth message** (with the `"session"` field, not only `sessionToken`).

**To use a demo account:** log into Pocket Option in **demo / practice** mode (switch to demo on the site), then get the SSID as below. The copied message will contain `"isDemo":1` and the server will use the demo balance and demo trading.

1. Open [Pocket Option](https://pocketoption.com) in the browser and log in (real or **demo**).
2. Press **F12** → **Network** → filter **WS** (WebSocket).
3. Select the Socket.IO connection to the Pocket Option domain.
4. Open the **Messages** tab.
5. Find the message that **starts with** `42["auth",` and contains a long `"session"` string (PHP-style serialized data).
6. Copy the **entire** message (from `42["auth",` to the closing `}]`).

Example shape (your actual string will be longer; `"isDemo":1` = demo account, `"isDemo":0` = real):

```
42["auth",{"session":"a:4:{s:10:\"session_id\";s:32:\"...\";...}...","isDemo":1,"uid":...,"platform":1,"isFastHistory":true,"isOptimized":true}]
```

### 5. Set the SSID (choose one option)

**Option A — Environment variable (recommended for terminal)**

Run the server with SSID in the same command (use **single quotes** around the value):

```bash
POCKETOPTION_SSID='42["auth",{"session":"a:4:{s:10:\"session_id\";...}...","isDemo":0,"uid":108414689,...}]' \
python3 -m uvicorn strat_trade.main:app --reload --host 127.0.0.1 --port 8000
```

**Option B — File (e.g. for VS Code tasks)**

1. Create a file `.ssid` in the project root.
2. Paste the **full** auth message into it as **one line** (no extra quotes, no newlines in the middle).
3. Save the file.
4. In `.env` set: `POCKETOPTION_SSID_FILE=.ssid`
5. Run the server (see step 6). The app will read SSID from `.ssid`.

**Important:** `.ssid` and `.env` are in `.gitignore` — do not commit them.

### 6. Run the API server

Use the same run commands whether you use a **demo** or real account — the account type is determined by the SSID you set in step 5 (demo SSID has `"isDemo":1`).

**From terminal:**

```bash
# If using Option A, the variable is already in the command above.
# If using Option B (file), run:
python3 -m uvicorn strat_trade.main:app --reload --host 127.0.0.1 --port 8000
```

**From VS Code:**

- **Run with debug (F5):** Run and Debug → choose **"Strat Trade: Run API (debug)"**.
- **Run without debug:** Terminal → Run Task… → **"Strat Trade: Start API server"** (or `Ctrl+Shift+B` / `Cmd+Shift+B`).

Ensure the Python interpreter is set to the project venv (`.venv`): Command Palette → **Python: Select Interpreter** → pick the one from `.venv`.

### 7. Check that it works

1. In the terminal you should see: `Pocket Option gateway ready` (and no `Failed to parse ssid`).
2. Open in the browser: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) (Swagger UI).
3. Try **GET /api/balance** → Execute. You should get your account balance.

### 8. Useful VS Code tasks

- **Kill port 8000:** Terminal → Run Task… → **"Strat Trade: Kill port 8000"**.
- **Restart API:** Terminal → Run Task… → **"Strat Trade: Restart API (kill + start)"**.

---

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/balance` | Current account balance |
| GET | `/api/candles` | OHLC candles. Query: `asset`, `period`, `limit` (e.g. `?asset=EURUSD_otc&period=60&limit=10`) |

Full docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## Tests

```bash
pytest
```

---

## Troubleshooting

- **503 / "Trading gateway not available"** — SSID not set or invalid. Check step 4 and 5; use the **full** auth message with `"session"`.
- **"Failed to parse ssid: Error parsing session data"** — The library expects the long format with `"session"` (PHP serialized). Copy the message from the **Messages** tab again; avoid the short `sessionToken`-only format.
- **`uvicorn: command not found`** — Activate the venv (step 2) and reinstall (step 3), or run: `python3 -m uvicorn strat_trade.main:app --reload --host 127.0.0.1 --port 8000`.
