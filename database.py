"""Database functions"""
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List
from utils import ensure_cdt_timezone, CDT

def init_database():
    """Initialize SQLite database with required tables"""
    conn = sqlite3.connect('poloseek.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS parking_pass (
            id INTEGER PRIMARY KEY,
            current_owner_id INTEGER NOT NULL,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            start_time TIMESTAMP NOT NULL,
            end_time TIMESTAMP NOT NULL,
            active_status BOOLEAN DEFAULT TRUE,
            approved BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            parking_memo TEXT
        )
    ''')
    
    # initialize parking pass if it doesn't exist
    cursor.execute('SELECT COUNT(*) FROM parking_pass')
    if cursor.fetchone()[0] == 0:
        from config import DEFAULT_OWNER_ID
        cursor.execute(
            'INSERT INTO parking_pass (current_owner_id) VALUES (?)',
            (DEFAULT_OWNER_ID,)
        )
    
    conn.commit()
    conn.close()

def get_current_owner() -> Optional[Dict]:
    """Get current parking pass owner"""
    conn = sqlite3.connect('poloseek.db')
    cursor = conn.cursor()
    cursor.execute('SELECT current_owner_id, last_updated FROM parking_pass WHERE id = 1')
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return {
            'current_owner_id': result[0],
            'last_updated': result[1]
        }
    return None

def update_parking_pass_owner(user_id: int):
    """Update parking pass owner"""
    conn = sqlite3.connect('poloseek.db')
    cursor = conn.cursor()
    now_cdt = datetime.now(CDT).isoformat()
    cursor.execute(
        'UPDATE parking_pass SET current_owner_id = ?, last_updated = ? WHERE id = 1',
        (user_id, now_cdt)
    )
    conn.commit()
    conn.close()

def transfer_pass_with_lock(from_user_id: int, to_user_id: int) -> bool:
    """Transfer pass with database-level locking to prevent race conditions"""
    conn = sqlite3.connect('poloseek.db')
    conn.isolation_level = 'EXCLUSIVE'  # lock database during transaction
    
    try:
        cursor = conn.cursor()
        cursor.execute('BEGIN EXCLUSIVE')
        
        # verify current owner hasn't changed
        cursor.execute('SELECT current_owner_id FROM parking_pass WHERE id = 1')
        current = cursor.fetchone()
        
        if current and current[0] == from_user_id:
            now_cdt = datetime.now(CDT).isoformat()
            cursor.execute(
                'UPDATE parking_pass SET current_owner_id = ?, last_updated = ? WHERE id = 1',
                (to_user_id, now_cdt)
            )
            conn.commit()
            return True
        else:
            conn.rollback()
            return False
            
    except Exception as e:
        conn.rollback()
        print(f"Error transferring pass: {e}")
        return False
    finally:
        conn.close()

def get_reservation_status(current_time: datetime) -> Optional[Dict]:
    """Get all relevant reservation info in one efficient query"""
    conn = sqlite3.connect('poloseek.db')
    cursor = conn.cursor()
    
    # get current owner
    cursor.execute('SELECT current_owner_id FROM parking_pass WHERE id = 1')
    current_owner = cursor.fetchone()
    
    if not current_owner:
        conn.close()
        return None
    
    # get expired reservations
    cursor.execute('''
        SELECT user_id, start_time, end_time 
        FROM reservations 
        WHERE active_status = TRUE AND substr(end_time, 1, 19) <= ?
    ''', (current_time.replace(tzinfo=None).isoformat(),))
    expired = cursor.fetchall()
    
    # get next approved reservation that should be active now or next in queue
    cursor.execute('''
        SELECT user_id, start_time, end_time 
        FROM reservations 
        WHERE active_status = TRUE 
        AND approved = TRUE 
        AND substr(end_time, 1, 19) > ?
        ORDER BY substr(start_time, 1, 19) 
        LIMIT 1
    ''', (current_time.replace(tzinfo=None).isoformat(),))
    next_approved = cursor.fetchone()
    
    conn.close()
    
    result = {
        'current_owner_id': current_owner[0],
        'expired_reservations': [
            {'user_id': r[0], 'start_time': r[1], 'end_time': r[2]} 
            for r in expired
        ],
        'next_approved': None
    }
    
    if next_approved:
        result['next_approved'] = {
            'user_id': next_approved[0],
            'start_time': next_approved[1],
            'end_time': next_approved[2]
        }
    
    return result

def check_reservation_conflicts(start_time: datetime, end_time: datetime, exclude_user_id: Optional[int] = None) -> List[Dict]:
    """Check for reservation conflicts in the given time range - only check approved reservations"""
    conn = sqlite3.connect('poloseek.db')
    cursor = conn.cursor()
    
    # ensure times are in CDT
    start_time = ensure_cdt_timezone(start_time)
    end_time = ensure_cdt_timezone(end_time)
    
    query = '''
        SELECT user_id, start_time, end_time, approved
        FROM reservations 
        WHERE active_status = TRUE
        AND approved = TRUE
        AND (
            (datetime(start_time) < datetime(?) AND datetime(end_time) > datetime(?)) OR
            (datetime(start_time) < datetime(?) AND datetime(end_time) > datetime(?)) OR
            (datetime(start_time) >= datetime(?) AND datetime(end_time) <= datetime(?))
        )
    '''
    
    params = [
        end_time.isoformat(), start_time.isoformat(),
        end_time.isoformat(), start_time.isoformat(),
        start_time.isoformat(), end_time.isoformat()
    ]
    
    if exclude_user_id:
        query += ' AND user_id != ?'
        params.append(exclude_user_id)
    
    cursor.execute(query, params)
    conflicts = cursor.fetchall()
    conn.close()
    
    return [{'user_id': c[0], 'start_time': c[1], 'end_time': c[2], 'approved': c[3]} for c in conflicts]

def create_reservation(user_id: int, start_time: datetime, end_time: datetime):
    """Create a new reservation"""
    conn = sqlite3.connect('poloseek.db')
    cursor = conn.cursor()
    
    # ensure times are in CDT and convert to ISO format
    start_time = ensure_cdt_timezone(start_time)
    end_time = ensure_cdt_timezone(end_time)
    
    cursor.execute(
        'INSERT INTO reservations (user_id, start_time, end_time) VALUES (?, ?, ?)',
        (user_id, start_time.isoformat(), end_time.isoformat())
    )
    conn.commit()
    conn.close()

def get_reservations() -> List[Dict]:
    """Get all active reservations"""
    conn = sqlite3.connect('poloseek.db')
    cursor = conn.cursor()
    cursor.execute(
        'SELECT user_id, start_time, end_time, approved FROM reservations WHERE active_status = TRUE ORDER BY datetime(start_time)'
    )
    reservations = cursor.fetchall()
    conn.close()
    
    return [{'user_id': r[0], 'start_time': r[1], 'end_time': r[2], 'approved': bool(r[3])} for r in reservations]

def get_user_reservations(user_id: int) -> List[Dict]:
    """Get all active reservations for a specific user"""
    conn = sqlite3.connect('poloseek.db')
    cursor = conn.cursor()
    cursor.execute(
        'SELECT user_id, start_time, end_time FROM reservations WHERE user_id = ? AND active_status = TRUE ORDER BY datetime(start_time)',
        (user_id,)
    )
    reservations = cursor.fetchall()
    conn.close()
    
    return [{'user_id': r[0], 'start_time': r[1], 'end_time': r[2]} for r in reservations]

def get_user_active_reservations(user_id: int, current_time: datetime) -> List[Dict]:
    """Get currently active reservations for a specific user"""
    conn = sqlite3.connect('poloseek.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, start_time, end_time 
        FROM reservations 
        WHERE user_id = ? 
        AND active_status = TRUE 
        AND datetime(start_time) <= datetime(?)
        AND datetime(end_time) > datetime(?)
        ORDER BY datetime(start_time)
    ''', (user_id, current_time.isoformat(), current_time.isoformat()))
    
    reservations = cursor.fetchall()
    conn.close()
    
    return [{'user_id': r[0], 'start_time': r[1], 'end_time': r[2]} for r in reservations]

