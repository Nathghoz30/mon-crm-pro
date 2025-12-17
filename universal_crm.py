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
# Assurez-vous d'avoir configuré .streamlit/secrets.toml
@st.cache_resource
def init_connection():
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        return create_client(url, key)
    except:
        st.error("Secrets Supabase manquants. Vérifiez votre fichier .streamlit/secrets.toml")
        st.stop()

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

# --- INTERFACE PRINCIPALE ---

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
                
                # --- GÉNÉRATION DU FORMULAIRE ---
                for field in fields_config:
                    label = field['name']
                    ftype = field['type']
                    # Indication visuelle si obligatoire
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
                    
                    # 1. VALIDATION "OBLIGATOIRE À LA SAISIE"
                    for field in fields_config:
                        fname = field['name']
                        if field.get('required', False):
                            val = final_data.get(fname)
                            
                            # Si c'est un fichier, on vérifie dans la map des uploads
                            if field['type'] == "Fichier":
                                if not uploaded_files_map.get(fname):
                                    errors.append(f"Le champ '{fname}' est obligatoire (document manquant).")
                            # Pour les autres champs
                            elif not val: 
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
                            if isinstance(v, (datetime, pd.Timestamp)):
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
    
    # 1. CRÉATION ACTIVITÉ
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
    
    # 2. CRÉATION MODÈLE
    with st.expander("2. Créer un NOUVEAU Modèle de Dossier"):
        acts = supabase.table("activities").select("*").execute().data
        if acts:
            target_act = st.selectbox("Lier à l'activité", [a['name'] for a in acts])
            act_id_target = next(a['id'] for a in acts if a['name'] == target_act)
            
            new_col_name = st.text_input("Nom du Modèle (ex: Dossier Client)")
            
            st.subheader("Définition des Champs")
            
            if "fields_temp" not in st.session_state:
                st.session_state.fields_temp = []
            
            # Ajout d'un champ
            c1, c2, c3 = st.columns([3, 2, 1])
            f_name = c1.text_input("Nom du champ")
            f_type = c2.selectbox("Type", ["Texte Court", "Texte Long", "Nombre", "Date", "SIRET", "Fichier", "Oui/Non"])
            
            # --- LES OPTIONS DE VALIDATION ---
            req_general = st.checkbox("Obligatoire à la saisie", help="Impossible d'enregistrer si vide.")
            
            req_pdf = False
            if f_type == "Fichier":
                req_pdf = st.checkbox("🔒 Requis pour la Fusion PDF", help="Bloque le téléchargement du PDF si manquant.")
            
            if c3.button("Ajouter ce champ"):
                if f_name:
                    st.session_state.fields_temp.append({
                        "name": f_name,
                        "type": f_type,
                        "required": req_general,
                        "required_for_pdf": req_pdf
                    })
                    st.rerun()
            
            # Liste des champs
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

    st.divider()

    # 3. GESTION DES MODÈLES EXISTANTS
    with st.expander("3. Gérer les Modèles existants (Modifier / Supprimer)", expanded=False):
        acts_manage = supabase.table("activities").select("*").execute().data
        
        if acts_manage:
            c_filter1, c_filter2 = st.columns(2)
            act_choice_manage = c_filter1.selectbox("Choisir l'Activité", [a['name'] for a in acts_manage], key="manage_act")
            act_id_manage = next(a['id'] for a in acts_manage if a['name'] == act_choice_manage)
            
            cols_manage = supabase.table("collections").select("*").eq("activity_id", act_id_manage).execute().data
            
            if cols_manage:
                col_choice_manage = c_filter2.selectbox("Choisir le Modèle à gérer", [c['name'] for c in cols_manage], key="manage_col")
                selected_col_manage = next(c for c in cols_manage if c['name'] == col_choice_manage)
                
                st.markdown(f"### 🔧 Modification : {selected_col_manage['name']}")
                
                current_fields = selected_col_manage['fields']
                updated_fields = []
                has_changes = False
                
                st.info("Cochez/Décochez les options pour mettre à jour la configuration.")
                
                for idx, field in enumerate(current_fields):
                    with st.container():
                        c_name, c_type, c_opt1, c_opt2 = st.columns([3, 2, 2, 2])
                        
                        c_name.text(f"📄 {field['name']}")
                        c_type.caption(f"Type : {field['type']}")
                        
                        # Modif : Obligatoire
                        new_req = c_opt1.checkbox(
                            "🔴 Obligatoire", 
                            value=field.get('required', False), 
                            key=f"manage_req_{selected_col_manage['id']}_{idx}"
                        )
                        
                        # Modif : Bloquant PDF
                        new_pdf = False
                        if field['type'] == "Fichier":
                            new_pdf = c_opt2.checkbox(
                                "🔒 Bloquant PDF", 
                                value=field.get('required_for_pdf', False), 
                                key=f"manage_pdf_{selected_col_manage['id']}_{idx}"
                            )
                        else:
                            c_opt2.empty()
                        
                        updated_field = field.copy()
                        if new_req != field.get('required', False):
                            updated_field['required'] = new_req
                            has_changes = True
                        
                        if field['type'] == "Fichier":
                            if new_pdf != field.get('required_for_pdf', False):
                                updated_field['required_for_pdf'] = new_pdf
                                has_changes = True
                                
                        updated_fields.append(updated_field)
                        st.divider()

                if st.button("💾 Enregistrer les modifications"):
                    if has_changes:
                        supabase.table("collections").update({"fields": updated_fields}).eq("id", selected_col_manage['id']).execute()
                        st.success("Configuration mise à jour avec succès !")
                        st.rerun()
                    else:
                        st.info("Aucune modification détectée.")

                st.write("")
                
                # --- SUPPRESSION ---
                with st.expander("🗑️ Zone de Danger (Suppression)"):
                    st.warning(f"Attention : Supprimer le modèle '{selected_col_manage['name']}' effacera TOUS les dossiers qui y sont liés.")
                    if st.button(f"❌ Supprimer définitivement '{selected_col_manage['name']}'"):
                        try:
                            supabase.table("collections").delete().eq("id", selected_col_manage['id']).execute()
                            st.error("Modèle supprimé.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Erreur lors de la suppression : {e}")
            else:
                st.warning("Aucun modèle trouvé pour cette activité.")
