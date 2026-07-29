"""Flask API + Dashboard server for VM CRM (Production-ready)"""

import os
import sys
from datetime import datetime, date, timedelta
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for,
                   jsonify, session, send_from_directory)
from flask_login import (LoginManager, login_user, logout_user,
                          login_required, current_user)
from flask_cors import CORS
from sqlalchemy import func
import requests as http_req

import os
import requests as http_req
import resend

# Add parent to path
sys.path.insert(0, os.path.dirname(__file__))

from models import db, User, Lead, Interaction, Appointment, init_db

# Resend — VM has its own domain!
RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')
if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY
RESEND_FROM = os.environ.get('RESEND_FROM', 'hola@veranomedia.digital')
RESEND_TO = os.environ.get('RESEND_TO', 'espartaco.rd@gmail.com')

def send_vm_email(subject, html_body, to=None):
    """Envía email via Resend con el dominio de VM."""
    try:
        resend.Emails.send({
            "from": RESEND_FROM,
            "to": to or [RESEND_TO],
            "subject": subject,
            "html": html_body,
        })
    except Exception as e:
        print(f"[Resend] Error: {e}")

# ============================================================
# Chat AI Config
# ============================================================
OPENROUTER_KEY = ''
for key_name in ['OPENROUTER_API_KEY_1', 'OPENROUTER_API_KEY_2', 'OPENROUTER_API_KEY']:
    val = os.environ.get(key_name, '')
    if val:
        OPENROUTER_KEY = val
        break
if not OPENROUTER_KEY:
    try:
        with open(os.path.expanduser('~/.env')) as f:
            for line in f:
                if 'OPENROUTER_API_KEY' in line and '=' in line:
                    OPENROUTER_KEY = line.split('=', 1)[1].strip().strip("'\"")
                    break
    except:
        pass

CHAT_MODEL = 'deepseek/deepseek-v4-flash'
try:
    with open(os.path.join(os.path.dirname(__file__), '..', 'maria_prompt_web.txt')) as f:
        MARIA_SYSTEM_PROMPT = f.read()
except:
    MARIA_SYSTEM_PROMPT = 'Eres Maria, ejecutiva de ventas de Verano Media RD.'

app = Flask(__name__,
            static_folder=os.path.join(os.path.dirname(__file__), '..', 'frontend'),
            template_folder=os.path.join(os.path.dirname(__file__), '..', 'frontend'))
app.debug = False

# Database: supports PostgreSQL (Render) and SQLite (local)
database_url = os.environ.get('DATABASE_URL', '')
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
os.environ['DATABASE_URL'] = database_url

with app.app_context():
    init_db(app)
    # Migration: add interaction columns
    for col in ['channel_id', 'source_phone', 'ai_response', 'ai_summary']:
        try:
            db.session.execute(db.text('ALTER TABLE interactions ADD COLUMN ' + col + ' TEXT DEFAULT \'\''))
            db.session.commit()
        except Exception:
            db.session.rollback()

# CORS
CORS_ORIGINS = os.environ.get('CORS_ORIGINS', 'https://veranomedia.digital,https://*.vercel.app')
CORS(app, origins=CORS_ORIGINS.split(','), supports_credentials=True)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


# user_loader is below

def call_ai(user_msg, history=None):
    messages = [{'role': 'system', 'content': MARIA_SYSTEM_PROMPT}]
    if history:
        for h in history[-8:]:
            messages.append({'role': 'user', 'content': h.get('user','')})
            if h.get('bot'):
                messages.append({'role': 'assistant', 'content': h['bot']})
    messages.append({'role': 'user', 'content': user_msg})
    resp = http_req.post(
        'https://openrouter.ai/api/v1/chat/completions',
        headers={
            'Authorization': 'Bearer ' + os.environ.get('OPENROUTER_API_KEY', ''),
            'Content-Type': 'application/json',
            'HTTP-Referer': 'https://veranomedia.digital',
        },
        json={'model': CHAT_MODEL, 'messages': messages, 'max_tokens': 800, 'temperature': 0.7},
        timeout=30,
    )
    if resp.status_code != 200:
        raise Exception('AI error: ' + str(resp.status_code))
    return resp.json()['choices'][0]['message']['content']



