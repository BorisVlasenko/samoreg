from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
import sqlite3
import hashlib
import secrets
import os
from datetime import datetime, timedelta
from werkzeug.security import check_password_hash, generate_password_hash
import json

app = Flask(__name__)
app.secret_key = os.environ.get('SESSION_SECRET', secrets.token_hex(16))
CORS(app, supports_credentials=True)

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')
ADMIN_PASSWORD_HASH = generate_password_hash(ADMIN_PASSWORD)
ADMIN_URL_SECRET = os.environ.get('ADMIN_URL_SECRET', 'admin_secret_change_me')
ADMIN_URL_HASH = hashlib.sha256(ADMIN_URL_SECRET.encode()).hexdigest()[:16]

DATABASE = 'events.db'

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            event_date DATE NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            slot_duration INTEGER NOT NULL,
            breaks TEXT,
            registration_open INTEGER DEFAULT 1,
            event_hash TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS registrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            child_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            slot_time TEXT NOT NULL,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (event_id) REFERENCES events (id),
            UNIQUE(event_id, slot_time)
        )
    ''')
    
    conn.commit()
    conn.close()

def generate_event_hash(title, event_date):
    data = f"{title}_{event_date}_{secrets.token_hex(8)}"
    return hashlib.sha256(data.encode()).hexdigest()[:16]

def generate_time_slots(start_time, end_time, slot_duration, breaks):
    slots = []
    start_dt = datetime.strptime(start_time, "%H:%M")
    end_dt = datetime.strptime(end_time, "%H:%M")
    
    break_periods = []
    if breaks:
        for break_item in breaks:
            break_start = datetime.strptime(break_item['start'], "%H:%M")
            break_end = datetime.strptime(break_item['end'], "%H:%M")
            break_periods.append((break_start, break_end))
    
    current_time = start_dt
    while current_time < end_dt:
        is_break = False
        for break_start, break_end in break_periods:
            if break_start <= current_time < break_end:
                is_break = True
                break
        
        if not is_break:
            slots.append(current_time.strftime("%H:%M"))
        
        current_time += timedelta(minutes=slot_duration)
    
    return slots

def capitalize_name(name):
    parts = name.strip().split()
    return ' '.join([part.capitalize() for part in parts])

@app.route(f'/admin/{ADMIN_URL_HASH}')
def admin_page():
    return render_template('admin.html', admin_hash=ADMIN_URL_HASH)

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.json
    password = data.get('password')
    
    if check_password_hash(ADMIN_PASSWORD_HASH, password):
        session['admin_logged_in'] = True
        return jsonify({'success': True})
    
    return jsonify({'success': False, 'message': 'Неверный пароль'}), 401

@app.route('/api/admin/events', methods=['GET'])
def get_admin_events():
    if not session.get('admin_logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    today = datetime.now().strftime('%Y-%m-%d')
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT e.*, COUNT(r.id) as registrations_count
        FROM events e
        LEFT JOIN registrations r ON e.id = r.event_id
        WHERE e.event_date = ?
        GROUP BY e.id
        ORDER BY e.event_date DESC, e.start_time
    ''', (today,))
    
    events = []
    for row in cursor.fetchall():
        events.append({
            'id': row['id'],
            'title': row['title'],
            'event_date': row['event_date'],
            'start_time': row['start_time'],
            'end_time': row['end_time'],
            'slot_duration': row['slot_duration'],
            'breaks': json.loads(row['breaks']) if row['breaks'] else [],
            'registration_open': bool(row['registration_open']),
            'event_hash': row['event_hash'],
            'registrations_count': row['registrations_count']
        })
    
    conn.close()
    return jsonify(events)

