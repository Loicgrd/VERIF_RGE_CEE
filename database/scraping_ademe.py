import requests
import pandas as pd
import time

def scraper_base_rge():
    # Liste pour accumuler les données
    all_lines = []
    
    # URL de base avec les optimisations conseillées par l'ADEME
    # On demande 10 000 résultats par page et uniquement les colonnes nécessaires
    columns = "siret,nom_entreprise,domaine,code_qualification,lien_date_debut,lien_date_fin,date_debut,date_fin,url_qualification,_id"
    base_url = f"https://data.ademe.fr/data-fair/api/v1/datasets/historique-rge/lines?size=10000&count=false&select={columns}"
    
    url = base_url
    page = 1
    start_time = time.time()

    print("🚀 Début du scraping de la base RGE (5,5 millions de lignes)...")

    while url:
        try:
            response = requests.get(url, timeout=30)
            if response.status_code != 200:
                print(f"❌ Erreur Code {response.status_code} à la page {page}. Nouvelle tentative dans 10s...")
                time.sleep(10)
                continue
                
            data = response.json()
            results = data.get('results', [])
            
            if not results:
                print("🏁 Fin des données atteintes (aucun résultat sur cette page).")
                break
                
            all_lines.extend(results)
            
            if page % 10 == 0:
                print(f"📦 Page {page} téléchargée... Enregistrements cumulés : {len(all_lines)}")
            
            # Récupération du lien de la page suivante fourni par l'ADEME
            url = data.get('next')
            page += 1
            
            # Petit sleep pour respecter le serveur de l'ADEME
            time.sleep(0.2)
            
        except Exception as e:
            print(f"⚠️ Erreur : {e}. Pause de 10s avant reprise...")
            time.sleep(10)
            continue

    print(f"💾 Téléchargement terminé en {round((time.time() - start_time)/60, 2)} minutes.")
    print(f"📊 Nombre total de lignes récupérées : {len(all_lines)}")

    # Conversion en DataFrame Pandas
    print("🧹 Conversion et optimisation du fichier...")
    df = pd.DataFrame(all_lines)

    # Sauvegarde au format Parquet avec compression maximale
    file_name = "rge_backup.parquet"
    df.to_parquet(file_name, compression='brotli', index=False)
    
    print(f"✨ Fichier sauvegardé avec succès sous le nom : {file_name}")

if __name__ == "__main__":
    # Pense à installer les packages requis : pip install requests pandas pyarrow fastparquet brotli
    scraper_base_rge()