@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ============================================================
# AUTH
# ============================================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user, remember=True)
            next_page = request.args.get('next', '/')
            return redirect(next_page)
        return render_template('login.html', error='Usuario o contraseña incorrectos')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('/login')


# ============================================================
# PAGES
# ============================================================

@app.route('/')
@login_required
def dashboard():
    return render_template('dashboard.html')


@app.route('/pipeline')
@login_required
def pipeline():
    return render_template('dashboard.html')


@app.route('/leads')
@login_required
def leads_page():
    return render_template('dashboard.html')


@app.route('/lead/<int:lead_id>')
@login_required
def lead_detail(lead_id):
    return render_template('dashboard.html')


@app.route('/calendar')
@login_required
def calendar():
    return render_template('dashboard.html')


@app.route('/reports')
@login_required
def reports():
    return render_template('dashboard.html')


# ============================================================
# ============================================================
# Helpers
# ============================================================

def rd_now():
    from datetime import timezone
    return datetime.now(timezone.utc) - timedelta(hours=4)

# ============================================================
# API — Health + Chat + Timeline
# ============================================================

@app.route('/api/health')
def api_health():
    return jsonify({'status': 'ok', 'time': rd_now().isoformat()})

@app.route('/api/chat', methods=['POST'])
def api_chat():
    try:
        data = request.get_json()
        if not data or 'message' not in data:
            return jsonify({'error': 'Mensaje requerido'}), 400
        reply = call_ai(data['message'].strip(), data.get('history', []))
        import re as _re
        lm = _re.search(r'---LEAD---(.*?)---FIN---', reply, _re.DOTALL)
        if lm:
            try:
                from models import Lead
                t = lm.group(1)
                nm = _re.search(r'Nombre:\\s*(.+)', t)
                pm = _re.search(r'Telefono:\\s*(.+)', t)
                if nm and pm:
                    n, p = nm.group(1).strip(), pm.group(1).strip()
                    lead = Lead.query.filter_by(phone=p).first()
                    if not lead:
                        bm = _re.search(r'Negocio:\\s*(.+)', t)
                        em = _re.search(r'Correo:\\s*(.+)', t)
                        sm = _re.search(r'Servicio:\\s*(.+)', t)
                        lead = Lead(name=n, phone=p, email=em.group(1).strip() if em else '', source='web_chat', status='caliente', business=bm.group(1).strip() if bm else '', notes='Servicio: ' + (sm.group(1).strip() if sm else ''))
                        db.session.add(lead)
                        db.session.flush()
                    else:
                        lead.status = 'caliente'
                    db.session.commit()
            except Exception:
                pass
        return jsonify({'response': reply, 'success': True})
    except Exception as e:
        print(f'[Chat API] Error: {e}')
        return jsonify({'error': 'Error interno'}), 500


# ============================================================
# API — Leads
# ============================================================

@app.route('/api/leads', methods=['GET'])
@login_required
def api_get_leads():
    status_filter = request.args.get('status')
    search = request.args.get('search', '').strip()
    days = request.args.get('days', type=int)

    query = Lead.query

    if status_filter:
        query = query.filter_by(status=status_filter)
    if search:
        like = f'%{search}%'
        query = query.filter(
            db.or_(Lead.name.ilike(like),
                   Lead.business.ilike(like),
                   Lead.phone.ilike(like),
                   Lead.email.ilike(like))
        )
    if days:
        cutoff = rd_now() - timedelta(days=days)
        query = query.filter(Lead.created_at >= cutoff)

    query = query.order_by(Lead.updated_at.desc())
    leads = query.all()
    return jsonify({
        'leads': [l.to_dict() for l in leads],
        'total': len(leads)
    })


