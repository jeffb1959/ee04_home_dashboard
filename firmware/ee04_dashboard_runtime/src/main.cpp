#include <Arduino.h>
#include <FS.h>
#include <HTTPClient.h>
#include <LittleFS.h>
#include <WiFi.h>
#include <WiFiClient.h>
#include <esp_system.h>

#include "driver.h"
#include "wifi_secrets.h"
#include "TFT_eSPI.h"

// =====================================================================
// Phase 1.5B.2 : telechargement + validation + affichage ePaper
// =====================================================================

static const char* kProjectName = "ee04_home_dashboard";
static const char* kProjectPhase = "1.5B.2";
static const char* kDashboardUrl = DASHBOARD_URL;
static const char* kDashboardPath = "/dashboard.bin";
static const char* kTempDashboardPath = "/dashboard.tmp";
static const char* kBackupDashboardPath = "/dashboard.bin.bak";
static const char* kUserAgent = "EE04-Home-Dashboard-Phase1.5B.2/1.0";
static const char* kExpectedMime = "application/octet-stream";

static const uint16_t kDashboardWidth = 800;
static const uint16_t kDashboardHeight = 480;
static const size_t kExpectedDashboardSize = static_cast<size_t>(kDashboardWidth) * kDashboardHeight; // 1 octet par pixel
static const uint8_t kMaxPixelValue = 5;

static const unsigned long kWifiTimeoutMs = 20000;
static const unsigned long kHttpTimeoutMs = 15000;
static const unsigned long kFirstDownloadDelayMs = 5000;
static const unsigned long kDownloadIntervalMs = 5UL * 60UL * 1000UL;
static const unsigned long kStatusIntervalMs = 10UL * 1000UL;
static const size_t kReadChunkSize = 1024;

struct DownloadResult {
  bool success = false;
  bool oldKept = true;
  int httpCode = -1;
  String contentType;
  size_t bytesReceived = 0;
  size_t invalidBytes = 0;
  unsigned long durationMs = 0;
  String failedStep;
  String failedReason;
  int rssi = 0;
  bool mimeDifferent = false;
};

struct DisplayResult {
  bool success = false;
  size_t invalidBytes = 0;
  size_t bytesRead = 0;
  unsigned long drawDurationMs = 0;
  unsigned long refreshDurationMs = 0;
  unsigned long totalDurationMs = 0;
  String failedStep;
  String failedReason;
};

unsigned long g_nextDownloadAtMs = 0;
unsigned long g_lastStatusReportMs = 0;
unsigned long g_lastReconnectAttemptMs = 0;
uint32_t g_cycleCount = 0;

bool g_littleFsMounted = false;
bool g_epaperInitialized = false;
bool g_displayInProgress = false;
bool g_lastScreenUpdateSuccess = false;
unsigned long g_lastScreenUpdateMs = 0;

EPaper epaper;

String resetReasonToString(esp_reset_reason_t reason) {
  switch (reason) {
    case ESP_RST_UNKNOWN: return "ESP_RST_UNKNOWN";
    case ESP_RST_POWERON: return "ESP_RST_POWERON";
    case ESP_RST_EXT: return "ESP_RST_EXT";
    case ESP_RST_SW: return "ESP_RST_SW";
    case ESP_RST_PANIC: return "ESP_RST_PANIC";
    case ESP_RST_INT_WDT: return "ESP_RST_INT_WDT";
    case ESP_RST_TASK_WDT: return "ESP_RST_TASK_WDT";
    case ESP_RST_WDT: return "ESP_RST_WDT";
    case ESP_RST_DEEPSLEEP: return "ESP_RST_DEEPSLEEP";
    case ESP_RST_BROWNOUT: return "ESP_RST_BROWNOUT";
    case ESP_RST_SDIO: return "ESP_RST_SDIO";
    default: return "ESP_RST_AUTRE";
  }
}

void printLittleFsInfo() {
  const size_t total = LittleFS.totalBytes();
  const size_t used = LittleFS.usedBytes();
  const size_t freeBytes = (total >= used) ? (total - used) : 0;
  Serial.printf("LittleFS total=%u used=%u free=%u octets\n", total, used, freeBytes);
}

void printBootInfo() {
  Serial.println("===== DEMARRAGE =====");
  Serial.printf("Projet : %s\n", kProjectName);
  Serial.printf("Phase : %s\n", kProjectPhase);
  Serial.printf("Raison reboot : %s\n", resetReasonToString(esp_reset_reason()).c_str());
  Serial.printf("Adresse MAC : %s\n", WiFi.macAddress().c_str());
  Serial.printf("LittleFS monte : %s\n", g_littleFsMounted ? "oui" : "non");
  printLittleFsInfo();
}

