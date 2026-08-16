#!/bin/sh
# Creates a CDC-NCM USB gadget via configfs and binds it to the dwc2 UDC,
# presenting a usb0 network interface to whatever host it's plugged into.
#
# NCM (not the legacy g_ether RNDIS/ECM composite) because Windows has had
# genuine inbox CDC-NCM driver support since Windows 10 -- it binds
# automatically like any standard USB class device, no manual driver
# selection needed. g_ether's RNDIS function requires Windows to pick the
# right driver among several candidates and can end up misbound to the
# generic serial/modem driver instead of a NIC.
#
# Run as root via nannycam-usb-gadget.service, early at boot, in place of
# modules-load=dwc2,g_ether (this repo now only loads dwc2 from cmdline.txt).
set -e

GADGET=/sys/kernel/config/usb_gadget/nannycam

if [ -d "$GADGET" ]; then
    echo "Gadget already configured, skipping"
    exit 0
fi

modprobe libcomposite

mkdir -p "$GADGET"
cd "$GADGET"

echo 0x1d6b > idVendor    # Linux Foundation
echo 0x0104 > idProduct   # Multifunction Composite Gadget
echo 0x0100 > bcdDevice
echo 0x0200 > bcdUSB

mkdir -p strings/0x409
echo "nannycam001" > strings/0x409/serialnumber
echo "NannyCam" > strings/0x409/manufacturer
echo "NannyCam USB Gadget" > strings/0x409/product

mkdir -p configs/c.1/strings/0x409
echo "NCM" > configs/c.1/strings/0x409/configuration
echo 250 > configs/c.1/MaxPower

mkdir -p functions/ncm.usb0
ln -s functions/ncm.usb0 configs/c.1/

udc=$(ls /sys/class/udc | head -n1)
echo "$udc" > UDC
