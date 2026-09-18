"""CRM Database models — SQLite/PostgreSQL

Mejoras adaptadas de trycompai/crm:
1. Sistema de evidencia (VERIFIED/PROBABLE/POSSIBLE) para datos de leads
2. Cola de trabajo con leasing (AgentTask con dueAt y leasedUntil)
3. Soporte para agente durable (tasks que se ejecutan async)
"""
import os
from datetime import datetime, date, timedelta
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

# ──────────────────────────────────────────────────────────────
# BANDAS DE EVIDENCIA (adaptado de trycompai/crm)
# ──────────────────────────────────────────────────────────────
EVIDENCE_VERIFIED = 'verified'    # Fuente confirmada (firma email, llamada)
EVIDENCE_PROBABLE = 'probable'    # Fuerte pero no confirmada (web, directorio)
EVIDENCE_POSSIBLE = 'possible'    # Débil, necesita confirmación humana

EVIDENCE_BANDS = {
    EVIDENCE_VERIFIED: {'weight': 3, 'label': 'Verificado', 'color': '#10b981'},
    EVIDENCE_PROBABLE: {'weight': 2, 'label': 'Probable', 'color': '#f59e0b'},
    EVIDENCE_POSSIBLE: {'weight': 1, 'label': 'Posible', 'color': '#6b7280'},
}


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Lead(db.Model):
    __tablename__ = 'leads'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    business = db.Column(db.String(200), default='')
    phone = db.Column(db.String(50), default='')
    email = db.Column(db.String(200), default='')
    status = db.Column(db.String(20), default='frio')
    source = db.Column(db.String(50), default='whatsapp')
    notes = db.Column(db.Text, default='')
    budget = db.Column(db.String(50), default='')
    location = db.Column(db.String(100), default='')
    score = db.Column(db.Integer, default=0)
    next_followup = db.Column(db.DateTime, nullable=True)
    last_contact = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Campos de prospección
    website = db.Column(db.String(300), default='')
    google_business = db.Column(db.Boolean, default=False)
    whatsapp_visible = db.Column(db.Boolean, default=False)
    google_rating = db.Column(db.Float, nullable=True)
    num_reviews = db.Column(db.Integer, default=0)
    categoria = db.Column(db.String(50), default='')
    ciudad = db.Column(db.String(100), default='')

    interactions = db.relationship('Interaction', backref='lead', lazy='dynamic',
                                    cascade='all, delete-orphan',
                                    order_by='Interaction.created_at.desc()')
    appointments = db.relationship('Appointment', backref='lead', lazy='dynamic',
                                    cascade='all, delete-orphan',
                                    order_by='Appointment.appt_datetime')
    evidence = db.relationship('LeadEvidence', backref='lead', lazy='dynamic',
                               cascade='all, delete-orphan',
                               order_by='LeadEvidence.created_at.desc()')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'business': self.business,
            'phone': self.phone,
            'email': self.email,
            'status': self.status,
            'source': self.source,
            'notes': self.notes,
            'budget': self.budget,
            'location': self.location,
            'score': self.score,
            'website': self.website,
            'google_business': self.google_business,
            'whatsapp_visible': self.whatsapp_visible,
            'google_rating': self.google_rating,
            'num_reviews': self.num_reviews,
            'categoria': self.categoria,
            'ciudad': self.ciudad,
            'next_followup': self.next_followup.isoformat() if self.next_followup else None,
            'last_contact': self.last_contact.isoformat() if self.last_contact else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'evidence_count': self.evidence.count(),
            'evidence_verified': self.evidence.filter_by(band=EVIDENCE_VERIFIED).count(),
            'evidence_probable': self.evidence.filter_by(band=EVIDENCE_PROBABLE).count(),
            'evidence_possible': self.evidence.filter_by(band=EVIDENCE_POSSIBLE).count(),
        }

    def status_color(self):
        colors = {
            'frio': '#6b7280',
            'tibio': '#f59e0b',
            'caliente': '#ef4444',
            'cerrado': '#10b981'
        }
        return colors.get(self.status, '#6b7280')

    def status_emoji(self):
        emojis = {
            'frio': '❄️',
            'tibio': '🔥',
            'caliente': '💥',
            'cerrado': '✅'
        }
        return emojis.get(self.status, '❄️')

    def evidence_score(self):
        """Calcula score de evidencia: suma ponderada por banda"""
        total = 0
        for ev in self.evidence:
            band = EVIDENCE_BANDS.get(ev.band, {})
            total += band.get('weight', 0)
        return total


