"""Error logging and monitoring utilities."""
from datetime import datetime
import logging

logger = logging.getLogger("portfolio")


def log_error(db, source: str, message: str, details: str = ""):
    """Log an error to Firestore for monitoring. Auto-cleans entries older than 7 days."""
    try:
        db.collection('error_log').add({
            "source": source,
            "message": message,
            "details": details[:500],
            "timestamp": datetime.utcnow(),
        })
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(days=7)
        old_docs = db.collection('error_log').where(
            'timestamp', '<', cutoff
        ).limit(50).stream()
        for doc in old_docs:
            doc.reference.delete()
    except Exception:
        pass
