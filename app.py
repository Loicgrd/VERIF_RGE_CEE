import streamlit as st
import pandas as pd
from datetime import datetime
import requests
import io
import zipfile
import re

st.set_page_config(page_title="Vérificateur RGE Historique", layout="wide")

# --- FONCTIONS UTILES ---

def extract_qualif_code(text):
    """Extrait uniquement le code entre parenthèses, sinon renvoie le texte brut."""
    if not text or text == "N/A":
        return "N/A"
    match = re.search(r'\((.*?)\)', text)
    if match:
        return match.group(1)
    return text

def fetch_ademe_data(siret):
    url = f"https://data.ademe.fr/data-fair/api/v1/datasets/historique-rge/lines?q=siret.exact:'{siret}'&size=1000"
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            return response.json().get('results', [])
        return []
    except Exception as e:
        st.error(f"Erreur API : {e}")
        return []

# --- INTERFACE ---
st.title("🛡️ Vérification des RGE")

date_eng = st.date_input("Date d'engagement des travaux :", datetime.now(), format="DD/MM/YYYY")

if 'siret_rows' not in st.session_state:
    st.session_state.siret_rows = pd.DataFrame([{"SIRET": ""}], dtype=str)

st.subheader("1. Liste des SIRET")
df_saisie = st.data_editor(st.session_state.siret_rows, num_rows="dynamic", use_container_width=True)

if st.button("🔍 Lancer l'analyse ADEME", type="primary"):
    sirets = [str(s).strip() for s in df_saisie["SIRET"] if s and str(s).strip()]
    
    if not sirets:
        st.warning("Veuillez saisir au moins un SIRET.")
    else:
        all_results = []
        with st.spinner("Extraction de l'historique ADEME..."):
            for s in sirets:
                api_lines = fetch_ademe_data(s)
                if api_lines:
                    nom_ent = api_lines[0].get('nom_entreprise') or api_lines[0].get('raison_sociale') or "Entreprise inconnue"
                    domaines_raw = {}
                    
                    for line in api_lines:
                        dom = str(line.get('domaine', 'Domaine non spécifié')).strip()
                        debut_str = line.get('date_debut_validite') or line.get('lien_date_debut')
                        fin_str = line.get('date_fin_validite') or line.get('lien_date_fin')
                        
                        if debut_str and fin_str:
                            try:
                                d_debut = datetime.strptime(debut_str[:10], '%Y-%m-%d').date()
                                d_fin = datetime.strptime(fin_str[:10], '%Y-%m-%d').date()
                                
                                if dom not in domaines_raw:
                                    domaines_raw[dom] = []
                                
                                # Nettoyage immédiat du numéro de qualification
                                raw_qualif = line.get('nom_qualification') or line.get('numero_certificat') or "N/A"
                                
                                domaines_raw[dom].append({
                                    "n_certif": extract_qualif_code(raw_qualif),
                                    "debut": d_debut,
                                    "fin": d_fin,
                                    "url": line.get('url_qualification') or line.get('lien_certificat'),
                                    "organisme": line.get('organisme')
                                })
                            except: continue

                    domaines_finaux = {}
                    for dom, periodes in domaines_raw.items():
                        valide_a_date = next((p for p in periodes if p['debut'] <= date_eng <= p['fin']), None)
                        if valide_a_date:
                            domaines_finaux[dom] = {**valide_a_date, "status_rge": True}
                        else:
                            plus_recent = max(periodes, key=lambda x: x['fin'])
                            domaines_finaux[dom] = {**plus_recent, "status_rge": False}

                    all_results.append({"SIRET": s, "Entreprise": nom_ent, "Domaines": domaines_finaux})
                else:
                    st.error(f"Aucune donnée historique pour le SIRET {s}")
            
            st.session_state.audit_results = all_results

# --- AFFICHAGE ET EXPORT ---
if 'audit_results' in st.session_state:
    st.subheader("2. Résultats et sélection")
    files_to_zip = []
    excel_data = []

    for res in st.session_state.audit_results:
        with st.expander(f"🏢 {res['Entreprise']} ({res['SIRET']})", expanded=True):
            c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
            
            with c1:
                choix_dom = st.selectbox("Choisir le domaine", options=list(res['Domaines'].keys()), key=f"s_{res['SIRET']}")
            
            info = res['Domaines'][choix_dom]
            status_txt = "Valide" if info['status_rge'] else "Expiré"
            
            with c2:
                if info['status_rge']:
                    st.success(f"✅ RGE {status_txt}")
                else:
                    st.error(f"❌ {status_txt}")
            
            with c3:
                st.write(f"**N° Qualif :** {info['n_certif']}")
                st.caption(f"Échéance : {info['fin'].strftime('%d/%m/%Y')}")
            
            with c4:
                if info['url']:
                    st.markdown(f"[📄 Voir PDF]({info['url']})")
                    clean_ent = res['Entreprise'].replace(" ", "_")
                    clean_dom = choix_dom.replace(" ", "_").replace("/", "-")
                    filename = f"{clean_ent}_{clean_dom}_{status_txt.upper()}.pdf"
                    files_to_zip.append({"url": info['url'], "nom": filename})

            # Préparation des données Excel pour chaque domaine sélectionné
            excel_data.append({
                "SIRET": res['SIRET'],
                "Nom d'entreprise": res['Entreprise'],
                "Domaine": choix_dom,
                "Numéro de certificat": info['n_certif'],
                "Validité RGE": status_txt,
                "Lien certificat": info['url']
            })

    # --- SECTION EXPORT ---
    if excel_data:
        st.divider()
        col_ex1, col_ex2 = st.columns(2)

        with col_ex1:
            if st.button("📦 Générer le ZIP des PDF", use_container_width=True):
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED) as zf:
                    for f in files_to_zip:
                        try:
                            resp = requests.get(f['url'], timeout=10)
                            if resp.status_code == 200:
                                zf.writestr(f['nom'], resp.content)
                        except: pass
                st.download_button("⬇️ Télécharger le ZIP", data=zip_buffer.getvalue(), file_name=f"Certificats_RGE_{datetime.now().strftime('%d_%m_%Y')}.zip", mime="application/zip", use_container_width=True)

        with col_ex2:
            # Création de l'Excel
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                # Création d'un dataframe temporaire pour le header
                df_header = pd.DataFrame([["Date d'engagement :", date_eng.strftime('%d/%m/%Y')]], columns=["A", "B"])
                df_header.to_excel(writer, index=False, header=False, sheet_name='Récapitulatif RGE')
                
                # Le tableau de données commence à la ligne 3
                df_main = pd.DataFrame(excel_data)
                df_main.to_excel(writer, index=False, startrow=2, sheet_name='Récapitulatif RGE')
                
                # Mise en forme basique (liens cliquables)
                workbook  = writer.book
                worksheet = writer.sheets['Récapitulatif RGE']
                # Ajustement de la largeur des colonnes
                worksheet.set_column('A:F', 20)
                
            st.download_button(
                label="📊 Télécharger le Récapitulatif Excel",
                data=output.getvalue(),
                file_name=f"Recap_RGE_{datetime.now().strftime('%d_%m_%Y')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )