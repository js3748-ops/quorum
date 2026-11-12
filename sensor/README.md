# Quorum sensor

A small person-counting client that reports room occupancy to Quorum, plus a simulator for demos and testing.
It lives outside the backend, has its own `requirements.txt`, and talks to Quorum only through
`POST /api/occupancy/readings`, using the sensor's `X-Sensor-Key`.

| File | Purpose |
|---|---|
| `quorum_sensor.py` | Camera client. Uses YOLO (Ultralytics) and OpenCV to count people, then posts the count. |
| `simulate_sensors.py` | Posts realistic fake counts for several rooms. Needs no camera and no YOLO. |
| `quorum_api.py` | Shared HTTP client, standard library only. Handles the rate limit, backoff and error messages. |
| `.env.example` | Settings for the camera client. Copy it to `.env`. |
| `simulated_sensors.example.json` | Simulator config with placeholder keys. Copy it to `simulated_sensors.json`. |

## Privacy

**Camera frames never leave the device.**

- Each frame is held in memory just long enough to count the people in it, then the next frame overwrites it.
- Frames are never written to disk, logged or uploaded.
- The only data sent to Quorum is `{"people_count": n}`. The server records the time it arrives.
- The backend rejects any extra field in a reading, so frame data can't be added by mistake.
- `--preview` draws a window on the local screen only. Nothing from it is saved or sent.
- Ultralytics usage analytics are switched off at startup (`settings.update({"sync": False})`).
- The client makes one other network call: the first run downloads the model weights file, and after that the model runs offline.
- Put cameras where people expect them, and tell people that occupancy is being counted.

## Install

You need Python 3.10 or newer. Use a separate virtual environment, so PyTorch stays out of the backend environment.

> **Download size:** installing `ultralytics` also installs **PyTorch and OpenCV, several hundred MB in total**.
> The first run downloads the YOLO nano weights as well, a few MB saved as `yolo11n.pt` in the folder you run from.
> `*.pt` files are gitignored. The simulator needs none of this. It only uses the standard library and `python-dotenv`.

```powershell
cd "C:\Users\Jahanvi Singh\Desktop\quorum"
python -m venv sensor\.venv
sensor\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r sensor\requirements.txt
```

If PowerShell refuses to run `Activate.ps1`, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.
Or skip activation and call `sensor\.venv\Scripts\python.exe` directly.

## Create a sensor key in Quorum

Quorum has no sensor screen in the frontend yet, so create sensors through the API. Start the backend first with
`python run_backend.py`, using `backend/seed.py` if the database is empty. Then run these in PowerShell:

```powershell
$base = "http://127.0.0.1:8000"
Invoke-RestMethod -Method Post -Uri "$base/api/auth/demo-login" -ContentType "application/json" -Body '{"email":"admin@quorum.local"}' -SessionVariable admin | Out-Null
(Invoke-RestMethod -Uri "$base/api/admin/resources" -WebSession $admin).resources | Select-Object id, name, type, capacity
```

Pick a resource `id` from the list, then create the sensor:

```powershell
$body = @{ resource_id = 6; name = "Quiet Room door camera"; is_simulated = $false } | ConvertTo-Json
$created = Invoke-RestMethod -Method Post -Uri "$base/api/sensors" -ContentType "application/json" -Body $body -WebSession $admin
$created.api_key
```

- `api_key` is the plain key, for example `7.Gx3…`. **It is shown only once.** Put it in `sensor/.env` as `SENSOR_KEY=`.
- If you lose it, run `Invoke-RestMethod -Method Post -Uri "$base/api/sensors/<id>/rotate-key" -WebSession $admin` to get a new one.
- For sensors used with the simulator, set `is_simulated = $true` instead.
- Any admin whose scope covers the resource can do this. Lab Coordinators can do it for labs, Facilities Officers for the other resource types, and the Campus Admin for everything.

## Run with a laptop webcam

