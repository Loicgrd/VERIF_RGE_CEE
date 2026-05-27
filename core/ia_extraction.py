import io
import json
import zipfile
import pandas as pd
import streamlit as st
from PyPDF2 import PdfReader
from datetime import datetime
from google import genai  # On utilise le nouveau SDK
import re

# Initialisation du client (pas de .configure() !)
# Assure-toi que st.secrets["GEMINI_API_KEY"] est bien défini dans ton streamlit



def process_file(file_name, file_bytes):
    text_content = ""
    if file_name.lower().endswith('.pdf'):
        try:
            reader = PdfReader(io.BytesIO(file_bytes))
            for page in reader.pages:
                text_content += page.extract_text() + "\n"
        except Exception:
            pass
    elif file_name.lower().endswith(('.xlsx', '.xls')):
        try:
            dfs = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None)
            for df in dfs.values():
                text_content += df.to_string() + "\n"
        except Exception:
            pass
    return text_content

def ask_ai_for_data(text):
    if not text.strip():
        return [], None
    
    api_key = st.secrets["GEMINI_API_KEY"]

# Initialisation du client
    client = genai.Client(api_key=api_key)


    prompt = f"""
    Tu es un assistant strict spécialisé dans les documents administratifs français.
    Extrais :
    1. Tous les numéros de SIRET UNIQUE(14 chiffres, sans espaces ni tirets).
    2. La date d'engagement au format YYYY-MM-DD seulement si elle est explicitement mentionnée sur un excel ou SEULEMENT si tu peux identifier la date parmis les 4 type de documents suivants :
        2.1. Ordre de Service c'est la date du document, s'il n'y en a pas c'est la date de signature.
        2.2.Acte d'engagement c'est la date du document, s'il n'y en a pas c'est la date de signature.
        2.3. Devis c'est la date de signature du maire d'ouvrage.
        2.4. Bon de commande c'est la date de signature du maitre d'ouvrage, ou la date du document s'il n'y en a pas.
        Si tu ne trouves pas une de ces dates ou que tu n'identifie pas exactement le document ne prend pas la date.

    Renvoie UNIQUEMENT un JSON valide :
    {{"sirets": ["num1", "num2"], "date": "YYYY-MM-DD"}}
    S'il n'y a pas de SIRET ou de date, mets une liste vide [] ou null.
    
    Texte : {text[:15000]}
    """
    
    try:
        # APPEL MODERNE AVEC LE NOUVEAU SDK
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite", 
            contents=prompt,
        )
        
        # Nettoyage
        clean_json = response.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(clean_json)
        
        date_obj = None
        if data.get("date"):
            try:
                date_obj = datetime.strptime(data["date"], '%Y-%m-%d').date()
            except: pass
                
        return data.get("sirets", []), date_obj
    except Exception as e:
        error_msg = str(e)
        error_msg_lower = error_msg.lower()
        
        # On intercepte spécifiquement les erreurs de quota (429)
        if "quota" in error_msg_lower or "429" in error_msg_lower or "exhausted" in error_msg_lower:
            wait_time = "quelques" # Valeur par défaut
            
            # 1ère méthode : on cherche 'retryDelay': '11s'
            match_delay = re.search(r"retryDelay':\s*'(\d+)s'", error_msg)
            if match_delay:
                wait_time = match_delay.group(1)
            else:
                # 2ème méthode : on cherche 'retry in 11.66s'
                match_text = re.search(r"retry in ([\d\.]+)s", error_msg)
                if match_text:
                    # On convertit le nombre à virgule en nombre entier (ex: 11.66 devient 11)
                    wait_time = str(int(float(match_text.group(1))))
                    
            print(f"DEBUG: Quota IA dépassé. Attente : {wait_time}s")
            # On renvoie le code d'erreur, ET on détourne la 2ème variable pour faire passer le temps d'attente
            return ["QUOTA_EXCEEDED"], wait_time
            
        print(f"DEBUG: ERREUR API IA : {e}")
        return [], None

def analyze_documents(uploaded_files):
    texte_global = ""

    for uploaded_file in uploaded_files:
        uploaded_file.seek(0) 
        file_bytes = uploaded_file.read()
        file_name = uploaded_file.name

        if file_name.lower().endswith('.zip'):
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
                for z_info in z.infolist():
                    if not z_info.is_dir():
                        z_bytes = z.read(z_info.filename)
                        
                        # Ajout de l'intercalaire avec le nom du fichier du ZIP
                        texte_global += f"\n\n--- DÉBUT DU DOCUMENT : {z_info.filename} ---\n"
                        texte_global += process_file(z_info.filename, z_bytes)
                        texte_global += f"\n--- FIN DU DOCUMENT : {z_info.filename} ---\n"
        else:
            # Ajout de l'intercalaire avec le nom du fichier classique
            texte_global += f"\n\n--- DÉBUT DU DOCUMENT : {file_name} ---\n"
            texte_global += process_file(file_name, file_bytes)
            texte_global += f"\n--- FIN DU DOCUMENT : {file_name} ---\n"

    if texte_global.strip():
        return ask_ai_for_data(texte_global)
    else:
        return [], None

