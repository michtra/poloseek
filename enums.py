"""Enums for PoloSeek"""
from enum import Enum

class ReservationStatus(Enum):
    """Reservation status enum for clearer state management"""
    PENDING = "pending"
    APPROVED = "approved"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
