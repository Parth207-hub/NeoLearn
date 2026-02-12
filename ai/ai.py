from flask import Flask, request, jsonify, render_template
import requests

app = Flask(__name__)

OLLAMA_URL = "http://localhost:11434/api/chat"   # or /api/generate for simple models
MODEL_NAME = "llama3"                            # change if using another model

@app.route("/")
def home():
    return render_template("chat.html")  # simple chat page

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json()
    user_message = data.get("message", "")

    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    try:
        # Call Ollama chat API
        payload = {
            "model": MODEL_NAME,
            "messages": [
                {"role": "user", "content": user_message}
            ],
            "stream": False   # keep it simple first; streaming can be added later
        }

        ollama_response = requests.post(OLLAMA_URL, json=payload)
        ollama_response.raise_for_status()
        result = ollama_response.json()

        # For /api/chat, response is usually in result["message"]["content"]
        reply = result.get("message", {}).get("content", "").strip()

        return jsonify({"reply": reply})

    except Exception as e:
        print("Error talking to Ollama:", e)
        return jsonify({"error": "Failed to connect to AI backend"}), 500


if __name__ == "__main__":
    app.run(debug=True)
