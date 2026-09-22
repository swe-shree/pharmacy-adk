from pathlib import Path
from uuid import uuid4

from app.database import database as DB
from app.tools.common import safe_tool, text


# ============================================================
# PRESCRIPTIONS
# ============================================================

@safe_tool
def list_prescriptions(user_id: str = "user_001") -> dict:
    """List prescriptions recorded for a user."""

    user_id = text(user_id, "user_id")

    return {
        "prescriptions": [
            dict(p)
            for p in DB["prescriptions"]
            if p["user_id"] == user_id
        ]
    }


@safe_tool
def get_prescription(
    prescription_id: str,
    user_id: str = "user_001",
) -> dict:
    """Get one prescription belonging to a user."""

    prescription_id = text(prescription_id, "prescription_id")
    user_id = text(user_id, "user_id")

    prescription = next(
        (
            p
            for p in DB["prescriptions"]
            if p["id"] == prescription_id
            and p["user_id"] == user_id
        ),
        None,
    )

    if not prescription:
        raise ValueError("Prescription not found")

    return dict(prescription)


@safe_tool
def upload_prescription(
    file_path: str,
    user_id: str = "user_001",
) -> dict:
    """
    Register an uploaded prescription file.

    Supported:
    PDF, JPG, JPEG, PNG, WEBP

    This tool only validates and stores the uploaded prescription.
    It does not provide medical interpretation.
    """

    file_path = text(file_path, "file_path")
    user_id = text(user_id, "user_id")

    path = Path(file_path)

    if not path.exists():
        raise ValueError("Prescription file not found")

    allowed_extensions = {
        ".pdf",
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
    }

    if path.suffix.lower() not in allowed_extensions:
        raise ValueError(
            "Unsupported prescription format. "
            "Use PDF, JPG, JPEG, PNG or WEBP."
        )

    prescription_id = f"rx_{uuid4().hex[:8]}"

    prescription = {
        "id": prescription_id,
        "user_id": user_id,
        "file_name": path.name,
        "file_path": str(path),
        "file_type": path.suffix.lower().replace(".", ""),
        "status": "uploaded",
        "medicines": [],
    }

    DB["prescriptions"].append(prescription)

    return {
        "prescription_id": prescription_id,
        "file_name": path.name,
        "status": "uploaded",
        "message": "Prescription uploaded successfully.",
    }


@safe_tool
def read_prescription(
    prescription_id: str,
    user_id: str = "user_001",
) -> dict:
    """
    Read a stored prescription and return extracted medicine data.

    OCR / vision extraction is not performed by this operation; it returns
    only extraction data recorded by the prescription-processing service.
    """

    prescription_id = text(prescription_id, "prescription_id")
    user_id = text(user_id, "user_id")

    prescription = next(
        (
            p
            for p in DB["prescriptions"]
            if p["id"] == prescription_id
            and p["user_id"] == user_id
        ),
        None,
    )

    if not prescription:
        raise ValueError("Prescription not found")

    medicines = prescription.get("medicines", [])

    return {
        "prescription_id": prescription_id,
        "status": "processed",
        "medicines": medicines,
        "medicine_count": len(medicines),
        "message": (
            "Prescription processed successfully."
            if medicines
            else "No medicines were extracted from the prescription."
        ),
    }


@safe_tool
def prepare_prescription_medicines_for_cart(
    prescription_id: str,
    user_id: str = "user_001",
) -> dict:
    """
    Prepare prescription medicines for commerce.

    This does not add anything to the cart.
    It only returns medicines that need to be resolved
    by the Commerce Agent.
    """

    prescription_id = text(prescription_id, "prescription_id")
    user_id = text(user_id, "user_id")

    prescription = next(
        (
            p
            for p in DB["prescriptions"]
            if p["id"] == prescription_id
            and p["user_id"] == user_id
        ),
        None,
    )

    if not prescription:
        raise ValueError("Prescription not found")

    medicines = prescription.get("medicines", [])

    if not medicines:
        return {
            "prescription_id": prescription_id,
            "items": [],
            "message": "No medicines available to add to cart.",
        }

    items = []

    for medicine in medicines:
        items.append(
            {
                "prescribed_name": medicine.get("name"),
                "strength": medicine.get("strength"),
                "dosage": medicine.get("dosage"),
                "frequency": medicine.get("frequency"),
                "duration": medicine.get("duration"),
            }
        )

    return {
        "prescription_id": prescription_id,
        "items": items,
        "message": "Prescription medicines are ready for product matching.",
    }