class LeadEvidence(db.Model):
    """Sistema de evidencia adaptado de trycompai/crm.
    Nada se adivina — cada dato tiene una fuente y un nivel de confianza."""
    __tablename__ = 'lead_evidence'

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('leads.id'), nullable=False)
    field = db.Column(db.String(50), nullable=False)  # phone, email, website, etc.
    value = db.Column(db.Text, nullable=False)         # el dato observado
    band = db.Column(db.String(20), default=EVIDENCE_POSSIBLE)  # verified/probable/possible
    source = db.Column(db.String(200), default='')     # URL, API, llamada, email
    source_type = db.Column(db.String(50), default='')  # google_maps, web, email_signature, manual
    observed_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    confirmed_by = db.Column(db.String(100), default='')  # quién confirmó (humano/IA)

    def to_dict(self):
        band_info = EVIDENCE_BANDS.get(self.band, {})
        return {
            'id': self.id,
            'lead_id': self.lead_id,
            'field': self.field,
            'value': self.value,
            'band': self.band,
            'band_label': band_info.get('label', ''),
            'band_color': band_info.get('color', ''),
            'source': self.source,
            'source_type': self.source_type,
            'observed_at': self.observed_at.isoformat() if self.observed_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'confirmed_by': self.confirmed_by,
        }


class Interaction(db.Model):
    __tablename__ = 'interactions'

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('leads.id'), nullable=False)
    direction = db.Column(db.String(10), nullable=False)  # inbound / outbound
    message = db.Column(db.Text, nullable=False)
    channel = db.Column(db.String(20), default='whatsapp')  # whatsapp / web
    channel_id = db.Column(db.String(100), default='')  # JID (WhatsApp) o UUID (web)
    source_phone = db.Column(db.String(50), default='')  # teléfono del cliente
    ai_response = db.Column(db.Text, default='')  # lo que respondió María/Valentina
    ai_summary = db.Column(db.Text, default='')  # resumen automático de la conversación
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'lead_id': self.lead_id,
            'direction': self.direction,
            'message': self.message[:300],
            'ai_response': self.ai_response[:300] if self.ai_response else '',
            'channel': self.channel,
            'channel_id': self.channel_id or '',
            'source_phone': self.source_phone or '',
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class Appointment(db.Model):
    __tablename__ = 'appointments'

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('leads.id'), nullable=False)
    appt_datetime = db.Column(db.DateTime, nullable=False)
    duration_minutes = db.Column(db.Integer, default=30)
    notes = db.Column(db.Text, default='')
    status = db.Column(db.String(20), default='pendiente')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'lead_id': self.lead_id,
            'lead_name': self.lead.name if self.lead else '',
            'datetime': self.appt_datetime.isoformat() if self.appt_datetime else None,
            'duration_minutes': self.duration_minutes,
            'notes': self.notes,
            'status': self.status,
        }


# ──────────────────────────────────────────────────────────────
# COLA DE TRABAJO CON LEASING (adaptado de trycompai/crm)
# Permite que un agente durable tome tareas, las procese y
# las libere o marque como completadas
# ──────────────────────────────────────────────────────────────

TASK_PENDING = 'pending'
TASK_LEASED = 'leased'
TASK_DONE = 'done'
TASK_FAILED = 'failed'

