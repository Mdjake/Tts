import requests
import json
from io import BytesIO
from flask import Flask, request, jsonify, Response
import os

app = Flask(__name__)

LMNT_API_KEY = os.environ.get("LMNT_API_KEY", "1fdc497ee58b4172aa9a0b82a3e14054")
LMNT_ENDPOINT = "https://api.lmnt.com/v1/ai/speech/bytes"
TMPFILES_UPLOAD_URL = "https://tmpfiles.org/api/v1/upload"
CHUNK_SIZE = 4800

# ─── PASTE YOUR TRANSLITERATE API URL HERE ────────────────────────────────────
TRANSLITERATE_API_URL = "https://transliterate-xi.vercel.app/transliterate"
# ─────────────────────────────────────────────────────────────────────────────

LMNT_VOICES = [
    "ansel", "autumn", "bella", "brandon", "cassian", "elowen",
    "evander", "huxley", "jacob", "juniper", "kennedy", "leah",
    "lucas", "morgan", "natalie", "nyssa", "ryan", "sadie",
    "stella", "tyler", "vesper", "violet", "warrick", "zain"
]


# ─── Transliteration (calls your separate transliterate API) ─────────────────

def transliterate_hinglish(text: str) -> str:
    """
    Calls your deployed transliterate API to convert Hinglish → Hindi script.
    Falls back to original text if the API call fails.
    """
    try:
        resp = requests.get(
            TRANSLITERATE_API_URL,
            params={'text': text},
            timeout=15
        )
        if resp.status_code == 200:
            data = json.loads(resp.text)
            if data.get('success') and data.get('hindi'):
                return data['hindi']
    except Exception as e:
        print(f"Transliterate API error: {e}")
    return text  # fallback to original text


# ─── Chunking ────────────────────────────────────────────────────────────────

def split_text(text: str, chunk_size: int = CHUNK_SIZE) -> list:
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    while len(text) > chunk_size:
        window = text[:chunk_size]
        split_pos = -1

        for delimiter in [". ", "! ", "? ", ".\n", "!\n", "?\n"]:
            pos = window.rfind(delimiter)
            if pos != -1:
                split_pos = pos + len(delimiter)
                break

        if split_pos == -1:
            split_pos = window.rfind(" ")
        if split_pos == -1:
            split_pos = chunk_size

        chunks.append(text[:split_pos].strip())
        text = text[split_pos:].strip()

    if text:
        chunks.append(text)

    return chunks


# ─── LMNT & Storage helpers ──────────────────────────────────────────────────

def generate_speech_chunk(text: str, voice: str) -> bytes:
    headers = {
        'X-API-Key': LMNT_API_KEY,
        'Content-Type': 'application/json'
    }
    payload = {
        'text': text,
        'voice': voice,
        'language': 'auto'
    }
    response = requests.post(LMNT_ENDPOINT, json=payload, headers=headers, timeout=30)
    if response.status_code == 200:
        return response.content
    raise Exception(f"LMNT API error {response.status_code}: {response.text}")


def join_audio(chunks: list) -> bytes:
    buf = BytesIO()
    for chunk in chunks:
        buf.write(chunk)
    return buf.getvalue()


def upload_to_tmpfiles(audio_bytes: bytes) -> str:
    files = {'file': ('audio.mp3', BytesIO(audio_bytes), 'audio/mpeg')}
    response = requests.post(TMPFILES_UPLOAD_URL, files=files, timeout=30)
    if response.status_code == 200:
        data = response.json()
        if data.get('status') == 'success' and data.get('data', {}).get('url'):
            url = data['data']['url']
            return url.replace('tmpfiles.org/', 'tmpfiles.org/dl/')
    raise Exception("Failed to upload audio to tmpfiles.org")


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.route('/', methods=['GET'])
def index():
    return jsonify({
        'name': 'LMNT Text-to-Speech API',
        'description': 'Unlimited-length AI speech synthesis powered by LMNT',
        'endpoints': {
            'GET /tts':    'Generate audio URL — returns JSON with tmpfiles link',
            'GET /audio':  'Stream raw MP3 directly — open in browser to play',
            'GET /voices': 'List all available voices'
        },
        'params': {
            'voice':    'required — voice name e.g. leah',
            'text':     'required — any length text',
            'hinglish': 'optional — true/false, converts Hinglish to Hindi before TTS'
        }
    })


