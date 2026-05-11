import smtplib
from email.mime.text import MIMEText
import traceback
import os

def send_error_report(error: Exception, context: dict = None):
    """
    Dispatches an email error report to the developer.
    Gathered context helps in diagnosing brittle API failures.
    """
    recipient = "jwlehane@gmail.com"
    subject = f"TaxGrieve Error: {type(error).__name__}"
    
    tb = traceback.format_exc()
    body = (
        f"TaxGrieve Pipeline Error Report\n"
        f"==============================\n\n"
        f"Error: {str(error)}\n"
        f"Type: {type(error).__name__}\n\n"
        f"Context:\n{context}\n\n"
        f"Traceback:\n{tb}\n"
    )
    
    # Always log to stdout for Cloud Run logs
    print(f"--- ERROR REPORT ---\n{body}\n--- END REPORT ---")
    
    # Attempt to send email if SMTP credentials are provided in env
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT", 587))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASSWORD")
    
    if smtp_server and smtp_user and smtp_pass:
        try:
            msg = MIMEText(body)
            msg['Subject'] = subject
            msg['From'] = smtp_user
            msg['To'] = recipient
            
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
            print("Admin email report sent.")
        except Exception as e:
            print(f"Failed to send admin email report: {e}")
    else:
        print("SMTP credentials not configured. Skipping email dispatch.")