class AgentTask(db.Model):
    """Cola de trabajo para el agente durable.
    Adaptado del patrón FOR UPDATE SKIP LOCKED de trycompai/crm."""
    __tablename__ = 'agent_tasks'

    id = db.Column(db.Integer, primary_key=True)
    task_type = db.Column(db.String(50), nullable=False)  # research_lead, enrich_company, follow_up, etc.
    lead_id = db.Column(db.Integer, db.ForeignKey('leads.id'), nullable=True)
    payload = db.Column(db.Text, default='')  # JSON con parámetros de la tarea
    status = db.Column(db.String(20), default=TASK_PENDING)

    # Leasing — el agente toma la tarea por un tiempo limitado
    leased_at = db.Column(db.DateTime, nullable=True)
    leased_until = db.Column(db.DateTime, nullable=True)
    leased_by = db.Column(db.String(100), default='')  # identificador del agente

    # Ejecución
    due_at = db.Column(db.DateTime, nullable=True)  # cuándo debe ejecutarse
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    # Resultado
    result = db.Column(db.Text, default='')  # JSON con el resultado
    error = db.Column(db.Text, default='')
    retry_count = db.Column(db.Integer, default=0)
    max_retries = db.Column(db.Integer, default=3)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'task_type': self.task_type,
            'lead_id': self.lead_id,
            'payload': self.payload,
            'status': self.status,
            'leased_at': self.leased_at.isoformat() if self.leased_at else None,
            'leased_until': self.leased_until.isoformat() if self.leased_until else None,
            'leased_by': self.leased_by,
            'due_at': self.due_at.isoformat() if self.due_at else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'result': self.result[:500] if self.result else '',
            'error': self.error[:500] if self.error else '',
            'retry_count': self.retry_count,
            'max_retries': self.max_retries,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    @staticmethod
    def lease_next(agent_id, lease_minutes=30):
        """Toma la siguiente tarea disponible (patrón skip-locked).
        Retorna la tarea o None si no hay disponibles."""
        now = datetime.utcnow()
        # Buscar tareas pendientes o con lease expirado
        task = AgentTask.query.filter(
            db.or_(
                AgentTask.status == TASK_PENDING,
                db.and_(AgentTask.status == TASK_LEASED, AgentTask.leased_until < now)
            ),
            db.or_(AgentTask.due_at.is_(None), AgentTask.due_at <= now)
        ).order_by(AgentTask.created_at.asc()).first()

        if task:
            task.status = TASK_LEASED
            task.leased_at = now
            task.leased_until = now + timedelta(minutes=lease_minutes)
            task.leased_by = agent_id
            task.started_at = now
            if task.retry_count == 0:
                task.started_at = now
            db.session.commit()
        return task

    @staticmethod
    def create(task_type, lead_id=None, payload='', due_at=None, priority=0):
        """Crea una nueva tarea en la cola."""
        task = AgentTask(
            task_type=task_type,
            lead_id=lead_id,
            payload=payload,
            due_at=due_at,
        )
        db.session.add(task)
        db.session.commit()
        return task

    @staticmethod
    def complete(task_id, result=''):
        """Marca una tarea como completada."""
        task = AgentTask.query.get(task_id)
        if task:
            task.status = TASK_DONE
            task.result = result
            task.completed_at = datetime.utcnow()
            db.session.commit()
        return task

    @staticmethod
    def fail(task_id, error=''):
        """Marca una tarea como fallida o incrementa retry."""
        task = AgentTask.query.get(task_id)
        if task:
            task.retry_count += 1
            if task.retry_count >= task.max_retries:
                task.status = TASK_FAILED
            else:
                task.status = TASK_PENDING  # vuelve a la cola
            task.error = error
            task.leased_at = None
            task.leased_until = None
            task.leased_by = ''
            db.session.commit()
        return task


def init_db(app):
    """Initialize database"""
    database_url = os.environ.get('DATABASE_URL') or ''
    if database_url and database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    if not database_url:
        if os.environ.get('FLY_APP_NAME'):
            # En Fly.io sin DATABASE_URL: usar SQLite persistente en /data
            data_dir = '/data'
            os.makedirs(data_dir, exist_ok=True)
            database_url = f'sqlite:///{data_dir}/vm_crm.db'
        else:
            database_url = f'sqlite:///{os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "vm_crm.db")}'
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.environ.get('CRM_SECRET_KEY', 'vm-crm-prod-key-2026')

    db.init_app(app)

    with app.app_context():
        db.create_all()
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(username='admin', is_admin=True)
            admin.set_password('vm2026')
            db.session.add(admin)
            db.session.commit()
