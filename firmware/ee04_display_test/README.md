# Phase 1.4A.1 - Conversion image pour Spectra 6

Ce dossier contient un outil de conversion hors firmware, utilisé sur PC pour comparer
plusieurs variantes de conversion de `assets/dashboard.png` vers la palette 6 couleurs
du Spectra 6 (`800 x 480`).

## Script

- Fichier : `tools/convert_spectra6.py`
- Type : Python + Pillow uniquement
- Palette utilisée :
  - 0 : noir `(0, 0, 0)`
  - 1 : blanc `(255, 255, 255)`
  - 2 : rouge `(255, 0, 0)`
  - 3 : jaune `(255, 255, 0)`
  - 4 : vert `(0, 255, 0)`
  - 5 : bleu `(0, 0, 255)`

## Commande

- Commande simple :
  - `python tools/convert_spectra6.py`
- Option :
  - `python tools/convert_spectra6.py --input assets/dashboard.png`

## Fichiers produits

- `generated/dashboard_direct.png`
- `generated/dashboard_direct.bin`
- `generated/dashboard_fs80.png`
- `generated/dashboard_fs80.bin`
- `generated/dashboard_fs60.png`
- `generated/dashboard_fs60.bin`
- `generated/dashboard_fs40.png`
- `generated/dashboard_fs40.bin`
- `generated/dashboard_bayer4.png`
- `generated/dashboard_bayer4.bin`
- `generated/dashboard_bayer8.png`
- `generated/dashboard_bayer8.bin`
- `generated/dashboard_hybrid.png`
- `generated/dashboard_hybrid.bin`

Le dossier `generated/` est créé automatiquement.

Les fichiers `.bin` contiennent **un octet par pixel** avec **un index palette de 0 à 5**,
dans l’ordre ligne par ligne (de gauche à droite puis de haut en bas).
La taille attendue est `384000` octets (`800 x 480`).

## Variantes produites

- `dashboard_direct`
  - Conversion directe.
  - Chaque pixel est converti vers la couleur de la palette la plus proche
    (distance euclidienne RGB).
- `dashboard_fs80`
  - Floyd-Steinberg avec facteur de diffusion `0.8`.
- `dashboard_fs60`
  - Floyd-Steinberg avec facteur de diffusion `0.6`.
- `dashboard_fs40`
  - Floyd-Steinberg avec facteur de diffusion `0.4`.
- `dashboard_bayer4`
  - Ordered dithering Bayer 4x4 avant quantification palette.
- `dashboard_bayer8`
  - Ordered dithering Bayer 8x8 avant quantification palette.
- `dashboard_hybrid`
  - Zone A : `y = 360..479` -> conversion directe sans dithering.
  - Zone B : `x = 500..779` et `y = 40..319` -> conversion directe sans dithering.
  - Zone C (reste) : Floyd-Steinberg à `60 %`.

## Validation effectuée par le script

- Vérification du fichier source :
  - existant
  - lisible
  - dimensions exactes `800 x 480` (sinon arrêt)
- Vérification de chaque image de sortie :
  - taille `800 x 480`
  - mode `RGB`
  - uniquement les 6 couleurs autorisées
- Vérification des `.bin` :
  - 1 octet par pixel
  - index entre 0 et 5
  - taille exacte `384000` octets
