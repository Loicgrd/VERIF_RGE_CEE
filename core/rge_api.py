import pandas as pd
import requests
import urllib.parse
import streamlit as st
from datetime import datetime

# On importe la fonction locale depuis le dossier database
from database.local_backup import fetch_local_backup

MAP_CEE = {
    "Fenêtres, volets, portes extérieures 2020": ["EN104", "EN108", "EN110"],
    "Isolation du toit 2020": ["EN101", "EN105", "EN106"],
    "Isolation des murs et planchers bas 2020": ["EN102", "EN103", "EN107"],
    "Isolation par l'intérieur des murs ou rampants de toitures ou plafonds": ["EN101", "EN102"],
    "Chaudière condensation ou micro-cogénération gaz ou fioul 2020": ["TH106", "TH107"],
    "Equipements électriques hors ENR : chauffage, eau chaude, éclairage 2020": ["EQ110", "EQ115"],
    "Pompe à chaleur : chauffage": ["TH171", "TH172", "TH129", "TH159"],
    "Isolation des combles perdus": ["EN101"],
    "Chauffe-Eau Thermodynamique": ["TH148", "TH169"],
    "Fenêtres, volets, portes donnant sur l'extérieur": ["EN104", "EN108"],
    "Chaudière condensation ou micro-cogénération gaz ou fioul": ["TH106", "TH107"],
    "Poêle ou insert bois": ["TH112"],
    "Isolation des murs par l'extérieur": ["EN102"],
    "Isolation des planchers bas": ["EN103"],
    "Isolation des toitures terrasses ou des toitures par l'extérieur": ["EN105"],
    "Fenêtres de toit": ["EN104"],
    "Radiateurs électriques, dont régulation.": ["TH158", "TH173"],
    "Chaudière bois": ["TH113"],
    "Panneaux solaires photovoltaïques": ["PV"],
    "Ventilation mécanique": ["TH127", "TH125", "TH155"],
    "Ventilation 2020": ["TH127", "TH125", "TH155"],
    "Audit énergétique Maison individuelle": ["TH164", "TH174"],
    "Architecte": ["TH164", "TH174"],
    "Chauffage et/ou eau chaude solaire": ["TH101", "TH143", "TH124"],
    "Pompe à chaleur et/ou Chauffe-eau thermodynamique 2020": ["TH171", "TH148", "TH159"],
    "Chauffage et/ou eau chaude au bois 2020": ["TH113", "TH112"],
    "Audit énergétique Logement collectif": ["TH145"],
    "Projet complet de rénovation": ["TH164", "TH145", "TH174"],
    "Chauffage et/ou eau chaude solaire 2020": ["TH101", "TH143"],
    "Forage géothermique": ["TH178"],
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