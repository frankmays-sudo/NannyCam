# NannyCam deployment

Steps to set up the direct USB transfer link and the footage web GUI on
`pizero01`, run from the Windows dev machine unless noted.

## Prerequisites

- SSH access to `pizero01` as `spacecamel`.
- Repo already cloned at `/home/spacecamel/NannyCam` on the Pi, and up to date
  (`git pull`).

## 1. USB gadget networking

This gives you a direct wired link (Pi `usb0` = `10.55.0.1`) over the Pi's
USB port, much faster than WiFi for pulling footage.

**Verify these two facts on-device before editing anything** — don't assume:

```sh
ls /boot/firmware/config.txt   # recent Raspberry Pi OS
ls /boot/config.txt            # older images — use whichever actually exists
systemctl is-active NetworkManager   # or: systemctl is-active dhcpcd
```

This uses a **CDC-NCM** gadget (via configfs + `nannycam-usb-gadget.service`),
not the legacy `g_ether`/RNDIS module. Windows has had genuine inbox
CDC-NCM support since Windows 10 — it binds automatically like any standard
USB class device, no manual driver selection. (`g_ether`'s RNDIS function
was tried first and ran into Windows repeatedly mis-binding it to the
generic serial/modem driver instead of a NIC, with no reliable way to force
the correct driver through Device Manager — see git history on this file
if you need the details.)

Steps:

1. Append the contents of `deploy/usb-gadget/config.txt.append` to the real
   `config.txt` path confirmed above.
2. Splice `modules-load=dwc2` into the existing single line of the real
   `cmdline.txt`, per the instructions in
   `deploy/usb-gadget/cmdline.txt.snippet`. Do not add a new line.
3. Install and enable the gadget service:
   ```sh
   chmod +x deploy/usb-gadget/ncm-gadget.sh
   sudo cp deploy/usb-gadget/nannycam-usb-gadget.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable nannycam-usb-gadget.service
   ```
4. Give `usb0` a static IP:
   - If `NetworkManager` is active: copy `deploy/usb-gadget/nm-usb0.sh` to the
     Pi and run it with `sudo` (`sudo sh nm-usb0.sh` — `nmcli connection add`
     needs root).
   - If `dhcpcd` is active: append `deploy/usb-gadget/dhcpcd-usb0.conf`'s
     contents to `/etc/dhcpcd.conf`.
5. `sudo reboot`.
6. After reboot, confirm the interface came up: `ip addr show usb0` should
   show `10.55.0.1/24`.
7. Plug the USB cable into the Windows machine (must be a data-capable
   cable, not charge-only, and into the Pi's data USB port, not the
   power-only port). Windows should enumerate a new network adapter
   automatically within a few seconds — check with `Get-NetAdapter` in
   PowerShell. Give it a static IP once, one time:
   ```powershell
   netsh interface ip set address name="<adapter name>" static 10.55.0.2 255.255.255.0
   ```
8. Verify: `ping 10.55.0.1` from Windows should succeed.

## 2. GUI setup

1. Generate a real password hash (don't ship the placeholder):
   ```sh
   python3 -c "import hashlib;print(hashlib.sha256(b'yourpassword').hexdigest())"
   ```
   Put it in `config/settings.yaml` under `gui.password_hash`, **directly on
   the Pi only — do not commit it**. This repo is public on GitHub, and a
   committed SHA-256 hash is a real offline brute-force target. Git will
   keep showing `config/settings.yaml` as locally modified on the Pi
   forever, which is expected. This means a future `git pull` can fail with
   "local changes would be overwritten" if an upstream commit ever touches
   the same lines in `settings.yaml` — if that happens, `git stash`, pull,
   then `git stash pop` (or just re-apply the password_hash line by hand)
   rather than discarding the local change.
2. Install Flask (this Pi has no venv, matching the existing recorder
   service — plain system python3):
   ```sh
   pip install -r requirements.txt --break-system-packages
   ```
3. Install and enable the systemd unit:
   ```sh
   sudo cp deploy/nannycam-gui.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now nannycam-gui
   sudo systemctl status nannycam-gui   # confirm active (running)
   ```

## 3. Using the GUI

Browse to `http://10.55.0.1:8080/` over the USB link, or
`http://pizero01:8080/` (or its WiFi IP) over WiFi — same server either way.
Log in with the shared password. Download or delete clips from the list.

## Troubleshooting

- **Boot path mismatch**: if `config.txt`/`cmdline.txt` edits don't seem to
  take effect, double-check you edited the actual active path (step 1 above)
  and not a stale copy.
- **NetworkManager vs dhcpcd**: only one should be actively managing `usb0` —
  running both configs at once can conflict. Re-check
  `systemctl is-active NetworkManager`/`dhcpcd` if `usb0` doesn't get
  `10.55.0.1`.
- **Adapter not enumerating on Windows**: try a different USB cable/port —
  some cables are charge-only. Check `Get-NetAdapter` after plugging in.
- **Windows shows a device but not a network adapter**: confirm
  `nannycam-usb-gadget.service` is actually active on the Pi
  (`systemctl status nannycam-usb-gadget`) and that `g_ether` isn't also
  loaded (`lsmod | grep g_ether` should be empty — if it's there,
  `cmdline.txt` still has `g_ether` in `modules-load`).
- **GUI can't delete files**: check `ls -la /footage` — it should be owned by
  `spacecamel`, the same user both `nannycam.service` and
  `nannycam-gui.service` run as. If ownership has drifted, fix with
  `sudo chown spacecamel:spacecamel /footage`.
