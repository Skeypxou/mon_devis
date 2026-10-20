# Atelier PVC Pro

Application Streamlit de gestion d'atelier de menuiserie PVC : répertoire clients/fournisseurs, catalogue de matériaux, calcul paramétrique, optimisation des coupes, devis PDF, ordres de fabrication, factures, règlements, stocks et export de sauvegarde JSON.

> **Limite technique importante :** les calculs de menuiserie utilisent des règles paramétrables et des valeurs initiales indicatives. Ils ne remplacent pas les abaques, plans de coupe et prescriptions du fabricant de profilés. Validez les règles par système et typologie avant de fabriquer. Le moteur complet multi-ouvrants / meneaux / traverses / parcloses / renforts n'est pas encore un configurateur industriel certifié.

## Windows — installation locale

1. Installez Python 3.11 ou 3.12.
2. Ouvrez PowerShell dans ce dossier.
3. Créez l'environnement et installez les dépendances :

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

L'application s'ouvre dans le navigateur. La base SQLite est créée automatiquement dans `data/atelier_pvc.db`.

Un lanceur `Lancer_Atelier_PVC.bat` est fourni pour simplifier le démarrage après installation.

## Déploiement Streamlit Community Cloud + Supabase

1. Envoyez ce dossier dans un dépôt GitHub.
2. Créez un projet PostgreSQL sur Supabase.
3. Dans les paramètres Secrets de Streamlit Community Cloud, ajoutez :

```toml
DATABASE_URL = "postgresql+psycopg://UTILISATEUR:MOT_DE_PASSE@HOTE:5432/postgres?sslmode=require"
```

4. Déployez `app.py` comme fichier principal.
5. Vérifiez que `DATABASE_URL` est correctement renseignée. Sans cette variable, SQLite sera utilisée; sur le cloud, le stockage local peut ne pas survivre aux redémarrages.

Ne commitez jamais `.streamlit/secrets.toml`, les mots de passe ou les données clients dans GitHub.

## Tests

```powershell
pip install -r requirements.txt
pytest -q
```

## Sauvegarde et migration

Depuis **Paramètres & sauvegarde**, téléchargez une sauvegarde JSON des entités métier. Pour la base locale, arrêtez l'application puis copiez `data/atelier_pvc.db`. Les créations de tables sont automatiques (`create_all`); pour des évolutions de schéma en production, ajouter Alembic avant d'utiliser des migrations complexes.

## Sécurité et usage en production

Cette première livraison n'inclut pas encore de système d'authentification multi-rôles, de restauration de sauvegarde JSON, de journal d'audit complet ni de synchronisation de stock automatisée par ordre de fabrication. Ne rendez pas l'instance publiquement accessible sans ajouter ces contrôles et effectuer une revue de sécurité.
