from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "✅ 봇이 살아있습니다!"

def run():
    app.run(host='0.0.0.0', port=3000)

def keep_alive():
    t = Thread(target=run)
    t.start()
