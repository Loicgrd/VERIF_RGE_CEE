import pandas as pd
import requests
import urllib.parse
import streamlit as st
from datetime import datetime
import sys
import os


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# On importe la fonction locale depuis le dossier database
from database.RGE.local_backup import fetch_local_backup

MAP_CEE = {
# --- ENVELOPPE (RGE Isolation / Menuiserie) ---
    "Fenêtres, volets, portes extérieures 2020": ["EN104", "EN108", "EN110"],
    "Fenêtres de toit": ["EN104"],
    "Fenêtres, volets, portes donnant sur l'extérieur": ["EN104", "EN108", "EN110"],
    "Isolation du toit 2020": ["EN101", "EN105", "EN106"],
    "Isolation des combles perdus": ["EN101"],
    "Isolation des toitures terrasses ou des toitures par l'extérieur": ["EN105"],
    "Isolation des murs et planchers bas 2020": ["EN102", "EN103", "EN107"],
    "Isolation par l'intérieur des murs ou rampants de toitures  ou plafonds": ["EN101", "EN102"],
    "Isolation des murs par l'extérieur": ["EN102"],
    "Isolation des planchers bas": ["EN103"],

    # --- GÉNÉRATEURS DE CHALEUR & ENR (RGE Chauffage+/QualiPac/QualiBois/QualiSol) ---
    "Chaudière condensation ou micro-cogénération gaz ou fioul 2020": ["TH106", "TH107"],
    "Chaudière condensation ou micro-cogénération gaz ou fioul": ["TH106", "TH107"],
    "Pompe à chaleur : chauffage": ["TH129", "TH150", "TH159", "TH171", "TH172"],
    "Pompe à chaleur et/ou Chauffe-eau thermodynamique 2020": ["TH148", "TH159", "TH171"],
    "Chauffe-Eau Thermodynamique": ["TH148", "TH169"],
    "Chauffage et/ou eau chaude au bois 2020": ["TH112", "TH113"],
    "Poêle ou insert bois": ["TH112"],
    "Chaudière bois": ["TH113", "TH128"],
    "Chauffage et/ou eau chaude solaire 2020": ["TH101", "TH143"],
    "Chauffage et/ou eau chaude solaire": ["TH101", "TH124", "TH143"],
    "Forage géothermique": ["TH178"], # Nécessite RGE QualiForage
    "Panneaux solaires hybrides (Thermique/PV)": ["TH162"],

    # --- VENTILATION (RGE Ventilation) ---
    "Ventilation 2020": ["TH125", "TH127", "TH155"],
    "Ventilation mécanique": ["TH127", "TH125", "TH155"],

    # --- AUDITS ET RÉNOVATION GLOBALE (RGE Études / RGE Travaux pour les artisans) ---
    "Audit énergétique Maison individuelle": ["TH164", "TH174"],
    "Audit énergétique Logement collectif": ["TH177", "TH145"],
    "Projet complet de rénovation": ["TH145", "TH164", "TH174", "TH175", "TH177"]
}

def extract_qualif_code(id_complet):
    if not id_complet or id_complet == "N/A": return "N/A"
    id_str = str(id_complet).strip()
    pos_tiret = id_str.find("-")
    longueur_fin = len(id_str) if pos_tiret == -1 else pos_tiret
    return id_str[1:longueur_fin] if id_str.startswith("Q") else id_str[:longueur_fin]

def clean_url(url):
    return urllib.parse.quote(url, safe=':/?&=') if url else ""

def get_cee_options(domaine):
    dom_clean = str(domaine).lower().strip()
    for key, codes in MAP_CEE.items():
        if key.lower() in dom_clean: return codes
    return ["RGE"]

def fetch_ademe_data(siret, force_local=False):
    url = f"https://data.ademe.fr/data-fair/api/v1/datasets/historique-rge/lines?q=siret.exact:'{siret}'&size=1000"
    
    if force_local:
        st.info(f"🗄️ Mode local forcé pour le SIRET {siret}")
        return fetch_local_backup(siret)
        
    try:
        r = requests.get(url, timeout=4)
        if r.status_code == 200:
            return r.json().get('results', [])
        else:
            raise requests.exceptions.RequestException()
    except (requests.exceptions.RequestException, Exception):
        st.warning(f"⚠️ Mode secours : Base ADEME injoignable. Recherche locale pour le SIRET {siret}")
        return fetch_local_backup(siret)
    


def fetch_gouv_data(siret_cible):
    siret_cible = str(siret_cible).strip()
    siren = siret_cible[:9] # Les 9 premiers chiffres forment le SIREN
    
    # ÉTAPE 1 : On cherche d'abord par SIREN pour avoir le nom exact de l'entreprise
    url_siren = f"https://recherche-entreprises.api.gouv.fr/search?q={siren}"
    
    try:
        r1 = requests.get(url_siren, timeout=4)
        if r1.status_code == 200:
            data1 = r1.json()
            results1 = data1.get('results', [])
            if not results1: 
                return {"trouve": False}
            
            entreprise_mere = results1[0]
            nom_exact = entreprise_mere.get('nom_complet') or entreprise_mere.get('nom_raison_sociale') or "Inconnu"
            
            # ÉTAPE 2 : Ton idée ! On cherche par nom, puis on croise avec le SIREN
            url_nom = f"https://recherche-entreprises.api.gouv.fr/search?q={urllib.parse.quote(nom_exact)}"
            r2 = requests.get(url_nom, timeout=4)
            
            toutes_agences = []
            if r2.status_code == 200:
                data2 = r2.json()
                for ent in data2.get('results', []):
                    # Le croisement décisif :
                    if ent.get('siren') == siren:
                        toutes_agences = ent.get('matching_etablissements', [])
                        break
                        
            # Sécurité : si l'astuce échoue, on garde au moins ce qu'on avait à l'étape 1
            if not toutes_agences:
                toutes_agences = entreprise_mere.get('matching_etablissements', [])

            # On isole l'agence scannée par l'utilisateur
            agence_cible = next((a for a in toutes_agences if a.get('siret') == siret_cible), None)
            
            # NOUVEAU : Si l'agence cible n'existe pas, on lève un drapeau d'erreur
            if not agence_cible:
                return {
                    "trouve": False,
                    "erreur_siret": True,  # Flag pour identifier une erreur de NIC
                    "nom": nom_exact,
                    "autres_agences": toutes_agences # On renvoie quand même les vraies agences pour aider l'utilisateur
                }
            
            # On stocke les autres agences (pour l'historique d'ouverture/fermeture)
            autres_agences = [a for a in toutes_agences if a.get('siret') != siret_cible]
            
            return {
                "trouve": True,
                "nom": nom_exact,
                "date_creation": agence_cible.get('date_creation') if agence_cible else None,
                "date_fermeture": agence_cible.get('date_fermeture') if agence_cible else None,
                "etat_admin": agence_cible.get('etat_administratif', 'A') if agence_cible else 'A',
                "adresse_complete": agence_cible.get('adresse', 'Adresse inconnue') if agence_cible else 'Inconnue',
                "cp": agence_cible.get('code_postal', '') if agence_cible else '',
                "commune": agence_cible.get('libelle_commune', '') if agence_cible else '',
                "autres_agences": autres_agences # La nouveauté est ici !
            }
    except Exception as e:
        print(f"DEBUG: Erreur API Gouv pour {siret_cible}: {e}")
    
    return {"trouve": False}