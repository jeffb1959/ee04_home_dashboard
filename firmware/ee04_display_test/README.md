# Phase 1.4A.2 - Intégration image binaire en firmware (PROGMEM)

Ce projet intègre temporairement l'image de test `dashboard_hybrid40_bwui.bin` dans le
firmware ESP32 pour une validation visuelle réelle sur l'écran Spectra 6.

## Script ajouté : `tools/bin_to_header.py`

- Rôle : convertir un fichier binaire d'indices (`0..5`) en header C++ `PROGMEM`.
- Fichier source par défaut : `generated/dashboard_hybrid40_bwui.bin`
- Vérifications :
  - existence du fichier source
  - taille exacte `384000` octets (`800 x 480`)
  - indices compris entre `0` et `5`
- Sortie : `include/dashboard_image.h`
- Vérifie/affiche en fin de génération :
  - fichier source
  - taille source
  - fichier généré
  - nombre d'octets
  - validation réussie

Commande :
- `python tools/bin_to_header.py`

## Fichier généré

- `include/dashboard_image.h`
- Contenu attendu :
  - `#pragma once`
  - `#include <Arduino.h>`
  - `DASHBOARD_IMAGE_WIDTH`
  - `DASHBOARD_IMAGE_HEIGHT`
  - `DASHBOARD_IMAGE_SIZE`
  - `const uint8_t DASHBOARD_IMAGE_DATA[] PROGMEM`

L’image est intégrée temporairement dans le firmware sous forme de tableau PROGMEM.

## Firmware (`src/main.cpp`)

- Affiche un en-tête série :
  - `Phase 1.4A.2`
  - `Affichage image Spectra 6 intégrée`
- Initialise l'écran, vérifie les dimensions déclarées, puis affiche l'image à partir de
  `DASHBOARD_IMAGE_DATA` via `drawPixel()`.
- Mise à jour écran effectuée une seule fois avec `epaper.update()`.
- Affiche :
  - durée d'initialisation
  - durée de dessin
  - durée de refresh
  - durée totale
  - nombre d'indices invalides détectés
- Log de progression toutes les 50 lignes.
- Après affichage, ne relance plus de refresh.
- `loop()` affiche toutes les 30 secondes :
  - `EE04 actif - image de test affichée.`

## Procédure Build / Upload / Monitor

- Build : `platformio run`
- Upload : `platformio run --target upload`
- Monitor : `platformio device monitor`

## Limites de cette méthode

- La méthode binaire->header augmente fortement la taille compilée du firmware (données en flash).
- Toute modification d'image nécessite de relancer `bin_to_header.py` et de recompiler.
- Méthode destinée à la validation visuelle rapide, pas une solution de production finale.