bool mountLittleFS() {
  Serial.println("Montage LittleFS (sans formatage de secours)...");
  if (LittleFS.begin(false)) {
    Serial.println("LittleFS monte avec succes.");
    g_littleFsMounted = true;
    return true;
  }

  Serial.println("Montage LittleFS initial echoue. Tentative de formatage de secours...");
  if (!LittleFS.format()) {
    Serial.println("Formatage LittleFS impossible.");
    return false;
  }

  Serial.println("Formatage execute, tentative de remontage...");
  if (!LittleFS.begin(false)) {
    Serial.println("Remontage LittleFS apres formatage impossible.");
    return false;
  }

  Serial.println("LittleFS monte apres formatage.");
  g_littleFsMounted = true;
  return true;
}

void printWifiState() {
  Serial.printf("Wi-Fi status: %d\n", WiFi.status());
  Serial.printf("IP: %s\n", WiFi.localIP().toString().c_str());
  Serial.printf("MAC: %s\n", WiFi.macAddress().c_str());
  Serial.printf("Canal: %d\n", WiFi.channel());
  Serial.printf("RSSI: %d dBm\n", WiFi.RSSI());
}

bool connectWifi(uint32_t timeoutMs) {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);

  if (WiFi.status() == WL_CONNECTED) {
    return true;
  }

  Serial.println("Connexion Wi-Fi station... (max 20s)");
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  const unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < timeoutMs) {
    delay(250);
    yield();
  }

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Connexion Wi-Fi non etablie avant timeout.");
    return false;
  }

  Serial.println("Wi-Fi connecte.");
  printWifiState();
  return true;
}

void printPeriodicStatus(unsigned long now) {
  if (g_displayInProgress) {
    return;
  }

  Serial.println("===== RAPPORT PERIODIQUE (10s) =====");
  Serial.printf("Uptime : %lus\n", now / 1000UL);
  Serial.printf("Wi-Fi connecte : %s\n", WiFi.status() == WL_CONNECTED ? "oui" : "non");
  Serial.printf("IP : %s\n", WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString().c_str() : "-");
  Serial.printf("RSSI : %d dBm\n", WiFi.status() == WL_CONNECTED ? WiFi.RSSI() : 0);

  long nextMs = (long)(g_nextDownloadAtMs - now);
  if (nextMs < 0) {
    nextMs = 0;
  }
  Serial.printf("Prochain telechargement dans : %lu s\n", (unsigned long)(nextMs / 1000UL));

  bool hasBin = LittleFS.exists(kDashboardPath);
  size_t fileSize = 0;
  if (hasBin) {
    File f = LittleFS.open(kDashboardPath, FILE_READ);
    if (f) {
      fileSize = f.size();
      f.close();
    }
  }
  Serial.printf("dashboard.bin present : %s\n", hasBin ? "oui" : "non");
  Serial.printf("taille dashboard.bin : %u octets\n", fileSize);

  Serial.printf("Ecran initialise : %s\n", g_epaperInitialized ? "oui" : "non");
  Serial.printf("Derniere mise a jour ecran reussie : %s\n", g_lastScreenUpdateSuccess ? "oui" : "non");
  if (g_lastScreenUpdateSuccess) {
    const unsigned long delta = (now >= g_lastScreenUpdateMs) ? (now - g_lastScreenUpdateMs) : 0;
    Serial.printf("Temps depuis derniere mise a jour ecran : %lu s\n", delta / 1000UL);
  } else {
    Serial.println("Temps depuis derniere mise a jour ecran : jamais");
  }
}

uint16_t colorFromPixelIndex(uint8_t index) {
  switch (index) {
    case 0: return TFT_BLACK;
    case 1: return TFT_WHITE;
    case 2: return TFT_RED;
    case 3: return TFT_YELLOW;
    case 4: return TFT_GREEN;
    case 5: return TFT_BLUE;
    default: return TFT_WHITE;
  }
}

bool initEpaperIfNeeded() {
  if (g_epaperInitialized) {
    return true;
  }

  epaper.begin();
  g_epaperInitialized = true;
  return true;
}

