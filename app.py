import streamlit as st
import pandas as pd
from sqlalchemy import select, func
from atelier_pvc.database import init_db, get_session, DATABASE_URL
from atelier_pvc.models import Party, Material, Quote, WorkOrder, Invoice
from atelier_pvc.services.client_service import list_parties, create_party
from atelier_pvc.services.catalog_service import list_materials, create_material
from atelier_pvc.services.quotation_service import create_quote, list_quotes
from atelier_pvc.services.production_service import create_work_order, list_work_orders
from atelier_pvc.services.invoice_service import create_invoice, register_payment, list_invoices
from atelier_pvc.services.inventory_service import low_stock, adjust_stock
from atelier_pvc.calculations import calculate_window
from atelier_pvc.cutting_optimizer import optimize_cuts
from atelier_pvc.pdf_service import quote_pdf
from atelier_pvc.backup_service import export_backup

st.set_page_config(page_title="Atelier PVC Pro", page_icon="🪟", layout="wide", initial_sidebar_state="expanded")
st.markdown("""<style>
.block-container{padding-top:1.7rem;padding-bottom:2.5rem;max-width:1500px}
[data-testid="stMetric"]{background:#fff;border:1px solid #e4e9f0;padding:16px;border-radius:12px}
[data-testid="stSidebar"]{border-right:1px solid #e4e9f0}
h1,h2,h3{letter-spacing:-.025em}
</style>""", unsafe_allow_html=True)
init_db()
if "notice" not in st.session_state: st.session_state.notice = ""
with get_session() as db:
    st.sidebar.title("🪟 Atelier PVC Pro")
    st.sidebar.caption("Gestion intégrée de votre atelier")
    page=st.sidebar.radio("Navigation",["Tableau de bord","Clients","Fournisseurs","Catalogue matériaux","Calculateur PVC","Optimisation des coupes","Devis","Fabrication","Factures & paiements","Stocks","Paramètres & sauvegarde"],label_visibility="collapsed")
    st.sidebar.divider()
    st.sidebar.caption("Stockage : " + ("PostgreSQL distant" if not DATABASE_URL.startswith('sqlite') else "SQLite local"))
    if DATABASE_URL.startswith('sqlite'):
        st.sidebar.info("Base SQLite locale. Sur Streamlit Cloud, configurez DATABASE_URL pour conserver les données entre redémarrages.")
    st.title(page)
    if page=="Tableau de bord":
        clients=db.scalar(select(func.count(Party.id)).where(Party.kind=='client',Party.active.is_(True))) or 0
        quotes=db.scalar(select(func.count(Quote.id)).where(Quote.status.in_(['Brouillon','Envoyé','En attente']))) or 0
        orders=db.scalar(select(func.count(WorkOrder.id)).where(WorkOrder.status.in_(['À fabriquer','En cours']))) or 0
        turnover=db.scalar(select(func.coalesce(func.sum(Invoice.total),0))) or 0
        paid=db.scalar(select(func.coalesce(func.sum(Invoice.paid),0))) or 0
        a,b,c,d=st.columns(4); a.metric("Clients actifs",clients); b.metric("Devis en attente",quotes); c.metric("Fabrications ouvertes",orders); d.metric("CA facturé",f"{turnover:,.2f} DA")
        a,b=st.columns(2); a.metric("Paiements reçus",f"{paid:,.2f} DA"); b.metric("Reste à encaisser",f"{turnover-paid:,.2f} DA")
        alerts=low_stock(db)
        st.subheader("Alertes de stock")
        if alerts: st.dataframe(pd.DataFrame([{"Référence":x.reference,"Article":x.name,"Catégorie":x.category,"Stock":x.stock_qty,"Seuil":x.alert_threshold,"Unité":x.unit} for x in alerts]),use_container_width=True,hide_index=True)
        else: st.success("Aucune alerte de stock actuellement.")
        st.subheader("Derniers devis")
        recent=list_quotes(db)[:5]
        if recent: st.dataframe(pd.DataFrame([{"N°":q.number,"Client":q.client_name,"Date":q.date,"Statut":q.status,"Total (DA)":q.total} for q in recent]),use_container_width=True,hide_index=True)
        else: st.caption("Aucun devis enregistré pour le moment.")
    elif page in ("Clients","Fournisseurs"):
        kind='client' if page=='Clients' else 'supplier'; st.subheader("Ajouter une fiche")
        with st.form("party_form",clear_on_submit=True):
            name=st.text_input("Nom / raison sociale *"); c1,c2=st.columns(2); phone=c1.text_input("Téléphone"); email=c2.text_input("E-mail"); address=st.text_input("Adresse"); notes=st.text_area("Notes"); submit=st.form_submit_button("Enregistrer",type="primary")
        if submit:
            try: create_party(db,kind,name,phone,email,address,notes); st.success("Fiche enregistrée."); st.rerun()
            except ValueError as e: st.error(str(e))
        st.subheader("Répertoire")
        rows=list_parties(db,kind); query=st.text_input("Rechercher",key=f"search_{kind}").lower()
        rows=[x for x in rows if query in x.name.lower() or query in x.phone.lower()]
        st.dataframe(pd.DataFrame([{"ID":x.id,"Nom":x.name,"Téléphone":x.phone,"E-mail":x.email,"Adresse":x.address,"Actif":x.active} for x in rows]),use_container_width=True,hide_index=True) if rows else st.info("Aucune fiche correspondante.")
        if rows:
            with st.form(f"deactivate_{kind}"):
                target=st.selectbox("Fiche à activer/désactiver",rows,format_func=lambda x:f"#{x.id} — {x.name}"); active=st.checkbox("Fiche active",value=target.active); upd=st.form_submit_button("Mettre à jour le statut")
            if upd: target.active=active; db.commit(); st.success("Statut mis à jour."); st.rerun()
    elif page=="Catalogue matériaux":
        st.caption("Profilés PVC, vitrages, accessoires, quincaillerie et renforts.")
        with st.expander("Ajouter un article",expanded=True):
            with st.form("material_form",clear_on_submit=True):
                c1,c2,c3=st.columns(3); ref=c1.text_input("Référence *"); name=c2.text_input("Désignation *"); category=c3.selectbox("Catégorie",["Profilé PVC","Vitrage","Accessoire","Quincaillerie","Renfort","Autre"])
                c1,c2,c3=st.columns(3); system=c1.text_input("Système / marque"); color=c2.text_input("Couleur",value="Blanc"); unit=c3.selectbox("Unité",["pièce","mètre","barre","m²","lot","paire"])
                c1,c2,c3,c4=st.columns(4); price=c1.number_input("Prix unitaire (DA)",min_value=0.0,step=100.0); stock=c2.number_input("Stock",min_value=0.0,step=1.0); threshold=c3.number_input("Seuil d'alerte",min_value=0.0,step=1.0); bar=c4.number_input("Longueur barre (mm)",min_value=1,value=6000,step=100)
                loss=st.number_input("Perte estimée (%)",min_value=0.0,max_value=100.0,value=5.0); notes=st.text_area("Notes techniques"); submit=st.form_submit_button("Ajouter au catalogue",type="primary")
            if submit:
                try: create_material(db,reference=ref,name=name,category=category,system=system,color=color,unit=unit,unit_price=price,stock_qty=stock,alert_threshold=threshold,bar_length_mm=int(bar),loss_percent=loss,notes=notes); st.success("Article ajouté."); st.rerun()
                except Exception as e: st.error(f"Impossible d'ajouter l'article : {e}")
        materials=list_materials(db); q=st.text_input("Filtrer le catalogue").lower(); materials=[m for m in materials if q in m.name.lower() or q in m.reference.lower() or q in m.category.lower()]
        st.dataframe(pd.DataFrame([{"Référence":m.reference,"Désignation":m.name,"Catégorie":m.category,"Système":m.system,"Couleur":m.color,"Unité":m.unit,"Prix DA":m.unit_price,"Stock":m.stock_qty,"Seuil":m.alert_threshold,"Actif":m.active} for m in materials]),use_container_width=True,hide_index=True) if materials else st.info("Catalogue vide.")
    elif page=="Calculateur PVC":
        st.warning("Important : les règles proposées sont des paramètres d'estimation. Validez-les avec la documentation du fabricant avant toute fabrication.")
        rules=db.scalars(select(__import__('atelier_pvc.models',fromlist=['TechnicalRule']).TechnicalRule).order_by(__import__('atelier_pvc.models',fromlist=['TechnicalRule']).TechnicalRule.system)).all()
        if not rules:
            from atelier_pvc.models import TechnicalRule
            rule=TechnicalRule(); db.add(rule); db.commit(); rules=[rule]
        systems=sorted(set(r.system for r in rules)); system=st.selectbox("Système technique",systems); rule=next(r for r in rules if r.system==system)
        with st.form("calc_form"):
            c1,c2,c3=st.columns(3); width=c1.number_input("Largeur (mm)",min_value=1,value=1200); height=c2.number_input("Hauteur (mm)",min_value=1,value=1400); qty=c3.number_input("Quantité",min_value=1,value=1,step=1)
            measured=st.radio("Dimensions saisies",["Ouverture maçonnée","Dimensions finales de fabrication"],horizontal=True)=="Ouverture maçonnée"
            go=st.form_submit_button("Calculer l'estimation",type="primary")
        if go:
            try:
                result=calculate_window(width,height,int(qty),measured,rule.installation_gap_mm,rule.frame_deduction_width_mm,rule.frame_deduction_height_mm,rule.glass_clearance_mm)
                a,b,c=st.columns(3); a.metric("Fabrication largeur",f"{result['fabrication_width_mm']:.0f} mm"); b.metric("Fabrication hauteur",f"{result['fabrication_height_mm']:.0f} mm"); c.metric("Surface vitrage estimée",f"{result['glass_area_m2']:.3f} m²")
                st.dataframe(pd.DataFrame([{"Élément":"Dormant — 2 largeurs","Longueur unitaire (mm)":result['fabrication_width_mm']-rule.frame_deduction_width_mm/2,"Quantité par ouvrage":2},{"Élément":"Dormant — 2 hauteurs","Longueur unitaire (mm)":result['fabrication_height_mm']-rule.frame_deduction_height_mm/2,"Quantité par ouvrage":2},{"Élément":"Vitrage estimé","Largeur (mm)":result['glass_width_mm'],"Hauteur (mm)":result['glass_height_mm']}]),use_container_width=True,hide_index=True)
                st.caption(f"Périmètre indicatif : {result['perimeter_m']:.3f} m. Quantité : {qty}.")
                for w in result['warnings']: st.error(w)
            except ValueError as e: st.error(str(e))
        with st.expander("Configurer les règles du système"):
            with st.form("rule_form"):
                sysname=st.text_input("Nom du système",value=rule.system); typology=st.text_input("Typologie",value=rule.typology); gap=st.number_input("Jeu de pose (mm, par côté)",min_value=0.0,value=float(rule.installation_gap_mm)); dw=st.number_input("Déduction dormant largeur (mm)",min_value=0.0,value=float(rule.frame_deduction_width_mm)); dh=st.number_input("Déduction dormant hauteur (mm)",min_value=0.0,value=float(rule.frame_deduction_height_mm)); gc=st.number_input("Tolérance vitrage (mm)",min_value=0.0,value=float(rule.glass_clearance_mm)); kerf=st.number_input("Trait de scie (mm)",min_value=0.0,value=float(rule.saw_kerf_mm)); bl=st.number_input("Barre commerciale (mm)",min_value=1,value=int(rule.bar_length_mm)); save=st.form_submit_button("Enregistrer les règles")
            if save:
                rule.system=sysname; rule.typology=typology; rule.installation_gap_mm=gap; rule.frame_deduction_width_mm=dw; rule.frame_deduction_height_mm=dh; rule.glass_clearance_mm=gc; rule.saw_kerf_mm=kerf; rule.bar_length_mm=int(bl); db.commit(); st.success("Règles enregistrées."); st.rerun()
    elif page=="Optimisation des coupes":
        st.write("Saisissez une longueur par ligne ou séparez les longueurs par des virgules. L'algorithme utilise une heuristique Best-Fit Decreasing.")
        lengths_text=st.text_area("Longueurs de coupe (mm)",value="1200, 1200, 1400, 1400, 800, 800"); c1,c2=st.columns(2); bar=c1.number_input("Longueur commerciale (mm)",min_value=1,value=6000); kerf=c2.number_input("Trait de scie (mm)",min_value=0.0,value=3.0)
        if st.button("Optimiser",type="primary"):
            try:
                lengths=[float(x.strip()) for x in lengths_text.replace('\n',',').split(',') if x.strip()]; result=optimize_cuts(lengths,bar,kerf)
                a,b,c=st.columns(3); a.metric("Barres nécessaires",result['bars_count']); b.metric("Taux d'utilisation",f"{result['utilization_percent']}%"); c.metric("Chutes + sciure",f"{result['waste_mm']:.0f} mm")
                st.dataframe(pd.DataFrame([{"Barre":i+1,"Coupes (mm)":" + ".join(map(str,b['cuts_mm'])),"Longueur utilisée (mm)":b['used_mm'],"Chute (mm)":b['offcut_mm']} for i,b in enumerate(result['bars'])]),use_container_width=True,hide_index=True)
            except Exception as e: st.error(str(e))
    elif page=="Devis":
        st.subheader("Créer un devis")
        clients=list_parties(db,'client'); client_names=[x.name for x in clients]+["Client comptoir"]
        with st.form("quote_form"):
            client=st.selectbox("Client",client_names); count=st.number_input("Nombre de lignes",min_value=1,max_value=15,value=1,step=1); lines=[]
            for i in range(int(count)):
                st.markdown(f"**Ligne {i+1}**"); c1,c2,c3,c4=st.columns([4,1,1,2]); desc=c1.text_input("Désignation",key=f"qd{i}"); qty=c2.number_input("Qté",min_value=0.01,value=1.0,key=f"qq{i}"); unit=c3.selectbox("Unité",["pièce","m²","mètre","lot"],key=f"qu{i}"); price=c4.number_input("Prix unitaire DA",min_value=0.0,value=0.0,key=f"qp{i}"); lines.append({"description":desc,"quantity":qty,"unit":unit,"unit_price":price})
            c1,c2=st.columns(2); discount=c1.number_input("Remise totale (DA)",min_value=0.0); tax=c2.number_input("Taxe (%)",min_value=0.0,max_value=100.0,value=0.0); notes=st.text_area("Notes et conditions"); save=st.form_submit_button("Enregistrer le devis",type="primary")
        if save:
            try:
                valid=[x for x in lines if x['description'].strip()]
                quote=create_quote(db,client,valid,discount,tax,notes); st.session_state['last_quote_id']=quote.id; st.success(f"Devis {quote.number} enregistré — {quote.total:,.2f} DA")
            except Exception as e: st.error(str(e))
        quotes=list_quotes(db); st.subheader("Historique des devis")
        if quotes:
            st.dataframe(pd.DataFrame([{"N°":q.number,"Client":q.client_name,"Date":q.date,"Statut":q.status,"Sous-total":q.subtotal,"Total DA":q.total} for q in quotes]),use_container_width=True,hide_index=True)
            choices={f"{q.number} — {q.client_name}":q for q in quotes}; selected=st.selectbox("Exporter un devis PDF",list(choices)); q=choices[selected]
            st.download_button("Télécharger le PDF",quote_pdf(q),file_name=f"{q.number}.pdf",mime="application/pdf")
            c1,c2=st.columns(2)
            with c1:
                if st.button("Marquer comme envoyé"): q.status='Envoyé'; db.commit(); st.rerun()
            with c2:
                if st.button("Confirmer comme accepté"): q.status='Accepté'; db.commit(); st.rerun()
        else: st.info("Aucun devis enregistré.")
    elif page=="Fabrication":
        quotes=[q for q in list_quotes(db) if q.status=='Accepté']; st.subheader("Créer un ordre de fabrication")
        with st.form("wo_form"):
            client=st.text_input("Client"); desc=st.text_area("Description de fabrication *"); qty=st.number_input("Quantité",min_value=1,value=1); due=st.date_input("Date prévue",value=None); quote_id=st.selectbox("Devis accepté (facultatif)",[None]+[q.id for q in quotes],format_func=lambda x:"Aucun" if x is None else next(q.number for q in quotes if q.id==x)); save=st.form_submit_button("Créer l'ordre",type="primary")
        if save:
            try: item=create_work_order(db,client,desc,int(qty),due,quote_id); st.success(f"Ordre {item.number} créé."); st.rerun()
            except Exception as e: st.error(str(e))
        orders=list_work_orders(db)
        if orders:
            st.dataframe(pd.DataFrame([{"N°":x.number,"Client":x.client_name,"Description":x.description,"Qté":x.quantity,"Statut":x.status,"Échéance":x.due_date} for x in orders]),use_container_width=True,hide_index=True)
            chosen=st.selectbox("Mettre à jour le statut de l'ordre",orders,format_func=lambda x:f"{x.number} — {x.client_name}"); status=st.selectbox("Nouveau statut",["À fabriquer","En cours","En attente matériaux","Terminé","Livré","Annulé"])
            if st.button("Enregistrer le statut"): chosen.status=status; db.commit(); st.success("Statut actualisé."); st.rerun()
        else: st.info("Aucun ordre de fabrication.")
    elif page=="Factures & paiements":
        quotes=[q for q in list_quotes(db) if q.status=='Accepté']; st.subheader("Émettre une facture")
        with st.form("invoice_form"):
            quote_id=st.selectbox("À partir d'un devis accepté",[None]+[q.id for q in quotes],format_func=lambda x:"Saisie manuelle" if x is None else next(q.number for q in quotes if q.id==x)); client=st.text_input("Client"); amount=st.number_input("Montant facturé (DA)",min_value=0.0); notes=st.text_area("Notes"); create=st.form_submit_button("Émettre la facture",type="primary")
        if create:
            q=next((x for x in quotes if x.id==quote_id),None); client_name=q.client_name if q else client; total=q.total if q else amount
            try: inv=create_invoice(db,client_name,total,quote_id,notes); st.success(f"Facture {inv.number} émise."); st.rerun()
            except Exception as e: st.error(str(e))
        invoices=list_invoices(db)
        if invoices:
            st.subheader("Factures")
            st.dataframe(pd.DataFrame([{"N°":i.number,"Client":i.client_name,"Date":i.date,"Total DA":i.total,"Payé DA":i.paid,"Reste DA":round(i.total-i.paid,2),"Statut":i.status} for i in invoices]),use_container_width=True,hide_index=True)
            unpaid=[i for i in invoices if i.paid<i.total]
            if unpaid:
                st.subheader("Enregistrer un règlement")
                with st.form("payment_form"):
                    inv=st.selectbox("Facture",unpaid,format_func=lambda x:f"{x.number} — reste {x.total-x.paid:.2f} DA"); amount=st.number_input("Montant reçu (DA)",min_value=0.01); method=st.selectbox("Mode",["Espèces","Virement","Chèque","Carte","Autre"]); ref=st.text_input("Référence du paiement"); save=st.form_submit_button("Enregistrer le paiement")
                if save:
                    try: register_payment(db,inv.id,amount,method,ref); st.success("Paiement enregistré."); st.rerun()
                    except Exception as e: st.error(str(e))
        else: st.info("Aucune facture.")
    elif page=="Stocks":
        materials=list_materials(db,active_only=True); alerts=low_stock(db); st.metric("Articles sous le seuil",len(alerts)); st.subheader("Ajustement de stock")
        if materials:
            with st.form("stock_form"):
                item=st.selectbox("Article",materials,format_func=lambda x:f"{x.reference} — {x.name} (stock : {x.stock_qty:g} {x.unit})"); delta=st.number_input("Variation (+ réception / − consommation)",value=0.0,step=1.0); save=st.form_submit_button("Appliquer le mouvement",type="primary")
            if save:
                try: adjust_stock(db,item.id,delta); st.success("Stock mis à jour."); st.rerun()
                except Exception as e: st.error(str(e))
            st.dataframe(pd.DataFrame([{"Référence":m.reference,"Article":m.name,"Stock":m.stock_qty,"Unité":m.unit,"Seuil":m.alert_threshold,"Valeur indicative DA":m.stock_qty*m.unit_price} for m in materials]),use_container_width=True,hide_index=True)
        else: st.info("Ajoutez d'abord des articles dans le catalogue.")
    elif page=="Paramètres & sauvegarde":
        st.subheader("Informations atelier")
        st.info("Les coordonnées peuvent être utilisées dans les documents après configuration. La devise de référence actuelle est le dinar algérien (DA).")
        st.text_input("Nom de l'atelier",value="Atelier PVC Pro",key="shop_name"); st.text_input("Téléphone",key="shop_phone"); st.text_input("Adresse",key="shop_address"); st.selectbox("Devise",["DA","EUR","USD"],index=0)
        st.subheader("Sauvegarde")
        st.download_button("Télécharger une sauvegarde JSON",export_backup(db),file_name="atelier_pvc_backup.json",mime="application/json",type="primary")
        st.warning("La restauration JSON n'est pas activée dans cette version afin d'éviter une importation non validée. Conservez aussi une copie du fichier SQLite en usage local.")
        st.subheader("Paramètres techniques enregistrés")
        from atelier_pvc.models import TechnicalRule
        rules=db.scalars(select(TechnicalRule)).all()
        st.dataframe(pd.DataFrame([{"Système":r.system,"Typologie":r.typology,"Jeu de pose":r.installation_gap_mm,"Déduction L":r.frame_deduction_width_mm,"Déduction H":r.frame_deduction_height_mm,"Jeu vitrage":r.glass_clearance_mm,"Trait de scie":r.saw_kerf_mm,"Barre":r.bar_length_mm} for r in rules]),use_container_width=True,hide_index=True) if rules else st.caption("Les règles seront créées au premier accès au calculateur.")
