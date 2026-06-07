import os
"""
Frontend TRIAGE — Gradio.

Tre ruoli:
  radiologo / radiologo123 → carica MRI, sottomette casi alla coda
  medico    / medico123    → revisiona casi in coda (predizione AI + valutazione)
  tecnico   / tecnico123   → monitoraggio operativo (log, servizi, modello)
"""

import base64, io, json, os
import gradio as gr
import httpx
import numpy as np
from PIL import Image

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8080")

LABELS = {0: "🟢 Sano (nessun tumore)", 1: "🔴 Malato (tumore rilevato)"}
ICONS  = {"alta": "🔴", "media": "🟡", "bassa": "🟢"}

def _auth(u, p): return (u, p)
def _decode_img(b64): return np.array(Image.open(io.BytesIO(base64.b64decode(b64))))


# ── Login / Logout ────────────────────────────────────────────────────────────

def login(username, password):
    if not username or not password:
        return (None, gr.update(visible=True),
                gr.update(visible=False), gr.update(visible=False),
                gr.update(visible=False), gr.update(visible=False), "",
                "⚠️ Inserisci username e password.")
    try:
        r = httpx.get(f"{GATEWAY_URL}/health", auth=_auth(username, password), timeout=5.0)
        if r.status_code == 401:
            return (None, gr.update(visible=True),
                    gr.update(visible=False), gr.update(visible=False),
                    gr.update(visible=False), gr.update(visible=False), "",
                    "❌ Credenziali non valide.")
    except Exception as exc:
        return (None, gr.update(visible=True),
                gr.update(visible=False), gr.update(visible=False),
                gr.update(visible=False), gr.update(visible=False), "",
                f"❌ Gateway non raggiungibile: {exc}")

    role = {"radiologo": "radiologo", "medico": "medico", "tecnico": "tecnico"}.get(username)
    if not role:
        return (None, gr.update(visible=True),
                gr.update(visible=False), gr.update(visible=False),
                gr.update(visible=False), gr.update(visible=False), "",
                "❌ Utente non riconosciuto.")

    return (
        {"username": username, "password": password, "role": role},
        gr.update(visible=False),
        gr.update(visible=True),
        gr.update(visible=(role == "radiologo")),
        gr.update(visible=(role == "medico")),
        gr.update(visible=(role == "tecnico")),
        f"👤 **{username}** ({role})",
        "",
    )


def logout():
    return (None,
            gr.update(visible=True), gr.update(visible=False),
            gr.update(visible=False), gr.update(visible=False),
            gr.update(visible=False), "")


# ── Pannello Radiologo ────────────────────────────────────────────────────────

def submit_case(auth, image_path, patient_id, age, sex):
    err_pid = "⚠️ ID Paziente obbligatorio." if not patient_id or not patient_id.strip() else ""
    err_age = "⚠️ Età obbligatoria."         if age is None or age == "" else ""
    err_sex = "⚠️ Sesso obbligatorio."        if not sex else ""
    if err_pid or err_age or err_sex:
        return "", err_pid, err_age, err_sex, None
    if not auth:    return "⚠️ Effettua il login.", "", "", "", None
    if not image_path: return "⚠️ Carica un'immagine MRI.", "", "", "", None

    cd = json.dumps({"patient_id": patient_id.strip(),
                     "age": int(age), "sex": sex, "features": {}})
    try:
        with open(image_path, "rb") as f: raw = f.read()
        r = httpx.post(f"{GATEWAY_URL}/api/v1/triage",
                       files={"image": ("mri.png", raw, "image/png")},
                       data={"clinical_data": cd},
                       auth=_auth(auth["username"], auth["password"]),
                       timeout=30.0)
        r.raise_for_status()
        d = r.json()
    except Exception as exc:
        return f"❌ {exc}", "", "", "", None
    p = d["triage"]["priority"]
    return (f"✅ Caso **{d['case_id'][:8]}...** in coda — "
            f"priorità: {ICONS.get(p,'⚪')} **{p.upper()}**",
            "", "", "", d["case_id"])


# ── Pannello Medico ───────────────────────────────────────────────────────────

def load_queue(auth):
    if not auth: return {}, gr.update(choices=[], value=None)
    try:
        r = httpx.get(f"{GATEWAY_URL}/api/v1/cases",
                      params={"status": "pending_review"},
                      auth=_auth(auth["username"], auth["password"]), timeout=10.0)
        r.raise_for_status()
        cases = r.json().get("cases", [])
    except Exception:
        return {}, gr.update(choices=[], value=None)
    if not cases:
        return {}, gr.update(choices=["Nessun caso in coda"], value=None)
    choices = [
        f"{ICONS.get(c['triage']['priority'],'⚪')} "
        f"[conf: {c.get('confidence', 0):.0%}] "
        f"{c.get('patient_id','?')} | {c['case_id'][:8]}..."
        for c in cases
    ]
    mapping = {lbl: c["case_id"] for lbl, c in zip(choices, cases)}
    return mapping, gr.update(choices=choices, value=None)


def show_case_col(case_mapping, selected):
    if not selected or selected == "Nessun caso in coda" or not case_mapping or selected not in case_mapping:
        return gr.update(visible=False), "⚠️ Seleziona un caso dalla lista prima di procedere."
    return gr.update(visible=True), ""


def load_case_content(auth, case_mapping, selected):
    """
    Carica il caso e mostra SOLO MRI + dati paziente + priorità triage.
    Il risultato AI è trattenuto nel case_state e rivelato solo dopo
    la valutazione indipendente del medico (automation bias prevention —
    Art. 14 Regolamento UE AI Act 2024/1689).
    """
    empty = (None, None, "", "")
    if not auth or not case_mapping or not selected: return empty
    if selected == "Nessun caso in coda": return empty
    case_id = case_mapping.get(selected)
    if not case_id: return empty
    try:
        r = httpx.get(f"{GATEWAY_URL}/api/v1/cases/{case_id}",
                      auth=_auth(auth["username"], auth["password"]), timeout=10.0)
        r.raise_for_status()
        case = r.json()
    except Exception:
        return empty

    triage  = case.get("triage", {})
    p       = triage.get("priority", "")
    mri_img = _decode_img(case["image_b64"])

    pat_info = (f"**Paziente**: {case.get('patient_id','N/A')}  \n"
                f"**Età**: {case.get('age','N/A')}  **Sesso**: {case.get('sex','N/A')}  \n"
                f"**Priorità triage**: {ICONS.get(p,'⚪')} {p.upper()} — {triage.get('reason','')}")

    return (case, mri_img, pat_info, case["case_id"],
            gr.update(visible=False),   # chiude ai_section
            None)                          # resetta valutazione indipendente


def show_ai_section(doctor_assessment):
    """Step 1 reveal: valida l'assessment e rende visibile la sezione AI."""
    if not doctor_assessment:
        raise gr.Error("⚠️ Inserisci la tua valutazione clinica indipendente prima di rivelare il risultato AI.")
    return gr.update(visible=True)


def populate_ai(case_state, doctor_assessment):
    """Step 2 reveal (via .then): popola il contenuto AI nel gruppo ora visibile."""
    if not case_state or not doctor_assessment:
        return "", None, None, 0.5, None
    inf      = case_state.get("inference", {})
    exp      = case_state.get("explanation", {})
    label    = inf.get("label", 0)
    conf     = inf.get("confidence", 0.5)
    saliency = _decode_img(exp["saliency_map_b64"]) if exp.get("saliency_map_b64") else None
    ai_info  = (f"**Classificazione AI**: {LABELS.get(label, str(label))}  \n"
                f"**Confidence**: {conf:.1%}  \n"
                + ("> ⚠️ *Stub — nessun valore diagnostico*" if inf.get("is_stub") else ""))
    return (ai_info, LABELS.get(label, str(label)), saliency,
            round(conf, 2), case_state["case_id"])