DisplayResult afficherDashboardDepuisLittleFS() {
  DisplayResult result;
  result.failedStep = "verification LittleFS";

  if (!g_littleFsMounted) {
    result.failedReason = "LittleFS n'est pas monte";
    return result;
  }

  result.failedStep = "controle dashboard.bin";
  if (!LittleFS.exists(kDashboardPath)) {
    result.failedReason = "dashboard.bin absent";
    return result;
  }

  File dashboardFile = LittleFS.open(kDashboardPath, FILE_READ);
  if (!dashboardFile) {
    result.failedStep = "ouverture dashboard.bin";
    result.failedReason = "Impossible d'ouvrir dashboard.bin en lecture";
    return result;
  }

  if (dashboardFile.size() != kExpectedDashboardSize) {
    result.failedStep = "taille dashboard.bin";
    result.failedReason = "dashboard.bin taille invalide";
    dashboardFile.close();
    return result;
  }

  if (!initEpaperIfNeeded()) {
    result.failedStep = "initialisation epaper";
    result.failedReason = "Impossible d'initialiser l'ecran";
    dashboardFile.close();
    return result;
  }

  const unsigned long startAll = millis();
  const unsigned long startDraw = millis();

  epaper.fillSprite(TFT_WHITE);

  uint8_t buffer[kReadChunkSize];
  bool invalidFound = false;
  bool readError = false;

  for (uint16_t y = 0; y < kDashboardHeight; ++y) {
    uint16_t x = 0;

    while (x < kDashboardWidth) {
      const size_t remainingInRow = static_cast<size_t>(kDashboardWidth - x);
      const size_t toRead = min(remainingInRow, sizeof(buffer));
      int readCount = dashboardFile.read(buffer, toRead);
      if (readCount <= 0) {
        result.failedStep = "lecture dashboard.bin";
        result.failedReason = "Lecture interrompue avant fin du fichier";
        readError = true;
        break;
      }

      for (int i = 0; i < readCount; ++i) {
        const uint8_t pixel = buffer[i];
        if (pixel > kMaxPixelValue) {
          ++result.invalidBytes;
          invalidFound = true;
        }
        epaper.drawPixel(x + i, y, colorFromPixelIndex(pixel));
      }

      result.bytesRead += readCount;
      x += readCount;

      if (invalidFound) {
        break;
      }
    }

    if (invalidFound) {
      result.failedReason = "Index pixel invalide detecte";
      break;
    }

    if (readError) {
      break;
    }

    if (((y + 1) % 50) == 0) {
      Serial.printf("Ligne %u / %u\n", y + 1, kDashboardHeight);
    }
  }

  dashboardFile.close();

  result.drawDurationMs = millis() - startDraw;

  if (result.invalidBytes > 0 || readError || result.bytesRead != kExpectedDashboardSize) {
    if (result.failedReason.length() == 0) {
      result.failedReason = "validation echec";
    }
    return result;
  }

  const unsigned long startRefresh = millis();
  epaper.update();
  result.refreshDurationMs = millis() - startRefresh;

  result.totalDurationMs = millis() - startAll;
  result.success = true;
  g_lastScreenUpdateSuccess = true;
  g_lastScreenUpdateMs = millis();
  return result;
}

