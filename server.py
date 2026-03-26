from flask import Flask, request, jsonify, send_from_directory
import requests
import json
import os
import base64

app = Flask(__name__)

CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.json')

def load_config():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

@app.route('/')
def index():
    return send_from_directory(os.path.dirname(__file__), 'index.html')


@app.route('/api/send-sms', methods=['POST'])
def send_sms():
    config  = load_config()
    data    = request.get_json(force=True) or {}
    phone   = str(data.get('phone', '')).strip()
    message = str(data.get('message', '')).strip()

    if not phone or not message:
        return jsonify({'success': False, 'error': 'Phone and message required'}), 400

    # Normalise to +976XXXXXXXX
    digits     = phone.replace('+976', '').replace('+', '').replace(' ', '').replace('-', '')
    full_phone = '+976' + digits

    provider = config.get('provider', 'android')

    if provider == 'android':
        return send_android(full_phone, message, config)
    elif provider == 'twilio':
        return send_twilio(full_phone, message, config)
    elif provider == 'vonage':
        vonage_to = '976' + digits
        return send_vonage(vonage_to, message, config)
    elif provider == 'textbelt':
        return send_textbelt(full_phone, message, config)
    else:
        return jsonify({'success': False, 'error': f'Unknown provider: {provider}'})


# ── Android SMS Gateway (FREE) ───────────────────────────────────────────────
def send_android(phone, message, config):
    host     = config.get('android_host', '')     # e.g. 192.168.1.5
    port     = config.get('android_port', 8080)
    login    = config.get('android_login', 'sms')
    password = config.get('android_password', '')

    if not host:
        return jsonify({'success': False,
                        'error': 'android_host тохируулаагүй байна. config.json-г шалгана уу.'})
    if not password:
        return jsonify({'success': False,
                        'error': 'android_password тохируулаагүй байна. config.json-г шалгана уу.'})

    url = f'http://{host}:{port}/api/v1/message'
    credentials = base64.b64encode(f'{login}:{password}'.encode()).decode()

    try:
        resp = requests.post(
            url,
            headers={
                'Authorization': f'Basic {credentials}',
                'Content-Type': 'application/json',
            },
            json={
                'message':      message,
                'phoneNumbers': [phone],
            },
            timeout=15
        )
        if resp.status_code in (200, 201, 202):
            return jsonify({'success': True})
        else:
            try:
                err = resp.json()
            except Exception:
                err = {'message': resp.text}
            return jsonify({'success': False,
                            'error': f'Android gateway алдаа [{resp.status_code}]: {err.get("message", resp.text)}'})
    except requests.exceptions.ConnectionError:
        return jsonify({'success': False,
                        'error': f'Утасны gateway-д холбогдож чадсангүй ({host}:{port}). '
                                  'Утас болон компьютер нэг WiFi-д байна уу? App ажиллаж байна уу?'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── Twilio ───────────────────────────────────────────────────────────────────
def send_twilio(phone, message, config):
    sid   = config.get('twilio_sid', '')
    token = config.get('twilio_token', '')
    from_ = config.get('twilio_from', '')
    if not sid or not token or not from_:
        return jsonify({'success': False, 'error': 'Twilio тохиргоо дутуу байна.'})
    try:
        from twilio.rest import Client
        client = Client(sid, token)
        msg = client.messages.create(body=message, from_=from_, to=phone)
        return jsonify({'success': True, 'sid': msg.sid})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── Vonage ───────────────────────────────────────────────────────────────────
def send_vonage(to, message, config):
    api_key    = config.get('vonage_api_key', '')
    api_secret = config.get('vonage_api_secret', '')
    sender     = config.get('vonage_from', 'Notify')
    if not api_key or not api_secret:
        return jsonify({'success': False, 'error': 'Vonage API key/secret тохируулаагүй байна.'})
    try:
        resp = requests.post('https://rest.nexmo.com/sms/json', data={
            'api_key': api_key, 'api_secret': api_secret,
            'to': to, 'from': sender, 'text': message,
        }, timeout=15)
        msg0   = resp.json().get('messages', [{}])[0]
        status = msg0.get('status', '99')
        if status == '0':
            return jsonify({'success': True})
        return jsonify({'success': False,
                        'error': f"Vonage [{status}]: {msg0.get('error-text', '')}"})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── TextBelt ─────────────────────────────────────────────────────────────────
def send_textbelt(phone, message, config):
    key = config.get('textbelt_key', 'textbelt')
    try:
        resp   = requests.post('https://textbelt.com/text',
                               data={'phone': phone, 'message': message, 'key': key}, timeout=15)
        result = resp.json()
        if result.get('success'):
            return jsonify({'success': True, 'quotaRemaining': result.get('quotaRemaining', '?')})
        return jsonify({'success': False, 'error': result.get('error', 'TextBelt error')})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


if __name__ == '__main__':
    print("\n  ✅  Staff Notification Server → http://localhost:5500\n")
    app.run(debug=False, port=5500)
