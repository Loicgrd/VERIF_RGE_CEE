import os
import json
import time
import tomllib
import tempfile
import requests
from bs4 import BeautifulSoup
from google import genai
from google.genai import types
from supabase import create_client
import re

# --- 1. CONFIGURATION ET CLÉS API ---
dossier_script = os.path.dirname(os.path.abspath(__file__))
# On remonte à la racine pour trouver .streamlit/secrets.toml
chemin_secrets = os.path.abspath(os.path.join(dossier_script, "..", "..", ".streamlit", "secrets.toml"))

try:
    with open(chemin_secrets, "rb") as f:
        secrets = tomllib.load(f)
        CLE_GEMINI = secrets.get("GEMINI_API_KEY")
        URL_SUPABASE = secrets.get("SUPABASE_URL")
        CLE_SUPABASE = secrets.get("SUPABASE_KEY")
except Exception as e:
    print(f"❌ Erreur de lecture des secrets : {e}")
    exit(1)

client_gemini = genai.Client(api_key=CLE_GEMINI)
supabase = create_client(URL_SUPABASE, CLE_SUPABASE)


# --- 2. LE PROMPT LITE (Spécial Scraping de masse) ---
PROMPT_VMC_LITE = """
Tu es un Ingénieur Expert en conformité documentaire pour les Certificats d'Économies d'Énergie (CEE).
Analyse cet Avis Technique (ATec) du CSTB.

Extrais les informations au format JSON strict avec la structure exacte suivante :
{
  "est_vmc": true, 
  "numero_atec": "Ex: 14.5/17-2273",
  "indice_revision": "Ex: 'V2', 'Modificatif 1' ou 'V1' si non précisé",
  "titulaire": "Le(s) constructeur(s) officiel(s)",
  "distributeur": "La marque commerciale. Si aucune marque distincte, remets le titulaire. Enlève le terme "société" du distributeur",
  "debut_validite": "YYYY-MM-DD",
  "fin_validite": "YYYY-MM-DD",
  "modeles": [
    {
      "nom_modele": "Le nom de base de la gamme (ex: EASYVEC)",
      "type_logement": "'Individuel', 'Collectif' ou 'Mixte'",
      "basse_pression": true ou false,
      "double_flux": true ou false,
      "courbe_montante": true ou false,
      "debits_disponibles": ["400", "700"],
      "puissance_hygro_a": null,
      "puissance_hygro_b": null
    }
  ]
}

RÈGLES D'EXTRACTION ABSOLUES :

1. FILTRE HORS PÉRIMÈTRE (TRÈS IMPORTANT) :
   - Si le document traite de systèmes de chauffage, pompes à chaleur, puits climatiques ou tout équipement qui N'EST PAS un système de Ventilation Mécanique Contrôlée (VMC), mets "est_vmc": false et laisse le reste vide.

2. IDENTIFICATION DES MODÈLES (ANTI-DÉCHETS) :
   - Extrais CHAQUE modèle de caisson VMC.
   - EXCLUSION STRICTE : Ne confonds pas les noms de modèles avec les légendes de graphiques ou descriptions de test. Ignore tout texte contenant "débits", "config", "Pmin", "courbe". Un modèle a un nom commercial court.

3. PUISSANCES (MODE LITE) :
   - IMPORTANT : Tu ne dois PAS chercher les puissances électriques (W-Th-C). Laisse TOUJOURS `puissance_hygro_a` et `puissance_hygro_b` sur la valeur exacte `null`.

4. CARACTÉRISTIQUES (LOGEMENT, BP, DF) :
   - "type_logement" : Individuel, Collectif, ou Mixte.
   - "basse_pression" : true UNIQUEMENT si "basse pression" ou "BP" est explicitement associé au modèle.
   - "double_flux" : true si mention de "Double Flux", "DF" ou échangeur thermique.
   - "debits_disponibles" : N'extrais un débit QUE s'il fait partie de l'appellation commerciale. Sinon [].

8. COURBE MONTANTE : Attribue `true` si le document mentionne explicitement une "courbe montante" ou "courbe de fonctionnement montante" ou "courbe débit pression montante" pour ce modèle spécifique. Sinon, mets `false`.

5. FORMAT :
   - Renvoie UNIQUEMENT l'objet JSON valide.
"""


# --- 3. FONCTIONS DE TRAITEMENT ---

def scraper_urls_cstb(famille="56", pages_max=2):
    """Parcourt les pages de recherche du CSTB pour trouver les URL des PDF."""
    print(f"🔍 Début du scraping sur le site du CSTB (Recherche sur {pages_max} pages)...")
    urls_trouvees = []
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    for page in range(0, pages_max):
        url_recherche = f"https://www.cstb.fr/bases-donnees/rechercher-un-document?take=36&page={page}&evaluations=1&familles={famille}"
        
        reponse = requests.get(url_recherche, headers=headers)
        if reponse.status_code != 200:
            print(f"⚠️ Erreur de connexion à la page {page}")
            continue

        soup = BeautifulSoup(reponse.text, 'html.parser')
        liens = soup.find_all('a', href=True)
        
        for lien in liens:
            href = lien['href']
            # On ne garde que les liens pointant vers le PDF officiel Batipedia
            if "batipedia.com/atec/pdf/document/" in href:
                urls_trouvees.append(href)
                
    urls_uniques = list(set(urls_trouvees))
    print(f"✅ {len(urls_uniques)} liens PDF uniques trouvés sur le site.")
    return urls_uniques


def pdf_deja_traite(url_pdf):
    """Vérifie si cette URL est déjà dans Supabase pour éviter les doublons."""
    reponse = supabase.table("referentiel_vmc").select("id").eq("url_batipedia", url_pdf).execute()
    return len(reponse.data) > 0


