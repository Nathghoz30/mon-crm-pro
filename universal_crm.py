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

# --- RECONNEXION AUTO ---
if not st.session_state.user:
    time.sleep(0.1)
    refresh_token = cookie_manager.get("sb_refresh_token")
    if refresh_token:
        try:
            res = supabase.auth.refresh_session(refresh_token)
            if res.user:
                p_data = supabase.table("profiles").select("*").eq("id", res.user.id).execute().data
                if p_data:
                    st.session_state.user = res.user
                    st.session_state.profile = p_data[0]
                    cookie_manager.set("sb_refresh_token", res.session.refresh_token, expires_at=datetime.now() + timedelta(days=30))
        except: cookie_manager.delete("sb_refresh_token")

# --- FONCTIONS ---
def logout():
    supabase.auth.sign_out()
    st.session_state.user = None
    st.session_state.profile = None
    cookie_manager.delete("sb_refresh_token")
    st.rerun()

def get_siret_info(siret):
    try:
        url = f"https://recherche-entreprises.api.gouv.fr/search?q={siret.replace(' ', '')}"
        res = requests.get(url)
        if res.status_code == 200:
            ent = res.json()['results'][0]
            siege = ent.get('siege', {})
            return {"NOM": ent.get('nom_complet'), "ADRESSE": siege.get('adresse'), "VILLE": siege.get('libelle_commune'), "CP": siege.get('code_postal'), "TVA": ent.get('numero_tva_intracommunautaire')}
    except: return None

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
        with st.form("login"):
            em = st.text_input("Email")
            pw = st.text_input("Mot de passe", type="password")
            if st.form_submit_button("Se connecter", use_container_width=True):
                try:
                    res = supabase.auth.sign_in_with_password({"email": em, "password": pw})
                    p_data = supabase.table("profiles").select("*").eq("id", res.user.id).execute().data
                    if p_data:
                        st.session_state.user = res.user
                        st.session_state.profile = p_data[0]
                        cookie_manager.set("sb_refresh_token", res.session.refresh_token)
                        st.rerun()
                except: st.error("Identifiants incorrects.")
    st.stop()

# ==========================================
# 🚀 APPLICATION
# ==========================================
MY_PROFILE = st.session_state.profile
MY_ROLE = MY_PROFILE.get('role', 'user')
MY_COMPANY_ID = MY_PROFILE.get('company_id')

with st.sidebar:
    st.markdown(f"### 👋 {MY_PROFILE.get('full_name')}")
    st.info(f"Rôle : {MY_ROLE.upper()}")
    if st.button("Se déconnecter", type="primary"): logout()

# --- SUPER ADMIN ---
if MY_ROLE == "super_admin":
    sa_tabs = st.tabs(["🏢 Entreprises", "👀 Voir CRM"])
    with sa_tabs[0]:
        with st.form("new_comp"):
            cn = st.text_input("Entreprise")
            ae = st.text_input("Email Gérant")
            ap = st.text_input("Pass", type="password")
            if st.form_submit_button("Créer"):
                r_c = supabase.table("companies").insert({"name": cn}).execute()
                r_a = supabase.auth.sign_up({"email": ae, "password": ap})
                supabase.table("profiles").insert({"id": r_a.user.id, "email": ae, "company_id": r_c.data[0]['id'], "role": "admin1", "full_name": f"Gérant {cn}"}).execute()
                st.rerun()
    with sa_tabs[1]:
        all_c = supabase.table("companies").select("*").execute().data
        target = st.selectbox("Accéder à :", [c['name'] for c in all_c])
        if target: MY_COMPANY_ID = next(c['id'] for c in all_c if c['name'] == target)

# --- ONGLETS ---
tabs_list = ["1. 📝 Nouveau Dossier", "2. 📂 Gestion des Dossiers"]
if MY_ROLE in ["admin1", "super_admin"]: tabs_list.append("3. ⚙️ Configuration")
if MY_ROLE in ["admin1", "admin2", "super_admin"]: tabs_list.append("4. 👥 Utilisateurs")
tabs = st.tabs(tabs_list)