def get_next_reservation_for_user(user_id: int) -> Optional[Dict]:
    """Get the next pending reservation for a specific user"""
    conn = sqlite3.connect('poloseek.db')
    cursor = conn.cursor()
    now = datetime.now(CDT).isoformat()
    cursor.execute(
        '''SELECT user_id, start_time, end_time 
           FROM reservations 
           WHERE user_id = ? AND active_status = TRUE AND datetime(start_time) > datetime(?)
           ORDER BY datetime(start_time) LIMIT 1''',
        (user_id, now)
    )
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return {'user_id': result[0], 'start_time': result[1], 'end_time': result[2]}
    return None

def get_next_approved_reservation(current_time: Optional[datetime] = None) -> Optional[Dict]:
    """Get the next approved reservation that should start now or in the future"""
    if current_time is None:
        current_time = datetime.now(CDT)
    
    # add 1-second buffer for edge cases
    buffer_time = current_time - timedelta(seconds=1)
    
    conn = sqlite3.connect('poloseek.db')
    cursor = conn.cursor()
    cursor.execute(
        '''SELECT user_id, start_time, end_time 
           FROM reservations 
           WHERE active_status = TRUE 
           AND approved = TRUE 
           AND datetime(start_time) <= datetime(?)
           AND datetime(end_time) > datetime(?)
           ORDER BY datetime(start_time) LIMIT 1''',
        (buffer_time.isoformat(), current_time.isoformat())
    )
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return {'user_id': result[0], 'start_time': result[1], 'end_time': result[2]}
    return None

