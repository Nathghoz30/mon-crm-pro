import streamlit as st
import pandas as pd
import requests
import json
from datetime import datetime
import io
import os
from supabase import create_client, Client
from pypdf import PdfWriter, PdfReader
from PIL import Image

# --- CONFIGURATION & SETUP ---
st.set_page_config(page_title="Universal CRM", page_icon="🗂️", layout="wide")

# Initialisation Supabase
@st.cache_resource
def init_connection():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_connection()

# --- FONCTIONS UTILITAIRES ---

def get_siret_info(siret):
    """Récupère les infos entreprise via l'API Gouv"""
    url = f"https://recherche-entreprises.api.gouv.fr/search?q={siret}"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            if data['results']:
                ent = data['results'][0]
                return {
                    "nom": ent.get('nom_complet'),
                    "adresse": ent.get('siege', {}).get('adresse'),
                    "ville": ent.get('siege', {}).get('libelle_commune'),
                    "cp": ent.get('siege', {}).get('code_postal'),
                    "tva": ent.get('numero_tva_intracommunautaire')
                }
    except:
        pass
    return None

def upload_file_to_supabase(file, path):
    """Upload un fichier vers Supabase Storage"""
    try:
        file_bytes = file.getvalue()
        supabase.storage.from_("fichiers").upload(
            path=path,
            file=file_bytes,
            file_options={"content-type": file.type, "upsert": "true"}
        )
        # Retourne l'URL publique
        public_url = supabase.storage.from_("fichiers").get_public_url(path)
        return public_url
    except Exception as e:
        st.error(f"Erreur upload: {e}")
        return None

def merge_files_to_pdf(files_urls):
    """Fusionne images et PDFs en un seul PDF"""
    merger = PdfWriter()
    
    for url in files_urls:
        try:
            response = requests.get(url)
            if response.status_code == 200:
                file_content = io.BytesIO(response.content)
                
                # Si c'est un PDF
                if url.lower().endswith(".pdf"):
                    reader = PdfReader(file_content)
                    merger.append(reader)
                
                # Si c'est une Image (JPG, PNG...)
                elif url.lower().endswith((".png", ".jpg", ".jpeg")):
                    img = Image.open(file_content)
                    img = img.convert('RGB')
                    img_pdf = io.BytesIO()
                    img.save(img_pdf, format='PDF')
                    img_pdf.seek(0)
                    merger.append(PdfReader(img_pdf))
        except Exception as e:
            st.warning(f"Impossible de fusionner le fichier {url}: {e}")
            
    output = io.BytesIO()
    merger.write(output)
    output.seek(0)
    return output

# --- INTERFACE ---

st.title("🗂️ Universal CRM & GED")

# Onglets de navigation
tab1, tab2, tab3 = st.tabs(["1. 📝 Nouveau Dossier", "2. 📂 Gestion des Dossiers", "3. ⚙️ Configuration (Admin)"])

