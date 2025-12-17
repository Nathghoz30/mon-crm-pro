import streamlit as st
from supabase import create_client
import pandas as pd
import time
import re
import uuid
import requests
import json
import io

# --- 0. CONFIG & MODULES ---
try:
    from streamlit_sortables import sort_items
except ImportError:
    st.error("⚠️ Module manquant ! Tape : pip install streamlit-sortables")
    st.stop()

# NOUVEAUX MODULES POUR PDF
try:
    from pypdf import PdfWriter, PdfReader
    from PIL import Image
except ImportError:
    st.error("⚠️ Modules PDF manquants ! Tape : pip install pypdf Pillow")
    st.stop()

try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
except:
    st.error("Secrets manquants (.streamlit/secrets.toml)")
    st.stop()

@st.cache_resource
def init_connection():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_connection()
BUCKET_NAME = "fichiers"

# --- 1. STYLES CSS ---
st.markdown("""
<style>
    .section-header {
        font-size: 1.3rem;
        font-weight: 700;
        color: #FFFFFF;
        background-color: #262730;
        padding: 10px 15px;
        border-radius: 8px;
        margin-top: 25px;
        margin-bottom: 15px;
        border-left: 5px solid #FF4B4B;
    }
    .file-card {
        background-color: #1E1E1E;
        border: 1px solid #414141;
        border-radius: 6px;
        padding: 8px 12px;
        margin-bottom: 5px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-size: 0.9em;
    }
    .file-card a { color: #4DA6FF; text-decoration: none; font-weight: bold; }
    .stCheckbox { padding-top: 30px; }
    .admin-card { background-color: #0E1117; border: 1px solid #303030; padding: 15px; border-radius: 10px; margin-bottom: 10px; }
</style>
""", unsafe_allow_html=True)

# --- 2. FONCTIONS UTILITAIRES ---

def get_company_info(siret):
    try:
        clean_siret = siret.replace(" ", "")
        url = f"https://recherche-entreprises.api.gouv.fr/search?q={clean_siret}"
        r = requests.get(url)
        if r.status_code == 200:
            data = r.json()
            if data['results']:
                res = data['results'][0]
                siege = res.get("siege", {})
                parts_rue = [siege.get("numero_voie"), siege.get("type_voie"), siege.get("libelle_voie")]
                rue = " ".join([p for p in parts_rue if p])
                cp = siege.get("code_postal", "")
                ville = siege.get("libelle_commune", "")
                if rue and cp and ville:
                    adresse_complete = f"{rue} {cp} {ville}"
                else:
                    adresse_complete = res.get("adresse", "") or siege.get("adresse", "")
                return {"nom": res.get("nom_complet", ""), "adresse": adresse_complete, "ville": ville, "code postal": cp, "siret": clean_siret}
    except: pass
    return None

def upload_file_to_supabase(file_obj):
    if not file_obj: return None
    ext = file_obj.name.split(".")[-1]
    name = f"{uuid.uuid4()}.{ext}"
    try:
        supabase.storage.from_(BUCKET_NAME).upload(name, file_obj.getvalue(), {"content-type": file_obj.type})
        url = supabase.storage.from_(BUCKET_NAME).get_public_url(name)
        return {"name": file_obj.name, "url": url, "type": file_obj.type}
    except Exception as e:
        st.error(f"Erreur upload: {e}")
        return None

def merge_files_to_pdf(files_list):
    """Fusionne PDF et Images en un seul PDF"""
    merger = PdfWriter()
    
    for f in files_list:
        try:
            url = f.get('url')
            # Téléchargement du fichier
            response = requests.get(url)
            if response.status_code == 200:
                file_bytes = io.BytesIO(response.content)
                fname = f.get('name', '').lower()
                
                # Si c'est un PDF
                if fname.endswith('.pdf'):
                    merger.append(file_bytes)
                
                # Si c'est une Image (JPG, PNG)
                elif fname.endswith(('.png', '.jpg', '.jpeg')):
                    img = Image.open(file_bytes)
                    img = img.convert('RGB') # Conversion nécessaire pour PDF
                    img_byte_arr = io.BytesIO()
                    img.save(img_byte_arr, format='PDF')
                    img_byte_arr.seek(0)
                    merger.append(img_byte_arr)
        except Exception as e:
            print(f"Erreur fusion fichier {f.get('name')}: {e}")
            continue

    output = io.BytesIO()
    merger.write(output)
    merger.close()
    return output.getvalue()

