"""Error reporting + Sentry init.

Sentry replaces the legacy SMTP email reporter when SENTRY_DSN is set.
Without it, init_sentry() is a no-op and send_error_report falls through
to SMTP (if configured) or just prints to stdout.
"""

import smtplib
from email.mime.text import MIMEText
import traceback
import os


_sentry_inited = False


def init_sentry():
    """Initialize Sentry once. Safe to call repeatedly. No-op without SENTRY_DSN.

    Call from main.py at startup so unhandled exceptions get captured. Does
    its own integration with FastAPI/Starlette via sentry-sdk[fastapi].
    """
    global _sentry_inited
    if _sentry_inited:
        return
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
        sentry_sdk.init(
            dsn=dsn,
            integrations=[StarletteIntegration(), FastApiIntegration()],
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0")),
            send_default_pii=False,  # Never auto-attach IPs/cookies/auth
            environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
        )
        _sentry_inited = True
        print(f"Sentry initialized (env={os.getenv('SENTRY_ENVIRONMENT', 'production')})")
    except Exception as e:
        # Don't let a bad SENTRY_DSN crash the app boot.
        print(f"Sentry init failed: {e}")


def send_error_report(error: Exception, context: dict = None):
    """Dispatch an error report. Order of preference:
    1. Sentry, if SENTRY_DSN is set (cheapest, indexed, retains).
    2. SMTP email, for older deployments still configured that way.
    3. stdout (Cloud Logging picks it up either way).
    """
    err_type = type(error).__name__ if isinstance(error, BaseException) else 'Error'
    subject = f"TaxGrieve Error: {err_type}"
    tb = traceback.format_exc()
    body = (
        f"TaxGrieve Pipeline Error Report\n"
        f"==============================\n\n"
        f"Error: {str(error)}\n"
        f"Type: {err_type}\n\n"
        f"Context:\n{context}\n\n"
        f"Traceback:\n{tb}\n"
    )

    # Always log to stdout for Cloud Logging
    print(f"--- ERROR REPORT ---\n{body}\n--- END REPORT ---")

    # Sentry path
    if os.getenv("SENTRY_DSN"):
        try:
            import sentry_sdk
            with sentry_sdk.push_scope() as scope:
                if context:
                    scope.set_context("griever", context)
                if isinstance(error, BaseException):
                    sentry_sdk.capture_exception(error)
                else:
                    sentry_sdk.capture_message(str(error))
            return
        except Exception as e:
            print(f"Sentry capture failed, falling through to SMTP: {e}")

    # SMTP fallback (legacy)
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT", 587))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASSWORD")

    if smtp_server and smtp_user and smtp_pass:
        recipient = os.getenv("ERROR_REPORT_TO", smtp_user)
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
        # No backends configured; stdout already has the report.
        pass
