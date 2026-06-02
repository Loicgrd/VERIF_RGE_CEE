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


# --- 2. LE PROMPT DÉFINITIF (Le Cerveau avec Bouclier Anti-Déchets) ---
PROMPT_VMC = """
Tu es un Ingénieur Expert en conformité documentaire pour les Certificats d'Économies d'Énergie (CEE).
Analyse cet Avis Technique (ATec) du CSTB.

Extrais les informations au format JSON strict avec la structure exacte suivante :
{
  "est_vmc": true, // METS false SI LE DOCUMENT NE TRAITE PAS DE VMC
  "numero_atec": "Ex: 14.5/17-2273",
  "indice_revision": "Ex: 'V2', 'Modificatif 1' ou 'V1' si non précisé",
  "titulaire": "Le(s) constructeur(s) officiel(s) (ex: ANJOS, ALDES / AERECO)",
  "distributeur": "La marque commerciale (ex: ATLANTIC). Si aucune marque distincte, remets le titulaire.",
  "debut_validite": "YYYY-MM-DD",
  "fin_validite": "YYYY-MM-DD",
  "modeles": [
    {
      "nom_modele": "Le nom spécifique du caisson (ex: EASYVEC, VEX, Copernic V)",
      "type_logement": "'Individuel', 'Collectif' ou 'Mixte'",
      "basse_pression": true ou false,
      "debits_disponibles": ["400"]
    }
  ]
}

RÈGLES D'EXTRACTION ABSOLUES (LIS ATTENTIVEMENT) :

1. FILTRE HORS PÉRIMÈTRE (TRÈS IMPORTANT) :
   - Si le document traite de systèmes de chauffage, pompes à chaleur, conduits de fumée, puits climatiques, répartiteurs, collecteurs ou tout équipement qui N'EST PAS un système de Ventilation Mécanique Contrôlée (VMC), mets "est_vmc": false et laisse le reste vide.

2. TITULAIRE ET DISTRIBUTEUR :
   - "titulaire" : Extrais cette donnée de la section "Titulaire(s)". Supprime les termes juridiques ("Société", "SA"). S'il y a plusieurs titulaires, joins-les avec un slash.
   - "distributeur" : Cherche une éventuelle mention "Distributeur" OU analyse la section "Sur le procédé". Si une marque (ex: ATLANTIC) apparaît dans le procédé mais n'est pas le titulaire, assigne-la au distributeur. Sinon, recopie le "titulaire".

3. IDENTIFICATION DES CAISSONS / MATÉRIEL (TRÈS IMPORTANT) :
   - INTERDICTION : Ne renvoie JAMAIS le nom général du "Procédé" comme étant un modèle. 
   - Tu dois chercher dans le texte les matériels physiques (Groupes d'extraction, Caissons de ventilation, etc.).

4. EXCLUSION DES RÉFÉRENCES CROISÉES :
   - N'extrais JAMAIS un modèle s'il est indiqué que ses caractéristiques relèvent d'un AUTRE Avis Technique.

5. TYPE DE LOGEMENT :
   - Cherche la section "Domaine d'emploi" ou "Domaine d'application".
   - "maisons individuelles" = "Individuel".
   - "logements collectifs" ou "bâtiments d'habitation collective" = "Collectif".
   - Si les deux = "Mixte".
   - Attention : "non destiné au collectif" = "Individuel".

6. CARACTÉRISTIQUE BASSE PRESSION (STRICT) :
   - Mets `true` UNIQUEMENT si les termes exacts "basse pression" ou "BP" sont explicitement associés au modèle. 
   - "pression constante", "PCI", "pression standard" = `false`.

7. DÉBITS (RESTRICTION MAJEURE) :
   - N'extrais un débit QUE s'il fait explicitement partie de l'appellation commerciale du caisson dans le texte.
   - INTERDICTION STRICTE : Ne lis SURTOUT PAS les tableaux de caractéristiques (techniques, thermiques, aérauliques).
   - Si le nom du modèle ne contient pas de notion de débit, renvoie une liste vide [].

8. FORMAT :
   - Renvoie UNIQUEMENT l'objet JSON valide, sans balises markdown.
"""


# --- 3. FONCTIONS DE TRAITEMENT ---

