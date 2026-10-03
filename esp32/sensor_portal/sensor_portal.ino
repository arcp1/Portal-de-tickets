/*
 * Sensor de planta para el Portal de Tickets TI — CGR de México.
 *
 * Publica temperatura, humedad y calidad del aire en Mosquitto, en
 *
 *     portal/<CLAVE_PLANTA>/sensores/<CLAVE_EQUIPO>/telemetria
 *
 * con un JSON como {"temperatura": 24.6, "humedad": 41.2, "calidad_aire": 412}.
 * El portal registra el equipo solo con su primer mensaje; TI le pone nombre,
 * ubicación y umbrales desde «Monitoreo ESP32».
 *
 * Hardware de referencia (cambie las lecturas si usa otro):
 *   - DHT22 (temperatura y humedad) en el pin 4.
 *   - MQ-135 (calidad del aire, aproximada) en el pin analógico 34.
 *
 * Bibliotecas (Gestor de bibliotecas del IDE de Arduino):
 *   - PubSubClient (Nick O'Leary)
 *   - DHT sensor library (Adafruit)
 *
 * Reglas del portal que conviene respetar:
 *   - Como mucho una lectura cada 5 s por equipo (IOT_INTERVALO_MINIMO_S); lo
 *     que llegue más seguido se descarta. Cada 30 s es más que suficiente.
 *   - Sin `retain`: el broker no acepta mensajes retenidos.
 *   - Valores imposibles (humedad > 100 %, NaN de un sensor suelto) se
 *     descartan; no hace falta filtrarlos aquí, pero tampoco mandarlos.
 *   - Si pasan 10 min sin publicar, TI recibe la alerta «sin señal».
 *
 * La contraseña es la de MQTT_DISPOSITIVO_PASSWORD en el .env del servidor.
 * No suba este archivo con la contraseña escrita a ningún repositorio.
 */

#include <WiFi.h>
#include <PubSubClient.h>
#include <DHT.h>

// ---- Configuración --------------------------------------------------------
const char* WIFI_RED       = "RED-DE-PLANTA";
const char* WIFI_CLAVE     = "********";
const char* MQTT_SERVIDOR  = "192.168.1.168";   // IP del servidor del portal en la red de planta
const uint16_t MQTT_PUERTO = 1883;
const char* MQTT_USUARIO   = "sensor";
const char* MQTT_CLAVE     = "********";        // MQTT_DISPOSITIVO_PASSWORD

const char* CLAVE_PLANTA   = "QRO";             // la clave de la planta en el portal
const char* CLAVE_EQUIPO   = "esp32-cuarto-servidores";  // única por equipo: letras, números, - y _

const unsigned long CADA_MS = 30000;            // una lectura cada 30 s

#define PIN_DHT 4
#define PIN_AIRE 34
// ---------------------------------------------------------------------------

DHT dht(PIN_DHT, DHT22);
WiFiClient red;
PubSubClient mqtt(red);
char tema[128];
unsigned long ultimo = 0;

void conectarWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_RED, WIFI_CLAVE);
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) delay(500);
}

void conectarMqtt() {
  while (!mqtt.connected()) {
    conectarWifi();
    // El id del cliente es la clave del equipo: dos ESP32 con la misma clave
    // se echarían uno al otro del broker, y así se nota enseguida.
    if (mqtt.connect(CLAVE_EQUIPO, MQTT_USUARIO, MQTT_CLAVE)) return;
    delay(5000);
  }
}

// Aproximación de ppm para el MQ-135. Calíbrelo contra un medidor de verdad
// si las cifras importan; para avisar de "el aire empeoró" basta.
float leerCalidadAire() {
  int crudo = analogRead(PIN_AIRE);          // 0..4095
  return crudo * (2000.0 / 4095.0) + 400.0;  // ~400 ppm de fondo
}

void setup() {
  Serial.begin(115200);
  dht.begin();
  snprintf(tema, sizeof(tema), "portal/%s/sensores/%s/telemetria", CLAVE_PLANTA, CLAVE_EQUIPO);
  mqtt.setServer(MQTT_SERVIDOR, MQTT_PUERTO);
  conectarWifi();
}

void loop() {
  conectarMqtt();
  mqtt.loop();

  if (millis() - ultimo < CADA_MS) return;
  ultimo = millis();

  float t = dht.readTemperature();
  float h = dht.readHumidity();
  float aire = leerCalidadAire();

  char cuerpo[160];
  // Lo que el sensor no pudo leer va como null: el portal guarda lo demás.
  char ts[16], hs[16];
  if (isnan(t)) strcpy(ts, "null"); else dtostrf(t, 0, 1, ts);
  if (isnan(h)) strcpy(hs, "null"); else dtostrf(h, 0, 1, hs);
  snprintf(cuerpo, sizeof(cuerpo),
           "{\"temperatura\":%s,\"humedad\":%s,\"calidad_aire\":%.0f,\"rssi\":%d}",
           ts, hs, aire, WiFi.RSSI());

  bool ok = mqtt.publish(tema, cuerpo, false);  // QoS 0, sin retain
  Serial.printf("%s %s -> %s\n", ok ? "OK " : "ERR", tema, cuerpo);
}
