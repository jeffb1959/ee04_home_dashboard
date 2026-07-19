#include <Arduino.h>
#include "driver.h"
#include <TFT_eSPI.h>

EPaper epaper;

const uint32_t HAUTEUR_ECRAN = 480;

void setup() {
  Serial.begin(115200);
  delay(1500);

  Serial.println();
  Serial.println("=== EE04 Display Test ===");
  Serial.println("Debut du test six couleurs");

  Serial.println("1) Debut du test six couleurs.");
  const uint32_t debutTest = millis();

  // Initialisation de l'ecran
  Serial.println("Initialisation de l'ecran...");
  const uint32_t debutInitialisation = millis();
  epaper.begin();
  const uint32_t dureeInitialisation = millis() - debutInitialisation;
  Serial.println("Initialisation terminee.");

  // Dessin des 6 bandes en memoire (fillRect)
  const uint32_t debutDessin = millis();
  epaper.fillRect(0, 0, 133, HAUTEUR_ECRAN, TFT_BLACK);
  epaper.fillRect(133, 0, 133, HAUTEUR_ECRAN, TFT_WHITE);
  epaper.fillRect(266, 0, 133, HAUTEUR_ECRAN, TFT_RED);
  epaper.fillRect(399, 0, 133, HAUTEUR_ECRAN, TFT_YELLOW);
  epaper.fillRect(532, 0, 133, HAUTEUR_ECRAN, TFT_GREEN);
  epaper.fillRect(665, 0, 135, HAUTEUR_ECRAN, TFT_BLUE);
  const uint32_t dureeDessin = millis() - debutDessin;
  Serial.println("Dessin des bandes termine.");

  // Rafraichissement final (un seul appel)
  Serial.println("Debut du rafraichissement.");
  const uint32_t debutRafraichissement = millis();
  epaper.update();
  const uint32_t dureeRafraichissement = millis() - debutRafraichissement;
  const uint32_t dureeTotale = millis() - debutTest;

  Serial.println("Test six couleurs termine.");
  Serial.printf(
    "Duree initialisation: %lu ms\n"
    "Duree dessin en memoire: %lu ms\n"
    "Duree rafraichissement: %lu ms\n"
    "Duree totale: %lu ms\n",
    static_cast<unsigned long>(dureeInitialisation),
    static_cast<unsigned long>(dureeDessin),
    static_cast<unsigned long>(dureeRafraichissement),
    static_cast<unsigned long>(dureeTotale)
  );
}

void loop() {
  static uint32_t dernierRapport = 0;

  if (millis() - dernierRapport >= 30000) {
    dernierRapport = millis();
    Serial.println("EE04 actif - mire six couleurs affichee.");
  }

  delay(10);
}
