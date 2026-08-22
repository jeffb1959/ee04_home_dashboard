# EE04 Home Dashboard

## Phase 1.6C

La phase **1.6C** passe Environnement Canada comme source météo principale.

Le serveur Flask continue de générer :

- `dashboard.png` (affichage 800 × 480 pour l’EPaper)
- `dashboard.bin` (format Spectra 6, 384 000 octets)
- `dashboard-spectra6.png` (aperçu conversion)

Le flux BME280 reste inchangé et conserve la carte **CAPTEUR EXTÉRIEUR**.

La carte météo principale affiche maintenant :

- `CONDITIONS ACTUELLES`
- température actuelle
- condition
- probabilité de précipitations
- min. et max.
- humidité
- pression
- direction et vitesse du vent

Un bandeau rouge **ALERTE MÉTÉO** est affiché en haut de l’écran uniquement quand une alerte est active.

## Configuration

Les variables sont lues de `.env`, puis écrasées par l’environnement courant.
Le token reste en mémoire et ne doit jamais être copié dans `.env.example`, les logs ou `/health`.

Copier le modèle :

```bash
cp .env.example .env
chmod 600 .env
```

Variables :

```dotenv
HOME_ASSISTANT_URL=http://IP_OU_HOST:8123
HOME_ASSISTANT_TOKEN=JETON_LONGUE_DUREE
HA_ENTITY_TEMPERATURE=sensor.xxx
HA_ENTITY_HUMIDITY=sensor.xxx
HA_ENTITY_PRESSURE=sensor.xxx
HA_ENTITY_WEATHER=weather.forecast_maison

HA_EC_WEATHER_ENTITY=weather.atelier_jeff_meteo_quebec_previsions
HA_EC_CONDITION=sensor.atelier_jeff_meteo_quebec_condition_actuelle
HA_EC_TEMPERATURE=sensor.atelier_jeff_meteo_quebec_temperature
HA_EC_HUMIDITY=sensor.atelier_jeff_meteo_quebec_humidite
HA_EC_PRESSURE=sensor.atelier_jeff_meteo_quebec_pression
HA_EC_WIND_DIRECTION_TEXT=sensor.atelier_jeff_meteo_quebec_direction_du_vent_2
HA_EC_WIND_SPEED=sensor.atelier_jeff_meteo_quebec_vitesse_du_vent
HA_EC_PRECIP_PROBABILITY=sensor.atelier_jeff_meteo_quebec_probabilite_de_precipitations
HA_EC_HIGH_TEMP=sensor.atelier_jeff_meteo_quebec_haute_temperature
HA_EC_LOW_TEMP=sensor.atelier_jeff_meteo_quebec_basse_temperature
HA_EC_SUMMARY=sensor.atelier_jeff_meteo_quebec_resume
HA_EC_ALERTS=sensor.atelier_jeff_meteo_quebec_alertes
HA_EC_ADVISORIES=sensor.atelier_jeff_meteo_quebec_avis
HA_EC_WATCHES=sensor.atelier_jeff_meteo_quebec_veilles
HA_EC_BULLETINS=sensor.atelier_jeff_meteo_quebec_bulletins
```

`HOME_ASSISTANT_URL` doit être l’adresse joignable depuis le Pi, sans `/api`.

## Architecture

- `config.py` charge la configuration, y compris les nouvelles entités Environnement Canada.
- `home_assistant_client.py` lit les entités par `GET /api/states/<entity_id>`, avec cache et fallback.
- `dashboard_renderer.py` formate la carte météo et la carte capteur.
- `app.py` expose les routes HTTP et alimente le rendu depuis `get_environment_canada_data()`.

Le client continue à réutiliser l’ancienne structure météo (`get_weather_data`) pour conserver une compatibilité minimale si la configuration Environnement Canada n’est pas complète.

## Gestion des données et tolérance

Pour chaque entité Home Assistant :

- `unknown`
- `unavailable`
- chaîne vide
- erreurs réseau

sont traités comme données non valides.

Le système :

- convertit proprement les valeurs numériques,
- garde les unités envoyées par Home Assistant,
- continue de fonctionner sur cache quand possible,
- évite tout arrêt de Flask même avec données incomplètes.

### Alertes météo

Les compteurs suivants sont lus :

- `HA_EC_ALERTS`
- `HA_EC_ADVISORIES`
- `HA_EC_WATCHES`
- `HA_EC_BULLETINS`

Une alerte est active si au moins un compteur est supérieur à zéro.

Le texte compact peut produire par exemple :

- `1 alerte`
- `1 veille / 1 bulletin`
- `1 alerte / 2 avis`

Le bandeau `ALERTE MÉTÉO` n’est affiché que si ce texte existe.

## `/health`

Nouveau bloc ajouté :

```json
{
  "environment_canada": {
    "configured": true,
    "last_fetch_ok": true,
    "source": "live",
    "condition": "Généralement nuageux",
    "alert_active": false,
    "alert_text": null,
    "entities": {...}
  }
}
```

`/health` n’expose pas le token.

## Installation

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

## Routes

- Page d’accueil : `http://localhost:5050/`
- `http://localhost:5050/dashboard.png`
- `http://localhost:5050/dashboard.bin`
- `http://localhost:5050/dashboard-spectra6.png`
- `http://localhost:5050/health`
- `http://localhost:5050/api/tube-vintage`

Le port est `5050`.

## API ESP32 `GET /api/tube-vintage`

EE04 expose uniquement la période calculée par Home Assistant.

La réponse valide contient exactement une clé :

```json
{ "period": "JOUR" }
```

Valeurs possibles :

- `JOUR` : correspond au profil utilisateur de jour
- `SOIR` : correspond au profil visuel de soirée
- `NUIT` : les LED doivent être éteintes

En cas de valeur inattendue ou d’indisponibilité, la route retourne :

```json
{ "error": "periode tube vintage indisponible" }
```

EE04 ne commande pas directement les LED. Il se contente de transmettre cette période.

Les entêtes anti-cache (`Cache-Control`, `Pragma`, `Expires`) sont utilisées pour éviter toute réutilisation d’un ancien état par l’ESP32.

## Vérifications rapides

```bash
curl -s http://localhost:5050/health
curl -o /tmp/dashboard.png http://localhost:5050/dashboard.png
curl -o /tmp/dashboard.bin http://localhost:5050/dashboard.bin
wc -c /tmp/dashboard.bin
```

## Tests

```bash
source .venv/bin/activate
pytest
```

Les tests vérifient :

- récupération Home Assistant (BME280, météo et Environnement Canada),
- gestion des valeurs manquantes ou non numériques,
- fallback cache,
- rendus `dashboard.png` / `dashboard.bin` / `dashboard-spectra6.png`,
- présence d’un bandeau d’alerte seulement si actif,
- absence du token dans les sorties publiques.

## Ce qui reste fictif après 1.6C

- Les champs Outlook / Chronogolf / logique MG M.
- Les données de diagnostic Wi‑Fi, heure de mise à jour et statut réseau.
