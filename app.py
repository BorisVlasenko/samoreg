from flask import Flask, render_template, request, jsonify, session
import sqlite3
import hashlib
import secrets
import os
from datetime import datetime, timedelta
from werkzeug.security import check_password_hash, generate_password_hash
import json

app = Flask(__name__)


# Настройка приложения
ADMIN_URL_SECRET = 'admin_secret_change_me'
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

def admin_page():
    return render_template('admin.html', admin_hash=ADMIN_URL_HASH)

# Регистрируем маршрут админ-панели динамически
app.add_url_rule(f'/admin/{ADMIN_URL_HASH}', 'admin_page', admin_page)

@app.route('/api/admin/events', methods=['GET'])
def get_admin_events():
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
    conn = get_db()
    cursor = conn.cursor()
    
    # Получаем информацию о мероприятии
    cursor.execute('SELECT * FROM events WHERE id = ?', (event_id,))
    event = cursor.fetchone()
    
    if not event:
        conn.close()
        return jsonify({'error': 'Event not found'}), 404
    
    # Генерируем все слоты
    breaks = json.loads(event['breaks']) if event['breaks'] else []
    all_slots = generate_time_slots(event['start_time'], event['end_time'], event['slot_duration'], breaks)
    
    # Получаем регистрации
    cursor.execute('''
        SELECT * FROM registrations 
        WHERE event_id = ?
    ''', (event_id,))
    
    registrations_dict = {}
    for row in cursor.fetchall():
        registrations_dict[row['slot_time']] = {
            'id': row['id'],
            'child_name': row['child_name'],
            'phone': row['phone'],
            'registered_at': row['registered_at']
        }
    
    # Формируем результат со всеми слотами
    slots_with_registrations = []
    for slot_time in all_slots:
        if slot_time in registrations_dict:
            reg = registrations_dict[slot_time]
            slots_with_registrations.append({
                'slot_time': slot_time,
                'occupied': True,
                'registration_id': reg['id'],
                'child_name': reg['child_name'],
                'phone': reg['phone'],
                'registered_at': reg['registered_at']
            })
        else:
            slots_with_registrations.append({
                'slot_time': slot_time,
                'occupied': False,
                'registration_id': None,
                'child_name': None,
                'phone': None,
                'registered_at': None
            })
    
    conn.close()
    return jsonify(slots_with_registrations)

@app.route('/api/admin/events', methods=['POST'])
def create_event():
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
    
    # Относительная ссылка для регистрации
    registration_url = f"/register/{event_hash}"
    
    return jsonify({
        'success': True,
        'event_id': event_id,
        'event_hash': event_hash,
        'registration_url': registration_url
    })

@app.route('/api/admin/events/<int:event_id>/toggle', methods=['POST'])
def toggle_registration(event_id):
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
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('DELETE FROM registrations WHERE event_id = ?', (event_id,))
    cursor.execute('DELETE FROM events WHERE id = ?', (event_id,))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/api/admin/registrations/<int:reg_id>', methods=['PUT'])
def update_registration(reg_id):
    data = request.json
    new_slot = data.get('slot_time')
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Получаем текущую регистрацию
    cursor.execute('SELECT * FROM registrations WHERE id = ?', (reg_id,))
    current_reg = cursor.fetchone()
    
    if not current_reg:
        conn.close()
        return jsonify({'error': 'Регистрация не найдена'}), 404
    
    # Проверяем, не занят ли новый слот другим участником
    cursor.execute('''
        SELECT * FROM registrations 
        WHERE event_id = ? AND slot_time = ? AND id != ?
    ''', (current_reg['event_id'], new_slot, reg_id))
    
    existing = cursor.fetchone()
    
    if existing:
        conn.close()
        return jsonify({'error': 'Этот слот уже занят'}), 409
    
    # Обновляем слот
    cursor.execute('''
        UPDATE registrations 
        SET slot_time = ?
        WHERE id = ?
    ''', (new_slot, reg_id))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'slot_time': new_slot})

@app.route('/api/admin/registrations/<int:reg_id>', methods=['DELETE'])
def delete_registration(reg_id):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('DELETE FROM registrations WHERE id = ?', (reg_id,))
    
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
    
    # Проверяем, есть ли уже регистрация этого пользователя
    cursor.execute('''
        SELECT * FROM registrations 
        WHERE event_id = ? AND child_name = ? AND phone = ?
    ''', (event['id'], child_name, phone))
    
    existing_user_reg = cursor.fetchone()
    
    # Проверяем, занят ли выбранный слот
    cursor.execute('''
        SELECT * FROM registrations 
        WHERE event_id = ? AND slot_time = ?
    ''', (event['id'], slot_time))
    
    slot_taken = cursor.fetchone()
    
    try:
        if existing_user_reg:
            # Пользователь уже зарегистрирован - меняем слот
            old_slot = existing_user_reg['slot_time']
            
            if old_slot == slot_time:
                # Пытается занять тот же слот
                conn.close()
                return jsonify({
                    'success': True,
                    'message': 'Вы уже зарегистрированы на это время',
                    'child_name': child_name,
                    'phone': phone,
                    'slot_time': slot_time
                })
            
            if slot_taken and slot_taken['phone'] != phone:
                # Слот занят другим пользователем
                conn.close()
                return jsonify({
                    'success': False, 
                    'error': 'Этот слот уже занят другим участником'
                }), 409
            
            # Обновляем слот в транзакции
            cursor.execute('''
                UPDATE registrations 
                SET slot_time = ?
                WHERE event_id = ? AND child_name = ? AND phone = ?
            ''', (slot_time, event['id'], child_name, phone))
            
            conn.commit()
            conn.close()
            
            return jsonify({
                'success': True,
                'message': f'Регистрация изменена с {old_slot} на {slot_time}',
                'child_name': child_name,
                'phone': phone,
                'slot_time': slot_time,
                'updated': True
            })
        else:
            # Новая регистрация
            if slot_taken:
                conn.close()
                return jsonify({
                    'success': False, 
                    'error': 'Этот слот уже занят',
                    'phone': slot_taken['phone']
                }), 409
            
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

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)
