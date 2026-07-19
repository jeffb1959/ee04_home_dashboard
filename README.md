# EE04 Home Dashboard

## Phase 1.1

Cette phase introduit le premier moteur de composition visuelle du projet. Le
serveur Flask génère avec Pillow une maquette réaliste de 800 × 480 pixels à
partir d'un arrière-plan illustré. Les blocs météo, activité MGM et diagnostic
utilisent encore des données fictives afin de valider la mise en page.

La logique visuelle se trouve dans `dashboard_renderer.py`; `app.py` conserve
les routes HTTP et délègue la création de l'image au renderer.

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
`/dashboard.png` reste donc disponible.

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

La phase 1.1 n'intègre pas encore Home Assistant, les données météo réelles,
MGM réel, Outlook, Chronogolf, ni la communication avec l'écran EE04. Les
valeurs affichées sont des données de démonstration. Aucun service systemd
n'est installé à cette étape.