@app.route('/api/leads', methods=['POST'])
@login_required
def api_create_lead():
    data = request.get_json()
    if not data or not data.get('name'):
        return jsonify({'error': 'name is required'}), 400

    lead = Lead(
        name=data['name'].strip(),
        business=data.get('business', '').strip(),
        phone=data.get('phone', '').strip(),
        email=data.get('email', '').strip(),
        status=data.get('status', 'frio'),
        source=data.get('source', 'whatsapp'),
        notes=data.get('notes', ''),
        budget=data.get('budget', ''),
        location=data.get('location', ''),
    )
    db.session.add(lead)
    db.session.commit()

    # Notify via Resend
    try:
        send_vm_email(
            f"🆕 Nuevo lead: {lead.name}",
            f"<h2>Nuevo lead registrado</h2>"
            f"<p><strong>Nombre:</strong> {lead.name}<br>"
            f"<strong>Negocio:</strong> {lead.business or '—'}<br>"
            f"<strong>Teléfono:</strong> {lead.phone or '—'}<br>"
            f"<strong>Email:</strong> {lead.email or '—'}<br>"
            f"<strong>Fuente:</strong> {lead.source}<br>"
            f"<strong>Presupuesto:</strong> {lead.budget or '—'}<br>"
            f"<strong>Ubicación:</strong> {lead.location or '—'}</p>"
            f"<p>Ingresa al CRM para dar seguimiento.</p>"
        )
    except Exception as e:
        print(f"[Resend] notify error: {e}")

    return jsonify({'lead': lead.to_dict(), 'success': True}), 201


@app.route('/api/leads/<int:lead_id>', methods=['GET'])
@login_required
def api_get_lead(lead_id):
    lead = db.session.get(Lead, lead_id)
    if not lead:
        return jsonify({'error': 'not found'}), 404

    data = lead.to_dict()
    data['interactions'] = [i.to_dict() for i in lead.interactions.all()]
    data['appointments'] = [a.to_dict() for a in lead.appointments.all()]
    return jsonify(data)


@app.route('/api/leads/<int:lead_id>', methods=['PUT'])
@login_required
def api_update_lead(lead_id):
    lead = db.session.get(Lead, lead_id)
    if not lead:
        return jsonify({'error': 'not found'}), 404

    data = request.get_json()
    for field in ['name', 'business', 'phone', 'email', 'status',
                  'source', 'notes', 'budget', 'location', 'score']:
        if field in data:
            setattr(lead, field, data[field])

    lead.updated_at = rd_now()
    db.session.commit()
    return jsonify({'lead': lead.to_dict(), 'success': True})


@app.route('/api/leads/<int:lead_id>', methods=['DELETE'])
@login_required
def api_delete_lead(lead_id):
    lead = db.session.get(Lead, lead_id)
    if not lead:
        return jsonify({'error': 'not found'}), 404
    db.session.delete(lead)
    db.session.commit()
    return jsonify({'success': True})


# ============================================================
# API — Interactions
# ============================================================

@app.route('/api/leads/<int:lead_id>/interactions', methods=['GET'])
@login_required
def api_get_interactions(lead_id):
    limit = request.args.get('limit', 50, type=int)
    interactions = Interaction.query.filter_by(lead_id=lead_id)\
        .order_by(Interaction.created_at.desc()).limit(limit).all()
    return jsonify({'interactions': [i.to_dict() for i in interactions]})


@app.route('/api/leads/<int:lead_id>/interactions', methods=['POST'])
@login_required
def api_add_interaction(lead_id):
    lead = db.session.get(Lead, lead_id)
    if not lead:
        return jsonify({'error': 'not found'}), 404

    data = request.get_json()
    interaction = Interaction(
        lead_id=lead_id,
        direction=data.get('direction', 'in'),
        message=data.get('message', ''),
        channel=data.get('channel', 'whatsapp'),
    )
    lead.last_contact = rd_now()
    db.session.add(interaction)
    db.session.commit()
    return jsonify({'interaction': interaction.to_dict(), 'success': True}), 201


# ============================================================
# API — Appointments
# ============================================================

@app.route('/api/appointments', methods=['GET'])
@login_required
def api_get_appointments():
    date_from = request.args.get('from')
    date_to = request.args.get('to')

    query = Appointment.query

    if date_from:
        query = query.filter(Appointment.appt_datetime >= datetime.fromisoformat(date_from))
    if date_to:
        query = query.filter(Appointment.appt_datetime <= datetime.fromisoformat(date_to))

    appointments = query.order_by(Appointment.appt_datetime).all()
    return jsonify({
        'appointments': [a.to_dict() for a in appointments],
        'total': len(appointments)
    })


