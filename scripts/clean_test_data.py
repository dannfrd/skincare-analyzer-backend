import sys
import os

# Add the parent directory to sys.path so we can import database
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db_connection import DatabaseConnection
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def clean_test_data():
    db = DatabaseConnection()
    if not db.engine:
        logger.error("Failed to connect to the database.")
        return

    try:
        with db.engine.begin() as conn:
            logger.info("Cleaning up notifications...")
            conn.execute(text("DELETE FROM notifications"))

            logger.info("Cleaning up non-admin users (this will automatically cascade and delete their scans, histories, etc.)...")
            # Delete all users EXCEPT admin
            result = conn.execute(text("DELETE FROM users WHERE role != 'admin' OR role IS NULL"))
            logger.info(f"Deleted {result.rowcount} non-admin users and their related data.")
            
            logger.info("Verifying admin user exists...")
            admin_check = conn.execute(text("SELECT email FROM users WHERE role = 'admin'")).fetchall()
            logger.info(f"Remaining admin users: {[row[0] for row in admin_check]}")
            
            logger.info("Cleanup completed successfully! The database is now fresh and ready for production.")

    except Exception as e:
        logger.error(f"Error during cleanup: {e}")

if __name__ == "__main__":
    clean_test_data()
