from flask import Flask, request, jsonify, send_from_directory
import requests
import json
import os
import base64

app = Flask(__name__)

DIR         = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(DIR, 'config.json')

def load_config():
    """Load from config.json, fall back to environment variables (for Railway)."""
    try:
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}

    # Environment variable overrides (used when deployed to Railway)
    for key in ['provider',
                'android_login', 'android_password', 'android_host', 'android_port',
                'twilio_sid', 'twilio_token', 'twilio_from',
                'vonage_api_key', 'vonage_api_secret', 'vonage_from',
                'textbelt_key']:
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


# ── SMS endpoint ─────────────────────────────────────────────────────────────

@app.route('/api/send-sms', methods=['POST'])
def send_sms():
    config  = load_config()
    data    = request.get_json(force=True) or {}
    phone   = str(data.get('phone', '')).strip()
    message = str(data.get('message', '')).strip()

    if not phone or not message:
        return jsonify({'success': False, 'error': 'Phone and message required'}), 400

    digits     = phone.replace('+976', '').replace('+', '').replace(' ', '').replace('-', '')
    full_phone = '+976' + digits

    provider = config.get('provider', 'android_cloud')

    if provider == 'android_cloud':
        return send_android_cloud(full_phone, message, config)
    elif provider == 'android':
        return send_android_local(full_phone, message, config)
    elif provider == 'twilio':
        return send_twilio(full_phone, message, config)
    elif provider == 'vonage':
        return send_vonage('976' + digits, message, config)
    elif provider == 'textbelt':
        return send_textbelt(full_phone, message, config)
    else:
        return jsonify({'success': False, 'error': f'Unknown provider: {provider}'})


# ── Android SMS Gateway — CLOUD (works from anywhere, free) ──────────────────
def send_android_cloud(phone, message, config):
    """
    Uses the sms-gateway.app cloud relay.
    The Android app must have 'Cloud' mode enabled.
    """
    login    = config.get('android_login', '')
    password = config.get('android_password', '')

    if not login or not password:
        return jsonify({'success': False,
                        'error': 'android_login / android_password тохируулаагүй байна.'})

    url         = 'https://api.sms-gateway.app/3rdparty/v1/messages'
    credentials = base64.b64encode(f'{login}:{password}'.encode()).decode()

    try:
        resp = requests.post(url,
            headers={'Authorization': f'Basic {credentials}',
                     'Content-Type': 'application/json'},
            json={'message': message, 'phoneNumbers': [phone]},
            timeout=20)
        if resp.status_code in (200, 201, 202):
            return jsonify({'success': True})
        try:
            err = resp.json()
        except Exception:
            err = {}
        return jsonify({'success': False,
                        'error': f'Cloud gateway алдаа [{resp.status_code}]: {err.get("message", resp.text)}'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── Android SMS Gateway — LOCAL (same WiFi only) ──────────────────────────────
def send_android_local(phone, message, config):
    host     = config.get('android_host', '')
    port     = config.get('android_port', 8080)
    login    = config.get('android_login', 'sms')
    password = config.get('android_password', '')

    if not host or not password:
        return jsonify({'success': False, 'error': 'android_host / android_password тохируулаагүй байна.'})

    url         = f'http://{host}:{port}/api/v1/message'
    credentials = base64.b64encode(f'{login}:{password}'.encode()).decode()
    try:
        resp = requests.post(url,
            headers={'Authorization': f'Basic {credentials}',
                     'Content-Type': 'application/json'},
            json={'message': message, 'phoneNumbers': [phone]},
            timeout=15)
        if resp.status_code in (200, 201, 202):
            return jsonify({'success': True})
        try:
            err = resp.json()
        except Exception:
            err = {}
        return jsonify({'success': False,
                        'error': f'Android gateway алдаа [{resp.status_code}]: {err.get("message", resp.text)}'})
    except requests.exceptions.ConnectionError:
        return jsonify({'success': False,
                        'error': f'Холбогдож чадсангүй ({host}:{port}). Нэг WiFi-д байна уу?'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── Twilio ────────────────────────────────────────────────────────────────────
def send_twilio(phone, message, config):
    sid, token, from_ = config.get('twilio_sid'), config.get('twilio_token'), config.get('twilio_from')
    if not all([sid, token, from_]):
        return jsonify({'success': False, 'error': 'Twilio тохиргоо дутуу байна.'})
    try:
        from twilio.rest import Client
        msg = Client(sid, token).messages.create(body=message, from_=from_, to=phone)
        return jsonify({'success': True, 'sid': msg.sid})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── Vonage ────────────────────────────────────────────────────────────────────
def send_vonage(to, message, config):
    key, secret = config.get('vonage_api_key'), config.get('vonage_api_secret')
    if not key or not secret:
        return jsonify({'success': False, 'error': 'Vonage тохиргоо дутуу байна.'})
    try:
        resp = requests.post('https://rest.nexmo.com/sms/json',
            data={'api_key': key, 'api_secret': secret,
                  'to': to, 'from': config.get('vonage_from', 'Notify'), 'text': message},
            timeout=15)
        msg0 = resp.json().get('messages', [{}])[0]
        if msg0.get('status') == '0':
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': f"Vonage: {msg0.get('error-text', '')}"})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── TextBelt ──────────────────────────────────────────────────────────────────
def send_textbelt(phone, message, config):
    try:
        resp   = requests.post('https://textbelt.com/text',
            data={'phone': phone, 'message': message, 'key': config.get('textbelt_key', 'textbelt')},
            timeout=15)
        result = resp.json()
        if result.get('success'):
            return jsonify({'success': True, 'quotaRemaining': result.get('quotaRemaining')})
        return jsonify({'success': False, 'error': result.get('error', 'TextBelt error')})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5500))
    print(f"\n  ✅  Staff Notification Server → http://localhost:{port}\n")
    app.run(host='0.0.0.0', debug=False, port=port)
