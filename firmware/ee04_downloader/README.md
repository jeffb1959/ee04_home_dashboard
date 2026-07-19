# Phase 1.2 – Diagnostic téléchargement dashboard (ee04_home_dashboard)

## Objectif

La phase 1.2 valide uniquement le chemin réseau et le stockage local :

- connexion Wi-Fi ESP32-S3 (XIAO ESP32-S3),
- téléchargement périodique de `dashboard.png` depuis le serveur Flask,
- écriture sûre dans LittleFS.

Aucune gestion d’écran ePaper ni redémarrage automatique de carte n’est implémentée dans cette phase.

## Emplacement des secrets

Créer (ou compléter) le fichier :

`include/wifi_secrets.h`

Exemple :

```cpp
#pragma once

#define WIFI_SSID "MON_SSID"
#define WIFI_PASSWORD "MON_MOT_DE_PASSE"
#define DASHBOARD_URL "http://192.168.2.172:5050/dashboard.png"
```

⚠️ Ce fichier est ignoré par Git et ne doit pas être commis.

## Commandes PlatformIO

- Build : `pio run`
- Upload : `pio run -t upload`
- Monitor : `pio device monitor -b 115200`

## Comportement attendu dans le moniteur série

Au démarrage :

- nom du projet,
- phase (`1.2`),
- raison du redémarrage,
- MAC,
- espace total / utilisé LittleFS.

Ensuite :

- état de montage LittleFS (direct puis formatage secours en échec si nécessaire),
- tentative de connexion Wi-Fi avec points de progression,
- informations Wi-Fi une fois connecté : IP, MAC, canal, RSSI,
- rapport périodique toutes les 10 secondes (uptime, état Wi-Fi, IP, RSSI, temps avant prochain téléchargement),
- cycle de téléchargement toutes les 45 secondes (premier cycle à ~5 s),
- log détaillé de succès/échec avec :
  - numéro de cycle,
  - code HTTP,
  - MIME,
  - octets reçus,
  - taille réelle du fichier,
  - durée,
  - RSSI,
  - succès ou échec,
  - et confirmation de conservation de l’ancienne image si échec.

## Procédure de test (20 téléchargements consécutifs)

1. Lancer `pio run` pour vérifier la compilation.
2. Flasher la carte : `pio run -t upload`.
3. Ouvrir le moniteur : `pio device monitor -b 115200`.
4. Vérifier l’apparition du premier téléchargement autour de `5000 ms`.
5. Vérifier qu’un cycle complet est déclenché toutes les `45000 ms` après la fin du précédent.
6. Confirmer à chaque succès :
   - code HTTP `200`,
   - MIME `image/png`,
   - signature PNG valide,
   - remplacement de `/dashboard.png` uniquement si le flux est valide.
7. Laisser tourner 20 cycles et noter les 20 logs `SUCCES`/`ECHEC`.
8. Vérifier qu’en cas d’échec réseau :
   - aucun redémarrage,
   - pas d’effacement de l’image valide existante,
   - reprise de la tentative de reconnexion périodique.
9. Contrôler `LittleFS` si nécessaire après la session en observant les tailles et l’espace libre affiché.
