import streamlit as st
import pandas as pd
import requests
import json
from datetime import datetime, timedelta
import io
import time
import re
from supabase import create_client, Client
from pypdf import PdfWriter, PdfReader
from PIL import Image

# Import Gestion des Cookies
try:
    import extra_streamlit_components as stx
except ImportError:
    st.error("⚠️ Librairie manquante : 'extra-streamlit-components'.")
    st.stop()

# Import Drag & Drop
try:
    from streamlit_sortables import sort_items
except ImportError:
    st.error("⚠️ Librairie manquante : 'streamlit-sortables'.")
    st.stop()

# --- CONFIGURATION PAGE ---
st.set_page_config(page_title="Universal CRM SaaS", page_icon="🚀", layout="wide")

# --- INITIALISATION SUPABASE ---
@st.cache_resource
def init_connection():
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        return create_client(url, key)
    except Exception as e:
        st.error(f"Erreur connexion : {e}")
        st.stop()

supabase = init_connection()
cookie_manager = stx.CookieManager()

# --- ÉTAT SESSION ---
if 'user' not in st.session_state: st.session_state.user = None
if 'profile' not in st.session_state: st.session_state.profile = None
if 'form_reset_id' not in st.session_state: st.session_state.form_reset_id = 0

# --- FONCTION LOGIN (Version V46 restaurée) ---
def login(email, password):
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        if res.user:
            # Sécurité anti-double clic (boucle d'attente)
            for _ in range(3):
                p_res = supabase.table("profiles").select("*").eq("id", res.user.id).execute()
                if p_res.data:
                    st.session_state.user = res.user
                    st.session_state.profile = p_res.data[0]
                    st.success("✅ Connexion réussie !")
                    time.sleep(0.5)
                    st.rerun()
                    return
                time.sleep(0.5)
            st.error("Erreur : Profil introuvable.")
    except:
        st.error("Identifiants incorrects.")

def logout():
    supabase.auth.sign_out()
    st.session_state.user = None
    st.session_state.profile = None
    st.rerun()

def upload_file(file, path):
    try:
        file_bytes = file.getvalue()
        supabase.storage.from_("fichiers").upload(path, file_bytes, {"content-type": file.type, "upsert": "true"})
        return supabase.storage.from_("fichiers").get_public_url(path)
    except: return None

def merge_files_to_pdf(file_urls):
    merger = PdfWriter()
    for url in file_urls:
        try:
            res = requests.get(url)
            if res.status_code == 200:
                f_data = io.BytesIO(res.content)
                if url.lower().endswith('.pdf'):
                    reader = PdfReader(f_data)
                    for page in reader.pages: merger.add_page(page)
                elif url.lower().endswith(('.png', '.jpg', '.jpeg')):
                    img = Image.open(f_data)
                    if img.mode == 'RGBA': img = img.convert('RGB')
                    img_pdf = io.BytesIO()
                    img.save(img_pdf, format='PDF')
                    img_pdf.seek(0)
                    merger.add_page(PdfReader(img_pdf).pages[0])
        except: continue
    output = io.BytesIO()
    merger.write(output)
    return output.getvalue()

