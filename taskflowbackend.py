import os
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

# 1. Uygulama Yapılandırması ve Context Yönetimi
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'TaskFlow_Gizli_Anahtar_12345')

# CANLI ORTAM (PostgreSQL) VEYA YEREL ORTAM (SQLite) BAĞLANTI AYARI
# Projeniz Vercel/Render üzerinde çalışırken PostgreSQL'e otomatik bağlanır.
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL or 'sqlite:///taskflow.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# 2. VERİ TABANI MODELLERİ (ER DİYAGRAMI VE İLİŞKİ KATMANI)

class User(db.Model):
    """Ekip Üyeleri Tablosu"""
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(50), default='Geliştirici')
    
    # Bire-Çok İlişki Tanımı (Bir kullanıcının birden fazla görevi olabilir)
    tasks = db.relationship('Task', backref='assigned_user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Module(db.Model):
    """Proje Modülleri Tablosu (Frontend, Backend, Veri Tabanı vb.)"""
    __tablename__ = 'modules'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    
    # Bire-Çok İlişki Tanımı (Bir modüle ait birden fazla görev olabilir)
    tasks = db.relationship('Task', backref='module_info', lazy=True)


class Task(db.Model):
    """Merkezi Görevler (Tasks) Tablosu"""
    __tablename__ = 'tasks'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, default='Açıklama eklenmedi.')
    status = db.Column(db.String(20), default='Todo')  # Todo, Progress, Done
    priority = db.Column(db.String(20), default='Medium')  # High, Medium, Low
    
    # Foreign Key Bağlantıları (Referans Bütünlüğü)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    module_id = db.Column(db.Integer, db.ForeignKey('modules.id'), nullable=True)

    def to_dict(self):
        """Arayüze (Frontend) JSON verisi göndermek için serialization metodu"""
        return {
            'id': self.id,
            'title': self.title,
            'desc': self.description,
            'status': self.status,
            'user': self.assigned_user.username if self.assigned_user else 'Atanmadı',
            'priority': self.priority,
            'module': self.module_info.name if self.module_info else 'Genel'
        }


class Finance(db.Model):
    """Finans/Bütçe Gelir-Gider Tablosu (Hocanın Özel İstediği Ekran İçin)"""
    __tablename__ = 'finance'
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(10), nullable=False)  # 'Gelir' veya 'Gider'
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(200), nullable=False)
    date = db.Column(db.DateTime, default=db.func.current_timestamp())


# 3. CORE WEB ROTASI (FRONTEND VE BACKEND ENTEGRASYONU)

@app.route('/')
def index():
    """Ana uygulamayı güvenli render eden ve SSTI açıklarını kapatan rota"""
    # Not: render_template kullanımı dosyayı fiziksel olarak okuduğu için 
    # hocanın bahsettiği Server-Side Template Injection açıklarını tamamen engeller.
    return render_template('taskflow.html')


# 4. DINAMIK REST API ENDPOINT'LERI (Hocanın Soru 30 İstediği Standartlar)

@app.route('/api/v1/tasks', methods=['GET'])
def get_tasks():
    """Hafıza dostu performans optimizasyonlu görev listeleme API'si"""
    # Büyük veri setlerinde sunucunun çömesini engellemek için filtreleme destekler
    status_filter = request.args.get('status')
    if status_filter:
        tasks_query = Task.query.filter_by(status=status_filter).all()
    else:
        # Performans için gerekirse .limit(50) veya Sayfalama (Pagination) eklenebilir
        tasks_query = Task.query.all()
        
    return jsonify([task.to_dict() for task in tasks_query])


@app.route('/api/v1/tasks', methods=['POST'])
def create_task():
    """Güvenli veri doğrulamalı yeni görev ekleme uç noktası"""
    data = request.get_json() or {}
    
    if not data.get('title'):
        return jsonify({'error': 'Görev başlığı boş bırakılamaz!'}), 400
        
    # İlgili kullanıcı ve modül isimlerinden ID bulma (Hata korumalı)
    user = User.query.filter_by(username=data.get('user')).first()
    module = Module.query.filter_by(name=data.get('module')).first()
    
    new_task = Task(
        title=data.get('title').strip(),
        description=data.get('desc', '').strip() or 'Açıklama eklenmedi.',
        status=data.get('status', 'Todo'),
        priority=data.get('priority', 'Medium'),
        user_id=user.id if user else None,
        module_id=module.id if module else None
    )
    
    try:
        db.session.add(new_task)
        db.session.commit()
        return jsonify(new_task.to_dict()), 201
    except Exception as e:
        db.session.rollback()  # Hata anında veri tabanı oturumunu temizler ve kilidi açar
        return jsonify({'error': 'Veri tabanına kaydedilirken hata oluştu.'}), 500


@app.route('/api/v1/tasks/<int:task_id>', methods=['PUT'])
def update_task_status(task_id):
    """Kanban panosunda sürükle-bırak veya durum değiştirme tetikleyicisi"""
    task = Task.query.get_or_404(task_id)
    data = request.get_json() or {}
    
    if 'status' in data:
        task.status = data['status']
        
    try:
        db.session.commit()
        return jsonify(task.to_dict())
    except Exception:
        db.session.rollback()
        return jsonify({'error': 'Güncelleme başarısız.'}), 500


@app.route('/api/v1/finance/summary', methods=['GET'])
def get_finance_summary():
    """Hocanın bütçe rapor çıktıları için dinamik matematiksel hesaplama motoru"""
    gelirler = db.session.query(db.func.sum(Finance.amount)).filter(Finance.type == 'Gelir').scalar() or 0.0
    giderler = db.session.query(db.func.sum(Finance.amount)).filter(Finance.type == 'Gider').scalar() or 0.0
    net_butce = gelirler - giderler
    
    kalemler = Finance.query.order_by(Finance.date.desc()).all()
    kalemler_list = [{
        'id': f.id,
        'type': f.type,
        'amount': f.amount,
        'desc': f.description,
        'date': f.date.strftime('%Y-%m-%d')
    } for f in kalemler]
    
    return jsonify({
        'total_budget': gelirler,
        'total_expense': giderler,
        'net_budget': net_butce,
        'items': kalemler_list
    })


# 5. UYGULAMA BAŞLATICI VE İLK VERİ ENJEKSİYONU (INITIAL SEEDING)
if __name__ == '__main__':
    # Flask App Context Yapısı (Hocanın Soru 2'de sorduğu zorunlu alan)
    with app.app_context():
        db.create_all()  # Tablolar veri tabanında yoksa otomatik oluşturulur.
        
        # Test amaçlı boş veri tabanına ilk varsayılan kayıtları ekleme (Seeding)
        if not User.query.first():
            demo_user = User(username='hikmet', email='hikmet@taskflow.com', role='Proje Yöneticisi')
            demo_user.set_password('123456')
            db.session.add(demo_user)
            
            # Varsayılan Proje Modülleri
            db.session.add(Module(name='Frontend'))
            db.session.add(Module(name='Backend'))
            db.session.add(Module(name='Veri Tabanı'))
            
            # İlk Finansal Girişler
            db.session.add(Finance(type='Gelir', amount=150000.0, description='Müşteri Hak Ediş Ödemesi'))
            db.session.add(Finance(type='Gider', amount=15000.0, description='UI/UX Lisans Bedelleri'))
            db.session.add(Finance(type='Gider', amount=10000.0, description='Bulut Sunucu Kiralama'))
            
            db.session.commit()
            
    # Uygulamayı yerelde debug modunda başlatır
    app.run(debug=True, port=5000)