# ONGLET 1 : CRÉATION (RESTAURÉ)
with tabs[0]:
    st.header("Créer un dossier")
    acts = supabase.table("activities").select("*").eq("company_id", MY_COMPANY_ID).execute().data
    if not acts: st.info("Configurez une activité.")
    else:
        act_sel = st.selectbox("Activité", [a['name'] for a in acts])
        act_id = next(a['id'] for a in acts if a['name'] == act_sel)
        cols = supabase.table("collections").select("*").eq("activity_id", act_id).execute().data
        if cols:
            sel_col_name = st.selectbox("Modèle", [c['name'] for c in cols])
            mod = next(c for c in cols if c['name'] == sel_col_name)
            fields = mod['fields']
            f_id = st.session_state.form_reset_id
            
            # SIRET
            if any(f['type'] == "SIRET" for f in fields):
                with st.expander("⚡ SIRET Auto-remplissage"):
                    s_in = st.text_input("Entrez le SIRET", key=f"s_in_{f_id}")
                    if st.button("Remplir"):
                        info = get_siret_info(s_in)
                        if info:
                            for i, f in enumerate(fields):
                                k = f"f_{mod['id']}_{i}_{f['name']}_{f_id}"
                                if f['type'] == 'SIRET': st.session_state[k] = s_in
                                elif "nom" in f['name'].lower(): st.session_state[k] = info['NOM']
                                elif "adresse" in f['name'].lower(): st.session_state[k] = info['ADRESSE']
            
            st.divider()
            data, f_map = {}, {}
            for i, f in enumerate(fields):
                k = f"f_{mod['id']}_{i}_{f['name']}_{f_id}"
                if f['type'] == "Section/Titre": st.markdown(f"**{f['name']}**")
                elif f['type'] == "Fichier/Image": f_map[f['name']] = st.file_uploader(f['name'], accept_multiple_files=True, key=k)
                else: data[f['name']] = st.text_input(f['name'], key=k)

            if st.button("💾 ENREGISTRER", type="primary", use_container_width=True):
                for fn, fl in f_map.items():
                    urls = []
                    if fl:
                        for fi in fl:
                            path = f"{MY_COMPANY_ID}/{mod['id']}/{int(time.time())}_{fi.name}"
                            u = upload_file(fi, path)
                            if u: urls.append(u)
                    data[fn] = urls
                supabase.table("records").insert({"collection_id": mod['id'], "data": data, "created_by": st.session_state.user.id}).execute()
                st.success("Dossier créé !")
                st.session_state.form_reset_id += 1
                time.sleep(1)
                st.rerun()

# ONGLET 2 : GESTION (RESTAURÉ)
with tabs[1]:
    st.header("Gestion des Dossiers")
    m_acts = supabase.table("activities").select("id").eq("company_id", MY_COMPANY_ID).execute().data
    if m_acts:
        a_cols = supabase.table("collections").select("*").in_("activity_id", [a['id'] for a in m_acts]).execute().data
        if a_cols:
            recs = supabase.table("records").select("*, collections(name, fields)").in_("collection_id", [c['id'] for c in a_cols]).order('created_at', desc=True).execute().data
            if recs:
                s_map = {f"👤 {r['data'].get('nom', 'Client')} | 📄 {r['collections']['name']} | 📅 {r['created_at'][:10]}": r for r in recs}
                sel = st.selectbox("Choisir dossier", list(s_map.keys()))
                if sel:
                    r = s_map[sel]
                    curr_d = r['data']
                    with st.form(f"ed_{r['id']}"):
                        new_d = curr_d.copy()
                        for f in r['collections']['fields']:
                            if f['type'] in ["Fichier/Image", "Section/Titre"]: continue
                            new_d[f['name']] = st.text_input(f['name'], value=curr_d.get(f['name'], ""))
                        if st.form_submit_button("💾 Sauvegarder"):
                            supabase.table("records").update({"data": new_d}).eq("id", r['id']).execute()
                            st.rerun()

                    st.divider()
                    all_urls = []
                    for f in [x for x in r['collections']['fields'] if x['type'] == "Fichier/Image"]:
                        fname = f['name']
                        urls = curr_d.get(fname, [])
                        all_urls.extend(urls)
                        with st.expander(f"📁 {fname} ({len(urls)})"):
                            for i, u in enumerate(urls):
                                c1, c2 = st.columns([4, 1])
                                c1.markdown(f"📄 [Fichier {i+1}]({u})")
                                if c2.button("❌", key=f"rm_{r['id']}_{fname}_{i}"):
                                    urls.remove(u)
                                    curr_d[fname] = urls
                                    supabase.table("records").update({"data": curr_d}).eq("id", r['id']).execute()
                                    st.rerun()
                            up = st.file_uploader("Ajout", accept_multiple_files=True, key=f"up_{r['id']}_{fname}")
                            if up and st.button("Envoyer", key=f"btn_{r['id']}_{fname}"):
                                for nf in up:
                                    path = f"{MY_COMPANY_ID}/{r['collection_id']}/{int(time.time())}_{nf.name}"
                                    pub = upload_file(nf, path)
                                    if pub: urls.append(pub)
                                curr_d[fname] = urls
                                supabase.table("records").update({"data": curr_d}).eq("id", r['id']).execute()
                                st.rerun()
                    
                    if all_urls and st.button("📄 GÉNÉRER PDF"):
                        pdf = merge_files_to_pdf(all_urls)
                        st.download_button("📥 Télécharger", pdf, f"Dossier_{r['id']}.pdf", "application/pdf")
                    
                    if st.button("💀 Supprimer Dossier", type="primary"):
                        supabase.table("records").delete().eq("id", r['id']).execute()
                        st.rerun()

