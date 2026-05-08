int pirPin = 2;
int relayPin = 8;

void setup() {
  pinMode(pirPin, INPUT);
  pinMode(relayPin, OUTPUT);
  digitalWrite(relayPin, LOW);
  Serial.begin(9600);
}

void loop() {
  int motion = digitalRead(pirPin);

  if (motion == HIGH) {
    Serial.println("Motion detected!");
    digitalWrite(relayPin, HIGH); // Turn ON light
    delay(15000); // keep light ON for 15 sec
  } else {
    digitalWrite(relayPin, LOW); // Turn OFF light
  }
}