def get_record_label(record_data, record_id):
    infos = []
    priority_keys = ["societe", "entreprise", "nom", "prenom"]
    for key in priority_keys:
        for k, v in record_data.items():
            if key in k.lower() and isinstance(v, str) and v:
                infos.append(v)
    if not infos:
        for k, v in record_data.items():
            if k != "ID" and isinstance(v, str) and len(v) > 1 and "http" not in v:
                infos.append(v)
    infos = list(dict.fromkeys(infos))[:2] 
    resume = " - ".join(infos)
    return f"Dossier #{record_id} | {resume}" if resume else f"Dossier #{record_id}"

# --- 3. FONCTIONS DB ---

def db_insert(table, data): return supabase.table(table).insert(data).execute()
def db_update(table, id, data): return supabase.table(table).update(data).eq("id", id).execute()
def db_delete(table, id): return supabase.table(table).delete().eq("id", id).execute()
def get_records_raw(collection_id): return supabase.table("records").select("*").eq("collection_id", collection_id).order("id").execute().data

# --- 4. INTERFACE ---

st.set_page_config(page_title="CRM Pro V12", layout="wide", page_icon="🗂️")

c_h1, c_h2 = st.columns([1, 6])
c_h1.title("🗂️")
c_h2.title("Mon CRM Métier")
st.divider()

activities = supabase.table("activities").select("*").order("name").execute().data
collections = supabase.table("collections").select("*").order("name").execute().data

menu = st.sidebar.radio("Menu", ["1. Nouveau Dossier", "2. Gestion des Dossiers", "3. Configuration (Admin)"])

# =========================================================
# 1. NOUVEAU DOSSIER
# =========================================================
if menu == "1. Nouveau Dossier":
    st.header("Créer un nouveau dossier")
    if not activities: st.warning("Configure l'admin d'abord."); st.stop()
    
    c1, c2 = st.columns(2)
    act_map = {a['name']: a['id'] for a in activities}
    cur_act = c1.selectbox("Activité", list(act_map.keys()))
    col_list = [c for c in collections if c['activity_id'] == act_map[cur_act]]
    
    if not col_list: st.info("Pas de modèle configuré."); st.stop()
    col_map = {c['name']: c for c in col_list}
    cur_mod = c2.selectbox("Type de Dossier", list(col_map.keys()))
    schema = col_map[cur_mod]
    fields = schema['fields']
    
    # SIRET
    has_siret = any(f['type'] == "SIRET" for f in fields)
    if has_siret:
        st.info("💡 Recherche Société (API Gouv)")
        cs1, cs2 = st.columns([3, 1])
        s_in = cs1.text_input("Entrez le SIRET ou SIREN", key="search_siret_input")
        if cs2.button("🔍 Auto-remplir") and s_in:
             info = get_company_info(s_in)
             if info:
                 for f in fields:
                     key = f"inp_{f['name']}"
                     fl = f['name'].lower()
                     ft = f['type']
                     val_to_set = None
                     if ft == "SIRET": val_to_set = info.get("siret")
                     elif ft == "Adresse": val_to_set = info.get("adresse")
                     elif "societe" in fl or "entreprise" in fl or "raison" in fl: val_to_set = info.get("nom")
                     elif "ville" in fl: val_to_set = info.get("ville")
                     elif "code" in fl or "cp" == fl: val_to_set = info.get("code postal")
                     if val_to_set: st.session_state[key] = val_to_set
                 st.success("Données récupérées !")
                 time.sleep(0.5); st.rerun()
             else: st.error("Rien trouvé.")
    
    main_addr_field_name = next((f['name'] for f in fields if f['type'] == "Adresse"), None)
    
    form_values = {} 
    sections_ordered = []
    seen = set()
    for f in fields:
        sec = f.get('section', 'Infos Générales')
        if sec not in seen: sections_ordered.append(sec); seen.add(sec)
    
    for section in sections_ordered:
        st.markdown(f"<div class='section-header'>{section}</div>", unsafe_allow_html=True)
        sec_fields = [f for f in fields if f.get('section', 'Infos Générales') == section]
        cols = st.columns(2)
        
        for idx, f in enumerate(sec_fields):
            c = cols[idx % 2]
            fname = f['name']
            ftype = f['type']
            widget_key = f"inp_{fname}"
            
            if ftype == "Adresse":
                form_values[fname] = c.text_input(f"{fname} 📍", key=widget_key)
            elif ftype == "Adresse Travaux":
                c_addr, c_check = c.columns([3, 1])
                use_same = c_check.checkbox("Identique ?", key=f"chk_{fname}")
                if use_same and main_addr_field_name:
                    live_main_value = st.session_state.get(f"inp_{main_addr_field_name}", "")
                    st.session_state[widget_key] = live_main_value
                    val = c_addr.text_input(f"{fname} 🏗️", disabled=True, key=widget_key)
                    form_values[fname] = live_main_value
                else:
                    val = c_addr.text_input(f"{fname} 🏗️", key=widget_key)
                    form_values[fname] = val
            elif ftype == "SIRET": form_values[fname] = c.text_input(f"{fname} 🏛️", key=widget_key)
            elif ftype == "Fichier/Image":
                # MULTI UPLOAD
                up = c.file_uploader(f"📂 {fname}", key=f"new_{fname}", accept_multiple_files=True)
                files_list = []
                if up:
                    for u in up:
                        res = upload_file_to_supabase(u)
                        if res: files_list.append(res)
                form_values[fname] = files_list
            elif ftype == "Oui/Non": form_values[fname] = c.checkbox(fname, key=widget_key)
            elif ftype == "Nombre": form_values[fname] = c.number_input(fname, step=1, key=widget_key)
            elif ftype == "Date": form_values[fname] = str(c.date_input(fname, key=widget_key))
            else: form_values[fname] = c.text_input(fname, key=widget_key)

    st.divider()
    if st.button("💾 Enregistrer le Dossier", type="primary", use_container_width=True):
        if not form_values: st.error("Formulaire vide.")
        else:
            clean_data = {k: ([x for x in v if x] if isinstance(v, list) else v) for k, v in form_values.items()}
            db_insert("records", {"collection_id": schema['id'], "data": clean_data})
            for key in list(st.session_state.keys()):
                if key.startswith("inp_"): del st.session_state[key]
            st.toast("Dossier créé !", icon="✅"); time.sleep(1); st.rerun()

