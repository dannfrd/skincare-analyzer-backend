import firebase_admin
from firebase_admin import credentials, messaging
import os

# Path ke file service account JSON
FIREBASE_CRED_PATH = os.path.join(os.path.dirname(__file__), '../dermify-e69de-firebase-adminsdk-fbsvc-eb6e0455ca.json')

# Inisialisasi Firebase Admin SDK (hanya sekali)
if not firebase_admin._apps:
    cred = credentials.Certificate(FIREBASE_CRED_PATH)
    firebase_admin.initialize_app(cred)

def send_notification_to_all(title: str, body: str, data: dict = None):
    """
    Mengirim notifikasi ke semua user (topic 'all')
    :param title: Judul notifikasi
    :param body: Isi pesan notifikasi
    :param data: Data tambahan (opsional)
    """
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