def submit_review(auth, case_state, case_id, final_label_choice, conf_slider, notes):
    if not auth or not case_state or not case_id:
        return "⚠️ Nessun caso aperto."
    if not final_label_choice:
        return "⚠️ Seleziona la decisione finale."
    ai_label  = case_state.get("inference", {}).get("label", 0)
    ai_conf   = case_state.get("inference", {}).get("confidence", 0.5)
    final_lbl = 1 if "Malato" in final_label_choice else 0
    agreed    = (final_lbl == ai_label)
    payload   = {
        "agreed":              agreed,
        "label_override":      None if agreed else final_lbl,
        "confidence_override": round(float(conf_slider), 2)
                               if abs(float(conf_slider) - ai_conf) > 0.01 else None,
        "notes":               notes or "",
    }
    try:
        r = httpx.post(f"{GATEWAY_URL}/api/v1/cases/{case_id}/review",
                       json=payload,
                       auth=_auth(auth["username"], auth["password"]), timeout=10.0)
        r.raise_for_status()
        return f"✅ Revisione registrata — caso {case_id[:8]}..."
    except Exception as exc:
        return f"❌ {exc}"


# ── Pannello Tecnico (monitoraggio) ──────────────────────────────────────────

def load_status(auth):
    if not auth or auth.get("role") != "tecnico": return {}
    try:
        r = httpx.get(f"{GATEWAY_URL}/api/v1/monitoring/status",
                      auth=_auth(auth["username"], auth["password"]), timeout=10.0)
        return r.json()
    except Exception as exc:
        return {"errore": str(exc)}


def load_model_info(auth):
    if not auth: return {"errore": "Non autenticato"}
    try:
        r = httpx.get(f"{GATEWAY_URL}/api/v1/monitoring/model",
                      auth=_auth(auth["username"], auth["password"]), timeout=10.0)
        return r.json()
    except Exception as exc:
        return {"errore": str(exc)}


def load_logs(auth, event_type_filter):
    if not auth: return {"errore": "Non autenticato"}
    params = {"limit": 50}
    if event_type_filter and event_type_filter != "Tutti":
        params["event_type"] = event_type_filter
    try:
        r = httpx.get(f"{GATEWAY_URL}/api/v1/monitoring/logs",
                      params=params,
                      auth=_auth(auth["username"], auth["password"]), timeout=10.0)
        data = r.json()
        events = data.get("events", [])
        # Formatto per la tabella
        rows = [[e.get("received_at",""), e.get("source",""), 
                 e.get("service",""), e.get("event_type",""),
                 str(e.get("actor",""))] for e in events]
        return rows if rows else [["—","—","—","—","—"]]
    except Exception as exc:
        return [[str(exc),"","","",""]]


def load_model_versions(auth):
    """Carica tutte le versioni disponibili dal Model Registry."""
    if not auth or auth.get("role") != "tecnico":
        return gr.update(choices=[], value=None)
    try:
        r = httpx.get(f"{GATEWAY_URL}/api/v1/monitoring/models",
                      auth=_auth(auth["username"], auth["password"]), timeout=5.0)
        r.raise_for_status()
        versions = r.json().get("versions", [])
        current  = r.json().get("current_version", "")
        # Mostra tutte le versioni tranne quella in produzione
        choices = []
        for v in versions:
            tag = "← in produzione" if v["version"] == current else f'[{v["status"]}]'
            choices.append(f"{v['version']} {tag}")
        mapping = {lbl: v["version"] for lbl, v in zip(choices, versions)}
        return gr.update(choices=choices, value=None), mapping
    except Exception:
        return gr.update(choices=[], value=None), {}


def do_rollback(auth, version_mapping, selected_label):
    if not auth or not selected_label or not version_mapping:
        return "⚠️ Seleziona una versione prima di procedere.", {}
    version = version_mapping.get(selected_label)
    if not version:
        return "⚠️ Versione non trovata.", {}
    try:
        r = httpx.post(
            f"{GATEWAY_URL}/api/v1/monitoring/model/promote/{version}",
            auth=_auth(auth["username"], auth["password"]), timeout=5.0
        )
        r.raise_for_status()
        # Ricarica il modello corrente dopo il rollback
        r2 = httpx.get(f"{GATEWAY_URL}/api/v1/monitoring/model",
                       auth=_auth(auth["username"], auth["password"]), timeout=5.0)
        return f"✅ Versione **{version}** promossa a produzione.", r2.json()
    except Exception as exc:
        return f"❌ {exc}", {}