DownloadResult validateAndStoreDashboard() {
  DownloadResult result;
  result.failedStep = "initialisation HTTP";
  unsigned long startMs = millis();

  if (WiFi.status() != WL_CONNECTED && !connectWifi(kWifiTimeoutMs)) {
    result.failedStep = "connexion Wi-Fi";
    result.failedReason = "Wi-Fi non disponible";
    result.durationMs = millis() - startMs;
    return result;
  }

  WiFiClient client;
  HTTPClient http;

  http.setTimeout(kHttpTimeoutMs);
  result.failedStep = "debut de requete HTTP";
  if (!http.begin(client, kDashboardUrl)) {
    result.failedReason = "HTTPClient.begin() a echoue";
    result.durationMs = millis() - startMs;
    return result;
  }

  http.setUserAgent(kUserAgent);
  http.addHeader("X-EE04-RSSI", String(WiFi.RSSI()));
  const char* headerKeys[] = {"Content-Type"};
  http.collectHeaders(headerKeys, 1);

  result.httpCode = http.GET();
  if (result.httpCode != HTTP_CODE_OK) {
    result.failedStep = "code HTTP";
    result.failedReason = "Code HTTP != 200";
    result.durationMs = millis() - startMs;
    http.end();
    return result;
  }

  result.contentType = http.header("Content-Type");
  if (!result.contentType.equals(kExpectedMime)) {
    result.mimeDifferent = true;
    Serial.printf("Avertissement MIME inattendu : %s (attendu: %s)\n", result.contentType.c_str(), kExpectedMime);
  }

  File tmp = LittleFS.open(kTempDashboardPath, FILE_WRITE);
  if (!tmp) {
    result.failedStep = "creation /dashboard.tmp";
    result.failedReason = "Impossible d'ouvrir /dashboard.tmp en ecriture";
    result.durationMs = millis() - startMs;
    http.end();
    return result;
  }

  WiFiClient* stream = http.getStreamPtr();
  uint8_t buffer[256];
  result.failedStep = "transfert flux HTTP";

  while (http.connected()) {
    size_t available = stream->available();
    if (available == 0) {
      delay(1);
      continue;
    }

    const size_t toRead = min(available, sizeof(buffer));
    int readCount = stream->readBytes(buffer, toRead);
    if (readCount <= 0) {
      continue;
    }

    for (int i = 0; i < readCount; ++i) {
      if (buffer[i] > kMaxPixelValue) {
        result.invalidBytes++;
      }
    }

    tmp.write(buffer, readCount);
    result.bytesReceived += readCount;

    if (result.invalidBytes > 0 || result.bytesReceived > kExpectedDashboardSize) {
      result.failedStep = "validation pendant telechargement";
      if (result.invalidBytes > 0) {
        result.failedReason = "valeur pixel > 5 detectee";
      } else {
        result.failedReason = "taille recue superieure a la taille attendue";
      }
      break;
    }
  }

  tmp.close();
  result.durationMs = millis() - startMs;
  result.rssi = WiFi.RSSI();
  http.end();

  if (result.invalidBytes > 0 || result.bytesReceived != kExpectedDashboardSize) {
    if (result.failedReason.length() == 0) {
      if (result.bytesReceived < kExpectedDashboardSize) {
        result.failedReason = "taille recue inferieure a la taille attendue";
      } else if (result.bytesReceived > kExpectedDashboardSize) {
        result.failedReason = "taille recue superieure a la taille attendue";
      } else {
        result.failedReason = "validation echouee";
      }
    }
    Serial.printf("Echec de validation : %s (octets=%u, invalides=%u)\n", result.failedReason.c_str(), result.bytesReceived, result.invalidBytes);
    if (LittleFS.exists(kTempDashboardPath)) {
      LittleFS.remove(kTempDashboardPath);
      Serial.println("fichier temporaire supprime.");
    }
    return result;
  }

  File tmpVerify = LittleFS.open(kTempDashboardPath, FILE_READ);
  if (!tmpVerify) {
    result.failedStep = "ouverture de verification";
    result.failedReason = "Fichier /dashboard.tmp introuvable apres ecriture";
    if (LittleFS.exists(kTempDashboardPath)) {
      LittleFS.remove(kTempDashboardPath);
    }
    return result;
  }
  size_t tmpSize = tmpVerify.size();
  tmpVerify.close();
  if (tmpSize != kExpectedDashboardSize) {
    result.failedStep = "taille fichier temp";
    result.failedReason = "taille de /dashboard.tmp incorrecte";
    LittleFS.remove(kTempDashboardPath);
    return result;
  }

  bool hadOld = LittleFS.exists(kDashboardPath);
  if (hadOld) {
    if (!LittleFS.rename(kDashboardPath, kBackupDashboardPath)) {
      result.failedStep = "sauvegarde ancien fichier";
      result.failedReason = "Impossible de sauvegarder l'ancien dashboard.bin";
      LittleFS.remove(kTempDashboardPath);
      return result;
    }
  }

  result.failedStep = "remplacement atomique";
  if (!LittleFS.rename(kTempDashboardPath, kDashboardPath)) {
    result.failedStep = "renommage dashboard.tmp";
    result.failedReason = "rename(/dashboard.tmp -> /dashboard.bin) en erreur";
    if (hadOld) {
      LittleFS.rename(kBackupDashboardPath, kDashboardPath);
    }
    return result;
  }

  if (LittleFS.exists(kBackupDashboardPath)) {
    LittleFS.remove(kBackupDashboardPath);
  }

  result.success = true;
  result.oldKept = true;
  return result;
}

void printSuccess(uint32_t cycle, const DownloadResult& d, const DisplayResult& e) {
  Serial.println("===== RESULTAT CYCLE =====");
  const unsigned long totalCycleDuration = d.durationMs + e.totalDurationMs;
  Serial.printf("Cycle : %u\n", cycle);
  Serial.printf("Fichier final recu : %u octets\n", d.bytesReceived);
  Serial.printf("Code HTTP : %d\n", d.httpCode);
  Serial.printf("Type MIME : %s\n", d.contentType.c_str());
  Serial.printf("Duree telechargement : %lu ms\n", d.durationMs);
  Serial.printf("Duree dessin : %lu ms\n", e.drawDurationMs);
  Serial.printf("Duree refresh : %lu ms\n", e.refreshDurationMs);
  Serial.printf("Duree totale affichage : %lu ms\n", e.totalDurationMs);
  Serial.printf("Duree totale : %lu ms\n", totalCycleDuration);
  Serial.printf("RSSI : %d dBm\n", d.rssi);
  Serial.printf("Index invalides (affichage) : %u\n", e.invalidBytes);
  Serial.println("Resultat final : SUCCES");
  printLittleFsInfo();
}

