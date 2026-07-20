#include <Arduino.h>
#include <FS.h>
#include <HTTPClient.h>
#include <LittleFS.h>
#include <WiFi.h>
#include <WiFiClient.h>
#include <esp_system.h>

#include "wifi_secrets.h"

// =====================================================================
// Phase 1.5B.1 : téléchargement + validation binaire dashboard
// =====================================================================

static const char* kProjectName = "ee04_home_dashboard";
static const char* kProjectPhase = "1.5B.1";
static const char* kDashboardUrl = DASHBOARD_URL;
static const char* kDashboardPath = "/dashboard.bin";
static const char* kTempDashboardPath = "/dashboard.tmp";
static const char* kBackupDashboardPath = "/dashboard.bin.bak";
static const char* kUserAgent = "EE04-Home-Dashboard-Phase1.5B.1/1.0";
static const char* kExpectedMime = "application/octet-stream";

static const size_t kExpectedDashboardSize = 384000;  // 800 x 480 x 1 octet
static const uint8_t kMaxPixelValue = 5;

static const unsigned long kWifiTimeoutMs = 20000;
static const unsigned long kHttpTimeoutMs = 15000;
static const unsigned long kFirstDownloadDelayMs = 5000;
static const unsigned long kDownloadIntervalMs = 5UL * 60UL * 1000UL;
static const unsigned long kStatusIntervalMs = 10UL * 1000UL;

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

unsigned long g_nextDownloadAtMs = 0;
unsigned long g_lastStatusReportMs = 0;
unsigned long g_lastReconnectAttemptMs = 0;
uint32_t g_cycleCount = 0;

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
  Serial.printf("LittleFS monte : %s\n", "oui");
  printLittleFsInfo();
}

bool mountLittleFS() {
  Serial.println("Montage LittleFS (sans formatage de secours)...");
  if (LittleFS.begin(false)) {
    Serial.println("LittleFS monte avec succes.");
    return true;
  }

  Serial.println("Montage LittleFS initial echoue. Tentative de formatage de secours...");
  if (!LittleFS.format()) {
    Serial.println("Formatage LittleFS impossible.");
    return false;
  }

  Serial.println("Formatage execute, tentative de remontage...");
  if (!LittleFS.begin(false)) {
    Serial.println("Remontage LittleFS après formatage impossible.");
    return false;
  }

  Serial.println("LittleFS monte après formatage.");
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

void printSuccess(uint32_t cycle, const DownloadResult& r) {
  Serial.println("===== RESULTAT TELECHARGEMENT =====");
  Serial.printf("Cycle : %u\n", cycle);
  Serial.printf("Code HTTP : %d\n", r.httpCode);
  Serial.printf("Type MIME : %s\n", r.contentType.c_str());
  Serial.printf("Octets recus : %u\n", r.bytesReceived);
  printLittleFsInfo();
  Serial.printf("Duree : %lu ms\n", r.durationMs);
  Serial.printf("RSSI : %d dBm\n", r.rssi);
  Serial.printf("Indices invalides : %u\n", r.invalidBytes);
  Serial.println("Resultat final : SUCCES");
  if (r.mimeDifferent) {
    Serial.println("Attention: MIME different de application/octet-stream.");
  }
}

void printFailure(uint32_t cycle, const DownloadResult& r) {
  Serial.println("===== RESULTAT TELECHARGEMENT =====");
  Serial.printf("Cycle : %u\n", cycle);
  Serial.printf("Etape echecee : %s\n", r.failedStep.c_str());
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

  connectWifi(kWifiTimeoutMs);
}

void loop() {
  const unsigned long now = millis();

  if ((long)(now - g_lastStatusReportMs) >= (long)kStatusIntervalMs) {
    printPeriodicStatus(now);
    g_lastStatusReportMs = now;
  }

  if (WiFi.status() != WL_CONNECTED && (long)(now - g_lastReconnectAttemptMs) >= 5000) {
    connectWifi(kWifiTimeoutMs);
    g_lastReconnectAttemptMs = now;
  }

  if ((long)(now - g_nextDownloadAtMs) >= 0) {
    g_cycleCount++;
    Serial.printf("\n=== Debut cycle %u ===\n", g_cycleCount);

    DownloadResult result = validateAndStoreDashboard();
    if (result.success) {
      printSuccess(g_cycleCount, result);
    } else {
      printFailure(g_cycleCount, result);
    }

    g_nextDownloadAtMs = now + kDownloadIntervalMs;
  }

  delay(20);
}