@app.route('/voices', methods=['GET'])
def voices():
    return jsonify({
        'success': True,
        'total': len(LMNT_VOICES),
        'voices': LMNT_VOICES
    })


@app.route('/tts', methods=['GET'])
def tts():
    voice    = request.args.get('voice', '').strip()
    text     = request.args.get('text', '').strip()
    hinglish = request.args.get('hinglish', 'false').lower() == 'true'

    if not text:
        return jsonify({'success': False, 'error': 'Parameter "text" is required'}), 400
    if not voice:
        return jsonify({'success': False, 'error': 'Parameter "voice" is required'}), 400
    if voice not in LMNT_VOICES:
        return jsonify({'success': False, 'error': f'Voice "{voice}" not found. Available: {", ".join(LMNT_VOICES)}'}), 400

    try:
        original_text = text
        if hinglish:
            text = transliterate_hinglish(text)

        chunks      = split_text(text)
        audio_parts = [generate_speech_chunk(c, voice) for c in chunks]
        final_audio = join_audio(audio_parts)
        audio_url   = upload_to_tmpfiles(final_audio)

        return jsonify({
            'success': True,
            'url': audio_url,
            'chunks_processed': len(chunks),
            'total_characters': len(text),
            'original_text': original_text if hinglish else None,
            'transliterated_text': text if hinglish else None
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/audio', methods=['GET'])
def audio():
    voice    = request.args.get('voice', '').strip()
    text     = request.args.get('text', '').strip()
    hinglish = request.args.get('hinglish', 'false').lower() == 'true'

    if not text:
        return jsonify({'success': False, 'error': 'Parameter "text" is required'}), 400
    if not voice:
        return jsonify({'success': False, 'error': 'Parameter "voice" is required'}), 400
    if voice not in LMNT_VOICES:
        return jsonify({'success': False, 'error': f'Voice "{voice}" not found. Available: {", ".join(LMNT_VOICES)}'}), 400

    try:
        transliterated = None
        if hinglish:
            transliterated = transliterate_hinglish(text)
            text = transliterated

        chunks      = split_text(text)
        audio_parts = [generate_speech_chunk(c, voice) for c in chunks]
        final_audio = join_audio(audio_parts)

        return Response(
            final_audio,
            mimetype='audio/mpeg',
            headers={
                'Content-Disposition': 'inline; filename=speech.mp3',
                'X-Chunks-Processed': str(len(chunks)),
                'X-Total-Characters': str(len(text)),
                'X-Transliterated': transliterated or ''
            }
        )

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/tts', methods=['POST'])
def tts_post():
    data     = request.get_json(force=True) or {}
    voice    = data.get('voice', '').strip()
    text     = data.get('text', '').strip()
    hinglish = str(data.get('hinglish', 'false')).lower() == 'true'

    if not text:
        return jsonify({'success': False, 'error': 'Field "text" is required'}), 400
    if not voice:
        return jsonify({'success': False, 'error': 'Field "voice" is required'}), 400
    if voice not in LMNT_VOICES:
        return jsonify({'success': False, 'error': f'Voice "{voice}" not found. Available: {", ".join(LMNT_VOICES)}'}), 400

    try:
        original_text = text
        if hinglish:
            text = transliterate_hinglish(text)

        chunks      = split_text(text)
        audio_parts = [generate_speech_chunk(c, voice) for c in chunks]
        final_audio = join_audio(audio_parts)
        audio_url   = upload_to_tmpfiles(final_audio)

        return jsonify({
            'success': True,
            'url': audio_url,
            'chunks_processed': len(chunks),
            'total_characters': len(text),
            'original_text': original_text if hinglish else None,
            'transliterated_text': text if hinglish else None
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.errorhandler(404)
def not_found(error):
    return jsonify({'success': False, 'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'success': False, 'error': 'Internal server error'}), 500


if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 3000)))

        return jsonify({'success': False, 'error': str(e)}), 500


@app.errorhandler(404)
def not_found(error):
    return jsonify({'success': False, 'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'success': False, 'error': 'Internal server error'}), 500


if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 3000)))
