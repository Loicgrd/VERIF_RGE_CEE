# 🛡️ Vérificateur RGE & CEE

Outil d'automatisation et de contrôle technique pour la validation des certificats **RGE** (Reconnu Garant de l'Environnement) en lien avec les fiches d'opérations standardisées **CEE**.

## 📋 Présentation
Cette application **Streamlit** permet aux chargés d'études et techniciens CEE de vérifier instantanément la conformité d'un professionnel à une date d'engagement donnée. Elle interroge en temps réel l'API "Historique RGE" de l'ADEME.

### Fonctionnalités clés :
* **Analyse multi-SIRET** : Saisie flexible via un éditeur de données dynamique.
* **Contrôle à date** : Vérification de la validité du certificat précisément à la date d'engagement des travaux.
* **Mapping métier CEE** : Correspondance automatique entre les domaines RGE et les codes de fiches (ex: TH171, EN101, etc.).
* **Visualisation temporelle** : Graphiques Plotly affichant l'historique complet des qualifications.
* **Export intelligent & Renommage** :
    * **Individuel** : Téléchargement nommé `{FICHE}-RGE-{OK/KO}.pdf`.
    * **Groupé** : Export ZIP nommé `{DOMAINE}-{ENTREPRISE}-{STATUT}.pdf`.
    * **Synthèse** : Fichier Excel récapitulatif de l'audit.


# 🛠️ Utilisation
1/ Saisissez la Date d'engagement des travaux.

2/ Remplissez la liste des SIRET (copier/coller depuis Excel possible).

3/ Cliquez sur Analyser les SIRET.

4/ Utilisez le bouton + pour ajouter des domaines spécifiques si besoin.

# 📂 Structure du Projet
app.py : Code principal de l'application.

README.md : Documentation du projet.

CHANGELOG.md : Historique des versions.

.gitignore : Exclusion des fichiers temporaires (PDF, Excel, ZIP).


# ⚖️ Logique métier
L'outil priorise la période de qualification couvrant la date d'engagement. Si aucune période n'est valide à cette date, l'outil récupère la qualification la plus récente pour permettre la consultation de la pièce, tout en marquant le statut en KO/Expiré.


## 🚀 Installation

1. **Cloner le projet**
   ```bash
   git clone [https://github.com/votre-compte/SITE_VERIF_RGE.git](https://github.com/votre-compte/SITE_VERIF_RGE.git)
   cd SITE_VERIF_RGE

2. **Créer un environnement virtuelt**
python -m venv venv
# Activation (Windows)
venv\Scripts\activate

3. **Installer les dépendances**
pip install streamlit pandas requests plotly xlsxwriter

4. **Lancement**
Lancez l'application avec la commande : streamlit run app.py