```powershell
Copy-Item sensor\.env.example sensor\.env
notepad sensor\.env        # set SENSOR_KEY=...; leave VIDEO_SOURCE=0 for the built-in camera
python sensor\quorum_sensor.py --preview
```

You should see the model load, then lines like:

```
FPS 14.2 | detected 2 | smoothed 2
[15:04:31] [camera] sent people_count=2 (reading #41)
```

- Press `q` in the preview window, or `Ctrl+C` in the terminal, to stop.
- Leave out `--preview` to run without a window.
- Command-line options override `.env`: `--key`, `--url`, `--source`, `--interval`, `--confidence`, `--model`.
- If the camera is busy or the wrong one opens, close other camera apps or try `--source 1`.

## Use an Android phone as an IP camera

1. Install an IP-camera app such as **IP Webcam** (by Pavel Khlebovich) from the Play Store.
2. Connect the phone and the laptop to the **same Wi-Fi network**.
3. In the app, scroll down and tap **Start server**. The screen shows an address like `http://192.168.1.23:8080`.
4. Check that `http://192.168.1.23:8080` opens in the laptop's browser.
5. Run the client with the video stream URL. For IP Webcam, add `/video` to the address:

```powershell
python sensor\quorum_sensor.py --source "http://192.168.1.23:8080/video" --preview
```

Or set `VIDEO_SOURCE=http://192.168.1.23:8080/video` in `sensor/.env`. If the client shows "Cannot read from …", check:
- that the browser test works
- that the phone screen and server are still on
- that a Windows firewall or Wi-Fi client isolation isn't blocking the connection

The client retries automatically with increasing delays. If the app has a username and password, put them in the URL
(`http://user:pass@192.168.1.23:8080/video`). They are hidden in the console output.

The stream only goes from the phone to the laptop on your local network. Counting happens on the laptop, and only the count goes to Quorum.

## Run the simulator

1. Create one sensor per room with `is_simulated = $true` (see above), and note each key.
2. Copy the example config and fill in the keys:

```powershell
Copy-Item sensor\simulated_sensors.example.json sensor\simulated_sensors.json
notepad sensor\simulated_sensors.json
python sensor\simulate_sensors.py
```

Each entry is `{ "label", "sensor_key", "pattern", "expected" }`, with an optional `"capacity"`:

| pattern | behaviour |
|---|---|
| `ghost` | 0–1 people (booked, but nobody turned up) |
| `normal` | wanders gently around `expected` |
| `overcrowded` | clearly above `capacity`, or above `expected` if no capacity is given |
| `fluctuating` | rises and falls around `expected` over about 5 minutes |
| `empty` | always 0 |

Options:
- `--interval 5`: seconds between readings per sensor. The minimum is 2.2, to respect Quorum's 2-second limit.
- `--once`: send one reading per sensor and exit. The exit code is non-zero if any reading was rejected.
- `--seed 1`: repeatable counts.
- `--config path.json`: use a different config file.

The simulator can't see a sensor's `is_simulated` flag from its key. It's up to you to use simulated sensors only.

## Console messages

| Message | Meaning |
|---|---|
| `sent people_count=n (reading #id)` | Quorum accepted the reading. |
| `401 sensor key rejected` | The key is wrong, or the sensor was deleted or its key rotated. Fix `SENSOR_KEY`. The client retries every 30 s. |
| `403 Sensor is inactive.` | An admin switched the sensor off (`PATCH /api/sensors/{id}`). The client retries every 30 s. |
| `422 reading rejected as invalid` | The count was outside 0–1000. This shouldn't happen with the clients here. |
| `429 rate limited` | A reading came sooner than 2 s after the last one, often because two clients share a key. The client waits as long as `Retry-After` says. |
| `server unreachable … retrying in Ns` | The backend is down or the URL is wrong. The client retries after 2, 4, 8 … up to 60 s and never exits on network errors. |
