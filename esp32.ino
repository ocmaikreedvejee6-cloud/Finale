#include <WiFi.h>
#include "SinricPro.h"
#include "SinricProSwitch.h"

// ================= WIFI =================
#define WIFI_SSID "KT888"
#define WIFI_PASS "KTBT@1987"

// ================= SINRIC =================
#define APP_KEY "dcd1743b-e8cd-4562-aae0-aee790a6219f"
#define APP_SECRET "600bd953-4697-4b2c-afd3-067bd9e0d83e-9b263e3c-ecfe-4bda-bb1d-40fee0e01ddd"

#define R1_ID "69e74da2ad44f4047d037c24"
#define R2_ID "69e74d5852800e7ce36c76d4"
#define R3_ID "69e74d8752800e7ce36c7764"

// ================= PINS =================
#define R1 5
#define R2 18
#define R3 19

// ================= RELAYS =================
void setRelay(int pin, bool state) {
  digitalWrite(pin, state ? HIGH : LOW);
}

// ================= SINRIC CONTROL =================
bool onPowerState(const String &deviceId, bool &state) {

  if (deviceId == R1_ID) {
    setRelay(R1, state);
    Serial.println(state ? "R1 ON" : "R1 OFF");
  }

  if (deviceId == R2_ID) {
    setRelay(R2, state);
    Serial.println(state ? "R2 ON" : "R2 OFF");
  }

  if (deviceId == R3_ID) {
    setRelay(R3, state);
    Serial.println(state ? "R3 ON" : "R3 OFF");
  }

  return true;
}

// ================= SETUP =================
void setup() {
  Serial.begin(9600);

  pinMode(R1, OUTPUT);
  pinMode(R2, OUTPUT);
  pinMode(R3, OUTPUT);

  // Default OFF
  setRelay(R1, false);
  setRelay(R2, false);
  setRelay(R3, false);

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println("\nWiFi Connected");

  SinricProSwitch &s1 = SinricPro[R1_ID];
  s1.onPowerState(onPowerState);

  SinricProSwitch &s2 = SinricPro[R2_ID];
  s2.onPowerState(onPowerState);

  SinricProSwitch &s3 = SinricPro[R3_ID];
  s3.onPowerState(onPowerState);

  SinricPro.begin(APP_KEY, APP_SECRET);

  Serial.println("SinricPro Ready - MANUAL MODE ONLY");
}

// ================= LOOP =================
void loop() {
  SinricPro.handle();
}
