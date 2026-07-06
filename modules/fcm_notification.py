import firebase_admin
from firebase_admin import credentials, messaging
import os

# Path ke file service account JSON
_env_path = os.getenv("FIREBASE_CREDENTIALS_PATH", "")
_local_path = os.path.join(os.path.dirname(__file__), '../dermify-e69de-firebase-adminsdk-fbsvc-769f097d9f.json')

if _env_path and os.path.exists(_env_path):
    FIREBASE_CRED_PATH = _env_path
else:
    FIREBASE_CRED_PATH = _local_path

# Inisialisasi Firebase Admin SDK (hanya sekali)
if not firebase_admin._apps:
    if os.path.exists(FIREBASE_CRED_PATH):
        try:
            cred = credentials.Certificate(FIREBASE_CRED_PATH)
            firebase_admin.initialize_app(cred)
            print(f"[FCM] Firebase Admin SDK initialized using {FIREBASE_CRED_PATH}")
        except Exception as e:
            print(f"[FCM] Warning: Failed to initialize Firebase Admin SDK: {e}")
    else:
        print(f"[FCM] Warning: Firebase credentials file not found at '{FIREBASE_CRED_PATH}'. Push notifications disabled.")

def send_notification_to_all(title: str, body: str, data: dict = None):
    """
    Mengirim notifikasi ke semua user (topic 'all')
    :param title: Judul notifikasi
    :param body: Isi pesan notifikasi
    :param data: Data tambahan (opsional)
    """
    if not firebase_admin._apps:
        return {"status": "disabled", "reason": "Firebase Admin SDK not initialized"}
    message = messaging.Message(
        notification=messaging.Notification(
            title=title,
            body=body
        ),
        topic='all',
        data=data or {}
    )
    response = messaging.send(message)
    return response


def send_notification(title: str, body: str, data: dict | None = None, topic: str | None = None, tokens: list | None = None):
    """
    Send notification either to a topic (single) or a list of device tokens (multicast).
    If `topic` is provided, message is sent to that topic. If `tokens` is provided and non-empty,
    a multicast message will be sent to those tokens. Returns Firebase response object or dict.
    """
    if not firebase_admin._apps:
        return {"status": "disabled", "reason": "Firebase Admin SDK not initialized"}
    if topic:
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            topic=topic,
            data=data or {}
        )
        return messaging.send(message)

    if tokens:
        # Trim tokens to list of strings
        tokens_list = [str(t).strip() for t in tokens if t]
        if not tokens_list:
            raise ValueError("No valid tokens provided for multicast send")

        multicast = messaging.MulticastMessage(
            notification=messaging.Notification(title=title, body=body),
            tokens=tokens_list,
            data=data or {}
        )
        response = messaging.send_multicast(multicast)
        # Return a simple dict summary
        return {
            "success_count": response.success_count,
            "failure_count": response.failure_count,
            "responses": [r.__dict__ for r in response.responses],
        }

    # Fallback to sending to 'all' topic
    return send_notification_to_all(title, body, data)
