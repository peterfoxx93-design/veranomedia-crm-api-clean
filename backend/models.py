"""CRM Database models — SQLite/PostgreSQL"""
import os
from datetime import datetime, date
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


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

    interactions = db.relationship('Interaction', backref='lead', lazy='dynamic',
                                    cascade='all, delete-orphan',
                                    order_by='Interaction.created_at.desc()')
    appointments = db.relationship('Appointment', backref='lead', lazy='dynamic',
                                    cascade='all, delete-orphan',
                                    order_by='Appointment.appt_datetime')

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
            'next_followup': self.next_followup.isoformat() if self.next_followup else None,
            'last_contact': self.last_contact.isoformat() if self.last_contact else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
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


def init_db(app):
    """Initialize database"""
    database_url = os.environ.get('DATABASE_URL') or ''
    if database_url and database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    if not database_url:
        if os.environ.get('FLY_APP_NAME'):
            database_url = 'sqlite:///:memory:'
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