@app.route('/api/admin/events/<int:event_id>/registrations', methods=['GET'])
def get_event_registrations(event_id):
    if not session.get('admin_logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT * FROM registrations 
        WHERE event_id = ?
        ORDER BY slot_time
    ''', (event_id,))
    
    registrations = []
    for row in cursor.fetchall():
        registrations.append({
            'id': row['id'],
            'child_name': row['child_name'],
            'phone': row['phone'],
            'slot_time': row['slot_time'],
            'registered_at': row['registered_at']
        })
    
    conn.close()
    return jsonify(registrations)

@app.route('/api/admin/events', methods=['POST'])
def create_event():
    if not session.get('admin_logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    title = data.get('title')
    event_date = data.get('event_date')
    start_time = data.get('start_time')
    end_time = data.get('end_time')
    slot_duration = int(data.get('slot_duration'))
    breaks = data.get('breaks', [])
    
    event_hash = generate_event_hash(title, event_date)
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO events (title, event_date, start_time, end_time, slot_duration, breaks, event_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (title, event_date, start_time, end_time, slot_duration, json.dumps(breaks), event_hash))
    
    conn.commit()
    event_id = cursor.lastrowid
    conn.close()
    
    registration_url = f"{request.host_url}register/{event_hash}"
    
    return jsonify({
        'success': True,
        'event_id': event_id,
        'event_hash': event_hash,
        'registration_url': registration_url
    })

@app.route('/api/admin/events/<int:event_id>/toggle', methods=['POST'])
def toggle_registration(event_id):
    if not session.get('admin_logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('SELECT registration_open FROM events WHERE id = ?', (event_id,))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        return jsonify({'error': 'Event not found'}), 404
    
    new_state = 0 if row['registration_open'] else 1
    cursor.execute('UPDATE events SET registration_open = ? WHERE id = ?', (new_state, event_id))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'registration_open': bool(new_state)})

@app.route('/api/admin/events/<int:event_id>', methods=['DELETE'])
def delete_event(event_id):
    if not session.get('admin_logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('DELETE FROM registrations WHERE event_id = ?', (event_id,))
    cursor.execute('DELETE FROM events WHERE id = ?', (event_id,))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/register/<event_hash>')
def register_page(event_hash):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM events WHERE event_hash = ?', (event_hash,))
    event = cursor.fetchone()
    conn.close()
    
    if not event:
        return "Мероприятие не найдено", 404
    
    if not event['registration_open']:
        return "Регистрация закрыта", 403
    
    return render_template('register.html', event_hash=event_hash)

@app.route('/api/event/<event_hash>')
def get_event_info(event_hash):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM events WHERE event_hash = ?', (event_hash,))
    event = cursor.fetchone()
    
    if not event:
        conn.close()
        return jsonify({'error': 'Event not found'}), 404
    
    event_info = {
        'id': event['id'],
        'title': event['title'],
        'event_date': event['event_date'],
        'start_time': event['start_time'],
        'end_time': event['end_time'],
        'slot_duration': event['slot_duration'],
        'breaks': json.loads(event['breaks']) if event['breaks'] else [],
        'registration_open': bool(event['registration_open'])
    }
    
    conn.close()
    return jsonify(event_info)

@app.route('/api/event/<event_hash>/slots')
def get_event_slots(event_hash):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM events WHERE event_hash = ?', (event_hash,))
    event = cursor.fetchone()
    
    if not event:
        conn.close()
        return jsonify({'error': 'Event not found'}), 404
    
    breaks = json.loads(event['breaks']) if event['breaks'] else []
    all_slots = generate_time_slots(event['start_time'], event['end_time'], event['slot_duration'], breaks)
    
    cursor.execute('SELECT slot_time, phone FROM registrations WHERE event_id = ?', (event['id'],))
    registrations = cursor.fetchall()
    
    occupied_slots = {}
    for reg in registrations:
        occupied_slots[reg['slot_time']] = reg['phone']
    
    slots_data = []
    for slot in all_slots:
        slots_data.append({
            'time': slot,
            'occupied': slot in occupied_slots,
            'phone': occupied_slots.get(slot, None)
        })
    
    conn.close()
    return jsonify(slots_data)

@app.route('/api/event/<event_hash>/register', methods=['POST'])
def register_for_slot(event_hash):
    data = request.json
    child_name = capitalize_name(data.get('child_name', ''))
    phone = data.get('phone', '')
    slot_time = data.get('slot_time', '')
    
    if len(phone) != 10 or not phone.isdigit():
        return jsonify({'error': 'Неверный формат телефона'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM events WHERE event_hash = ?', (event_hash,))
    event = cursor.fetchone()
    
    if not event:
        conn.close()
        return jsonify({'error': 'Event not found'}), 404
    
    if not event['registration_open']:
        conn.close()
        return jsonify({'error': 'Регистрация закрыта'}), 403
    
    cursor.execute('''
        SELECT * FROM registrations 
        WHERE event_id = ? AND slot_time = ?
    ''', (event['id'], slot_time))
    
    existing = cursor.fetchone()
    
    if existing:
        conn.close()
        return jsonify({
            'success': False, 
            'error': 'Этот слот уже занят',
            'phone': existing['phone']
        }), 409
    
    try:
        cursor.execute('''
            INSERT INTO registrations (event_id, child_name, phone, slot_time)
            VALUES (?, ?, ?, ?)
        ''', (event['id'], child_name, phone, slot_time))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'child_name': child_name,
            'phone': phone,
            'slot_time': slot_time
        })
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({
            'success': False,
            'error': 'Этот слот уже занят'
        }), 409

@app.route('/api/event/<event_hash>/my-registration')
def get_my_registration(event_hash):
    phone = request.args.get('phone')
    
    if not phone:
        return jsonify({'registered': False})
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('SELECT id FROM events WHERE event_hash = ?', (event_hash,))
    event = cursor.fetchone()
    
    if not event:
        conn.close()
        return jsonify({'error': 'Event not found'}), 404
    
    cursor.execute('''
        SELECT child_name, phone, slot_time 
        FROM registrations 
        WHERE event_id = ? AND phone = ?
    ''', (event['id'], phone))
    
    registration = cursor.fetchone()
    conn.close()
    
    if registration:
        return jsonify({
            'registered': True,
            'child_name': registration['child_name'],
            'phone': registration['phone'],
            'slot_time': registration['slot_time']
        })
    
    return jsonify({'registered': False})

@app.route('/')
def index():
    return f'''
    <html>
        <head>
            <meta charset="UTF-8">
            <title>Регистрация на мероприятие</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    max-width: 800px;
                    margin: 50px auto;
                    padding: 20px;
                    background: #f5f5f5;
                }}
                .container {{
                    background: white;
                    padding: 40px;
                    border-radius: 8px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                h1 {{
                    color: #333;
                }}
                .info {{
                    background: #e7f3ff;
                    padding: 15px;
                    border-radius: 4px;
                    margin: 20px 0;
                }}
                a {{
                    color: #007bff;
                    text-decoration: none;
                }}
                a:hover {{
                    text-decoration: underline;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Система регистрации на мероприятия</h1>
                <p>Добро пожаловать! Это веб-приложение для организации регистрации на однодневные мероприятия.</p>
                
                <div class="info">
                    <h3>Для администраторов</h3>
                    <p><strong>Ссылка на админ-панель:</strong> <a href="/admin/{ADMIN_URL_HASH}">/admin/{ADMIN_URL_HASH}</a></p>
                    <p>Используйте пароль из переменной окружения ADMIN_PASSWORD (по умолчанию: admin123)</p>
                    <p><strong>Важно:</strong> Не забудьте настроить переменные окружения ADMIN_PASSWORD и ADMIN_URL_SECRET для безопасной работы!</p>
                </div>
                
                <div class="info">
                    <h3>Для участников</h3>
                    <p>Если вы получили ссылку для регистрации на мероприятие, используйте эту ссылку для записи на удобное время.</p>
                </div>
                
                <p style="margin-top: 30px; color: #666; font-size: 14px;">
                    Подробная документация доступна в файле README.md
                </p>
            </div>
        </body>
    </html>
    '''

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)