def get_user_next_unapproved_reservation(user_id: int) -> Optional[Dict]:
    """Get the next unapproved reservation for a specific user"""
    conn = sqlite3.connect('poloseek.db')
    cursor = conn.cursor()
    now = datetime.now(CDT).isoformat()
    cursor.execute(
        '''SELECT user_id, start_time, end_time 
           FROM reservations 
           WHERE user_id = ? AND active_status = TRUE AND approved = FALSE AND datetime(start_time) > datetime(?)
           ORDER BY datetime(start_time) LIMIT 1''',
        (user_id, now)
    )
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return {'user_id': result[0], 'start_time': result[1], 'end_time': result[2]}
    return None

def approve_reservation_by_details(user_id: int, start_time: str):
    """Mark a specific reservation as approved using transaction"""
    conn = sqlite3.connect('poloseek.db')
    conn.isolation_level = 'EXCLUSIVE'
    
    try:
        cursor = conn.cursor()
        cursor.execute('BEGIN EXCLUSIVE')
        cursor.execute(
            'UPDATE reservations SET approved = TRUE WHERE user_id = ? AND start_time = ? AND active_status = TRUE',
            (user_id, start_time)
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error approving reservation: {e}")
    finally:
        conn.close()

def get_expired_reservations(current_time: datetime) -> List[Dict]:
    """Get reservations that have expired"""
    conn = sqlite3.connect('poloseek.db')
    cursor = conn.cursor()
    cursor.execute(
        'SELECT user_id, start_time, end_time FROM reservations WHERE active_status = TRUE AND substr(end_time, 1, 19) <= ?',
        (current_time.replace(tzinfo=None).isoformat(),)
    )
    expired = cursor.fetchall()
    conn.close()
    
    return [{'user_id': r[0], 'start_time': r[1], 'end_time': r[2]} for r in expired]

def mark_reservation_inactive(user_id: int, start_time: str):
    """Mark a reservation as inactive"""
    conn = sqlite3.connect('poloseek.db')
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE reservations SET active_status = FALSE WHERE user_id = ? AND start_time = ?',
        (user_id, start_time)
    )
    conn.commit()
    conn.close()

def clear_user_pending_reservations(user_id: int):
    """Clear all pending reservations for a user"""
    conn = sqlite3.connect('poloseek.db')
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE reservations SET active_status = FALSE WHERE user_id = ? AND active_status = TRUE',
        (user_id,)
    )
    conn.commit()
    conn.close()

def approve_reservation(user_id: int, start_time: str):
    """Approve a reservation."""
    approve_reservation_by_details(user_id, start_time)

def get_user_memo(user_id: int) -> Optional[str]:
    """Get user's parking memo"""
    conn = sqlite3.connect('poloseek.db')
    cursor = conn.cursor()
    cursor.execute('SELECT parking_memo FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    return result[0] if result else None

def is_reservation_ready_to_start(reservation: Dict, current_time: datetime) -> bool:
    """Check if a reservation should start now with 1-second buffer"""
    start_time = ensure_cdt_timezone(datetime.fromisoformat(reservation['start_time']))
    
    # add small buffer for edge cases
    buffer_time = current_time - timedelta(seconds=1)
    return start_time <= buffer_time

def cleanup_old_reservations(cutoff_date: datetime):
    """Delete old inactive reservations from the database"""
    conn = sqlite3.connect('poloseek.db')
    cursor = conn.cursor()
    
    # delete inactive reservations older than cutoff date
    cursor.execute('''
        DELETE FROM reservations 
        WHERE active_status = FALSE 
        AND datetime(end_time) < datetime(?)
    ''', (cutoff_date.isoformat(),))
    
    deleted_count = cursor.rowcount
    conn.commit()
    conn.close()
    
    print(f"Deleted {deleted_count} old reservation records")
    return deleted_count

def get_user_most_recent_approved_reservation(user_id: int) -> Optional[Dict]:
    """Get the most recent approved reservation for a specific user"""
    conn = sqlite3.connect('poloseek.db')
    cursor = conn.cursor()
    cursor.execute(
        '''SELECT user_id, start_time, end_time 
        FROM reservations 
        WHERE user_id = ? AND active_status = TRUE AND approved = TRUE
        ORDER BY datetime(start_time) DESC LIMIT 1''',
        (user_id,)
    )
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return {'user_id': result[0], 'start_time': result[1], 'end_time': result[2]}
    return None
