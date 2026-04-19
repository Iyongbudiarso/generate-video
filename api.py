from flask import Flask, request, jsonify
# Import fungsi utama dari file render_video.py Anda
from generate_video.render_video import create_quran_video

app = Flask(__name__)

@app.route('/generate-video', methods=['POST'])
def generate():
    # Ambil payload JSON dari n8n
    data = request.json

    # Validasi parameter wajib (required=True di argparse Anda)
    if not all(k in data for k in ("ayat", "trans", "audio", "bg")):
        return jsonify({
            "status": "error",
            "message": "Parameter 'ayat', 'trans', 'audio', dan 'bg' wajib diisi!"
        }), 400

    try:
        # Jalankan fungsi render dengan mapping parameter dari JSON
        # Gunakan .get() untuk memberikan nilai default yang sama seperti argparse Anda
        hasil_render = create_quran_video(
            ayat_texts=data.get("ayat"),
            translations=data.get("trans"),
            audio_paths=data.get("audio"),
            bg_path=data.get("bg"),
            output_name=data.get("output", "/shared_data/output_video.mp4"), # Arahkan ke shared volume
            latin_texts=data.get("latin", ""),
            hook=data.get("hook", ""),
            watermark=data.get("watermark", ""),
            overlay_opacity=float(data.get("overlay", 0.3)),
            taawudz_url=data.get("taawudz", "https://cdn.equran.id/audio-partial/Abdullah-Al-Juhany/001000.mp3"),
            audio_bg_url=data.get("audio_bg", ""),
            surah=data.get("surah", ""),
            cta=data.get("cta", ""),
            gap_duration=float(data.get("gap", 0.0)),
            pitch_factor=float(data.get("pitch", 1.0))
        )

        return jsonify({
            "status": "success",
            "message": "Video berhasil di-render!",
            "data_render": hasil_render
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    # Berjalan di port 5000, menerima koneksi dari container mana pun di network Docker
    app.run(host='0.0.0.0', port=5000, debug=True)