@safe_tool
def request_refill(
    prescription_id: str,
    user_id: str = "user_001",
) -> dict:
    """Provide a non-clinical refill request status."""

    prescription = get_prescription.__wrapped__(
        prescription_id,
        user_id,
    )

    return {
        "prescription_id": prescription["id"],
        "eligible": False,
        "message": "Refill eligibility requires clinician review",
    }


# ============================================================
# HOUSEHOLD
# ============================================================

@safe_tool
def list_household_members(
    user_id: str = "user_001",
) -> dict:
    """List household members associated with a user."""

    user_id = text(user_id, "user_id")

    return {
        "members": [
            dict(m)
            for m in DB["household_members"]
            if m["user_id"] == user_id
        ]
    }


@safe_tool
def get_household_member(
    member_id: str,
    user_id: str = "user_001",
) -> dict:
    """Get one household member belonging to a user."""

    member_id = text(member_id, "member_id")
    user_id = text(user_id, "user_id")

    member = next(
        (
            m
            for m in DB["household_members"]
            if m["id"] == member_id
            and m["user_id"] == user_id
        ),
        None,
    )

    if not member:
        raise ValueError("Household member not found")

    return dict(member)


@safe_tool
def add_household_member(
    name: str,
    relationship: str,
    user_id: str = "user_001",
) -> dict:
    """Add a household member to a user's care profile."""

    user_id = text(user_id, "user_id")
    name = text(name, "name")
    relationship = text(relationship, "relationship")

    member = {
        "id": f"member_{len(DB['household_members']) + 1:03d}",
        "user_id": user_id,
        "name": name,
        "relationship": relationship,
    }

    DB["household_members"].append(member)

    return member


@safe_tool
def remove_household_member(
    member_id: str,
    user_id: str = "user_001",
) -> dict:
    """Remove a household member belonging to a user."""

    member_id = text(member_id, "member_id")
    user_id = text(user_id, "user_id")

    before = len(DB["household_members"])

    DB["household_members"][:] = [
        m
        for m in DB["household_members"]
        if not (
            m["id"] == member_id
            and m["user_id"] == user_id
        )
    ]

    if len(DB["household_members"]) == before:
        raise ValueError("Household member not found")

    return {
        "removed": True,
        "member_id": member_id,
    }


# ============================================================
# CARE
# ============================================================

@safe_tool
def get_care_summary(
    user_id: str = "user_001",
) -> dict:
    """Summarize recorded care data."""

    user_id = text(user_id, "user_id")

    return {
        "user_id": user_id,
        "prescription_count": len(
            [
                p
                for p in DB["prescriptions"]
                if p["user_id"] == user_id
            ]
        ),
        "household_member_count": len(
            [
                m
                for m in DB["household_members"]
                if m["user_id"] == user_id
            ]
        ),
        "note": "Consult a licensed clinician for medical advice",
    }


@safe_tool
def emergency_info() -> str:
    """Provide basic emergency guidance."""

    return (
        "If this is a medical emergency, call your local emergency "
        "services immediately. In India, call 112 or 109 to seek the "
        "nearest emergency department. Do not delay urgent medical "
        "care while using this assistant."
    )


# ============================================================
# CARE TOOLS
# ============================================================

CARE_TOOLS = [
    # Prescription
    list_prescriptions,
    get_prescription,
    upload_prescription,
    read_prescription,
    prepare_prescription_medicines_for_cart,
    request_refill,

    # Household
    list_household_members,
    get_household_member,
    add_household_member,
    remove_household_member,

    # Care
    get_care_summary,
    emergency_info,
]
