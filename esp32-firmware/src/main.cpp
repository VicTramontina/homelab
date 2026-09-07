// homelab Wake-on-LAN bridge.
//
// Listens on the server-command MQTT feed (Adafruit IO) and sends a
// Wake-on-LAN magic packet for any action other than "shutdown_pc". The
// gameserver PC is asleep/off most of the time and can't run an MQTT
// client itself, so this ESP32 stays powered and acts as the always-on
// listener that wakes it up.
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

#include "config.h"

WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);
WiFiUDP udp;

const char MQTT_TOPIC[] = AIO_USERNAME "/feeds/server-command";
const uint16_t WOL_PORT = 9;

const uint8_t targetMac[6] = TARGET_MAC_ADDR;

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;

  Serial.printf("Connecting to Wi-Fi \"%s\"...\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 30000) {
    delay(500);
    Serial.print('.');
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\nWi-Fi connected, IP: %s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("\nWi-Fi connect timed out, will retry in loop().");
  }
}

void sendMagicPacket() {
  uint8_t packet[102];
  memset(packet, 0xFF, 6);
  for (int i = 1; i <= 16; i++) {
    memcpy(&packet[i * 6], targetMac, 6);
  }

  udp.beginPacket(BROADCAST_ADDR, WOL_PORT);
  udp.write(packet, sizeof(packet));
  udp.endPacket();

  Serial.println("Wake-on-LAN magic packet sent.");
}

void handleMessage(char* topic, byte* payload, unsigned int length) {
  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, payload, length);
  if (err) {
    Serial.printf("Failed to parse server-command payload: %s\n", err.c_str());
    return;
  }

  const char* action = doc["action"] | "";
  Serial.printf("server-command received, action=\"%s\"\n", action);

  if (strlen(action) == 0) return;

  if (strcmp(action, "shutdown_pc") != 0) {
    sendMagicPacket();
  }
}

void connectMqtt() {
  while (!mqttClient.connected()) {
    Serial.print("Connecting to Adafruit IO MQTT...");
    String clientId = "esp32-wol-" + String((uint32_t)ESP.getEfuseMac(), HEX);

    if (mqttClient.connect(clientId.c_str(), AIO_USERNAME, AIO_KEY)) {
      Serial.println(" connected.");
      mqttClient.subscribe(MQTT_TOPIC);
      Serial.printf("Subscribed to %s\n", MQTT_TOPIC);
    } else {
      Serial.printf(" failed, rc=%d. Retrying in 5s.\n", mqttClient.state());
      delay(5000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(200);

  connectWiFi();

  mqttClient.setServer(AIO_SERVER, AIO_SERVERPORT);
  mqttClient.setCallback(handleMessage);
}

void loop() {
  connectWiFi();

  if (WiFi.status() == WL_CONNECTED) {
    if (!mqttClient.connected()) {
      connectMqtt();
    }
    mqttClient.loop();
  }
}