def scraper_urls_cstb(famille="56", pages_max=2):
    """Parcourt les pages de recherche du CSTB pour trouver les URL des PDF."""
    print(f"🔍 Début du scraping sur le site du CSTB (Recherche sur {pages_max} pages)...")
    urls_trouvees = []
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    for page in range(1, pages_max+1):
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
    
    # On cherche un motif à la fin de l'URL : "-3.pdf", "_V3.pdf", "_3.pdf"
    match = re.search(r'[-_]?[vV]?(\d+)\.pdf$', url_actuelle)
    
    if match:
        version_actuelle = int(match.group(1))
        # On coupe l'URL juste avant le numéro (ex: ".../VFAF")
        base_url = url_actuelle[:match.start()]
        
        # On boucle à l'envers, de la version actuelle - 1 jusqu'à 1
        for v in range(version_actuelle - 1, 0, -1):
            
            # Les formats les plus courants sur Batipedia
            formats_a_tester = [
                f"{base_url}-{v}.pdf",
                f"{base_url}_V{v}.pdf",
                f"{base_url}_{v}.pdf"
            ]
            
            version_trouvee = False
            for url_test in formats_a_tester:
                try:
                    # Utilisation de requests.head pour ne lire que l'en-tête (ultra rapide)
                    reponse = requests.head(url_test, timeout=5)
                    if reponse.status_code == 200:
                        urls_historiques.append(url_test)
                        print(f"   🕰️ Version historique trouvée : {url_test.split('/')[-1]}")
                        version_trouvee = True
                        break # On a trouvé le bon format, on passe à la version n-1
                except:
                    continue
            
            # Cas spécial : la toute première version n'a parfois aucun suffixe (ex: VFAF.pdf)
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
        print("   🧠 Analyse par Gemini en cours...")
        fichier_upload = client_gemini.files.upload(file=chemin_temp)
        
        reponse_ia = client_gemini.models.generate_content(
            model='gemini-3.1-flash-lite',
            contents=[fichier_upload, PROMPT_VMC],
            config=types.GenerateContentConfig(response_mime_type="application/json"),
            temperature=0.0
        )
        
        client_gemini.files.delete(name=fichier_upload.name)
        

        
        donnees = json.loads(reponse_ia.text)
        
        # --- LE BOUCLIER ANTI-DÉCHETS ---
        if donnees.get("est_vmc") is False:
            print("   🛡️ Document hors périmètre (Ce n'est pas une VMC). Poubelle.")
            return
            
        # On nettoie la clé "est_vmc" avant l'envoi pour respecter la structure Supabase
        donnees.pop("est_vmc", None)
        
        # On ajoute l'URL pour la traçabilité
        donnees['url_batipedia'] = url_pdf
        
        print(f"   💾 Insertion de l'Avis N° {donnees.get('numero_atec', 'Inconnu')} dans Supabase...")
        supabase.table("referentiel_vmc").insert(donnees).execute()
        print("   ✅ Succès !")

    except Exception as e:
        print(f"   ❌ Erreur d'analyse ou d'insertion : {e}")
        
    finally:
        if os.path.exists(chemin_temp):
            os.remove(chemin_temp)
    print("Pause de 15 secondes pour l'api GEMINI ...")
    time.sleep(15)


# --- 4. LANCEMENT DU PIPELINE ---
if __name__ == "__main__":
    print("========================================")
    print("🚀 DÉMARRAGE DU PIPELINE D'EXTRACTION VMC")
    print("========================================")
    
    # 1. On récupère les URL récentes depuis le moteur de recherche
    liste_urls_recentes = scraper_urls_cstb(pages_max=2)
    
    # 2. On utilise un "set" (ensemble) pour éviter les doublons automatiquement
    toutes_les_urls = set(liste_urls_recentes)
    
    # 3. Rétro-ingénierie : on cherche les anciennes versions pour chaque PDF récent
    print("\n🔎 Recherche des historiques (anciennes révisions)...")
    for url in liste_urls_recentes:
        anciennes = trouver_anciennes_versions(url)
        toutes_les_urls.update(anciennes) # Ajoute les anciennes versions à la liste globale
        
    liste_urls_finale = list(toutes_les_urls)
    print(f"\n📊 Total à traiter : {len(liste_urls_finale)} documents (récents + historiques).")
    
    # 4. Traitement de la liste complète
    for i, url in enumerate(liste_urls_finale):
        print(f"\n--- Fichier {i+1} / {len(liste_urls_finale)} ---")
        traiter_pdf_a_la_volee(url)
        
    print("\n🎉 TERMINÉ ! Le référentiel est à jour avec tout son historique.")