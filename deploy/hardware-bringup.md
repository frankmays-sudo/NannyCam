# Hardware bring-up

Steps to go from a bare Raspberry Pi Zero 2 W + parts to a running
`nannycam.service`. Written up from the original bring-up session — useful
for a re-flash or a second unit. For the *later* USB-gadget-link + GUI setup
(a separate track, done after this), see `deploy/README.md`.

## Parts

- Raspberry Pi Zero 2 W
- Pi Camera Module 3 NoIR Wide
- HC-SR501 PIR sensor
- PiSugar 3 Plus (5000mAh)
- Samsung PRO Endurance 128GB microSD

## 1. Wiring

- **HC-SR501 PIR**: `VCC` → 5V, `OUT` → GPIO17 (BCM numbering, physical pin
  11), `GND` → GND. Set the sensitivity/delay jumper to **H** (repeat
  trigger mode — `motion.cooldown_seconds` in `config/settings.yaml`
  governs the actual recording cutoff, not the sensor's own delay pot).
  The sensor needs **~60s warm-up** after power-on before it stops
  false-triggering — don't judge it as faulty during that window.
- **PiSugar 3 Plus**: stacks on the GPIO header as a HAT; battery connects
  to the PiSugar's own JST port.
- **Camera Module 3 NoIR Wide**: connects via the CSI ribbon cable to the
  Pi Zero 2 W's camera port.

## 2. Flash and first boot

1. Flash **Raspberry Pi OS Lite** (64-bit) to the microSD using Raspberry
   Pi Imager. In the Imager's advanced options, set hostname, enable SSH
   with your public key, and configure WiFi — this avoids needing a
   monitor/keyboard at all. (This build used hostname `pizero01`, user
   `spacecamel` — adjust as you like for a different unit.)
2. Boot the Pi, then SSH in: `ssh <user>@<hostname>`.
3. A fresh Lite image ships with **neither `git` nor `pip`**:
   ```sh
   sudo apt update
   sudo apt install -y git python3-pip
   ```
4. Enable I2C (needed for PiSugar communication):
   ```sh
   sudo raspi-config
   # Interface Options -> I2C -> Enable
   ```
   The camera does **not** need manual enabling on recent Raspberry Pi
   OS — it's auto-detected via device tree.

## 3. Verify the camera and PIR

```sh
rpicam-hello --list-cameras   # should show imx708_noir for the NoIR Wide
```
```sh
watch -n 0.5 pinctrl get 17   # toggle something in front of the PIR, watch lo/hi flip
```
A single one-shot `pinctrl get 17` easily misses the pulse — use `watch`.

**Naming note**: recent Raspberry Pi OS renamed `libcamera-vid`/
`libcamera-hello` → `rpicam-vid`/`rpicam-hello`, and `raspi-gpio` →
`pinctrl`. If you're following an older guide that references the old
names, substitute the new ones.

## 4. Install PiSugar software

```sh
curl -o pisugar-install.sh https://cdn.pisugar.com/release/pisugar-power-manager.sh
sudo bash pisugar-install.sh
```
**Don't pipe directly to `sudo bash`** (`curl ... | sudo bash`) — the
script has an interactive model-selection menu, and piping consumes
stdin so the menu can't read your input. Download first, then run it as
a separate step. When prompted, select **PiSugar 3** (covers both plain
PiSugar 3 and PiSugar 3 Plus — the installer's model list doesn't
distinguish them).

Once installed, open the PiSugar web UI (`http://<pi-ip>:8421`) and set
the low-battery auto-shutdown threshold (this build uses **≤10%**).

## 5. Deploy the application

```sh
git clone https://github.com/frankmays-sudo/NannyCam.git ~/NannyCam
cd ~/NannyCam
pip install -r requirements.txt --break-system-packages
```
`--break-system-packages` is required on this Debian release (PEP 668's
externally-managed-environment guard) — without it, `pip install` refuses
to touch system Python at all.

```sh
sudo cp deploy/nannycam.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nannycam.service
sudo systemctl status nannycam   # confirm active (running)
```
The unit file's `User=`/`WorkingDirectory=` must match the real account —
this build uses `spacecamel`/`/home/spacecamel/NannyCam`; edit
`deploy/nannycam.service` first if yours differs.

## 6. Verify end-to-end

- Trigger the PIR (wave in front of it) and check `journalctl -u nannycam
  -f` for "Recording started" / "Recording stopped" log lines.
- Confirm a `.h264` file landed in `/footage` and plays back (pull it via
  `scp`, or once set up, via the GUI — see `deploy/README.md`).
- Reboot (`sudo reboot`) and confirm `systemctl status nannycam` comes back
  `active (running)` automatically, with a boot-time PID.

## Troubleshooting

- **`RuntimeError: Failed to add edge detection`**: `RPi.GPIO`'s
  `add_event_detect` needs root on this OS/kernel combo — its legacy
  sysfs-based interrupt mechanism isn't covered by the `gpio` group's udev
  permissions, even though basic pin I/O is. Don't run the service as
  root to fix this — instead this repo already ships `rpi-lgpio` in
  `requirements.txt` (drop-in `RPi.GPIO` replacement backed by the modern
  character-device interface), which resolves it with no application code
  changes.
- **`vcgencmd get_throttled` non-zero**: indicates undervoltage — check
  the power supply/PiSugar charge before debugging anything else.
- **PIR firing on a suspiciously regular cadence** (e.g. every ~2
  minutes): almost certainly a cyclical heat/motion source in its field
  of view (ceiling fan, HVAC vent, blinking IR light), not a wiring or
  config problem — confirmed on this build (see
  `journalctl -u nannycam`'s "Recording started/stopped" timestamps to
  spot the pattern). Real motion is bursty/irregular; a fixed interval is
  the tell.
- **`sudo poweroff` seems to leave the Pi drawing power**: without
  PiSugar's software installed, a plain `poweroff` halts the OS but
  doesn't cut PiSugar's own power feed. `pisugar-power-manager`'s
  `pisugar-poweroff` service hooks the Linux shutdown sequence to cut
  power properly — confirm it's installed and enabled (step 4 above).
