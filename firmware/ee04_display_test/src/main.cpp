#include <Arduino.h>
#include "driver.h"
#include <TFT_eSPI.h>

EPaper epaper;

void setup() {
  Serial.begin(115200);
  delay(1500);

  Serial.println();
  Serial.println("=== EE04 Display Test ===");
  Serial.println("Phase 1.3A - écran blanc");

  Serial.println("Initialisation de l'écran...");
  const uint32_t debutInitialisation = millis();

  epaper.begin();

  Serial.printf(
    "Initialisation terminée en %lu ms\n",
    static_cast<unsigned long>(millis() - debutInitialisation)
  );

  Serial.println("Remplissage du tampon en blanc...");
  epaper.fillScreen(TFT_WHITE);

  Serial.println("Début du rafraîchissement...");
  const uint32_t debutRafraichissement = millis();

  epaper.update();

  const uint32_t duree = millis() - debutRafraichissement;

  Serial.printf(
    "Rafraîchissement terminé en %lu ms\n",
    static_cast<unsigned long>(duree)
  );

  Serial.println("Test terminé. Aucun autre rafraîchissement ne sera lancé.");
}

void loop() {
  static uint32_t dernierRapport = 0;

  if (millis() - dernierRapport >= 30000) {
    dernierRapport = millis();
    Serial.println("EE04 actif - test écran blanc terminé.");
  }

  delay(10);
}