@app.route('/api/appointments', methods=['POST'])
@login_required
def api_create_appointment():
    data = request.get_json()
    if not data or not data.get('lead_id') or not data.get('appt_datetime'):
        return jsonify({'error': 'lead_id and appt_datetime required'}), 400

    appointment = Appointment(
        lead_id=data['lead_id'],
        appt_datetime=datetime.fromisoformat(data['appt_datetime']),
        duration_minutes=data.get('duration_minutes', 30),
        notes=data.get('notes', ''),
        status=data.get('status', 'pendiente'),
    )
    db.session.add(appointment)
    db.session.commit()
    return jsonify({'appointment': appointment.to_dict(), 'success': True}), 201


@app.route('/api/appointments/<int:appt_id>', methods=['PUT'])
@login_required
def api_update_appointment(appt_id):
    appointment = db.session.get(Appointment, appt_id)
    if not appointment:
        return jsonify({'error': 'not found'}), 404

    data = request.get_json()
    for field in ['appt_datetime', 'duration_minutes', 'notes', 'status']:
        if field in data:
            if field == 'appt_datetime':
                setattr(appointment, field, datetime.fromisoformat(data[field]))
            else:
                setattr(appointment, field, data[field])

    db.session.commit()
    return jsonify({'appointment': appointment.to_dict(), 'success': True})


# ============================================================
# API — Reports & Export
# ============================================================

@app.route('/api/report', methods=['GET'])
@login_required
def api_get_report():
    days = request.args.get('days', 30, type=int)
    lead_only_filter = request.args.get('lead_only', '').lower() == 'true'
    include_charts = request.args.get('charts', 'true').lower() != 'false'

    now = rd_now()
    cutoff = now - timedelta(days=days) if days > 0 else datetime(2020, 1, 1)

    # Load report config
    import json
    try:
        with open(os.path.join(os.path.dirname(__file__), '..', 'config', 'report_config.json')) as f:
            config = json.load(f)
    except:
        config = {"clinica": {"nombre": "Verano Media RD"}}

    # Leads in period
    leads_query = Lead.query.filter(Lead.created_at >= cutoff).order_by(Lead.created_at.desc())
    leads = leads_query.all()

    # Stats
    total = len(leads)
    by_status = {}
    for s in ['frio', 'tibio', 'caliente', 'cerrado']:
        by_status[s] = sum(1 for l in leads if l.status == s)

    # Appointments in period
    appts = Appointment.query.filter(Appointment.appt_datetime >= cutoff).order_by(Appointment.appt_datetime).all()

    # Daily breakdown for chart
    from collections import Counter
    daily_counts = Counter()
    for l in leads:
        day_key = l.created_at.strftime('%Y-%m-%d')
        daily_counts[day_key] += 1

    # Sort daily data
    daily_sorted = sorted(daily_counts.items())
    daily_labels = [d[0][5:] for d in daily_sorted]  # MM-DD
    daily_values = [d[1] for d in daily_sorted]

    # Score distribution
    score_ranges = {'0-3': 0, '4-6': 0, '7-8': 0, '9-10': 0}
    for l in leads:
        s = l.score or 0
        if s <= 3: score_ranges['0-3'] += 1
        elif s <= 6: score_ranges['4-6'] += 1
        elif s <= 8: score_ranges['7-8'] += 1
        else: score_ranges['9-10'] += 1

    # Lead detail rows
    lead_rows = []
    for l in leads:
        lead_rows.append({
            'nombre': l.name,
            'negocio': l.business,
            'telefono': l.phone,
            'email': l.email,
            'estado': l.status,
            'score': l.score or 0,
            'presupuesto': l.budget,
            'creado': l.created_at.strftime('%d/%m/%Y'),
        })

    return jsonify({
        'config': config,
        'periodo': {'dias': days, 'desde': cutoff.isoformat(), 'hasta': now.isoformat()},
        'resumen': {
            'total': total,
            'por_estado': by_status,
            'tasa_calientes': round((by_status.get('caliente', 0) / max(total, 1)) * 100),
            'tasa_cerrados': round((by_status.get('cerrado', 0) / max(total, 1)) * 100),
            'citas': len(appts),
        },
        'daily': {'labels': daily_labels, 'values': daily_values},
        'score_dist': score_ranges,
        'leads': lead_rows if not lead_only_filter else [],
        'appointments': [
            {'lead': a.lead.name if a.lead else '', 'fecha': a.appt_datetime.strftime('%d/%m/%Y %H:%M'),
             'duracion': a.duration_minutes, 'estado': a.status}
            for a in appts
        ],
        'generated_at': now.isoformat(),
    })


