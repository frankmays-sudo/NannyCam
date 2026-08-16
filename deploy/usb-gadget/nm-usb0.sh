#!/bin/sh
# Use this only if NetworkManager is the active network manager on the Pi
# (systemctl is-active NetworkManager -- see deploy/README.md). If dhcpcd is
# active instead, use dhcpcd-usb0.conf.
#
# Gives the usb0 gadget interface a static IP once it exists (after reboot
# with the dwc2/g_ether config applied). Safe to re-run.

set -e

if nmcli -t -f NAME connection show | grep -qx "usb0-static"; then
    echo "usb0-static connection already exists, skipping"
else
    nmcli connection add type ethernet ifname usb0 con-name usb0-static ip4 10.55.0.1/24
    echo "Created usb0-static connection (10.55.0.1/24)"
fi
