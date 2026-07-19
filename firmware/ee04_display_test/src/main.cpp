#include <Arduino.h>
#include "driver.h"
#include <TFT_eSPI.h>
#include "dashboard_image.h"

EPaper epaper;

static const uint32_t LARGEUR_ATTENDUE = 800;
static const uint32_t HAUTEUR_ATTENDUE = 480;
static const uint32_t TAILLE_ATTENDUE = 384000;

static uint16_t couleur_depuis_index(uint8_t index) {
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

void setup() {
  Serial.begin(115200);
  delay(1500);

  Serial.println();
  Serial.println("Phase 1.4A.2");
  Serial.println("Affichage image Spectra 6 intégrée");

  Serial.println("Initialisation de l'ecran...");
  const uint32_t debutTest = millis();
  const uint32_t debutInitialisation = millis();
  epaper.begin();
  const uint32_t dureeInitialisation = millis() - debutInitialisation;

  Serial.printf(
    "Dimension declarees tableau : %u x %u\n",
    static_cast<unsigned int>(DASHBOARD_IMAGE_WIDTH),
    static_cast<unsigned int>(DASHBOARD_IMAGE_HEIGHT)
  );
  if (DASHBOARD_IMAGE_WIDTH != LARGEUR_ATTENDUE || DASHBOARD_IMAGE_HEIGHT != HAUTEUR_ATTENDUE) {
    Serial.println("Erreur : dimensions declarees != 800x480");
    return;
  }
  if (DASHBOARD_IMAGE_SIZE != TAILLE_ATTENDUE) {
    Serial.println("Erreur : taille declaree != 384000");
    return;
  }
  Serial.println("Dimensions de l'image valides.");

  // Préparer le tampon en blanc avant affichage pixel par pixel.
  epaper.fillScreen(TFT_WHITE);

  Serial.println("Debut du dessin de l'image...");
  const uint32_t debutDessin = millis();
  uint32_t invalides = 0;

  for (uint32_t indexPixel = 0; indexPixel < DASHBOARD_IMAGE_SIZE; indexPixel++) {
    const uint32_t x = indexPixel % LARGEUR_ATTENDUE;
    const uint32_t y = indexPixel / LARGEUR_ATTENDUE;

    const uint8_t idxCouleur = pgm_read_byte(&DASHBOARD_IMAGE_DATA[indexPixel]);
    uint8_t idxValide = idxCouleur;
    if (idxValide > 5) {
      invalides++;
      idxValide = 1; // sécurité visuelle: blanc
    }

    epaper.drawPixel(x, y, couleur_depuis_index(idxValide));

    // Progression toutes les 50 lignes pour ne pas saturer le moniteur.
    if ((y % 50) == 0 && x == 0) {
      Serial.printf("Progression : ligne %lu / %lu\n", static_cast<unsigned long>(y + 1), static_cast<unsigned long>(HAUTEUR_ATTENDUE));
    }
  }
  const uint32_t dureeDessin = millis() - debutDessin;

  Serial.println("Debut du rafraichissement...");
  const uint32_t debutRafraichissement = millis();
  epaper.update();
  const uint32_t dureeRafraichissement = millis() - debutRafraichissement;

  const uint32_t dureeTotale = millis() - debutTest;
  Serial.printf("Duree initialisation: %lu ms\n", static_cast<unsigned long>(dureeInitialisation));
  Serial.printf("Duree dessin: %lu ms\n", static_cast<unsigned long>(dureeDessin));
  Serial.printf("Duree rafraichissement: %lu ms\n", static_cast<unsigned long>(dureeRafraichissement));
  Serial.printf("Duree totale: %lu ms\n", static_cast<unsigned long>(dureeTotale));
  Serial.printf("Indices invalides detectes: %lu\n", static_cast<unsigned long>(invalides));
  Serial.println("SUCCES : Image Spectra 6 intégrée affichée.");
}

void loop() {
  static uint32_t dernierRapport = 0;
  if (millis() - dernierRapport >= 30000) {
    dernierRapport = millis();
    Serial.println("EE04 actif - image de test affichée.");
  }
  delay(10);
}
