import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import logging

logger = logging.getLogger(__name__)

# SMTP Configuration
# In production, these should come from environment variables.
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER", "") # e.g. dermify@gmail.com
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "") # e.g. 16-character App Password

def send_otp_email(to_email: str, otp: str) -> bool:
    """
    Sends a 6-digit OTP to the user's email.
    If SMTP credentials are not configured, it will simulate sending by logging it.
    """
    if not SMTP_USER or not SMTP_PASSWORD:
        logger.warning(f"SMTP is not configured. Simulating sending OTP '{otp}' to '{to_email}'")
        print(f"\n{'='*40}")
        print(f"SIMULATED EMAIL SENT")
        print(f"To: {to_email}")
        print(f"Subject: Dermify Password Reset OTP")
        print(f"OTP Code: {otp}")
        print(f"{'='*40}\n")
        return True

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Kode OTP Reset Password Dermify"
        msg["From"] = f"Dermify Support <noreply@dermify.my.id>"
        msg["To"] = to_email

        text_content = f"Halo,\n\nKami menerima permintaan untuk mereset password akun Anda di aplikasi Dermify.\n\nKode OTP Anda adalah: {otp}\n\nKode ini berlaku selama 10 menit.\n\nJika Anda tidak pernah meminta reset password, mohon abaikan pesan ini.\n\nPesan ini dikirimkan otomatis oleh sistem Dermify. Harap jangan membalas email ini.\n\nTim Dermify"
        html_content = f"""\
        <!DOCTYPE html>
        <html>
          <head>
            <meta charset="utf-8">
          </head>
          <body style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px;">
            <div style="max-width: 600px; margin: 0 auto; background: #ffffff; padding: 30px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                <h2 style="color: #333333; margin-top: 0;">Reset Password Akun Dermify</h2>
                <p style="color: #555555; line-height: 1.5;">Halo,</p>
                <p style="color: #555555; line-height: 1.5;">Kami menerima permintaan untuk mereset password akun Anda di aplikasi Dermify. Berikut adalah kode OTP Anda:</p>
                <div style="background-color: #f9f9f9; padding: 15px; text-align: center; border-radius: 6px; margin: 25px 0;">
                    <h1 style="color: #4CB35B; font-size: 40px; margin: 0; letter-spacing: 8px;">{otp}</h1>
                </div>
                <p style="color: #555555; line-height: 1.5;">Kode OTP ini hanya berlaku selama <strong>10 menit</strong>.</p>
                <p style="color: #888888; font-size: 12px; margin-top: 30px; border-top: 1px solid #eeeeee; padding-top: 20px; line-height: 1.6;">
                    Jika Anda tidak pernah meminta reset password, mohon abaikan email ini. Pastikan akun Anda tetap aman.<br><br>
                    <em>Pesan ini dikirimkan otomatis oleh sistem Dermify. Harap jangan membalas (reply) ke alamat email ini.</em><br><br>
                    &copy; 2026 Dermify App. All rights reserved.
                </p>
            </div>
          </body>
        </html>
        """

        part1 = MIMEText(text_content, "plain")
        part2 = MIMEText(html_content, "html")
        msg.attach(part1)
        msg.attach(part2)

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(msg["From"], to_email, msg.as_string())
        server.quit()
        
        logger.info(f"OTP email successfully sent to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send OTP email to {to_email}: {e}")
        return False