# =========================================================
# 2. GESTION DES DOSSIERS
# =========================================================
elif menu == "2. Gestion des Dossiers":
    st.header("🗂️ Suivi des Dossiers")
    if not activities: st.stop()

    c1, c2, c3 = st.columns([2, 2, 4])
    act_map = {a['name']: a['id'] for a in activities}
    cur_act = c1.selectbox("Activité", list(act_map.keys()))
    col_list = [c for c in collections if c['activity_id'] == act_map[cur_act]]
    
    if not col_list: st.info("Vide."); st.stop()
    col_map = {c['name']: c for c in col_list}
    cur_mod = c2.selectbox("Type", list(col_map.keys()))
    schema = col_map[cur_mod]
    
    raw = get_records_raw(schema['id'])
    if not raw: st.info("Aucun dossier."); st.stop()
    
    opts = {get_record_label(r['data'], r['id']): r['id'] for r in raw}
    sel_label = c3.selectbox("🔍 Rechercher un dossier", list(opts.keys()))
    sel_id = opts[sel_label]
    
    record = next(r for r in raw if r['id'] == sel_id)
    rec_data = record['data']
    fields = schema['fields']

    st.markdown("---")

    with st.form("edit_record_form"):
        new_data = rec_data.copy()
        
        sections_ordered = []
        seen = set()
        for f in fields:
            sec = f.get('section', 'Infos Générales')
            if sec not in seen: sections_ordered.append(sec); seen.add(sec)
            
        for section in sections_ordered:
            st.markdown(f"<div class='section-header'>{section}</div>", unsafe_allow_html=True)
            sec_fields = [f for f in fields if f.get('section', 'Infos Générales') == section]
            cols = st.columns(2)
            
            for idx, f in enumerate(sec_fields):
                c = cols[idx % 2]
                fname, ftype = f['name'], f['type']
                old_val = rec_data.get(fname, "")
                
                if ftype == "Fichier/Image":
                    c.markdown(f"**📂 {fname}**")
                    current_files = old_val if isinstance(old_val, list) else []
                    if current_files:
                        for fi in current_files:
                            url = fi.get('url') if isinstance(fi, dict) else fi
                            name = fi.get('name', 'Fichier') if isinstance(fi, dict) else 'Fichier'
                            c.markdown(f"<div class='file-card'><span>📄 {name}</span><a href='{url}' target='_blank'>Voir</a></div>", unsafe_allow_html=True)
                    
                    # MULTI UPLOAD EDIT
                    new_ups = c.file_uploader(f"Ajouter", key=f"edit_{sel_id}_{fname}", accept_multiple_files=True)
                    if new_ups: new_data[f"__upload_{fname}"] = new_ups
                    new_data[fname] = current_files

                elif ftype == "Adresse Travaux": new_data[fname] = c.text_input(f"{fname} 🏗️", value=str(old_val))
                elif ftype == "Oui/Non": new_data[fname] = c.checkbox(fname, value=bool(old_val))
                elif ftype == "Nombre": new_data[fname] = c.number_input(fname, value=float(old_val) if old_val else 0)
                elif ftype == "Date": new_data[fname] = str(c.date_input(fname))
                else: new_data[fname] = c.text_input(fname, value=str(old_val))

        st.divider()
        if st.form_submit_button("💾 Sauvegarder modifications", type="primary"):
            for f in fields:
                if f['type'] == "Fichier/Image":
                    fname = f['name']
                    up_key = f"__upload_{fname}"
                    if new_data.get(up_key):
                        # GESTION LISTE FICHIERS
                        uploaded_objs = []
                        for u in new_data[up_key]:
                             res = upload_file_to_supabase(u)
                             if res: uploaded_objs.append(res)
                        
                        if isinstance(new_data[fname], list): new_data[fname].extend(uploaded_objs)
                        else: new_data[fname] = uploaded_objs
                        del new_data[up_key]
            db_update("records", sel_id, {"data": new_data})
            st.toast("Modifié !", icon="✅"); time.sleep(1); st.rerun()

    # --- FUSION PDF ---
    st.markdown("### 🖨️ Actions")
    with st.expander("📄 Générer un PDF Complet du dossier"):
        st.write("Cela va fusionner tous les fichiers (Images et PDF) du dossier en un seul document.")
        if st.button("Lancer la fusion"):
            all_files = []
            for f in fields:
                if f['type'] == "Fichier/Image":
                    val = rec_data.get(f['name'])
                    if isinstance(val, list): all_files.extend(val)
            
            if not all_files:
                st.warning("Aucun fichier dans ce dossier.")
            else:
                with st.spinner("Fusion en cours..."):
                    pdf_bytes = merge_files_to_pdf(all_files)
                    st.download_button(
                        label="📥 Télécharger le Dossier Complet (PDF)",
                        data=pdf_bytes,
                        file_name=f"Dossier_Complet_{sel_id}.pdf",
                        mime="application/pdf"
                    )

    st.write("")
    with st.expander("🗑️ Zone de danger"):
        if st.button("Supprimer ce dossier"):
            db_delete("records", sel_id); st.rerun()

