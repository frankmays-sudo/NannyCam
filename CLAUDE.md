# NannyCam

Raspberry Pi Zero 2 W nanny cam. Records on motion, stores footage in a circular overwrite ring on a 128GB SD card.

## Hardware

- **Compute:** Raspberry Pi Zero 2 W (quad-core Cortex-A53 @ 1GHz, 512MB RAM)
- **Camera:** Pi Camera Module 3 NoIR Wide
- **Motion:** HC-SR501 PIR sensor — primary trigger; software frame-diff is the validation layer
- **Power:** PiSugar 3 Plus 5000mAh
- **Storage:** Samsung PRO Endurance 128GB microSD

## Stack

Python 3 + `picamera2` + `RPi.GPIO` + `ffmpeg` + `Flask` (footage GUI). Keep processing lightweight — the Zero 2 W cannot handle heavy CV workloads.

## Project Layout

```
src/
  motion/      # PIR GPIO handling + software frame-diff validation
  recording/   # rpicam-vid / ffmpeg pipeline, segmented H.264
  storage/     # circular overwrite daemon, quota enforcement
  webui/       # Flask GUI to browse/download/delete footage (separate systemd service)
config/        # runtime config (thresholds, paths, quota)
deploy/        # systemd units + USB gadget networking setup (deploy/README.md)
tests/
```

## Key Constraints

- Footage segments: 60s H.264 chunks via `rpicam-vid --codec h264 --segment 60`
- Storage quota: ~100GB reserved for footage on 128GB card
- Oldest segment deleted when quota exceeded — no custom filesystem needed
- Software motion at 640x480 max to stay within CPU budget