# ==========================================
# ONGLET 1 : NOUVEAU DOSSIER
# ==========================================
with tab1:
    st.header("Créer un nouveau dossier")
    
    # Choix du modèle
    activities = supabase.table("activities").select("*").execute().data
    if not activities:
        st.info("Commencez par configurer une Activité dans l'onglet Admin.")
    else:
        act_choice = st.selectbox("Activité", options=[a['name'] for a in activities], key="new_act")
        act_id = next(a['id'] for a in activities if a['name'] == act_choice)
        
        collections = supabase.table("collections").select("*").eq("activity_id", act_id).execute().data
        
        if collections:
            col_choice = st.selectbox("Modèle de dossier", options=[c['name'] for c in collections], key="new_col")
            selected_collection = next(c for c in collections if c['name'] == col_choice)
            fields_config = selected_collection['fields']
            
            with st.form("new_record_form"):
                form_data = {}
                uploaded_files_map = {} # Pour stocker les fichiers temporairement
                
                # Tri des champs par section pour affichage propre
                # On suppose que les champs sont stockés dans une liste
                
                # --- LOGIQUE D'AFFICHAGE DU FORMULAIRE ---
                # On groupe par "section" si vous en avez défini, sinon on affiche tout à la suite
                # Ici simplifions : on itère sur la liste
                
                for field in fields_config:
                    label = field['name']
                    ftype = field['type']
                    # Gestion de l'astérisque visuel pour l'obligatoire
                    display_label = f"{label} *" if field.get('required') else label
                    
                    if ftype == "Texte Court":
                        form_data[label] = st.text_input(display_label)
                    elif ftype == "Texte Long":
                        form_data[label] = st.text_area(display_label)
                    elif ftype == "Nombre":
                        form_data[label] = st.number_input(display_label, step=1.0)
                    elif ftype == "Date":
                        form_data[label] = st.date_input(display_label, value=None)
                    elif ftype == "SIRET":
                        c1, c2 = st.columns([3, 1])
                        siret_val = c1.text_input(display_label)
                        if c2.form_submit_button("🔍 Auto-fill"):
                            infos = get_siret_info(siret_val)
                            if infos:
                                st.success(f"Trouvé : {infos['nom']}")
                                # Note : Pour pré-remplir les autres champs, il faudrait recharger la page ou utiliser session_state
                                # Ici on stocke juste le SIRET pour l'exemple
                        form_data[label] = siret_val
                    elif ftype == "Fichier":
                        uploaded = st.file_uploader(display_label, accept_multiple_files=True)
                        uploaded_files_map[label] = uploaded
                    elif ftype == "Oui/Non":
                        form_data[label] = st.checkbox(display_label)
                    else:
                        form_data[label] = st.text_input(display_label)

                submit = st.form_submit_button("💾 Enregistrer le Dossier")
                
                if submit:
                    errors = []
                    final_data = form_data.copy()
                    
                    # 1. VALIDATION "OBLIGATOIRE"
                    for field in fields_config:
                        fname = field['name']
                        if field.get('required', False):
                            # Vérification spécifique selon le type
                            val = final_data.get(fname)
                            
                            # Si c'est un fichier, on vérifie dans la map des uploads
                            if field['type'] == "Fichier":
                                if not uploaded_files_map.get(fname):
                                    errors.append(f"Le champ '{fname}' est obligatoire (document manquant).")
                            # Pour les autres champs
                            elif not val: # Check if empty string, None, etc.
                                errors.append(f"Le champ '{fname}' est obligatoire.")

                    if errors:
                        for e in errors:
                            st.error(e)
                    else:
                        # 2. UPLOAD DES FICHIERS SI TOUT EST OK
                        timestamp = int(datetime.now().timestamp())
                        
                        for field in fields_config:
                            if field['type'] == "Fichier":
                                flist = uploaded_files_map.get(field['name'])
                                urls = []
                                if flist:
                                    for f in flist:
                                        # Chemin : id_collection/timestamp_nomfichier
                                        path = f"{selected_collection['id']}/{timestamp}_{f.name}"
                                        url = upload_file_to_supabase(f, path)
                                        if url:
                                            urls.append(url)
                                final_data[field['name']] = urls

                        # 3. SAUVEGARDE EN BDD
                        # Conversion des dates en string pour JSON
                        for k, v in final_data.items():
                            if isinstance(v, (datetime, pd.Timestamp)): # Correction pour date
                                final_data[k] = v.isoformat()

                        supabase.table("records").insert({
                            "collection_id": selected_collection['id'],
                            "data": final_data
                        }).execute()
                        
                        st.success("Dossier enregistré avec succès !")
                        st.balloons()

# ==========================================
# ONGLET 2 : GESTION & PDF
# ==========================================
with tab2:
    st.header("Gestion des Dossiers")
    
    # Filtres
    all_cols = supabase.table("collections").select("id, name, fields").execute().data
    if all_cols:
        filter_col = st.selectbox("Filtrer par Modèle", ["Tous"] + [c['name'] for c in all_cols])
        
        query = supabase.table("records").select("*, collections(name, fields)")
        if filter_col != "Tous":
            query = query.eq("collections.name", filter_col)
            
        records = query.execute().data
        
        if records:
            # Affichage en tableau sommaire
            df_display = []
            for r in records:
                row = r['data'].copy()
                row['ID'] = r['id']
                row['Modèle'] = r['collections']['name']
                row['Date Création'] = r['created_at'][:10]
                df_display.append(row)
            
            st.dataframe(pd.DataFrame(df_display).set_index("ID"))
            
            st.divider()
            
            # Sélection d'un dossier pour action
            selected_id = st.number_input("Entrez l'ID du dossier à gérer", min_value=0, step=1)
            
            if selected_id in [r['id'] for r in records]:
                record = next(r for r in records if r['id'] == selected_id)
                rec_data = record['data']
                col_config = record['collections']['fields'] # La config des champs
                
                st.subheader(f"Dossier #{selected_id}")
                st.json(rec_data, expanded=False)
                
                # BOUTON DE FUSION PDF AVEC VALIDATION
                st.markdown("### 🖨️ Actions")
                
                if st.button("📥 Télécharger le Dossier Complet (PDF)"):
                    # 1. VÉRIFICATION "REQUIS POUR FUSION"
                    blocking_errors = []
                    files_to_merge = []
                    
                    for field in col_config:
                        fname = field['name']
                        
                        # On ne s'intéresse qu'aux champs fichiers pour la fusion
                        if field['type'] == "Fichier":
                            existing_files = rec_data.get(fname, [])
                            
                            # Vérification du bloquage
                            if field.get('required_for_pdf', False):
                                if not existing_files or len(existing_files) == 0:
                                    blocking_errors.append(f"❌ Document manquant : {fname}")
                            
                            # Si fichiers présents, on les ajoute à la liste de fusion
                            if existing_files:
                                files_to_merge.extend(existing_files)

                    if blocking_errors:
                        st.error("Impossible de générer le PDF. Le dossier est incomplet :")
                        for err in blocking_errors:
                            st.write(err)
                    else:
                        # 2. GÉNÉRATION SI OK
                        if not files_to_merge:
                            st.warning("Aucun fichier trouvé dans ce dossier.")
                        else:
                            with st.spinner("Fusion des documents en cours..."):
                                pdf_bytes = merge_files_to_pdf(files_to_merge)
                                st.download_button(
                                    label="💾 Cliquez ici pour télécharger le PDF",
                                    data=pdf_bytes,
                                    file_name=f"Dossier_{selected_id}_Complet.pdf",
                                    mime="application/pdf"
                                )

        else:
            st.info("Aucun dossier trouvé.")