# ONGLET 3 : CONFIGURATION (FONCTIONNALITÉS D'ÉDITION RESTAURÉES)
if "3. ⚙️ Configuration" in tabs_list:
    idx = tabs_list.index("3. ⚙️ Configuration")
    with tabs[idx]:
        st.header("⚙️ Configuration (Droits Gérant)")
        
        # 1. ACTIVITÉS
        with st.form("add_act"):
            na = st.text_input("Nouvelle activité")
            if st.form_submit_button("Ajouter"):
                supabase.table("activities").insert({"name": na, "company_id": MY_COMPANY_ID}).execute()
                st.rerun()
        
        # 2. MODÈLES & GESTION DES CHAMPS
        st.divider()
        acts = supabase.table("activities").select("*").eq("company_id", MY_COMPANY_ID).execute().data
        if acts:
            s_act = st.selectbox("Sélectionner activité :", [a['name'] for a in acts])
            s_id = next(a['id'] for a in acts if a['name'] == s_act)
            
            with st.expander("➕ Créer un nouveau modèle"):
                nm = st.text_input("Nom du modèle")
                if "tmp" not in st.session_state: st.session_state.tmp = []
                c1, c2, c3 = st.columns([3, 2, 1])
                fn, ft = c1.text_input("Nom champ"), c2.selectbox("Type", ["Texte Court", "SIRET", "Fichier/Image", "Section/Titre"], key="ntype")
                if c3.button("Ajouter"):
                    st.session_state.tmp.append({"name": fn, "type": ft})
                    st.rerun()
                if st.session_state.tmp:
                    st.write(st.session_state.tmp)
                    if st.button("💾 Sauvegarder"):
                        supabase.table("collections").insert({"name": nm, "activity_id": s_id, "fields": st.session_state.tmp}).execute()
                        st.session_state.tmp = []
                        st.rerun()
            
            st.write("---")
            mods = supabase.table("collections").select("*").eq("activity_id", s_id).execute().data
            for m in mods:
                with st.expander(f"📝 Gérer {m['name']}"):
                    # A. AJOUTER UN CHAMP À CE MODÈLE
                    st.markdown("#### ➕ Ajouter un champ spécifique")
                    ca1, ca2, ca3 = st.columns([3, 2, 1])
                    new_fn = ca1.text_input("Nom du champ", key=f"nfn_{m['id']}")
                    new_ft = ca2.selectbox("Type", ["Texte Court", "SIRET", "Fichier/Image", "Section/Titre"], key=f"nft_{m['id']}")
                    if ca3.button("Ajouter", key=f"abtn_{m['id']}"):
                        updated_f = m['fields'] + [{"name": new_fn, "type": new_ft}]
                        supabase.table("collections").update({"fields": updated_f}).eq("id", m['id']).execute()
                        st.success("Champ ajouté !")
                        st.rerun()
                    
                    st.write("---")
                    # B. RÉORGANISATION ET SUPPRESSION INDIVIDUELLE
                    st.markdown("#### 🔃 Ordre & 🗑️ Suppression individuelle")
                    current_fields = m['fields']
                    f_labels = [f"{f['name']} [{f['type']}]" for f in current_fields]
                    
                    # Composant de tri
                    sorted_labels = sort_items(f_labels, direction='vertical', key=f"sort_{m['id']}")
                    
                    col_sav, col_del_m = st.columns([3, 1])
                    if col_sav.button("💾 Valider l'ordre", key=f"save_{m['id']}"):
                        new_fields_list = []
                        for label in sorted_labels:
                            # On retrouve l'objet original
                            original = next(f for f in current_fields if f"{f['name']} [{f['type']}]" == label)
                            new_fields_list.append(original)
                        supabase.table("collections").update({"fields": new_fields_list}).eq("id", m['id']).execute()
                        st.rerun()

                    # C. SUPPRESSION CIBLÉE DE CHAMPS
                    st.markdown("#### ❌ Supprimer des champs précis")
                    to_remove = st.multiselect("Sélectionnez les champs à retirer :", [f['name'] for f in current_fields], key=f"msel_{m['id']}")
                    if to_remove and st.button(f"Confirmer la suppression de {len(to_remove)} champs", key=f"conf_del_f_{m['id']}"):
                        rem_fields = [f for f in current_fields if f['name'] not in to_remove]
                        supabase.table("collections").update({"fields": rem_fields}).eq("id", m['id']).execute()
                        st.rerun()

                    if col_del_m.button("💀 Supprimer le modèle entier", key=f"kil_{m['id']}", type="primary"):
                        supabase.table("collections").delete().eq("id", m['id']).execute()
                        st.rerun()

