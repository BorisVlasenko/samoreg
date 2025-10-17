# Инструкция по развертыванию на VDS

## Подготовка сервера

### 1. Обновите систему и установите Python

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3 python3-pip python3-venv nginx -y
```

### 2. Создайте пользователя для приложения

```bash
sudo useradd -m -s /bin/bash webapp
sudo su - webapp
```

### 3. Скопируйте файлы приложения

Загрузите все файлы проекта на сервер в директорию `/home/webapp/event-registration/`:

```bash
mkdir -p /home/webapp/event-registration
cd /home/webapp/event-registration
```

Необходимые файлы:
- `app.py`
- `config.txt`
- `templates/admin.html`
- `templates/register.html`
- `README.md`

## Настройка приложения

### 1. Создайте виртуальное окружение

```bash
python3 -m venv venv
source venv/bin/activate
```

### 2. Установите зависимости

```bash
pip install flask werkzeug gunicorn
```

### 3. Настройте config.txt

Отредактируйте файл `config.txt` и измените настройки:

```bash
nano config.txt
```

Измените:
```
ADMIN_PASSWORD=ваш_надежный_пароль_здесь
ADMIN_URL_SECRET=длинная_случайная_строка_для_безопасности
SESSION_SECRET=
```

Сохраните (Ctrl+O, Enter, Ctrl+X)

### 4. Проверьте работу приложения

```bash
python app.py
# Откройте в браузере http://ваш-ip:5000
# Если работает - нажмите Ctrl+C для остановки
```

## Настройка автозапуска с systemd

### 1. Создайте systemd service

```bash
sudo nano /etc/systemd/system/event-registration.service
```

Содержимое файла:

```ini
[Unit]
Description=Event Registration App
After=network.target

[Service]
User=webapp
Group=webapp
WorkingDirectory=/home/webapp/event-registration
Environment="PATH=/home/webapp/event-registration/venv/bin"
ExecStart=/home/webapp/event-registration/venv/bin/gunicorn -w 4 -b 127.0.0.1:5000 app:app

[Install]
WantedBy=multi-user.target
```

### 2. Запустите сервис

```bash
sudo systemctl daemon-reload
sudo systemctl start event-registration
sudo systemctl enable event-registration
sudo systemctl status event-registration
```

## Настройка Nginx (рекомендуется)

### 1. Создайте конфигурацию Nginx

```bash
sudo nano /etc/nginx/sites-available/event-registration
```

Содержимое:

```nginx
server {
    listen 80;
    server_name ваш-домен.ru;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 2. Активируйте конфигурацию

```bash
sudo ln -s /etc/nginx/sites-available/event-registration /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

## Настройка HTTPS (SSL)

### 1. Установите Certbot

```bash
sudo apt install certbot python3-certbot-nginx -y
```

### 2. Получите SSL сертификат

```bash
sudo certbot --nginx -d ваш-домен.ru
```

### 3. Автообновление сертификата

Certbot автоматически настроит обновление. Проверьте:

```bash
sudo certbot renew --dry-run
```

## Управление приложением

### Просмотр логов

```bash
sudo journalctl -u event-registration -f
```

### Перезапуск

```bash
sudo systemctl restart event-registration
```

### Остановка

```bash
sudo systemctl stop event-registration
```

## Получение admin URL

После запуска приложения откройте главную страницу:

```
http://ваш-домен.ru/
```

Там будет указана ссылка на админ-панель вида `/admin/{хеш}`

## Безопасность

1. **Измените config.txt** - используйте надежные пароли
2. **Настройте firewall:**

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

3. **Регулярно обновляйте систему:**

```bash
sudo apt update && sudo apt upgrade -y
```

## Резервное копирование

### База данных

```bash
# Создать backup
cp /home/webapp/event-registration/events.db /home/webapp/backup-$(date +%Y%m%d).db

# Восстановить
cp /home/webapp/backup-YYYYMMDD.db /home/webapp/event-registration/events.db
sudo systemctl restart event-registration
```

## Решение проблем

### Приложение не запускается

```bash
# Проверьте логи
sudo journalctl -u event-registration -n 50

# Проверьте файлы
ls -la /home/webapp/event-registration/

# Проверьте права
sudo chown -R webapp:webapp /home/webapp/event-registration/
```

### База данных заблокирована

```bash
sudo systemctl stop event-registration
rm /home/webapp/event-registration/events.db-journal
sudo systemctl start event-registration
```

## Готово! 🎉

Ваше приложение развернуто и доступно по адресу: `https://ваш-домен.ru`
