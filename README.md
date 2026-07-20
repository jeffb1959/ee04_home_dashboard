# EE04 Home Dashboard

## Phase 1.5A

Le serveur Flask génère avec Pillow une maquette réaliste de 800 × 480 pixels à
partir d'un arrière-plan illustré. La phase 1.5A ajoute la conversion hybride
vers la palette Spectra 6 et un fichier directement consommable par le futur
firmware EE04. Les blocs météo, activité MGM et diagnostic utilisent encore des
données fictives afin de valider la mise en page.

La logique visuelle se trouve dans `dashboard_renderer.py`; `app.py` conserve
les routes HTTP et délègue la création de l'image au renderer. La conversion
isolée dans `spectra6_converter.py` utilise uniquement Pillow et Python, sans
NumPy.

## Arrière-plan

Le fichier utilisé par défaut doit se trouver ici :

```text
assets/backgrounds/lundi_beau.png
```

L'arrière-plan est adapté en haute qualité à une zone supérieure de
800 × 360 pixels, en conservant son ratio et avec un léger recadrage si
nécessaire. La météo reste dans cette partie illustrée.

Les 120 pixels inférieurs forment une bande crème opaque et indépendante de
l'illustration. Elle contient les quatre lignes de l'activité MGM fictive,
puis une dernière ligne plus discrète réservée au diagnostic.

Si le fichier est absent ou illisible, le serveur génère automatiquement une
image de secours claire portant le message `ARRIÈRE-PLAN INTROUVABLE`. La route
`/dashboard.png` reste donc disponible et retourne toujours l'image couleur
originale, sans conversion ni tramage.

Le rendu privilégie les polices système de Raspberry Pi OS. Une copie locale
de DejaVu Sans, accompagnée de sa licence dans `assets/fonts/`, garantit le
rendu des accents français si ces polices système sont absentes.

## Installation

À la racine du projet, activer l'environnement virtuel existant et installer
les dépendances :

```bash
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Lancement

```bash
source .venv/bin/activate
python app.py
```

Le serveur écoute sur toutes les interfaces réseau, au port `5050`.

## URL de test

- Page d'accueil : http://localhost:5050/
- Image couleur originale : http://localhost:5050/dashboard.png
- Binaire pour le firmware : http://localhost:5050/dashboard.bin
- Aperçu de la conversion : http://localhost:5050/dashboard-spectra6.png
- État du service : http://localhost:5050/health

Depuis un autre appareil du réseau, remplacer `localhost` par l'adresse IP du
Raspberry Pi. Les dernières versions sont aussi sauvegardées dans
`output/dashboard.png`, `output/dashboard.bin` et
`output/dashboard_spectra6.png`.

## Format binaire Spectra 6

La route `GET /dashboard.bin` repart directement de la même image RGB originale
que `/dashboard.png`; elle ne reconvertit jamais un PNG déjà tramé. La réponse
utilise le type `application/octet-stream` et contient exactement 384 000
octets, soit un octet par pixel, parcouru de gauche à droite puis de haut en
bas. Les index sont :

- `0` : noir
- `1` : blanc
- `2` : rouge
- `3` : jaune
- `4` : vert
- `5` : bleu

La conversion hybride applique Floyd–Steinberg avec 40 % de diffusion et la
palette complète sur le fond illustré. Deux zones sont protégées et converties
depuis leurs pixels RGB originaux par luminance, avec un seuil initial de 180,
sans tramage et uniquement en noir ou blanc :

- carte météo : `x = 500..779`, `y = 40..319`;
- bande inférieure : `x = 0..799`, `y = 360..479`.

Aucune erreur de diffusion ne peut entrer dans ces zones ni en sortir. La route
`GET /dashboard-spectra6.png` expose l'aperçu RGB 800 × 480 correspondant pour
une vérification rapide dans un navigateur. Les trois réponses de tableau de
bord désactivent le cache HTTP.

## Tests automatisés

```bash
source .venv/bin/activate
pytest
```

La phase 1.5A n'intègre pas encore Home Assistant, les données météo réelles,
MGM réel, Outlook, Chronogolf, ni la communication avec l'écran EE04. Les
valeurs affichées sont des données de démonstration. Le serveur produit le
fichier attendu, mais le firmware ne le télécharge pas encore. Aucun service
systemd n'est installé à cette étape.
