from flask import Flask, request, jsonify, send_from_directory
import requests
import json
import os
import base64
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)

DIR         = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(DIR, 'config.json')

def load_config():
    try:
        with open(CONFIG_FILE, encoding='utf-8') as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    for key in ['provider', 'gmail_address', 'gmail_app_password', 'gmail_subject']:
        env_val = os.environ.get(key.upper())
        if env_val:
            cfg[key] = env_val
    return cfg


# ── Static files ─────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory(DIR, 'index.html')

@app.route('/manifest.json')
def manifest():
    return send_from_directory(DIR, 'manifest.json')

@app.route('/sw.js')
def service_worker():
    resp = send_from_directory(DIR, 'sw.js')
    resp.headers['Service-Worker-Allowed'] = '/'
    return resp

@app.route('/icon.svg')
def icon_svg():
    return send_from_directory(DIR, 'icon.svg')

@app.route('/icon-<int:size>.png')
def icon_png(size):
    png_path = os.path.join(DIR, f'icon-{size}.png')
    if not os.path.exists(png_path):
        _generate_icon_png(size, png_path)
    return send_from_directory(DIR, f'icon-{size}.png')

def _generate_icon_png(size, path):
    try:
        from PIL import Image, ImageDraw
        img  = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([0, 0, size-1, size-1], radius=size//8, fill='#1a237e')
        cx, cy, rad = size//2, size//2, int(size*0.32)
        draw.ellipse([cx-rad, cy-rad, cx+rad, cy+rad], fill='white')
        d2 = int(size*0.12)
        draw.ellipse([cx-d2, cy-d2, cx+d2, cy+d2], fill='#1a237e')
        img.save(path, 'PNG')
    except ImportError:
        svg_path = os.path.join(DIR, 'icon.svg')
        if os.path.exists(svg_path):
            import shutil; shutil.copy(svg_path, path)


# ── Send notification ─────────────────────────────────────────────────────────

@app.route('/api/send-sms', methods=['POST'])
def send_notification():
    config  = load_config()
    data    = request.get_json(force=True) or {}
    email   = str(data.get('email', '')).strip()
    message = str(data.get('message', '')).strip()
    subject = str(data.get('subject', config.get('gmail_subject', 'Ажилтны мэдэгдэл'))).strip()

    if not email or not message:
        return jsonify({'success': False, 'error': 'Email and message required'}), 400

    provider = config.get('provider', 'gmail')

    if provider == 'gmail':
        return send_gmail(email, subject, message, config)
    else:
        return jsonify({'success': False, 'error': f'Unknown provider: {provider}'})


# ── Gmail ─────────────────────────────────────────────────────────────────────

def send_gmail(to_email, subject, message, config):
    gmail_address  = config.get('gmail_address', '')
    gmail_password = config.get('gmail_app_password', '')

    if not gmail_address or not gmail_password:
        return jsonify({'success': False,
                        'error': 'Gmail тохиргоо дутуу байна. Admin → Gmail тохиргоо хэсгийг бөглөнө үү.'})
    try:
        msg = MIMEMultipart()
        msg['From']    = gmail_address
        msg['To']      = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(message, 'plain', 'utf-8'))

        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(gmail_address, gmail_password)
            server.sendmail(gmail_address, to_email, msg.as_string())

        return jsonify({'success': True})
    except smtplib.SMTPAuthenticationError:
        return jsonify({'success': False,
                        'error': 'Gmail нэвтрэх алдаа. App Password зөв үү? '
                                 '(myaccount.google.com → Security → App Passwords)'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── Config save from admin panel ──────────────────────────────────────────────

@app.route('/api/save-config', methods=['POST'])
def save_config():
    data = request.get_json(force=True) or {}
    try:
        try:
            with open(CONFIG_FILE) as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
        cfg.update(data)
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/get-config', methods=['GET'])
def get_config():
    cfg = load_config()
    # Only send non-sensitive fields to frontend
    return jsonify({
        'gmail_address': cfg.get('gmail_address', ''),
        'gmail_subject': cfg.get('gmail_subject', 'Ажилтны мэдэгдэл'),
        'has_password':  bool(cfg.get('gmail_app_password', '')),
    })


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 7500))
    print(f"\n  ✅  Staff Notification Server → http://localhost:{port}\n")
    app.run(host='0.0.0.0', debug=False, port=port)
