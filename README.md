# Vérificateur RGE & CEE

Outil d'automatisation et de contrôle technique pour la validation des certificats **RGE** (Reconnu Garant de l'Environnement) en lien avec les fiches d'opérations standardisées **CEE**.

## Présentation

Cette application **Streamlit** multi-pages permet aux chargés d'études et techniciens CEE de vérifier instantanément la conformité d'un professionnel à une date d'engagement donnée. Elle interroge en temps réel l'API "Historique RGE" de l'ADEME, avec bascule automatique sur une base locale en cas d'indisponibilité.

## Pages

### 1 — Vérification RGE (`1_Verification_RGE.py`)
- **Analyse multi-SIRET** : saisie flexible via un éditeur de données dynamique (copier/coller depuis Excel).
- **Contrôle à date** : vérification de la validité du certificat précisément à la date d'engagement des travaux.
- **Mapping métier CEE** : correspondance automatique entre les domaines RGE et les codes de fiches (ex : TH171, EN101…).
- **Visualisation temporelle** : graphiques Plotly affichant l'historique complet des qualifications.
- **Export intelligent** :
  - Individuel : `{FICHE}-RGE-{OK/KO}.pdf`
  - Groupé : ZIP nommé `{DOMAINE}-{ENTREPRISE}-{STATUT}.pdf`
  - Synthèse : fichier Excel récapitulatif de l'audit.
- **Extraction IA** : analyse multimodale (PDF, images, Excel) via Gemini pour détecter automatiquement les SIRET et la date d'engagement.

### 2 — Avis Technique VMC (`pages/2_Avis_Tech_VMC.py`)
Vérification des avis techniques VMC.

### 3 — Supervision Dossier (`pages/3_Supervision_Dossier.py`)
- Import de dossiers JSON depuis la plateforme Odicee.
- Workflow structuré en 4 étapes de vérification par lot.
- Regroupement par fiche de référence et SIRET (même facture).
- Liens Google Maps pour les adresses de chantier.
- Tableau de totaux pour les champs numériques cumulables.

## Structure du projet

```
SITE_VERIF_RGE/
├── 1_Verification_RGE.py       # Page principale
├── pages/
│   ├── 2_Avis_Tech_VMC.py
│   └── 3_Supervision_Dossier.py
├── core/
│   ├── rge_api.py              # Appels ADEME & API Gouv, mapping CEE
│   ├── ia_extraction.py        # Extraction IA (Gemini multimodal)
│   ├── utils_supervision.py    # Utilitaires page supervision
│   └── utils_vmc.py
├── database/
│   └── RGE/
│       └── local_backup.py     # Base locale de secours ADEME
├── requirements.txt
├── CHANGELOG.md
└── README.md
```

## Logique métier

L'outil priorise la période de qualification couvrant la date d'engagement. Si aucune période n'est valide à cette date, il récupère la qualification la plus récente pour permettre la consultation de la pièce, tout en marquant le statut **KO / Expiré**.

Pour **Qualibat**, en cas de périodes qui se chevauchent, la logique sélectionne le certificat le plus récent (`lien_debut` le plus tardif).

## Installation

1. **Cloner le projet**
   ```bash
   git clone https://github.com/votre-compte/SITE_VERIF_RGE.git
   cd SITE_VERIF_RGE
   ```

2. **Créer un environnement virtuel**
   ```bash
   python -m venv venv
   # Windows
   venv\Scripts\activate
   ```

3. **Installer les dépendances**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configurer les secrets**

   Créer `.streamlit/secrets.toml` :
   ```toml
   GEMINI_API_KEY = "votre_clé_api_gemini"
   ```
   La clé est nécessaire uniquement pour la fonctionnalité d'extraction IA (page 1).

5. **Lancer l'application**
   ```bash
   streamlit run 1_Verification_RGE.py
   ```

## Dépendances principales

| Paquet | Usage |
|---|---|
| `streamlit` | Interface web |
| `pandas` | Manipulation des données |
| `plotly` | Graphiques historiques |
| `requests` | Appels API ADEME & Gouv |
| `xlsxwriter` / `openpyxl` | Export Excel |
| `google-genai` | Extraction IA multimodale |
| `PyPDF2` / `Pillow` | Lecture PDF & images |
| `supabase` | Base de données distante |
| `pytz` | Gestion des fuseaux horaires |
