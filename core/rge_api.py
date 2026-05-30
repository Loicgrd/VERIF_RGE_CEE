import pandas as pd
import requests
import urllib.parse
import streamlit as st
from datetime import datetime

# On importe la fonction locale depuis le dossier database
from database.local_backup import fetch_local_backup

MAP_CEE = {
# --- ENVELOPPE (RGE Isolation / Menuiserie) ---
    "Fenêtres, volets, portes extérieures 2020": ["EN104", "EN108", "EN110"],
    "Fenêtres de toit": ["EN104"],
    "Fenêtres, volets, portes donnant sur l'extérieur": ["EN104", "EN108", "EN110"],
    "Isolation du toit 2020": ["EN101", "EN105", "EN106"],
    "Isolation des combles perdus": ["EN101"],
    "Isolation des toitures terrasses ou des toitures par l'extérieur": ["EN105"],
    "Isolation des murs et planchers bas 2020": ["EN102", "EN103", "EN107"],
    "Isolation par l'intérieur des murs ou rampants de toitures ou plafonds": ["EN101", "EN102"],
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
    "Ventilation mécanique": ["TH125", "TH127", "TH155"],

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
    


def fetch_gouv_data(siret):
    url = f"https://recherche-entreprises.api.gouv.fr/search?q={siret}"
    try:
        r = requests.get(url, timeout=4)
        if r.status_code == 200:
            data = r.json()
            results = data.get('results', [])
            if results:
                # On prend le premier résultat (l'entreprise correspondante)
                entreprise = results[0]
                
                # Infos de base
                nom = entreprise.get('nom_complet') or entreprise.get('nom_raison_sociale') or "Inconnu"
                
                # Infos spécifiques à l'établissement via son SIRET
                etablissements = entreprise.get('matching_etablissements', [])
                etab = etablissements[0] if etablissements else {}
                
                return {
                    "trouve": True,
                    "nom": nom,
                    "date_creation": etab.get('date_creation'),
                    "date_fermeture": etab.get('date_fermeture'),
                    "etat_admin": etab.get('etat_administratif'), # 'A' (Actif) ou 'F' (Fermé)
                    "adresse_complete": etab.get('adresse', 'Adresse inconnue'),
                    "cp": etab.get('code_postal', ''),
                    "commune": etab.get('libelle_commune', '')
                }
    except Exception as e:
        print(f"DEBUG: Erreur API Gouv pour {siret}: {e}")

    return {"trouve": False}