def trouver_anciennes_versions(url_actuelle):
    """
    Prend une URL comme .../VFAF-3.pdf et teste si les versions 2 et 1 existent.
    """
    urls_historiques = []
    
    match = re.search(r'[-_]?[vV]?(\d+)\.pdf$', url_actuelle)
    
    if match:
        version_actuelle = int(match.group(1))
        base_url = url_actuelle[:match.start()]
        
        for v in range(version_actuelle - 1, 0, -1):
            
            formats_a_tester = [
                f"{base_url}-{v}.pdf",
                f"{base_url}_V{v}.pdf",
                f"{base_url}_{v}.pdf"
            ]
            
            version_trouvee = False
            for url_test in formats_a_tester:
                try:
                    reponse = requests.head(url_test, timeout=5)
                    if reponse.status_code == 200:
                        urls_historiques.append(url_test)
                        print(f"   🕰️ Version historique trouvée : {url_test.split('/')[-1]}")
                        version_trouvee = True
                        break
                except:
                    continue
            
            if v == 1 and not version_trouvee:
                url_base_seule = f"{base_url}.pdf"
                try:
                    if requests.head(url_base_seule, timeout=5).status_code == 200:
                        urls_historiques.append(url_base_seule)
                        print(f"   🕰️ Version initiale (sans suffixe) trouvée : {url_base_seule.split('/')[-1]}")
                except:
                    pass
                    
    return urls_historiques


def traiter_pdf_a_la_volee(url_pdf):
    """Télécharge, fait lire à Gemini, vérifie si c'est une VMC, et pousse sur Supabase."""
    print(f"\n⚙️ Traitement de : {url_pdf}")
    
    if pdf_deja_traite(url_pdf):
        print("   ⏭️ Déjà présent dans Supabase. Ignoré.")
        return

    print("   📥 Téléchargement temporaire...")
    reponse_pdf = requests.get(url_pdf)
    
    if reponse_pdf.status_code != 200:
        print("   ❌ Impossible de télécharger le PDF.")
        return

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as fichier_temp:
        fichier_temp.write(reponse_pdf.content)
        chemin_temp = fichier_temp.name

    try:
        print("   🧠 Analyse par Gemini Lite en cours...")
        fichier_upload = client_gemini.files.upload(file=chemin_temp)
        
        # Utilisation de la version Lite (très haut quota)
        reponse_ia = client_gemini.models.generate_content(
            model='gemini-3.1-flash-lite',
            contents=[fichier_upload, PROMPT_VMC_LITE],
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.0)
        )
        
        client_gemini.files.delete(name=fichier_upload.name)
        
        raw_text = reponse_ia.text.replace("```json", "").replace("```", "").strip()
        donnees = json.loads(raw_text)
        
        # --- LE BOUCLIER HORS PÉRIMÈTRE ---
        if donnees.get("est_vmc") is False:
            print("   🛡️ Document hors périmètre (Ce n'est pas une VMC). Poubelle.")
            return
            
        donnees.pop("est_vmc", None)
        
        # --- FILTRE POST-IA (NETTOYAGE DES FAUX MODÈLES) ---
        if donnees.get("modeles"):
            vrais_modeles = []
            mots_interdits = [
                "débits", "décroissants", "config", "bouches", "pmin", 
                "multipiquage", "courbe", "caractéristique",
                "b100", "b200", "fan_", "-fan", "t.flow", "thermodynamique"
            ]
            
            for m in donnees["modeles"]:
                nom = str(m.get("nom_modele", "")).lower()
                
                # Vérification de la longueur et des mots interdits
                if len(nom) < 45 and not any(mot in nom for mot in mots_interdits):
                    vrais_modeles.append(m)
                    
            donnees["modeles"] = vrais_modeles
            print(f"   🧹 Nettoyage post-IA : {len(donnees['modeles'])} modèles valides conservés.")
        
        donnees['url_batipedia'] = url_pdf
        
        print(f"   💾 Insertion de l'Avis N° {donnees.get('numero_atec', 'Inconnu')} dans Supabase...")
        supabase.table("referentiel_vmc").insert(donnees).execute()
        print("   ✅ Succès !")

    except Exception as e:
        print(f"   ❌ Erreur d'analyse ou d'insertion : {e}")
        
    finally:
        if os.path.exists(chemin_temp):
            os.remove(chemin_temp)
            
    print("   ⏳ Pause de 5 secondes pour préserver l'API...")
    time.sleep(5) # Avec le modèle Lite, tu peux te permettre une pause plus courte (5s au lieu de 15s)


# --- 4. LANCEMENT DU PIPELINE ---
if __name__ == "__main__":
    print("========================================")
    print("🚀 DÉMARRAGE DU PIPELINE D'EXTRACTION VMC")
    print("========================================")
    
    liste_urls_recentes = scraper_urls_cstb(pages_max=2)
    toutes_les_urls = set(liste_urls_recentes)
    
    print("\n🔎 Recherche des historiques (anciennes révisions)...")
    for url in liste_urls_recentes:
        anciennes = trouver_anciennes_versions(url)
        toutes_les_urls.update(anciennes) 
        
    liste_urls_finale = list(toutes_les_urls)
    print(f"\n📊 Total à traiter : {len(liste_urls_finale)} documents (récents + historiques).")
    
    for i, url in enumerate(liste_urls_finale):
        print(f"\n--- Fichier {i+1} / {len(liste_urls_finale)} ---")
        traiter_pdf_a_la_volee(url)
        
    print("\n🎉 TERMINÉ ! Le référentiel est à jour.")