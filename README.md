# EE04 Home Dashboard

## Phase 1.6B

Le serveur Flask génère avec Pillow une maquette réaliste de 800 × 480 pixels à
partir d'un arrière-plan illustré. La phase 1.6B alimente la météo principale
avec l'état actuel de `weather.forecast_maison` : condition traduite en
français, température, humidité et pression. La section **EXTÉRIEUR** demeure
distincte et continue d'afficher les trois mesures du BME280 exposé dans Home
Assistant. Le serveur conserve la conversion hybride vers la palette Spectra
6 et le fichier de 384 000 octets consommé par le firmware EE04.

La logique visuelle se trouve dans `dashboard_renderer.py`; `app.py` conserve
les routes HTTP et délègue la création de l'image au renderer. La conversion
isolée dans `spectra6_converter.py` utilise uniquement Pillow et Python, sans
NumPy. `config.py` charge la configuration locale et
`home_assistant_client.py` contient le client REST et le repli sur cache.

## Configuration Home Assistant

Copier le modèle local, puis remplacer ses valeurs :

```bash
cp .env.example .env
chmod 600 .env
```

Variables obligatoires dans `.env` :

```dotenv
HOME_ASSISTANT_URL=http://IP_OU_HOST:8123
HOME_ASSISTANT_TOKEN=JETON_LONGUE_DUREE
HA_ENTITY_TEMPERATURE=sensor.xxx
HA_ENTITY_HUMIDITY=sensor.xxx
HA_ENTITY_PRESSURE=sensor.xxx
HA_ENTITY_WEATHER=weather.forecast_maison
```

`HOME_ASSISTANT_URL` doit être l'adresse joignable de Home Assistant depuis le
Raspberry Pi. Ne pas ajouter `/api` à cette adresse. Les identifiants d'entité
peuvent être vérifiés dans Home Assistant, dans **Outils de développement →
États**, en recherchant les trois capteurs du BME280 et l'entité météo.
`HA_ENTITY_WEATHER` désigne uniquement la météo principale; elle ne remplace
pas les entités BME280 de la section **EXTÉRIEUR**.

Pour créer le jeton, ouvrir le profil utilisateur Home Assistant, aller à la
section **Jetons d'accès longue durée**, créer un jeton dédié au tableau de
bord, puis le copier immédiatement dans `.env`. Home Assistant n'affiche le
jeton complet qu'au moment de sa création. Ne jamais le placer dans
`.env.example`, le README, un journal ou Git.

Les variables déjà présentes dans l'environnement du processus ont priorité
sur celles de `.env`. Le projet n'ajoute pas de bibliothèque dotenv : le format
simple `NOM=valeur` est chargé directement par `config.py`.

### Tolérance aux pannes et cache

Chaque rendu demande les trois entités BME280 et l'entité météo par
`GET /api/states/<entity_id>` avec l'en-tête `Authorization: Bearer …`. Les
états `unknown`, `unavailable`, les réponses non numériques, les attributs
météo manquants, une entité absente, un jeton refusé et les pannes réseau sont
journalisés sans interrompre Flask.

Après une lecture réussie, les dernières valeurs BME280 et météo valides sont
écrites atomiquement dans `data/home_assistant_cache.json`, dans des sections
distinctes. Si une lecture suivante échoue, les valeurs en cache sont
affichées. Sans cache, une condition « Données indisponibles » et les
placeholders `-- °C`, `-- %` et `--`/`----` pour la pression sont utilisés.
`.env` et ce cache sont ignorés par Git.

## Arrière-plan

Le fichier utilisé par défaut doit se trouver ici :

```text
assets/backgrounds/lundi_beau.png
```

L'arrière-plan est adapté en haute qualité à une zone supérieure de
800 × 360 pixels, en conservant son ratio et avec un léger recadrage si
nécessaire. La météo principale issue de `weather.forecast_maison` reste dans
cette partie illustrée; le BME280 conserve sa zone **EXTÉRIEUR**.

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

Vérification rapide depuis le Raspberry Pi :

```bash
curl -s http://localhost:5050/health
curl -o /tmp/dashboard.png http://localhost:5050/dashboard.png
curl -o /tmp/dashboard.bin http://localhost:5050/dashboard.bin
wc -c /tmp/dashboard.bin
```

La dernière commande doit afficher `384000`. Ouvrir `/dashboard.png` dans un
navigateur permet de vérifier visuellement la météo principale et les mesures
distinctes de la section **EXTÉRIEUR**; `/dashboard-spectra6.png` permet de
vérifier leur lisibilité après conversion.

`/health` conserve l'état général du service et ajoute un objet de ce type :

```json
{
  "home_assistant": {
    "configured": true,
    "last_fetch_ok": true,
    "source": "live",
    "entities": {
      "temperature": "sensor.bme280_temperature",
      "humidity": "sensor.bme280_humidity",
      "pressure": "sensor.bme280_pressure"
    }
  },
  "weather": {
    "configured": true,
    "entity_id": "weather.forecast_maison",
    "last_fetch_ok": true,
    "source": "live",
    "condition_raw": "cloudy",
    "condition_fr": "Nuageux"
  }
}
```

Pour les deux diagnostics, `source` vaut `live`, `cache` ou `fallback`. Le
jeton n'est jamais retourné. `/health` reflète la dernière tentative effectuée
par une route de rendu; il ne déclenche pas lui-même de requête vers Home
Assistant.

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

Les appels HTTP Home Assistant sont simulés dans les tests : leur exécution ne
nécessite ni serveur Home Assistant ni vrai jeton. La suite vérifie aussi que
`/dashboard.png` reste disponible, que `/dashboard.bin` contient exactement
384 000 octets et que `/health` n'expose aucun secret.

## Ce qui reste fictif ou non intégré

Après la phase 1.6B, la météo actuelle principale provient de
`weather.forecast_maison` et la section **EXTÉRIEUR** provient toujours du
BME280. Restent fictifs ou volontairement absents :

- les températures minimale et maximale et les prévisions détaillées;
- les alertes météo et toute intégration MGM supplémentaire;
- la prochaine activité MGM et les participants;
- les données de diagnostic Wi-Fi, l'heure de mise à jour et l'état affiché;
- toute donnée Outlook ou Chronogolf.

Cette phase ne modifie ni les projets firmware, ni les arrière-plans, ni la
logique Spectra 6 côté EE04.