# =========================================================
# 3. CONFIGURATION (ADMIN) - REFONTE TOTALE
# =========================================================
elif menu == "3. Configuration (Admin)":
    st.header("⚙️ Configuration Avancée")
    t1, t2, t3 = st.tabs(["Activités", "Créer Modèle", "Modifier Structure"])
    
    with t1:
        st.subheader("Activités")
        na = st.text_input("Nom")
        if st.button("Créer Activité"):
            db_insert("activities", {"name": na}); st.rerun()
        if activities: st.caption("Liste : " + ", ".join([a['name'] for a in activities]))

    with t2:
        st.subheader("Créer un NOUVEAU Modèle")
        if not activities: st.warning("Crée une activité."); st.stop()
        par = st.selectbox("Lier à l'activité", [a['name'] for a in activities])
        nc = st.text_input("Nom du Modèle")
        
        st.write("Ajout initial des champs :")
        if "b_fields" not in st.session_state: st.session_state.b_fields = []
        c1, c2, c3 = st.columns([2, 2, 2])
        sec = c1.text_input("Section", placeholder="1. Contact")
        fn = c2.text_input("Nom du champ")
        ft = c3.selectbox("Type", ["Texte", "Nombre", "Date", "Fichier/Image", "Email", "Téléphone", "SIRET", "Adresse", "Adresse Travaux", "Oui/Non"])
        
        if st.button("➕ Ajouter"):
            if fn and sec: st.session_state.b_fields.append({"name": fn, "type": ft, "section": sec})
        
        if st.session_state.b_fields:
            st.dataframe(pd.DataFrame(st.session_state.b_fields), use_container_width=True)
            act_id = next(a['id'] for a in activities if a['name'] == par)
            if st.button("✅ Sauvegarder"):
                db_insert("collections", {"name": nc, "fields": st.session_state.b_fields, "activity_id": act_id})
                st.session_state.b_fields = []
                st.success("Modèle créé !"); time.sleep(1); st.rerun()

    # --- MODIFICATION AVANCEE ---
    with t3:
        st.subheader("🛠️ Modifier une Structure Existante")
        if not collections: st.info("Rien à modifier."); st.stop()
        
        tgt_name = st.selectbox("Choisir le modèle à éditer", [c['name'] for c in collections])
        tgt = next(c for c in collections if c['name'] == tgt_name)
        curr_fields = tgt['fields']

        st.info("⚠️ Attention : Changer le nom d'un champ peut masquer les données existantes associées à l'ancien nom.")

        # 1. REORGANISATION (DRAG & DROP)
        st.markdown("#### 1. Réorganiser")
        field_labels = [f"{f['section']} | {f['name']}" for f in curr_fields]
        sorted_labels = sort_items(field_labels)
        
        # 2. EDITION LISTE
        st.markdown("#### 2. Modifier / Supprimer")
        
        # On reconstruit la liste basée sur l'ordre du tri
        new_schema = []
        
        # Formulaire global pour tout sauvegarder d'un coup
        with st.form("update_structure"):
            for label in sorted_labels:
                # Retrouver l'objet original
                original = next((f for f in curr_fields if f"{f['section']} | {f['name']}" == label), None)
                if not original: continue
                
                # Carte d'édition
                st.markdown(f"<div class='admin-card'>", unsafe_allow_html=True)
                c_s, c_n, c_t, c_del = st.columns([3, 3, 3, 1])
                
                new_sec = c_s.text_input("Section", value=original['section'], key=f"s_{label}")
                new_name = c_n.text_input("Nom", value=original['name'], key=f"n_{label}")
                new_type = c_t.selectbox("Type", ["Texte", "Nombre", "Date", "Fichier/Image", "Email", "Téléphone", "SIRET", "Adresse", "Adresse Travaux", "Oui/Non"], index=["Texte", "Nombre", "Date", "Fichier/Image", "Email", "Téléphone", "SIRET", "Adresse", "Adresse Travaux", "Oui/Non"].index(original['type']), key=f"t_{label}")
                to_delete = c_del.checkbox("🗑️", key=f"del_{label}")
                
                st.markdown("</div>", unsafe_allow_html=True)
                
                if not to_delete:
                    new_schema.append({"section": new_sec, "name": new_name, "type": new_type})

            # AJOUT RAPIDE DANS L'EXISTANT
            st.markdown("#### + Ajouter un nouveau champ")
            ca, cb, cc = st.columns(3)
            add_s = ca.text_input("Nouvelle Section")
            add_n = cb.text_input("Nouveau Nom")
            add_t = cc.selectbox("Nouveau Type", ["Texte", "Fichier/Image", "Nombre", "Date", "Adresse", "SIRET"])
            
            if st.form_submit_button("💾 Enregistrer la nouvelle structure"):
                # Si ajout
                if add_n and add_s:
                    new_schema.append({"section": add_s, "name": add_n, "type": add_t})
                
                db_update("collections", tgt['id'], {"fields": new_schema})
                st.success("Structure mise à jour !"); time.sleep(1); st.rerun()

        st.divider()
        if st.button("Supprimer définitivement ce modèle"):
            db_delete("collections", tgt['id']); st.rerun()