void printDownloadFailure(uint32_t cycle, const DownloadResult& r) {
  Serial.println("===== RESULTAT CYCLE =====");
  Serial.printf("Cycle : %u\n", cycle);
  Serial.printf("Etape echec : %s\n", r.failedStep.c_str());
  if (r.httpCode > 0) {
    Serial.printf("Code HTTP : %d\n", r.httpCode);
  }
  if (r.failedReason.length() > 0) {
    Serial.printf("Erreur : %s\n", r.failedReason.c_str());
  }
  Serial.printf("Duree : %lu ms\n", r.durationMs);
  Serial.printf("Ancienne image conservee : %s\n", r.oldKept ? "OUI" : "NON");
  Serial.println("Resultat final : ECHEC");
}

void printDisplayFailure(uint32_t cycle, const DisplayResult& r, size_t receivedBytes, int rssi) {
  Serial.println("===== RESULTAT CYCLE =====");
  Serial.printf("Cycle : %u\n", cycle);
  Serial.printf("Etape echec affichage : %s\n", r.failedStep.c_str());
  if (r.failedReason.length() > 0) {
    Serial.printf("Erreur : %s\n", r.failedReason.c_str());
  }
  Serial.printf("Octets lus dashboard.bin : %u\n", receivedBytes);
  Serial.printf("Index invalides (affichage) : %u\n", r.invalidBytes);
  Serial.printf("RSSI : %d dBm\n", rssi);
  Serial.printf("Ancienne image conservee : OUI\n");
  Serial.println("Resultat final : ECHEC");
}

void setup() {
  Serial.begin(115200);
  while (!Serial) {
    delay(10);
  }

  delay(100);

  Serial.printf("\n=== %s ===\n", kProjectName);
  Serial.printf("Phase %s\n", kProjectPhase);

  if (!mountLittleFS()) {
    Serial.println("Arret : LittleFS indisponible.");
    while (true) {
      delay(1000);
    }
  }

  printBootInfo();

  g_nextDownloadAtMs = millis() + kFirstDownloadDelayMs;
  g_lastStatusReportMs = millis();

  g_displayInProgress = true;
  DisplayResult startupDisplay = afficherDashboardDepuisLittleFS();
  if (!startupDisplay.success) {
    Serial.printf("Affichage initial non effectue : %s\n", startupDisplay.failedReason.c_str());
  }
  g_displayInProgress = false;

  connectWifi(kWifiTimeoutMs);
}

void loop() {
  const unsigned long now = millis();

  if (!g_displayInProgress && (long)(now - g_lastStatusReportMs) >= (long)kStatusIntervalMs) {
    printPeriodicStatus(now);
    g_lastStatusReportMs = now;
  }

  if (WiFi.status() != WL_CONNECTED && (long)(now - g_lastReconnectAttemptMs) >= 5000) {
    connectWifi(kWifiTimeoutMs);
    g_lastReconnectAttemptMs = now;
  }

  if ((long)(now - g_nextDownloadAtMs) >= 0 && !g_displayInProgress) {
    g_cycleCount++;
    Serial.printf("\n=== Debut cycle %u ===\n", g_cycleCount);
    g_displayInProgress = true;

    DownloadResult downloadResult = validateAndStoreDashboard();
    if (!downloadResult.success) {
      printDownloadFailure(g_cycleCount, downloadResult);
      g_displayInProgress = false;
      g_nextDownloadAtMs = millis() + kDownloadIntervalMs;
      return;
    }

    DisplayResult displayResult = afficherDashboardDepuisLittleFS();
    if (!displayResult.success) {
      printDisplayFailure(g_cycleCount, displayResult, downloadResult.bytesReceived, downloadResult.rssi);
      g_displayInProgress = false;
      g_nextDownloadAtMs = millis() + kDownloadIntervalMs;
      return;
    }

    printSuccess(g_cycleCount, downloadResult, displayResult);

    g_displayInProgress = false;
    g_nextDownloadAtMs = millis() + kDownloadIntervalMs;
  }

  delay(20);
}