# ============================================================
# API — Export CSV
# ============================================================

@app.route('/api/report/csv', methods=['GET'])
@login_required
def api_export_csv():
    days = request.args.get('days', 30, type=int)
    cutoff = rd_now() - timedelta(days=days) if days > 0 else datetime(2020, 1, 1)
    leads = Lead.query.filter(Lead.created_at >= cutoff).order_by(Lead.created_at.desc()).all()

    import csv, io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Nombre', 'Negocio', 'Telefono', 'Email', 'Estado', 'Score', 'Presupuesto', 'Creado'])
    for l in leads:
        writer.writerow([l.name, l.business, l.phone, l.email, l.status, l.score or 0, l.budget,
                        l.created_at.strftime('%d/%m/%Y')])

    return output.getvalue(), 200, {
        'Content-Type': 'text/csv; charset=utf-8',
        'Content-Disposition': 'attachment; filename="vm_crm_report.csv"',
    }


# ============================================================
# API — Export Markdown
# ============================================================

@app.route('/api/report/md', methods=['GET'])
@login_required
def api_export_md():
    days = request.args.get('days', 30, type=int)
    cutoff = rd_now() - timedelta(days=days) if days > 0 else datetime(2020, 1, 1)
    leads = Lead.query.filter(Lead.created_at >= cutoff).order_by(Lead.created_at.desc()).all()

    try:
        with open(os.path.join(os.path.dirname(__file__), '..', 'config', 'report_config.json')) as f:
            config = json.load(f)
    except:
        config = {"clinica": {"nombre": "Verano Media RD"}}

    clinica = config.get('clinica', {})
    total = len(leads)
    by_status = {}
    for s in ['frio', 'tibio', 'caliente', 'cerrado']:
        by_status[s] = sum(1 for l in leads if l.status == s)
    calientes = by_status.get('caliente', 0)
    cerrados = by_status.get('cerrado', 0)

    md = []
    md.append(f'# {clinica.get("nombre", "Verano Media RD")}')
    md.append(f'*{clinica.get("eslogan", "")}*')
    md.append(f'')
    md.append(f'**Reporte generado:** {rd_now().strftime("%d/%m/%Y %H:%M")}')
    md.append(f'**Periodo:** {days} dias')
    md.append(f'')
    md.append(f'## Resumen')
    md.append(f'')
    md.append(f'| Métrica | Valor |')
    md.append(f'|---|---|')
    md.append(f'| Total Leads | {total} |')
    md.append(f'| Calientes | {calientes} ({round(calientes/max(total,1)*100)}%) |')
    md.append(f'| Cerrados | {cerrados} ({round(cerrados/max(total,1)*100)}%) |')
    md.append(f'')
    md.append(f'## Leads')
    md.append(f'')
    md.append(f'| Nombre | Negocio | Estado | Score |')
    md.append(f'|---|---|---|---|')
    for l in leads:
        md.append(f'| {l.name} | {l.business or "-"} | {l.status} | {l.score or 0}/10 |')
    md.append(f'')
    md.append(f'---')
    md.append(f'*Generado por VM CRM — {rd_now().strftime("%d/%m/%Y %H:%M")}*')

    return '\n'.join(md), 200, {
        'Content-Type': 'text/markdown; charset=utf-8',
        'Content-Disposition': 'attachment; filename="vm_crm_report.md"',
    }


@app.route('/api/report/config', methods=['GET', 'PUT'])
@login_required
def api_report_config():
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'report_config.json')
    import json

    if request.method == 'PUT':
        data = request.get_json()
        if data:
            with open(config_path, 'w') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return jsonify({'success': True})
        return jsonify({'error': 'no data'}), 400

    try:
        with open(config_path) as f:
            return jsonify(json.load(f))
    except:
        return jsonify({"clinica": {"nombre": "Verano Media RD"}})

