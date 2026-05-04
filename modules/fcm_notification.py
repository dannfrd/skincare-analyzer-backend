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