# ==========================================
# 🔐 LOGIN
# ==========================================
if not st.session_state.user:
    st.markdown("<h1 style='text-align: center;'>🔐 Connexion CRM</h1>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        with st.form("login_f"):
            em = st.text_input("Email")
            pw = st.text_input("Mot de passe", type="password")
            if st.form_submit_button("Se connecter", use_container_width=True):
                login(em, pw)
    st.stop()

# ==========================================
# 🚀 APP
# ==========================================
MY_PROFILE = st.session_state.profile
if not MY_PROFILE: 
    st.warning("Session expirée.")
    if st.button("Recharger"): logout()
    st.stop()

MY_ROLE = MY_PROFILE.get('role', 'user')
MY_COMPANY_ID = MY_PROFILE.get('company_id')

with st.sidebar:
    st.markdown(f"### 👋 {MY_PROFILE.get('full_name')}")
    st.info(f"Rôle : {MY_ROLE.upper()}")
    if st.button("Se déconnecter", type="primary", use_container_width=True): logout()

# --- SUPER ADMIN ---
if MY_ROLE == "super_admin":
    all_c = supabase.table("companies").select("*").execute().data
    target = st.selectbox("🏢 Entreprise cible :", ["Choisir..."] + [c['name'] for c in all_c])
    if target != "Choisir...":
        MY_COMPANY_ID = next(c['id'] for c in all_c if c['name'] == target)
    else:
        st.info("👈 Sélectionnez une entreprise.")
        st.stop()

# --- ONGLETS ---
tabs_list = ["1. 📝 Nouveau Dossier", "2. 📂 Gestion des Dossiers"]
if MY_ROLE in ["admin1", "super_admin"]: tabs_list.append("3. ⚙️ Configuration")
if MY_ROLE in ["admin1", "admin2", "super_admin"]: tabs_list.append("4. 👥 Utilisateurs")
tabs = st.tabs(tabs_list)

# ONGLET 1 : CRÉATION
with tabs[0]:
    st.header("Créer un dossier")
    acts = supabase.table("activities").select("*").eq("company_id", MY_COMPANY_ID).execute().data
    if acts:
        act_sel = st.selectbox("Activité", [a['name'] for a in acts])
        act_id = next(a['id'] for a in acts if a['name'] == act_sel)
        cols = supabase.table("collections").select("*").eq("activity_id", act_id).execute().data
        if cols:
            mod = next(c for c in cols if c['name'] == st.selectbox("Modèle", [c['name'] for c in cols]))
            f_id = st.session_state.form_reset_id
            st.divider()
            data, f_map, main_addr = {}, {}, ""
            for i, f in enumerate(mod['fields']):
                k = f"f_{mod['id']}_{i}_{f['name']}_{f_id}"
                if f['type'] == "Section/Titre": st.markdown(f"**{f['name']}**")
                elif f['type'] == "Fichier/Image": f_map[f['name']] = st.file_uploader(f['name'], accept_multiple_files=True, key=k)
                elif f['type'] == "Texte Long": data[f['name']] = st.text_area(f['name'], key=k)
                elif f['type'] == "Adresse Travaux":
                    copy = st.checkbox(f"Copier adresse : {main_addr}", key=f"chk_{k}") if main_addr else False
                    data[f['name']] = st.text_input(f['name'], value=main_addr if copy else "", key=k)
                else:
                    data[f['name']] = st.text_input(f['name'], key=k)
                    if f['type'] == "Adresse": main_addr = data[f['name']]

            if st.button("💾 ENREGISTRER", type="primary"):
                for fn, fl in f_map.items():
                    urls = [upload_file(fi, f"{MY_COMPANY_ID}/{mod['id']}/{int(time.time())}_{fi.name}") for fi in fl]
                    data[fn] = [u for u in urls if u]
                supabase.table("records").insert({"collection_id": mod['id'], "data": data, "created_by": st.session_state.user.id}).execute()
                st.session_state.form_reset_id += 1
                st.rerun()

# ONGLET 2 : GESTION
with tabs[1]:
    st.header("Gestion des Dossiers")
    m_acts = supabase.table("activities").select("id").eq("company_id", MY_COMPANY_ID).execute().data
    if m_acts:
        a_cols = supabase.table("collections").select("*").in_("activity_id", [a['id'] for a in m_acts]).execute().data
        if a_cols:
            recs = supabase.table("records").select("*, collections(name, fields)").in_("collection_id", [c['id'] for c in a_cols]).order('created_at', desc=True).execute().data
            if recs:
                s_map = {f"👤 {r['data'].get('nom', 'Dossier')} | 📄 {r['collections']['name']}": r for r in recs}
                sel_label = st.selectbox("Choisir dossier", list(s_map.keys()))
                if sel_label:
                    r = s_map[sel_label]
                    
                    with st.form(f"edit_{r['id']}"):
                        new_d = r['data'].copy()
                        for f in r['collections']['fields']:
                            if f['type'] not in ["Fichier/Image", "Section/Titre"]:
                                if f['type'] == "Texte Long": new_d[f['name']] = st.text_area(f['name'], value=r['data'].get(f['name'], ""))
                                else: new_d[f['name']] = st.text_input(f['name'], value=r['data'].get(f['name'], ""))
                        if st.form_submit_button("💾 Sauvegarder"):
                            supabase.table("records").update({"data": new_d}).eq("id", r['id']).execute()
                            st.rerun()

                    st.divider()
                    all_urls = []
                    for f in [x for x in r['collections']['fields'] if x['type'] == "Fichier/Image"]:
                        fname = f['name']
                        urls = r['data'].get(fname, [])
                        all_urls.extend(urls)
                        with st.expander(f"📁 {fname} ({len(urls)})"):
                            for i, u in enumerate(urls):
                                c1, c2 = st.columns([4, 1])
                                c1.markdown(f"📄 [Lien fichier {i+1}]({u})")
                                if c2.button("❌", key=f"d_{r['id']}_{fname}_{i}"):
                                    urls.remove(u)
                                    r['data'][fname] = urls
                                    supabase.table("records").update({"data": r['data']}).eq("id", r['id']).execute()
                                    st.rerun()
                            up = st.file_uploader("Ajouter", key=f"up_{r['id']}_{fname}")
                            if up and st.button("Envoyer", key=f"send_{r['id']}_{fname}"):
                                pub = upload_file(up, f"{MY_COMPANY_ID}/{r['collection_id']}/{int(time.time())}_{up.name}")
                                if pub:
                                    urls.append(pub)
                                    r['data'][fname] = urls
                                    supabase.table("records").update({"data": r['data']}).eq("id", r['id']).execute()
                                    st.rerun()
                    
                    if all_urls and st.button("📄 TÉLÉCHARGER DOSSIER COMPLET (PDF)"):
                        st.download_button("📥 Télécharger", merge_files_to_pdf(all_urls), f"Dossier_{r['id']}.pdf", "application/pdf")
                    
                    if st.button("💀 Supprimer ce dossier", type="primary"):
                        supabase.table("records").delete().eq("id", r['id']).execute()
                        st.rerun()
            else: st.info("Aucun dossier.")

# ONGLET 3 : CONFIGURATION (CORRIGÉ & VALIDE)
if "3. ⚙️ Configuration" in tabs_list:
    idx = tabs_list.index("3. ⚙️ Configuration")
    with tabs[idx]:
        st.header("⚙️ Configuration")
        with st.form("na"):
            n = st.text_input("Nouvelle activité")
            if st.form_submit_button("Ajouter"):
                supabase.table("activities").insert({"name": n, "company_id": MY_COMPANY_ID}).execute()
                st.rerun()
        
        st.divider()
        acts = supabase.table("activities").select("*").eq("company_id", MY_COMPANY_ID).execute().data
        if acts:
            aid = next(a['id'] for a in acts if a['name'] == st.selectbox("Activité :", [a['name'] for a in acts]))
            type_list = ["Texte Court", "Texte Long", "SIRET", "Adresse", "Adresse Travaux", "Fichier/Image", "Section/Titre"]
            
            # --- CRÉATION NOUVEAU MODÈLE ---
            with st.expander("➕ Créer Modèle"):
                st.write("Définissez les champs ci-dessous puis sauvegardez.")
                nm = st.text_input("Nom du modèle")
                
                # Zone de définition (HORS DU BOUTON)
                c1, c2, c3 = st.columns([3, 2, 1])
                fn = c1.text_input("Nom champ", key="new_fn")
                ft = c2.selectbox("Type", type_list, key="new_ft")
                
                if c3.button("Ajouter à la liste", key="add_to_list"):
                    if "t" not in st.session_state: st.session_state.t = []
                    st.session_state.t.append({"name": fn, "type": ft})
                    st.rerun()
                
                if "t" in st.session_state and st.session_state.t:
                    st.write(st.session_state.t)
                    if st.button("💾 SAUVEGARDER LE MODÈLE"):
                        supabase.table("collections").insert({"name": nm, "activity_id": aid, "fields": st.session_state.t}).execute()
                        st.session_state.t = []
                        st.success("Modèle créé !")
                        time.sleep(1)
                        st.rerun()

            # --- GESTION DES MODÈLES EXISTANTS ---
            for m in supabase.table("collections").select("*").eq("activity_id", aid).execute().data:
                with st.expander(f"📝 Gérer {m['name']}"):
                    st.markdown("#### Ajouter un champ")
                    
                    # CORRECTION ICI : INPUTS DÉFINIS AVANT LE CLIC
                    ca1, ca2, ca3 = st.columns([3, 2, 1])
                    new_field_name = ca1.text_input("Nom", key=f"n_{m['id']}")
                    new_field_type = ca2.selectbox("Type", type_list, key=f"t_{m['id']}")
                    
                    if ca3.button("Ajouter", key=f"add_{m['id']}"):
                        if new_field_name:
                            nf = m['fields'] + [{"name": new_field_name, "type": new_field_type}]
                            supabase.table("collections").update({"fields": nf}).eq("id", m['id']).execute()
                            st.success("Champ ajouté !")
                            st.rerun()
                    
                    st.divider()
                    st.markdown("#### Trier / Supprimer")
                    fl = [f"{f['name']} [{f['type']}]" for f in m['fields']]
                    sl = sort_items(fl, direction='vertical', key=f"s_{m['id']}")
                    
                    if st.button("💾 Valider l'ordre", key=f"sv_{m['id']}"):
                         nl = [next(f for f in m['fields'] if f"{f['name']} [{f['type']}]" == l) for l in sl]
                         supabase.table("collections").update({"fields": nl}).eq("id", m['id']).execute()
                         st.rerun()
                    
                    tr = st.multiselect("Supprimer :", [f['name'] for f in m['fields']], key=f"del_{m['id']}")
                    if tr and st.button("Confirmer suppression", key=f"c_{m['id']}"):
                        supabase.table("collections").update({"fields": [f for f in m['fields'] if f['name'] not in tr]}).eq("id", m['id']).execute()
                        st.rerun()
                    
                    if st.button("💀 Supprimer ce modèle", key=f"k_{m['id']}", type="primary"):
                         supabase.table("collections").delete().eq("id", m['id']).execute()
                         st.rerun()

# ONGLET 4 : UTILISATEURS
if "4. 👥 Utilisateurs" in tabs_list:
    idx = tabs_list.index("4. 👥 Utilisateurs")
    with tabs[idx]:
        st.header("👥 Équipe")
        with st.form("ua"):
            ue, up = st.text_input("Email"), st.text_input("Pass", type="password")
            ur = st.selectbox("Rôle", ["admin2", "user"] if MY_ROLE == "admin1" else ["user"])
            if st.form_submit_button("Ajouter"):
                res = supabase.auth.sign_up({"email": ue, "password": up})
                supabase.table("profiles").insert({"id": res.user.id, "email": ue, "company_id": MY_COMPANY_ID, "role": ur, "full_name": ue.split('@')[0]}).execute()
                st.rerun()
        
        st.divider()
        ul = supabase.table("profiles").select("*").eq("company_id", MY_COMPANY_ID).execute().data
        if ul:
            st.dataframe(pd.DataFrame(ul)[["email", "role"]], use_container_width=True)
            for u in ul:
                if u['id'] != st.session_state.user.id:
                    if (MY_ROLE == "admin1") or (MY_ROLE == "admin2" and u['role'] == "user"):
                        if st.button(f"🗑️ Supprimer {u['email']}", key=f"d_{u['id']}", type="secondary"):
                            supabase.table("profiles").delete().eq("id", u['id']).execute()
                            st.success("Utilisateur supprimé.")
                            time.sleep(0.5)
                            st.rerun()
