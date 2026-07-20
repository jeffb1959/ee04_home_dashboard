# Phase 1.5B.2 — telechargement valide puis affichage ePaper

## Objectif

Ajouter l affichage de `/dashboard.bin` sur l ecran ePaper du EE04 avec le flux suivant:
- telechargement depuis le Raspberry Pi
- validation binaire strictement `1 octet par pixel`
- ecriture atomique dans LittleFS
- affichage uniquement apres validation complete

## Flux fonctionnel

1. Le firmware telecharge `dashboard.bin` via HTTP et conserve `/dashboard.tmp` pendant le telechargement.
2. Le fichier est valide si:
   - code HTTP = `200`
   - taille exacte = `384000` octets
   - chaque octet compris entre `0` et `5`
3. En cas de succ?s, remplacement atomique:
   - `/dashboard.tmp` remplace `/dashboard.bin`
   - ancien fichier retire uniquement apres succes complet
4. L affichage n est effectue que si le telechargement est valide.
5. Le rendu pixel par pixel est realise ligne par ligne sans charger l image complete en RAM.

## Format attendue binaire

- Resolution: `800 x 480`
- Taille: `384000` octets
- Palette:
  - `0 -> noir`
  - `1 -> blanc`
  - `2 -> rouge`
  - `3 -> jaune`
  - `4 -> vert`
  - `5 -> bleu`

## Comportement ePaper

- Palette et constantes mappes sur les couleurs Seeed/GFX
- Tampon initialise en blanc avant dessin.
- Lecture du fichier avec petit tampon (1024 octets).
- Dessin ligne par ligne avec `drawPixel`.
- Rapport console toutes ~50 lignes (`Ligne 50 / 480`, etc).
- `epaper.update()` appele une seule fois par cycle reussi.
- Si un affichage echoue, l image precedente reste visible.

## Build / Upload / Monitor

Depuis `firmware/ee04_dashboard_runtime`:
- `pio run`
- `pio run -t upload`
- `pio device monitor -b 115200`

## Cadence

- 1er telechargement au demarrage + ~5 secondes.
- Telechargement + affichage toutes les 5 minutes (prochaine iteration basee sur fin complete du cycle).
- Rapport d etat toutes les 10 secondes.

## Test manuel (5 cycles minimum)

1. Lancer le moniteur serie en 115200.
2. Verifier au demarrage:
   - boot info (projet, phase, reboot, MAC, LittleFS)
   - affichage initial si `/dashboard.bin` valide present.
3. Attendre au moins 5 cycles.
4. Verifier pour chaque cycle:
   - code HTTP, MIME, octets recus, durees de telechargement/dessin/refresh, RSSI
   - etat final `SUCCES` ou `ECHEC`
5. Verifier en cas d erreur d affichage que l ancienne image reste visible (pas de ecran vide ni nouveau fichier partiel).

## Contraintes appliquees

- Pas de deep sleep.
- Pas d usage de PNG.
- Pas de Home Assistant.
- Pas d upload automatique.
- Pas de modification de `platformio.ini`, `include/wifi_secrets.h`, `lib/driver/driver.h`, `lib/Seeed_GFX`.