def load_training_data(auth):
    if not auth: return {"errore": "Non autenticato"}
    try:
        r = httpx.get(f"{GATEWAY_URL}/api/v1/monitoring/training-data",
                      auth=_auth(auth["username"], auth["password"]), timeout=10.0)
        return r.json()
    except Exception as exc:
        return {"errore": str(exc)}


# ── UI ────────────────────────────────────────────────────────────────────────

with gr.Blocks(title="TRIAGE") as demo:

    auth_state   = gr.State(None)
    case_state   = gr.State(None)
    case_mapping = gr.State({})

    with gr.Row():
        gr.Markdown("# TRIAGE\n"
                    "Sistema di supporto alla decisione clinica per tumori cerebrali.")
        with gr.Column(scale=0, min_width=350):
            with gr.Row(visible=False) as top_bar:
                user_display = gr.Markdown("", container=False)
                logout_btn   = gr.Button("Esci", size="sm", variant="secondary", min_width=80)

    # Login
    with gr.Group() as login_group:
        gr.Markdown("### 🔐 Accesso")
        with gr.Row():
            username_in = gr.Textbox(label="Username",
                                     placeholder="radiologo / medico / tecnico")
            password_in = gr.Textbox(label="Password", type="password")
        login_btn    = gr.Button("Accedi", variant="primary")
        login_status = gr.Markdown("")

    # ── Pannello Radiologo ────────────────────────────────────────────────────
    with gr.Group(visible=False) as radiologo_panel:
        gr.Markdown("## Pannello Radiologo")
        img_in      = gr.Image(type="filepath", label="Immagine MRI")
        patient_in  = gr.Textbox(label="ID Paziente", placeholder="es. P001")
        patient_err = gr.Markdown("")
        age_in      = gr.Number(label="Età", minimum=0, maximum=120, value=None)
        age_err     = gr.Markdown("")
        sex_in      = gr.Radio(["M", "F"], label="Sesso")
        sex_err     = gr.Markdown("")
        submit_btn  = gr.Button("📤 Sottometti caso", variant="primary")
        submit_out  = gr.Markdown("")

    # ── Pannello Medico ───────────────────────────────────────────────────────
    with gr.Group(visible=False) as medico_panel:
        gr.Markdown("## Pannello Medico")
        with gr.Row():
            with gr.Column(scale=1):
                load_btn = gr.Button("Carica casi in coda", variant="primary")
                open_btn = gr.Button("Apri caso selezionato")
                open_error_msg = gr.Markdown("")
            with gr.Column(scale=3):
                case_radio = gr.Radio(label="Casi in attesa (ordinati per confidence crescente)",
                                      choices=[], interactive=True)

        with gr.Column(visible=False) as case_col:
            gr.Markdown("---")
            with gr.Row():
                # Colonna sinistra: MRI + dati paziente (sempre visibili)
                with gr.Column(scale=1):
                    mri_display  = gr.Image(label="Immagine MRI (224×224)")
                    patient_info = gr.Markdown("")

                # Colonna destra: valutazione indipendente → reveal → revisione
                with gr.Column(scale=1):
                    gr.Markdown(
                        "### ⚕️ Valutazione clinica indipendente\n"
                        "*Esprimi la tua diagnosi **prima** di vedere il risultato AI.*"
                    )
                    doctor_assessment = gr.Radio(
                        ["Sano (nessun tumore)", "Malato (tumore rilevato)"],
                        label="Tua valutazione")
                    reveal_btn = gr.Button("Rivela risultato AI", variant="secondary")

                    # Risultato AI — nascosto fino al reveal
                    with gr.Group(visible=False) as ai_section:
                        ai_info_out  = gr.Markdown("")
                        saliency_out = gr.Image(label="Saliency Map")

                        gr.Markdown("### Revisione clinica")
                        current_case_id = gr.Textbox(visible=False)
                        final_label = gr.Radio(
                            ["Sano (nessun tumore)", "Malato (tumore rilevato)"],
                            label="Decisione finale")
                        conf_slider = gr.Slider(0.0, 1.0, step=0.01,
                            label="Confidence finale",
                            info="Pre-riempita con la confidence AI — modifica se non concordi")
                        notes_in   = gr.Textbox(label="Note cliniche", lines=3)
                        review_btn = gr.Button("Invia revisione", variant="primary")
                        review_out = gr.Markdown("")

    # ── Pannello Tecnico (monitoraggio) ───────────────────────────────────────
    with gr.Group(visible=False) as tecnico_panel:
        gr.Markdown("## 🔧 Pannello Tecnico — Monitoraggio Operativo")

        with gr.Row():
            with gr.Column():
                gr.Markdown("### Stato microservizi")
                status_out = gr.JSON(label="Health dei servizi")
                status_btn = gr.Button("Aggiorna stato")

            with gr.Column():
                gr.Markdown("### Modello in produzione")
                model_out = gr.JSON(label="Versione attiva")
                gr.Markdown("#### Rollback")
                version_mapping_state = gr.State({})
                version_dropdown = gr.Dropdown(
                    choices=[], label="Seleziona versione",
                    info="Versioni disponibili nel Model Registry")
                rollback_btn  = gr.Button("Promuovi versione selezionata", variant="stop")
                rollback_out  = gr.Markdown("")

        gr.Markdown("### Log eventi")
        log_filter = gr.Dropdown(
            choices=["Tutti", "service.started", "service.error",
                     "triage.completed", "inference.completed",
                     "feedback.submitted", "review.submitted",
                     "model.promoted", "ingestion.completed"],
            value="Tutti", label="Filtra per tipo evento")
        log_btn = gr.Button("Carica log")
        log_table = gr.Dataframe(
            headers=["Timestamp", "Fonte", "Servizio", "Tipo evento", "Attore"],
            datatype=["str","str","str","str","str"],
            interactive=False)

        gr.Markdown("### Campioni per retraining")
        training_out = gr.JSON(label="Campioni etichettati")
        training_btn = gr.Button("Aggiorna")

    # ── Handlers ──────────────────────────────────────────────────────────────

    login_btn.click(fn=login,
        inputs=[username_in, password_in],
        outputs=[auth_state, login_group, top_bar,
                 radiologo_panel, medico_panel, tecnico_panel,
                 user_display, login_status]
    ).then(
        fn=load_status,
        inputs=[auth_state],
        outputs=[status_out]
    ).then(
        fn=load_model_info,
        inputs=[auth_state],
        outputs=[model_out]
    ).then(
        fn=load_model_versions,
        inputs=[auth_state],
        outputs=[version_dropdown, version_mapping_state]
    )

    logout_btn.click(fn=logout,
        inputs=[],
        outputs=[auth_state, login_group, top_bar,
                 radiologo_panel, medico_panel, tecnico_panel, user_display])

    submit_btn.click(fn=submit_case,
        inputs=[auth_state, img_in, patient_in, age_in, sex_in],
        outputs=[submit_out, patient_err, age_err, sex_err, gr.State()])

    load_btn.click(fn=load_queue,
        inputs=[auth_state], outputs=[case_mapping, case_radio])

    open_btn.click(
        fn=show_case_col,
        inputs=[case_mapping, case_radio],
        outputs=[case_col, open_error_msg]
    ).then(
        fn=load_case_content,
        inputs=[auth_state, case_mapping, case_radio],
        outputs=[case_state, mri_display, patient_info, current_case_id,
                 ai_section, doctor_assessment])

    reveal_btn.click(
        fn=show_ai_section,
        inputs=[doctor_assessment],
        outputs=[ai_section]
    ).then(
        fn=populate_ai,
        inputs=[case_state, doctor_assessment],
        outputs=[ai_info_out, final_label, saliency_out,
                 conf_slider, current_case_id])

    review_btn.click(fn=submit_review,
        inputs=[auth_state, case_state, current_case_id,
                final_label, conf_slider, notes_in],
        outputs=[review_out])

    status_btn.click(fn=load_status,
        inputs=[auth_state], outputs=[status_out])
    rollback_btn.click(fn=do_rollback,
        inputs=[auth_state, version_mapping_state, version_dropdown],
        outputs=[rollback_out, model_out])
    log_btn.click(fn=load_logs,
        inputs=[auth_state, log_filter], outputs=[log_table])
    training_btn.click(fn=load_training_data,
        inputs=[auth_state], outputs=[training_out])


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, theme=gr.themes.Soft())
