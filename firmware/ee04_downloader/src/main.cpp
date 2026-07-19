#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <LittleFS.h>
#include <esp_system.h>
#include "wifi_secrets.h"

// ===== Constantes =====
namespace Config {
  constexpr char kProjectName[] = "ee04_home_dashboard";
  constexpr char kPhase[] = "1.2";
  constexpr char kDownloadUrl[] = DASHBOARD_URL;
  constexpr char kUserAgent[] = "ee04_home_dashboard/1.2 (+ESP32-S3)";
  constexpr char kDashboardFile[] = "/dashboard.png";
  constexpr char kTmpDashboardFile[] = "/dashboard.tmp";
  constexpr char kExpectedPngSignature[8] = {
    static_cast<char>(0x89), 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A
  };
  constexpr uint32_t kFirstDelayMs = 5000;
  constexpr uint32_t kDownloadIntervalMs = 300000;
  constexpr uint32_t kStatusIntervalMs = 10000;
  constexpr uint32_t kWifiTimeoutMs = 20000;
  constexpr uint32_t kHttpTimeoutMs = 15000;
  constexpr uint32_t kWifiReconnectIntervalMs = 5000;
  constexpr size_t kStreamBufferSize = 1024;
}

// ===== Variables d'état =====
bool gFsMounted = false;
uint32_t gNextDownloadMs = 0;
uint32_t gNextStatusMs = 0;
uint32_t gNextReconnectMs = 0;
uint32_t gCycleCount = 0;
bool gPreviousWifiState = false;

// ===== Utilitaires =====
const char* getResetReasonText(esp_reset_reason_t reason) {
  switch (reason) {
    case ESP_RST_POWERON:
      return "Démarrage à froid / mise sous tension";
    case ESP_RST_EXT:
      return "Réinitialisation externe";
    case ESP_RST_SW:
      return "Reset logiciel";
    case ESP_RST_PANIC:
      return "Panique/exception";
    case ESP_RST_INT_WDT:
      return "Watchdog interrupt";
    case ESP_RST_TASK_WDT:
      return "Watchdog tâche";
    case ESP_RST_WDT:
      return "Watchdog";
    case ESP_RST_DEEPSLEEP:
      return "Sortie deep sleep";
    case ESP_RST_BROWNOUT:
      return "Brownout";
    case ESP_RST_SDIO:
      return "Reset SDIO";
    case ESP_RST_USB:
      return "Reset USB";
    case ESP_RST_UNKNOWN:
      return "Raison inconnue";
    default:
      return "Raison non répertoriée";
  }
}

void printProjectHeader() {
  Serial.println("=== ee04_home_dashboard ===");
  Serial.printf("Projet : %s\n", Config::kProjectName);
  Serial.printf("Phase  : %s\n", Config::kPhase);
  Serial.printf("Raison de reboot : %s\n", getResetReasonText(esp_reset_reason()));
  Serial.printf("MAC : %s\n", WiFi.macAddress().c_str());
  const size_t total = LittleFS.totalBytes();
  const size_t used = LittleFS.usedBytes();
  const size_t free = total >= used ? total - used : 0;
  Serial.printf("LittleFS total : %u octets\n", static_cast<unsigned>(total));
  Serial.printf("LittleFS used  : %u octets\n", static_cast<unsigned>(used));
  Serial.printf("LittleFS libre : %u octets\n", static_cast<unsigned>(free));
}

void printWifiDetails() {
  Serial.printf("IP locale   : %s\n", WiFi.localIP().toString().c_str());
  Serial.printf("MAC         : %s\n", WiFi.macAddress().c_str());
  Serial.printf("Canal       : %d\n", WiFi.channel());
  Serial.printf("RSSI        : %d dBm\n", WiFi.RSSI());
}

void printPeriodicReport() {
  const uint32_t now = millis();
  const int32_t remaining = static_cast<int32_t>(gNextDownloadMs - now);
  Serial.println("---- Rapport périodique ----");
  Serial.printf("Uptime                  : %lu ms\n", (unsigned long)now);
  Serial.printf("État Wi-Fi              : %s\n", WiFi.isConnected() ? "connecté" : "déconnecté");
  Serial.printf("IP                      : %s\n", WiFi.isConnected() ? WiFi.localIP().toString().c_str() : "n/a");
  if (WiFi.isConnected()) {
    Serial.printf("RSSI                    : %d dBm\n", WiFi.RSSI());
  } else {
    Serial.println("RSSI                    : n/a");
  }
  if (remaining > 0) {
    Serial.printf("Temps avant téléchargement: %ld ms\n", (long)remaining);
  } else {
    Serial.println("Téléchargement prêt à démarrer");
  }
  Serial.println("---------------------------");
}

