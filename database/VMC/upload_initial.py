import json
import os
import tomllib
from supabase import create_client

# 1. Chemins adaptés à ton arborescence
dossier_script = os.path.dirname(os.path.abspath(__file__))
chemin_secrets = os.path.abspath(os.path.join(dossier_script, "..", "..", ".streamlit", "secrets.toml"))
chemin_json = os.path.join(dossier_script, "referentiel_cstb.json")

# 2. Récupération des clés
with open(chemin_secrets, "rb") as f:
    secrets = tomllib.load(f)

# Ajoute cette ligne pour voir ce que lit vraiment ton script
print("URL lue par Python :", repr(secrets.get("SUPABASE_URL")))

supabase = create_client(secrets["SUPABASE_URL"], secrets["SUPABASE_KEY"])

# 3. Lecture du JSON local
with open(chemin_json, 'r', encoding='utf-8') as f:
    referentiel = json.load(f)

# 4. Formatage et Envoi
lignes_a_inserer = []
for num_atec, liste_revisions in referentiel.items():
    for revision in liste_revisions:
        lignes_a_inserer.append({
            "numero_atec": revision.get("numero_atec"),
            "indice_revision": revision.get("indice_revision", "V1"),
            "fabricant": revision.get("fabricant"),
            "debut_validite": revision.get("debut_validite"),
            "fin_validite": revision.get("fin_validite"),
            "url_batipedia": revision.get("url_batipedia", None), # Sera NULL pour le moment
            "modeles": revision.get("modeles", [])
        })

try:
    reponse = supabase.table("referentiel_vmc").upsert(lignes_a_inserer).execute()
    print(f"✅ {len(reponse.data)} Avis Techniques insérés dans Supabase !")
except Exception as e:
    print(f"❌ Erreur : {e}")