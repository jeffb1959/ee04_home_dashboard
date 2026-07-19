# EE04 Home Dashboard

## Phase 1.0

Cette phase fournit un serveur Flask minimal qui génère dynamiquement avec
Pillow une image PNG de 800 × 480 pixels. Elle permet de valider la base du
serveur et le format de l'image avant l'ajout des sources de données et de
l'écran ePaper EE04.

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
- Image générée : http://localhost:5050/dashboard.png
- État du service : http://localhost:5050/health

Depuis un autre appareil du réseau, remplacer `localhost` par l'adresse IP du
Raspberry Pi. La dernière image générée est aussi sauvegardée dans
`output/dashboard.png`.

## Tests automatisés

```bash
source .venv/bin/activate
pytest
```

La phase 1.0 n'intègre pas encore les sources de données externes, Home
Assistant, la météo, MGM, Outlook, Chronogolf, ni la communication avec
l'écran EE04. Aucun service systemd n'est installé à cette étape.
