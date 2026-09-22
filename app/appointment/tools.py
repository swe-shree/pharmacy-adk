from app.database import database as DB
from app.tools.common import safe_tool, text


def _appointment(user_id: str, appointment_id: str) -> dict:
    appointment = next((a for a in DB["appointments"] if a["id"] == appointment_id and a["user_id"] == user_id), None)
    if not appointment:
        raise ValueError("Appointment not found")
    return appointment


@safe_tool
def search_doctors(specialty: str, city: str = "Bengaluru") -> dict:
    """Find doctors by specialty and city."""
    specialty, city = text(specialty, "specialty").lower(), text(city, "city").lower()
    return {"doctors": [dict(d) for d in DB["doctors"] if specialty in d["specialty"].lower() and d["city"].lower() == city]}


@safe_tool
def get_doctor_availability(doctor_id: str, date: str) -> dict:
    """List deterministic available slots for a doctor and date."""
    doctor_id, date = text(doctor_id, "doctor_id"), text(date, "date")
    if not any(d["id"] == doctor_id for d in DB["doctors"]):
        raise ValueError("Doctor not found")
    booked = any(a["doctor_id"] == doctor_id and a["date"] == date and a["status"] != "cancelled" for a in DB["appointments"])
    return {"doctor_id": doctor_id, "date": date, "slots": [] if booked else ["10:00", "14:00", "16:30"]}


@safe_tool
def list_appointments(user_id: str = "user_001") -> dict:
    """List appointments for a user."""
    return {"appointments": [dict(a) for a in DB["appointments"] if a["user_id"] == text(user_id, "user_id")]}


@safe_tool
def get_appointment(appointment_id: str, user_id: str = "user_001") -> dict:
    """Get one appointment belonging to a user."""
    return dict(_appointment(text(user_id, "user_id"), text(appointment_id, "appointment_id")))


@safe_tool
def book_appointment(doctor_id: str, date: str, time: str, user_id: str = "user_001") -> dict:
    """Book an available doctor slot."""
    doctor_id, date, time, user_id = text(doctor_id, "doctor_id"), text(date, "date"), text(time, "time"), text(user_id, "user_id")
    slots = get_doctor_availability.__wrapped__(doctor_id, date)["slots"]
    if time not in slots:
        raise ValueError("Requested slot is unavailable")
    appointment = {"id": f"appt_{len(DB['appointments']) + 1:03d}", "user_id": user_id, "doctor_id": doctor_id, "date": date, "time": time, "status": "confirmed"}
    DB["appointments"].append(appointment)
    return appointment


@safe_tool
def reschedule_appointment(appointment_id: str, date: str, time: str, user_id: str = "user_001") -> dict:
    """Move a user's appointment to an available slot."""
    user_id, appointment_id, date, time = text(user_id, "user_id"), text(appointment_id, "appointment_id"), text(date, "date"), text(time, "time")
    appointment = _appointment(user_id, appointment_id)
    if time not in get_doctor_availability.__wrapped__(appointment["doctor_id"], date)["slots"]:
        raise ValueError("Requested slot is unavailable")
    appointment.update({"date": date, "time": time})
    return dict(appointment)


@safe_tool
def cancel_appointment(appointment_id: str, user_id: str = "user_001") -> dict:
    """Cancel a user's appointment."""
    appointment = _appointment(text(user_id, "user_id"), text(appointment_id, "appointment_id"))
    appointment["status"] = "cancelled"
    return dict(appointment)


@safe_tool
def get_appointment_status(appointment_id: str, user_id: str = "user_001") -> dict:
    """Get the status of a user's appointment."""
    appointment = _appointment(text(user_id, "user_id"), text(appointment_id, "appointment_id"))
    return {"appointment_id": appointment["id"], "status": appointment["status"]}


APPOINTMENT_TOOLS = [search_doctors, get_doctor_availability, list_appointments, get_appointment, book_appointment, reschedule_appointment, cancel_appointment, get_appointment_status]
