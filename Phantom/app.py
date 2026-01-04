import time
import secrets
import threading
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, join_room, leave_room, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(16)

# Async mode required for performance
socketio = SocketIO(app, cors_allowed_origins="*")

# In-memory storage: { token: { 'expiry': timestamp, 'users': count } }
active_rooms = {}
ROOM_TTL = 600  # 10 minutes (600 seconds)

def cleanup_rooms():
    """Background task to delete expired rooms."""
    while True:
        time.sleep(10)
        current_time = time.time()
        # Use list(keys) to avoid runtime errors during modification
        for token in list(active_rooms.keys()):
            if current_time > active_rooms[token]['expiry']:
                socketio.emit('room_expired', room=token)
                del active_rooms[token]

# Start the cleanup daemon
threading.Thread(target=cleanup_rooms, daemon=True).start()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate_token', methods=['POST'])
def generate_token():
    token = secrets.token_urlsafe(8) # Short URL-safe token
    active_rooms[token] = {
        'expiry': time.time() + ROOM_TTL,
        'users': 0
    }
    return jsonify({'token': token, 'expires_in': ROOM_TTL})

@app.route('/validate_token', methods=['POST'])
def validate_token():
    data = request.json
    token = data.get('token')
    if token in active_rooms:
        remaining = active_rooms[token]['expiry'] - time.time()
        if remaining > 0:
            return jsonify({'valid': True, 'remaining': remaining})
    return jsonify({'valid': False})

# --- Socket Events ---

@socketio.on('join')
def on_join(data):
    token = data['token']
    if token in active_rooms:
        join_room(token)
        active_rooms[token]['users'] += 1
        # Broadcast new user count
        emit('update_status', {'count': active_rooms[token]['users']}, room=token)

@socketio.on('leave')
def on_leave(data):
    token = data['token']
    if token in active_rooms:
        leave_room(token)
        active_rooms[token]['users'] = max(0, active_rooms[token]['users'] - 1)
        emit('update_status', {'count': active_rooms[token]['users']}, room=token)

@socketio.on('message')
def handle_message(data):
    token = data['token']
    if token in active_rooms:
        # Relay message to everyone in the room
        # data includes: msg, sender_id, msg_id, timestamp
        emit('message', data, room=token)

@socketio.on('confirm_delivery')
def confirm_delivery(data):
    """
    1. Receiver gets message -> sends 'confirm_delivery'
    2. Server receives this -> forwards 'msg_delivered' ONLY to the original sender
    """
    sender_sid = data.get('sender_socket_id')
    if sender_sid:
        emit('msg_delivered', {'msg_id': data['msg_id']}, room=sender_sid)

@socketio.on('typing')
def handle_typing(data):
    token = data['token']
    emit('display_typing', {}, room=token, include_self=False)

@socketio.on('stop_typing')
def handle_stop_typing(data):
    token = data['token']
    emit('hide_typing', {}, room=token, include_self=False)

@socketio.on('ping_check')
def ping_check():
    return time.time() # Ack for latency check

@socketio.on('share_metrics')
def share_metrics(data):
    token = data['token']
    emit('update_peer_metrics', {'ping': data['ping']}, room=token, include_self=False)

if __name__ == '__main__':
    socketio.run(app, debug=True)