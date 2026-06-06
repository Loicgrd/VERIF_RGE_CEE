import os
import json
import tomllib
from google import genai
from google.genai import types

# --- RÉCUPÉRATION DE LA CLÉ API ---
dossier_script = os.path.dirname(os.path.abspath(__file__))
chemin_secrets = os.path.abspath(os.path.join(dossier_script, "..", "..", ".streamlit", "secrets.toml"))

try:
    with open(chemin_secrets, "rb") as f:
        secrets = tomllib.load(f)
        CLE_API = secrets.get("GEMINI_API_KEY") 
except Exception as e:
    print(f"❌ Erreur de lecture des secrets : {e}")
    exit(1)

client = genai.Client(api_key=CLE_API)

# --- LE NOUVEAU PROMPT V4 (Double extraction Titulaire / Distributeur) ---
# --- LE NOUVEAU PROMPT V5 (Anti-Références Croisées) ---
# --- LE NOUVEAU PROMPT V6 (Restriction sur les débits) ---
# --- LE NOUVEAU PROMPT V7 (Focus Matériel & Caissons) ---
PROMPT_VMC = """
Tu es un Ingénieur Expert en conformité documentaire pour les Certificats d'Économies d'Énergie (CEE).
Analyse cet Avis Technique (ATec) du CSTB pour des systèmes de ventilation.

Extrais les informations au format JSON strict avec la structure exacte suivante :
{
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
      "debits_disponibles": ["400"] // UNIQUEMENT si inclus dans le nom commercial
    }
  ]
}

RÈGLES D'EXTRACTION ABSOLUES (LIS ATTENTIVEMENT) :

1. TITULAIRE ET DISTRIBUTEUR :
   - "titulaire" : Extrais cette donnée de la section "Titulaire(s)". Supprime les termes juridiques ("Société", "SA"). S'il y a plusieurs titulaires, joins-les avec un slash ("Aldes / Aereco").
   - "distributeur" : Cherche une éventuelle mention "Distributeur" OU analyse la section "Sur le procédé". Si une marque (ex: ATLANTIC) apparaît dans le procédé mais n'est pas le titulaire, assigne-la au distributeur. Sinon, recopie le "titulaire".

2. IDENTIFICATION DES CAISSONS / MATÉRIEL (TRÈS IMPORTANT) :
   - INTERDICTION : Ne renvoie JAMAIS le nom général du "Procédé" (ex: "BAHIA solution collective" ou "VMC HYGRO") comme étant un modèle. 
   - Tu dois chercher dans le texte les matériels physiques. Cherche spécifiquement les sections qui parlent de "Groupes d'extraction", "Caissons de ventilation", ou "Unités d'extraction".
   - Ce sont ces matériels (ex: EASY VEC, C4, VEX, etc.) qui constituent les "modeles" attendus.

3. EXCLUSION DES RÉFÉRENCES CROISÉES :
   - N'extrais JAMAIS un modèle s'il est indiqué que ses caractéristiques relèvent d'un AUTRE Avis Technique.

4. TYPE DE LOGEMENT :
   - Cherche la section "Domaine d'emploi" ou "Domaine d'application".
   - "maisons individuelles" = "Individuel".
   - "logements collectifs" ou "bâtiments d'habitation collective" = "Collectif".
   - Si les deux = "Mixte".
   - Attention : "non destiné au collectif" = "Individuel".

5. CARACTÉRISTIQUE BASSE PRESSION (STRICT) :
   - Mets `true` UNIQUEMENT si les termes exacts "basse pression" ou "BP" sont explicitement associés au modèle. 
   - "pression constante", "PCI", "pression standard" = `false`.

6. DÉBITS (RESTRICTION MAJEURE) :
   - N'extrais un débit QUE s'il fait explicitement partie de l'appellation commerciale du caisson dans le texte (ex: caisson "Modèle X 400" -> extrait "400").
   - INTERDICTION STRICTE : Ne lis SURTOUT PAS les tableaux de caractéristiques (techniques, thermiques, aérauliques).
   - Si le nom du modèle ne contient pas de notion de débit, renvoie une liste vide [].

7. FORMAT :
   - Renvoie UNIQUEMENT l'objet JSON valide, sans balises markdown.
"""

def tester_pdf(chemin_pdf):
    nom_fichier = os.path.basename(chemin_pdf)
    print(f"\n🚀 Analyse de : {nom_fichier}...")
    
    try:
        fichier_upload = client.files.upload(file=chemin_pdf)
        
        reponse = client.models.generate_content(
            model='gemini-3.1-flash-lite',
            contents=[fichier_upload, PROMPT_VMC],
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        
        client.files.delete(name=fichier_upload.name)
        
        donnees = json.loads(reponse.text)
        print("\n✅ RÉSULTAT DE L'EXTRACTION :\n")
        print(json.dumps(donnees, indent=4, ensure_ascii=False))
        
    except Exception as e:
        print(f"❌ Erreur lors de l'analyse : {e}")

if __name__ == "__main__":
    dossier_actuel = os.path.dirname(os.path.abspath(__file__))
    
    # Test avec le fichier BAHIA
    nom_du_pdf_test = "test.pdf" # Remets "test.pdf" si tu testes le fichier d'avant
    chemin = os.path.join(dossier_actuel, nom_du_pdf_test)
    
    if os.path.exists(chemin):
        tester_pdf(chemin)
    else:
        print(f"⚠️ Fichier introuvable : {chemin}")