# ==========================================
# ONGLET 3 : CONFIGURATION (ADMIN)
# ==========================================
with tab3:
    st.header("⚙️ Configuration des Modèles")
    
    with st.expander("1. Créer une Activité (ex: Rénovation, Administratif)"):
        new_act_name = st.text_input("Nom de l'activité")
        if st.button("Créer Activité"):
            if new_act_name:
                try:
                    supabase.table("activities").insert({"name": new_act_name}).execute()
                    st.success(f"Activité '{new_act_name}' créée !")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erreur : {e}")

    st.divider()
    
    with st.expander("2. Créer un Modèle de Dossier", expanded=True):
        acts = supabase.table("activities").select("*").execute().data
        if acts:
            target_act = st.selectbox("Lier à l'activité", [a['name'] for a in acts])
            act_id_target = next(a['id'] for a in acts if a['name'] == target_act)
            
            new_col_name = st.text_input("Nom du Modèle (ex: Dossier Client)")
            
            st.subheader("Définition des Champs")
            
            # Gestion dynamique des champs via Session State
            if "fields_temp" not in st.session_state:
                st.session_state.fields_temp = []
            
            # Ajout d'un champ
            c1, c2, c3 = st.columns([3, 2, 1])
            f_name = c1.text_input("Nom du champ")
            f_type = c2.selectbox("Type", ["Texte Court", "Texte Long", "Nombre", "Date", "SIRET", "Fichier", "Oui/Non"])
            
            # --- LES OPTIONS DE VALIDATION ---
            # Option 1 : Toujours visible
            req_general = st.checkbox("Obligatoire", help="L'utilisateur ne pourra pas enregistrer le dossier si ce champ est vide.")
            
            # Option 2 : Visible seulement si Fichier
            req_pdf = False
            if f_type == "Fichier":
                req_pdf = st.checkbox("🔒 Requis pour la Fusion PDF", help="Bloque la génération du PDF final si ce fichier manque.")
            
            if c3.button("Ajouter ce champ"):
                if f_name:
                    st.session_state.fields_temp.append({
                        "name": f_name,
                        "type": f_type,
                        "required": req_general,        # Stockage de l'option 1
                        "required_for_pdf": req_pdf     # Stockage de l'option 2
                    })
                    st.rerun()
            
            # Liste des champs actuels
            if st.session_state.fields_temp:
                st.write("### Champs configurés :")
                for i, f in enumerate(st.session_state.fields_temp):
                    req_txt = "🔴 Obligatoire" if f.get('required') else ""
                    pdf_txt = "🔒 Bloquant PDF" if f.get('required_for_pdf') else ""
                    st.text(f"{i+1}. {f['name']} ({f['type']}) {req_txt} {pdf_txt}")
                
                if st.button("🗑️ Reset Champs"):
                    st.session_state.fields_temp = []
                    st.rerun()
            
            if st.button("✅ Sauvegarder le Modèle"):
                if new_col_name and st.session_state.fields_temp:
                    supabase.table("collections").insert({
                        "name": new_col_name,
                        "activity_id": act_id_target,
                        "fields": st.session_state.fields_temp
                    }).execute()
                    st.success("Modèle créé avec succès !")
                    st.session_state.fields_temp = [] # Reset
                    st.rerun()
                else:
                    st.error("Nom ou champs manquants.")
        else:
            st.warning("Créez d'abord une activité.")