bool mountLittleFS() {
  if (LittleFS.begin(false)) {
    Serial.println("LittleFS monté avec succès (sans formatage).");
    gFsMounted = true;
    return true;
  }

  Serial.println("ERREUR: montage LittleFS impossible.");
  Serial.println("Tentative de formatage secours...");
  if (LittleFS.begin(true)) {
    Serial.println("LittleFS monté après formatage secours.");
    gFsMounted = true;
    return true;
  }

  Serial.println("ERREUR FATALE: échec du formatage secours.");
  gFsMounted = false;
  return false;
}

bool connectWiFiBlocking() {
  Serial.printf("Connexion Wi-Fi au SSID '%s' ...\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  const uint32_t start = millis();
  while (millis() - start < Config::kWifiTimeoutMs) {
    if (WiFi.status() == WL_CONNECTED) {
      Serial.println("\nWi-Fi connecté.");
      printWifiDetails();
      return true;
    }
    Serial.print('.');
    delay(500);
  }
  Serial.println();
  Serial.printf("ERREUR: timeout Wi-Fi (%u ms), état=%d\n", Config::kWifiTimeoutMs, WiFi.status());
  return false;
}

void printDownloadResult(bool success,
                        uint32_t cycle,
                        int httpCode,
                        const String& contentType,
                        size_t bytesReceived,
                        size_t fileSize,
                        uint32_t durationMs,
                        bool oldKept,
                        const char* failedStep,
                        const String& failureMessage) {
  if (success) {
    Serial.println("=== RÉSULTAT FINAL : SUCCES ===");
    Serial.printf("Cycle            : %u\n", static_cast<unsigned>(cycle));
    Serial.printf("Code HTTP        : %d\n", httpCode);
    Serial.printf("MIME             : %s\n", contentType.c_str());
    Serial.printf("Octets reçus     : %u\n", static_cast<unsigned>(bytesReceived));
    Serial.printf("Taille LittleFS   : %u octets\n", static_cast<unsigned>(fileSize));
    Serial.printf("Durée            : %u ms\n", static_cast<unsigned>(durationMs));
    Serial.printf("RSSI             : %d dBm\n", WiFi.RSSI());
    return;
  }

  Serial.println("=== RÉSULTAT FINAL : ECHEC ===");
  Serial.printf("Cycle            : %u\n", static_cast<unsigned>(cycle));
  Serial.printf("Étape échouée    : %s\n", failedStep);
  Serial.printf("Code/Msg         : %s\n", failureMessage.c_str());
  Serial.printf("Durée            : %u ms\n", static_cast<unsigned>(durationMs));
  Serial.printf("Ancienne image conservée : %s\n", oldKept ? "OUI" : "NON");
}

bool doDownloadCycle(uint32_t cycle) {
  const uint32_t startMs = millis();
  bool ok = false;
  int httpCode = -1;
  size_t bytesReceived = 0;
  size_t finalSize = 0;
  String contentType = "n/a";
  const char* failedStep = "préparation";
  String failureMessage = "non exécuté";
  bool oldImageKept = true;

  Serial.printf("\n-- Cycle téléchargement #%u --\n", static_cast<unsigned>(cycle));

  if (!gFsMounted) {
    failedStep = "montage LittleFS";
    failureMessage = "LittleFS indisponible";
    printDownloadResult(false, cycle, httpCode, contentType, bytesReceived, finalSize, millis() - startMs, oldImageKept, failedStep, failureMessage);
    return false;
  }

  if (!WiFi.isConnected()) {
    failedStep = "Wi-Fi";
    failureMessage = "Réseau non connecté";
    printDownloadResult(false, cycle, httpCode, contentType, bytesReceived, finalSize, millis() - startMs, oldImageKept, failedStep, failureMessage);
    return false;
  }

  if (LittleFS.exists(Config::kTmpDashboardFile)) {
    LittleFS.remove(Config::kTmpDashboardFile);
  }

  HTTPClient http;
  WiFiClient client;
  failedStep = "initialisation HTTP";
  http.setTimeout(Config::kHttpTimeoutMs);
  if (!http.begin(client, Config::kDownloadUrl)) {
    failureMessage = "Échec init HTTPClient";
    printDownloadResult(false, cycle, httpCode, contentType, bytesReceived, finalSize, millis() - startMs, oldImageKept, failedStep, failureMessage);
    return false;
  }
  http.addHeader("User-Agent", Config::kUserAgent);

  failedStep = "requête HTTP";
  const char* headerKeys[] = {"Content-Type"};
  http.collectHeaders(headerKeys, 1);
  httpCode = http.GET();
  if (httpCode != HTTP_CODE_OK) {
    failureMessage = "Code HTTP incorrect: " + String(httpCode);
    http.end();
    printDownloadResult(false, cycle, httpCode, contentType, bytesReceived, finalSize, millis() - startMs, oldImageKept, failedStep, failureMessage);
    return false;
  }

  contentType = http.header("Content-Type");
  if (contentType.length() == 0) {
    failureMessage = "En-tête Content-Type absent";
    http.end();
    printDownloadResult(false, cycle, httpCode, contentType, bytesReceived, finalSize, millis() - startMs, oldImageKept, "validation MIME", failureMessage);
    return false;
  }
  Serial.printf("Content-Type reçu : %s\n", contentType.c_str());
  if (contentType.indexOf("image/png") < 0) {
    failureMessage = "MIME différent de image/png";
    Serial.printf("Avertissement : MIME inattendu (%s)\n", contentType.c_str());
    http.end();
    printDownloadResult(false, cycle, httpCode, contentType, bytesReceived, finalSize, millis() - startMs, oldImageKept, "validation MIME", failureMessage);
    return false;
  }

  File out = LittleFS.open(Config::kTmpDashboardFile, "w");
  if (!out) {
    failedStep = "création fichier temporaire";
    failureMessage = "Impossible d'ouvrir /dashboard.tmp";
    http.end();
    printDownloadResult(false, cycle, httpCode, contentType, bytesReceived, finalSize, millis() - startMs, oldImageKept, failedStep, failureMessage);
    return false;
  }

  Stream* stream = http.getStreamPtr();
  if (!stream) {
    failedStep = "accès flux HTTP";
    failureMessage = "Flux HTTP indisponible";
    out.close();
    http.end();
    printDownloadResult(false, cycle, httpCode, contentType, bytesReceived, finalSize, millis() - startMs, oldImageKept, failedStep, failureMessage);
    return false;
  }

  uint8_t pngSignature[8];
  size_t signatureLen = 0;
  uint8_t buffer[Config::kStreamBufferSize];
  uint32_t lastActivityMs = millis();

  while (true) {
    const int available = stream->available();
    if (available > 0) {
      int toRead = min(available, static_cast<int>(sizeof(buffer)));
      int read = stream->readBytes(buffer, toRead);
      if (read > 0) {
        out.write(buffer, read);
        for (int i = 0; i < read && signatureLen < sizeof(pngSignature); ++i) {
          pngSignature[signatureLen++] = buffer[i];
        }
        bytesReceived += static_cast<size_t>(read);
        lastActivityMs = millis();
      }
      continue;
    }
    if (!http.connected()) {
      break;
    }
    if (millis() - lastActivityMs > Config::kHttpTimeoutMs) {
      failureMessage = "Timeout inactivité HTTP";
      failedStep = "téléchargement HTTP";
      out.close();
      http.end();
      printDownloadResult(false, cycle, httpCode, contentType, bytesReceived, finalSize, millis() - startMs, oldImageKept, failedStep, failureMessage);
      return false;
    }
    delay(1);
  }
  out.close();

  if (bytesReceived == 0) {
    failedStep = "validation taille";
    failureMessage = "Réponse vide";
    http.end();
    printDownloadResult(false, cycle, httpCode, contentType, bytesReceived, finalSize, millis() - startMs, oldImageKept, failedStep, failureMessage);
    return false;
  }
  if (signatureLen < sizeof(pngSignature)) {
    failedStep = "validation signature";
    failureMessage = "Image trop petite pour signature PNG";
    http.end();
    printDownloadResult(false, cycle, httpCode, contentType, bytesReceived, finalSize, millis() - startMs, oldImageKept, failedStep, failureMessage);
    return false;
  }
  if (memcmp(pngSignature, Config::kExpectedPngSignature, sizeof(pngSignature)) != 0) {
    failedStep = "validation signature";
    failureMessage = "Signature PNG invalide";
    http.end();
    printDownloadResult(false, cycle, httpCode, contentType, bytesReceived, finalSize, millis() - startMs, oldImageKept, failedStep, failureMessage);
    return false;
  }

  oldImageKept = !LittleFS.exists(Config::kDashboardFile);
  if (LittleFS.exists(Config::kDashboardFile)) {
    LittleFS.remove(Config::kDashboardFile);
  }
  if (!LittleFS.rename(Config::kTmpDashboardFile, Config::kDashboardFile)) {
    failedStep = "remplacement fichier";
    failureMessage = "Impossible de remplacer /dashboard.png";
    http.end();
    printDownloadResult(false, cycle, httpCode, contentType, bytesReceived, finalSize, millis() - startMs, oldImageKept, failedStep, failureMessage);
    return false;
  }

  File finalFile = LittleFS.open(Config::kDashboardFile, "r");
  if (!finalFile) {
    failedStep = "validation finale";
    failureMessage = "Impossible de réouvrir dashboard.png";
    http.end();
    printDownloadResult(false, cycle, httpCode, contentType, bytesReceived, finalSize, millis() - startMs, oldImageKept, failedStep, failureMessage);
    return false;
  }
  finalSize = finalFile.size();
  finalFile.close();
  if (finalSize == 0) {
    failedStep = "validation finale";
    failureMessage = "dashboard.png final vide";
    http.end();
    printDownloadResult(false, cycle, httpCode, contentType, bytesReceived, finalSize, millis() - startMs, oldImageKept, failedStep, failureMessage);
    return false;
  }

  http.end();
  ok = true;
  printDownloadResult(ok, cycle, httpCode, contentType, bytesReceived, finalSize, millis() - startMs, oldImageKept, "", "");
  Serial.printf("Cycle %u : SUCCES\n", static_cast<unsigned>(cycle));
  if (LittleFS.exists(Config::kDashboardFile)) {
    const size_t dashboardSize = LittleFS.open(Config::kDashboardFile, "r").size();
    const size_t fsUsed = LittleFS.usedBytes();
    Serial.printf("Taille réelle fichier : %u octets\n", static_cast<unsigned>(dashboardSize));
    Serial.printf("LittleFS used         : %u octets\n", static_cast<unsigned>(fsUsed));
  }
  return ok;
}

void handleWiFiState() {
  const bool connected = WiFi.isConnected();
  if (connected != gPreviousWifiState) {
    if (connected) {
      Serial.println("Changement état Wi-Fi : CONNECTÉ");
      printWifiDetails();
    } else {
      Serial.println("Changement état Wi-Fi : DÉCONNECTÉ");
    }
    gPreviousWifiState = connected;
  }
}

void setup() {
  Serial.begin(115200);
  while (!Serial) {
    delay(10);
  }

  mountLittleFS();
  printProjectHeader();

  gPreviousWifiState = WiFi.isConnected();
  connectWiFiBlocking();

  gNextDownloadMs = millis() + Config::kFirstDelayMs;
  gNextStatusMs = millis() + Config::kStatusIntervalMs;
  gNextReconnectMs = millis() + Config::kWifiReconnectIntervalMs;
}

void loop() {
  const uint32_t now = millis();
  handleWiFiState();

  if (!WiFi.isConnected() && now >= gNextReconnectMs) {
    gNextReconnectMs = now + Config::kWifiReconnectIntervalMs;
    connectWiFiBlocking();
  }

  if (now >= gNextStatusMs) {
    printPeriodicReport();
    gNextStatusMs = now + Config::kStatusIntervalMs;
  }

  if (now >= gNextDownloadMs) {
    gCycleCount++;
    const bool cycleSuccess = doDownloadCycle(gCycleCount);
    if (!cycleSuccess) {
      Serial.println("La précédente image valide est conservée.");
    }
    gNextDownloadMs = millis() + Config::kDownloadIntervalMs;
  }
}
