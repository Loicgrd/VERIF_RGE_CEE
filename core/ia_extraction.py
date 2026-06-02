import io
import json
import zipfile
import pandas as pd
import streamlit as st
from datetime import datetime
from google import genai 

def ask_ai_for_data(files_data, extra_text):
    """
    Envoie les fichiers bruts à Gemini pour analyse multimodale.
    files_data est une liste de dictionnaires : {"data": bytes, "mime_type": str, "name": str}
    """
    api_key = st.secrets["GEMINI_API_KEY"]
    client = genai.Client(api_key=api_key)

    # Préparation du contenu pour l'IA
    contents = []
    # Ajout du texte extrait des Excel
    if extra_text:
        contents.append(f"Voici des données extraites de fichiers Excel : {extra_text}")
    
    # Ajout des fichiers (PDF/Images)
    for f in files_data:
        contents.append({"inline_data": {"data": f["data"], "mime_type": f["mime_type"]}})
        contents.append(f"Document : {f['name']}")

    contents.append("Utilise ces informations (Excel + Images/PDF) pour extraire les SIRET et la date...")

    prompt = """
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
    """
    contents.append(prompt)
    
    try:
        # Utilisation de gemini-2.0-flash pour ses capacités multimodales excellentes
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite", 
            contents=contents,
        )
        
        clean_json = response.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(clean_json)
        
        date_obj = None
        if data.get("date"):
            try:
                date_obj = datetime.strptime(data["date"], '%Y-%m-%d').date()
            except: pass
                
        return data.get("sirets", []), date_obj

    except Exception as e:
        error_msg = str(e).lower()
        if "quota" in error_msg or "429" in error_msg or "exhausted" in error_msg:
            return ["QUOTA_EXCEEDED"], "60"
        print(f"DEBUG: ERREUR API IA : {e}")
        return [], None

def analyze_documents(uploaded_files):
    files_to_process = []
    
    # On stocke le texte des Excel pour les envoyer en tant que texte brut
    texte_extra_excel = ""

    for uploaded_file in uploaded_files:
        uploaded_file.seek(0)
        file_bytes = uploaded_file.read()
        file_name = uploaded_file.name.lower()
        
        # 1. Traitement spécifique des Excel
        if file_name.endswith(('.xlsx', '.xls')):
            try:
                dfs = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None)
                for sheet_name, df in dfs.items():
                    texte_extra_excel += f"\n--- Contenu Excel ({file_name} - {sheet_name}) ---\n"
                    texte_extra_excel += df.to_string()
            except Exception as e:
                st.error(f"Erreur lecture Excel {file_name}: {e}")
        
        # 2. Traitement des PDF et Images (IA Multimodale)
        elif file_name.endswith(('.pdf', '.jpg', '.jpeg', '.png')):
            mime = "application/pdf" if file_name.endswith('.pdf') else "image/jpeg"
            files_to_process.append({
                "data": file_bytes,
                "mime_type": mime,
                "name": file_name
            })
            
    # 3. Appel de l'IA avec les deux types de données
    return ask_ai_for_data(files_to_process, texte_extra_excel)