@app.route('/api/stats', methods=['GET'])
@login_required
def api_get_stats():
    now = rd_now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())

    total_leads = Lead.query.count()
    today_leads = Lead.query.filter(Lead.created_at >= today_start).count()
    week_leads = Lead.query.filter(Lead.created_at >= week_start).count()

    by_status = {}
    for s in ['frio', 'tibio', 'caliente', 'cerrado']:
        by_status[s] = Lead.query.filter_by(status=s).count()

    today_appts = Appointment.query.filter(
        Appointment.appt_datetime >= today_start,
        Appointment.appt_datetime < today_start + timedelta(days=1)
    ).count()

    upcoming_appts = Appointment.query.filter(
        Appointment.appt_datetime >= now,
        Appointment.status.in_(['pendiente', 'confirmada'])
    ).count()

    return jsonify({
        'total_leads': total_leads,
        'today_leads': today_leads,
        'week_leads': week_leads,
        'by_status': by_status,
        'today_appointments': today_appts,
        'upcoming_appointments': upcoming_appts,
    })


# ============================================================
# API — María Integration (no auth — called from Hermes)
# ============================================================

@app.route('/api/maria/lead', methods=['POST'])
def maria_create_lead():
    """Endpoint called by María (Hermes) to save a lead.
    Uses a shared secret for auth instead of session cookies."""
    auth = request.headers.get('X-VM-Secret', '')
    expected = os.environ.get('VM_MARIA_SECRET', 'vm-maria-secret-default')

    if auth != expected:
        return jsonify({'error': 'unauthorized'}), 401

    data = request.get_json()
    if not data or not data.get('name'):
        return jsonify({'error': 'name is required'}), 400

    lead = Lead(
        name=data['name'].strip(),
        business=data.get('business', '').strip(),
        phone=data.get('phone', '').strip(),
        email=data.get('email', '').strip(),
        status=data.get('status', 'frio'),
        source='whatsapp',
        notes=data.get('notes', ''),
        budget=data.get('budget', ''),
    )

    score = calculate_lead_score(lead)
    lead.score = score

    # Auto-classify
    if score >= 7:
        lead.status = 'caliente'
    elif score >= 4:
        lead.status = 'tibio'
    else:
        lead.status = 'frio'

    # Auto-schedule followup
    if lead.status == 'caliente':
        lead.next_followup = rd_now() + timedelta(hours=2)
    elif lead.status == 'tibio':
        lead.next_followup = rd_now() + timedelta(days=1)
    else:
        lead.next_followup = rd_now() + timedelta(days=3)

    db.session.add(lead)
    db.session.commit()

    # Add initial interaction
    if data.get('first_message'):
        interaction = Interaction(
            lead_id=lead.id,
            direction='in',
            message=data['first_message'],
            channel='whatsapp',
        )
        db.session.add(interaction)
        db.session.commit()

    return jsonify({'lead': lead.to_dict(), 'success': True}), 201


def calculate_lead_score(lead):
    """Score a lead 0-10 based on available data"""
    score = 0

    # Has business name
    if lead.business:
        score += 2
        # Keywords that indicate higher value
        biz_lower = lead.business.lower()
        if any(k in biz_lower for k in ['clinic', 'dental', 'odont', 'doctor',
                                          'inmobili', 'real estate', 'agency',
                                          'corp', 'group']):
            score += 1

    # Has phone
    if lead.phone:
        score += 2

    # Has email
    if lead.email:
        score += 1

    # Has budget mentioned
    if lead.budget:
        score += 2

    # Notes indicate engagement
    if lead.notes and len(lead.notes) > 10:
        score += 1

    # Source quality
    if lead.source == 'whatsapp':
        score += 1

    return min(score, 10)


# ============================================================
# Static files
# ============================================================

@app.route('/static/<path:path>')
def serve_static(path):
    return send_from_directory(
        os.path.join(os.path.dirname(__file__), '..', 'frontend', 'static'),
        path
    )


# ============================================================
# Run
# ============================================================

if __name__ == '__main__':
    port = int(os.environ.get('CRM_PORT', 8765))
    host = os.environ.get('CRM_HOST', '0.0.0.0')
    debug = os.environ.get('CRM_DEBUG', 'false').lower() == 'true'

    print(f'🚀 VM CRM Dashboard')
    print(f'   Host: {host}')
    print(f'   Port: {port}')
    print(f'   DB:   {os.path.join(os.path.dirname(__file__), "..", "data", "vm_crm.db")}')
    print(f'')
    print(f'   📱 Open in browser: http://localhost:{port}')
    print(f'   🔑 Login: admin / vm2026')
    print(f'')

    app.run(host=host, port=port, debug=debug)
