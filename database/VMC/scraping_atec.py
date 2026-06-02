import os
import json
import time
import tomllib
import shutil  # Permet de déplacer les fichiers
from google import genai
from google.genai import types

# --- RÉCUPÉRATION DE LA CLÉ API DEPUIS STREAMLIT SECRETS ---
dossier_du_script = os.path.dirname(os.path.abspath(__file__))
dossier_racine = os.path.abspath(os.path.join(dossier_du_script, "..", ".."))
chemin_secrets = os.path.join(dossier_racine, ".streamlit", "secrets.toml")

try:
    with open(chemin_secrets, "rb") as f:
        secrets = tomllib.load(f)
        CLE_API = secrets.get("GEMINI_API_KEY") 
    if not CLE_API:
        raise ValueError("La clé GEMINI_API_KEY n'a pas été trouvée.")
except FileNotFoundError:
    print(f"❌ ERREUR : Le fichier {chemin_secrets} est introuvable.")
    exit(1)

client = genai.Client(api_key=CLE_API)

def analyser_pdf_cstb(chemin_pdf):
    """Upload le PDF, l'analyse avec Gemini et retourne un dictionnaire Python."""
    nom_fichier = os.path.basename(chemin_pdf)
    print(f"  -> Upload de {nom_fichier} vers l'API Gemini...")
    
    try:
        fichier_upload = client.files.upload(
            file=chemin_pdf, 
            config={'display_name': 'ATec_VMC'}
        )
        
        # --- NOUVEAU PROMPT (Avec gestion des débits) ---
        prompt = """
        Tu es un expert en conformité documentaire CEE.
        Analyse ce document (Avis Technique du CSTB pour la ventilation) pour en extraire l'arborescence.
        
        Extrais les informations au format JSON strict avec la structure exacte suivante :
        {
          "numero_atec": "Le numéro de l'Avis (ex: 14.5/17-2273)",
          "indice_revision": "Ex: 'V2', 'Modificatif 1' ou 'V1' si non précisé",
          "fabricant": "Le nom du titulaire",
          "debut_validite": "YYYY-MM-DD",
          "fin_validite": "YYYY-MM-DD",
          "modeles": [
            {
              "nom_modele": "Nom de la gamme (ex: Copernic V)",
              "type_logement": "'Individuel', 'Collectif' ou 'Mixte'",
              "basse_pression": true ou false,
              "debits_disponibles": ["400", "700", "1000"]
            }
          ]
        }
        
        Règles D'EXTRACTION ABSOLUES :
        
        1. REGROUPEMENT ET DÉBITS :
           - Regroupe les modèles d'une même gamme sous un seul "nom_modele" (ex: "Copernic V").
           - Cherche les débits associés (souvent exprimés en m3/h, ex: 400, 700, 1000) et liste-les dans "debits_disponibles" (tableau de strings).
           - S'il y a un intervalle (ex: "de 100 à 500"), écris ["100-500"].
           - S'il n'y a pas de débits spécifiques, renvoie une liste vide [].

        2. CARACTÉRISTIQUE BASSE PRESSION :
           - `true` UNIQUEMENT si le document indique explicitement que ce modèle est "basse pression" ou "BP". Sinon `false`.

        3. PURETÉ DU JSON :
           - Renvoie UNIQUEMENT l'objet JSON, pas de W-Th-C ni de courbes.
        """
        
        reponse = client.models.generate_content(
            model='gemini-3.1-flash-lite',
            contents=[fichier_upload, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )
        
        client.files.delete(name=fichier_upload.name)
        return json.loads(reponse.text)

    except Exception as e:
        print(f"  ❌ Erreur lors de l'analyse : {e}")
        return None

def consolider_referentiel(dossier_source, dossier_archives, fichier_json_sortie):
    """Parcourt les PDF, met à jour le JSON, et archive les fichiers traités."""
    referentiel = {}
    
    if os.path.exists(fichier_json_sortie) and os.path.getsize(fichier_json_sortie) > 0:
        try:
            with open(fichier_json_sortie, 'r', encoding='utf-8') as f:
                referentiel = json.load(f)
        except json.JSONDecodeError:
            print("  ⚠️ JSON illisible. Création d'un nouveau référentiel.")
            referentiel = {}

    fichiers_pdf = [f for f in os.listdir(dossier_source) if f.endswith('.pdf')]
    print(f"Lancement de l'analyse sur {len(fichiers_pdf)} nouveaux fichiers...\n")

    for nom_fichier in fichiers_pdf:
        chemin_complet = os.path.join(dossier_source, nom_fichier)
        print(f"Traitement en cours : {nom_fichier}")
        
        donnees = analyser_pdf_cstb(chemin_complet)
        
        if donnees and "numero_atec" in donnees:
            num_atec = donnees["numero_atec"]
            
            if num_atec not in referentiel:
                referentiel[num_atec] = []
                
            version_existante = any(
                doc.get("indice_revision") == donnees.get("indice_revision") 
                for doc in referentiel[num_atec]
            )
            
            if not version_existante:
                referentiel[num_atec].append(donnees)
                print(f"  ✅ Succès : Ajout de {num_atec}.")
            else:
                print(f"  ⚠️ La version {donnees.get('indice_revision')} existait déjà dans le JSON. Mise à jour ignorée pour éviter les doublons.")
            
            # --- L'ARCHIVAGE (La solution au problème d'API) ---
            # Que ce soit un succès d'ajout ou un doublon repéré, on déplace le PDF
            # pour ne plus avoir à le lire au prochain lancement.
            chemin_archive = os.path.join(dossier_archives, nom_fichier)
            shutil.move(chemin_complet, chemin_archive)
            print(f"  📁 Fichier archivé.")
            
        time.sleep(2)

    with open(fichier_json_sortie, 'w', encoding='utf-8') as f:
        json.dump(referentiel, f, indent=4, ensure_ascii=False)
    
    print(f"\n🎉 Terminé ! Base de données mise à jour.")

# --- DÉMARRAGE ---
if __name__ == "__main__":
    dossier_du_script = os.path.dirname(os.path.abspath(__file__))
    
    # Nos trois chemins clés
    DOSSIER_SOURCE = os.path.join(dossier_du_script, "ATec_VMC")
    DOSSIER_ARCHIVES = os.path.join(dossier_du_script, "ATec_Archives")
    FICHIER_BDD = os.path.join(dossier_du_script, "referentiel_cstb.json")
    
    # Création des dossiers s'ils n'existent pas
    os.makedirs(DOSSIER_SOURCE, exist_ok=True)
    os.makedirs(DOSSIER_ARCHIVES, exist_ok=True)
    
    consolider_referentiel(DOSSIER_SOURCE, DOSSIER_ARCHIVES, FICHIER_BDD)