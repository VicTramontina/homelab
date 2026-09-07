// Copy this file to config.h (same directory) and fill in real values.
// config.h is gitignored on purpose -- never commit real credentials or
// the real target MAC address.
#pragma once

// --- Wi-Fi (2.4GHz only -- the ESP32 does not support 5GHz) ---
#define WIFI_SSID "your-wifi-ssid"
#define WIFI_PASSWORD "your-wifi-password"

// --- Adafruit IO MQTT broker ---
#define AIO_USERNAME "your-adafruit-io-username"
#define AIO_KEY "your-adafruit-io-key"
#define AIO_SERVER "io.adafruit.com"
#define AIO_SERVERPORT 1883

// --- Target machine ---
// MAC address of the gameserver PC's network interface, as 6 hex bytes.
// Wake-on-LAN must be enabled for this interface in both the BIOS/UEFI
// and the OS (see docs/setup.md).
#define TARGET_MAC_ADDR {0xDE, 0xAD, 0xBE, 0xEF, 0x00, 0x01}

// Local broadcast address for the magic packet. 255.255.255.255 works on
// most home networks; use your subnet's directed broadcast (e.g.
// 192.168.1.255) if your router does not forward the global broadcast.
#define BROADCAST_ADDR "255.255.255.255"
