import io
import json
import zipfile
import pandas as pd
import streamlit as st
from PyPDF2 import PdfReader
from datetime import datetime
from google import genai  # On utilise le nouveau SDK

# Initialisation du client (pas de .configure() !)
# Assure-toi que st.secrets["GEMINI_API_KEY"] est bien défini dans ton streamlit
client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])


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
    
    prompt = f"""
    Tu es un assistant strict spécialisé dans les documents administratifs français.
    Extrais :
    1. Tous les numéros de SIRET (14 chiffres, sans espaces ni tirets).
    2. La date d'engagement au format YYYY-MM-DD seulement si elle est explicitement mentionnée, ou bien les différentes possibilités sont les suivantes :
        Pour les documents suivants : Ordre de Service et Acte d'engagement, c'est la date du document, s'il n'y en a pas c'est la date de signature.
        Pour un devis c'est la date de signature du maire d'ouvrage.
        Pour un Bon de commande c'est la date de signature du maitre d'ouvrage, ou la date du document s'il n'y en a pas.

    Renvoie UNIQUEMENT un JSON valide :
    {{"sirets": ["num1", "num2"], "date": "YYYY-MM-DD"}}
    S'il n'y a pas de SIRET ou de date, mets une liste vide [] ou null.
    
    Texte : {text[:15000]}
    """
    
    try:
        # APPEL MODERNE AVEC LE NOUVEAU SDK
        response = client.models.generate_content(
            model="gemini-flash-latest", 
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
        print(f"DEBUG: ERREUR API IA : {e}")
        return [], None

def analyze_documents(uploaded_files):
    all_sirets = set()
    found_date = None

    for uploaded_file in uploaded_files:
        uploaded_file.seek(0) 
        file_bytes = uploaded_file.read()
        file_name = uploaded_file.name

        if file_name.lower().endswith('.zip'):
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
                for z_info in z.infolist():
                    if not z_info.is_dir():
                        z_bytes = z.read(z_info.filename)
                        text = process_file(z_info.filename, z_bytes)
                        sirets, date = ask_ai_for_data(text)
                        all_sirets.update(sirets)
                        if not found_date and date: found_date = date
        else:
            text = process_file(file_name, file_bytes)
            sirets, date = ask_ai_for_data(text)
            all_sirets.update(sirets)
            if not found_date and date: found_date = date

    return list(all_sirets), found_date