# ONGLET 4 : UTILISATEURS (LOGIQUE DE SUPPRESSION FIABILISÉE)
if "4. 👥 Utilisateurs" in tabs_list:
    idx = tabs_list.index("4. 👥 Utilisateurs")
    with tabs[idx]:
        st.header("👥 Gestion de l'équipe")
        with st.form("add_user"):
            ue, up = st.text_input("Email"), st.text_input("Mot de passe", type="password")
            ur = st.selectbox("Rôle", ["admin2", "user"] if MY_ROLE == "admin1" else ["user"])
            if st.form_submit_button("Ajouter le collaborateur"):
                try:
                    res = supabase.auth.sign_up({"email": ue, "password": up})
                    if res.user:
                        supabase.table("profiles").insert({"id": res.user.id, "email": ue, "company_id": MY_COMPANY_ID, "role": ur, "full_name": ue.split('@')[0]}).execute()
                        st.success("Compte créé !")
                        st.rerun()
                except Exception as e: st.error(f"Erreur : {e}")
        
        st.divider()
        st.subheader("Membres actuels")
        u_list = supabase.table("profiles").select("*").eq("company_id", MY_COMPANY_ID).execute().data
        if u_list:
            # Affichage tableau
            st.dataframe(pd.DataFrame(u_list)[["email", "role", "full_name"]], use_container_width=True)
            
            # Liste d'actions (Boutons de suppression)
            for user in u_list:
                # Sécurité : On ne peut pas se supprimer soi-même
                if user['id'] == st.session_state.user.id:
                    continue
                
                # Sécurité hiérarchique
                can_delete = False
                if MY_ROLE == "admin1": can_delete = True
                elif MY_ROLE == "admin2" and user['role'] == "user": can_delete = True

                if can_delete:
                    # On utilise un conteneur pour isoler le bouton
                    col_info, col_btn = st.columns([4, 1])
                    col_info.write(f"🗑️ **Supprimer l'accès de :** {user['email']} ({user['role']})")
                    if col_btn.button("Confirmer", key=f"del_user_{user['id']}", type="secondary"):
                        try:
                            # 1. On supprime de la table profiles
                            supabase.table("profiles").delete().eq("id", user['id']).execute()
                            st.success(f"Utilisateur {user['email']} retiré.")
                            time.sleep(0.5)
                            st.rerun() # FORCAGE DU RAFRAICHISSEMENT
                        except Exception as e:
                            st.error(f"Erreur technique : {e}")
