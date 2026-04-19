"""Mock External API Lambda handler.

Returns realistic Indian travel data for all 8 external API endpoints
so the AI agents receive meaningful context to pass to Bedrock.

Routes:
    GET /trains/search          — IRCTC-style train routes
    GET /flights/search         — Domestic flight options
    GET /accommodations/search  — Hotel/hostel/homestay listings
    GET /pricing/transport      — Transport cost data
    GET /pricing/accommodation  — Accommodation pricing tiers
    GET /pricing/activities     — Activity/experience pricing
    GET /weather/forecast       — IMD-style weather forecasts
    GET /tourism/experiences    — Curated tourism experiences
"""

import json
import hashlib
from datetime import date, timedelta

# ---------------------------------------------------------------------------
# Seed data — realistic Indian travel content
# ---------------------------------------------------------------------------

CITIES = ["Delhi", "Mumbai", "Jaipur", "Goa", "Varanasi", "Udaipur", "Kochi", "Manali", "Rishikesh", "Darjeeling"]

TRAINS = [
    {"name": "Rajdhani Express", "number": "12952", "from": "Delhi", "to": "Mumbai", "duration_hours": 15.5, "classes": ["1A", "2A", "3A"], "fare_inr": {"1A": 4215, "2A": 2470, "3A": 1730}},
    {"name": "Shatabdi Express", "number": "12002", "from": "Delhi", "to": "Jaipur", "duration_hours": 4.5, "classes": ["CC", "EC"], "fare_inr": {"CC": 870, "EC": 1640}},
    {"name": "Duronto Express", "number": "12284", "from": "Delhi", "to": "Goa", "duration_hours": 23, "classes": ["2A", "3A", "SL"], "fare_inr": {"2A": 2890, "3A": 1950, "SL": 780}},
    {"name": "Garib Rath", "number": "12216", "from": "Delhi", "to": "Varanasi", "duration_hours": 11.5, "classes": ["3A"], "fare_inr": {"3A": 1105}},
    {"name": "Vande Bharat Express", "number": "22436", "from": "Delhi", "to": "Varanasi", "duration_hours": 8, "classes": ["CC", "EC"], "fare_inr": {"CC": 1570, "EC": 2860}},
    {"name": "Palace on Wheels", "number": "POW01", "from": "Delhi", "to": "Jaipur", "duration_hours": 6, "classes": ["1A"], "fare_inr": {"1A": 8500}},
    {"name": "Konkan Kanya Express", "number": "10112", "from": "Mumbai", "to": "Goa", "duration_hours": 12, "classes": ["2A", "3A", "SL"], "fare_inr": {"2A": 1680, "3A": 1150, "SL": 450}},
    {"name": "Kerala Express", "number": "12626", "from": "Delhi", "to": "Kochi", "duration_hours": 43, "classes": ["1A", "2A", "3A", "SL"], "fare_inr": {"1A": 5340, "2A": 3120, "3A": 2180, "SL": 870}},
]

FLIGHTS = [
    {"airline": "IndiGo", "code": "6E-2145", "from": "Delhi", "to": "Mumbai", "duration_hours": 2.1, "fare_inr": 4500, "departure": "06:30", "arrival": "08:40"},
    {"airline": "Air India", "code": "AI-865", "from": "Delhi", "to": "Goa", "duration_hours": 2.5, "fare_inr": 5800, "departure": "09:15", "arrival": "11:45"},
    {"airline": "SpiceJet", "code": "SG-723", "from": "Delhi", "to": "Jaipur", "duration_hours": 1.0, "fare_inr": 3200, "departure": "07:00", "arrival": "08:00"},
    {"airline": "Vistara", "code": "UK-945", "from": "Delhi", "to": "Varanasi", "duration_hours": 1.5, "fare_inr": 4800, "departure": "10:30", "arrival": "12:00"},
    {"airline": "IndiGo", "code": "6E-5067", "from": "Delhi", "to": "Kochi", "duration_hours": 3.2, "fare_inr": 6200, "departure": "05:45", "arrival": "09:00"},
    {"airline": "Air India", "code": "AI-470", "from": "Mumbai", "to": "Goa", "duration_hours": 1.2, "fare_inr": 3800, "departure": "14:00", "arrival": "15:10"},
    {"airline": "Vistara", "code": "UK-627", "from": "Delhi", "to": "Udaipur", "duration_hours": 1.5, "fare_inr": 4200, "departure": "08:20", "arrival": "09:50"},
    {"airline": "IndiGo", "code": "6E-6103", "from": "Delhi", "to": "Manali", "duration_hours": 1.8, "fare_inr": 5500, "departure": "06:00", "arrival": "07:50"},
]

ACCOMMODATIONS = [
    {"name": "Taj Lake Palace", "type": "hotel", "city": "Udaipur", "rating": 4.8, "cost_per_night_inr": 28000, "amenities": ["pool", "spa", "lake view", "restaurant"]},
    {"name": "Zostel Jaipur", "type": "hostel", "city": "Jaipur", "rating": 4.3, "cost_per_night_inr": 650, "amenities": ["wifi", "common kitchen", "rooftop"]},
    {"name": "The Oberoi Amarvilas", "type": "hotel", "city": "Agra", "rating": 4.9, "cost_per_night_inr": 35000, "amenities": ["Taj view", "pool", "spa", "fine dining"]},
    {"name": "Treebo Trend Royal", "type": "hotel", "city": "Goa", "rating": 3.8, "cost_per_night_inr": 2200, "amenities": ["wifi", "AC", "breakfast"]},
    {"name": "Madpackers Hostel", "type": "hostel", "city": "Delhi", "rating": 4.1, "cost_per_night_inr": 800, "amenities": ["wifi", "lockers", "common area"]},
    {"name": "Rambagh Palace", "type": "hotel", "city": "Jaipur", "rating": 4.7, "cost_per_night_inr": 22000, "amenities": ["heritage", "pool", "spa", "gardens"]},
    {"name": "Old Quarter Goa", "type": "homestay", "city": "Goa", "rating": 4.5, "cost_per_night_inr": 3500, "amenities": ["beach access", "breakfast", "wifi"]},
    {"name": "Hotel & Spa Manali", "type": "resort", "city": "Manali", "rating": 4.2, "cost_per_night_inr": 4800, "amenities": ["mountain view", "spa", "restaurant"]},
    {"name": "BrijRama Palace", "type": "hotel", "city": "Varanasi", "rating": 4.6, "cost_per_night_inr": 12000, "amenities": ["Ganga view", "heritage", "restaurant"]},
    {"name": "Brunton Boatyard", "type": "hotel", "city": "Kochi", "rating": 4.5, "cost_per_night_inr": 9500, "amenities": ["harbour view", "pool", "Ayurveda spa"]},
]

EXPERIENCES = [
    {"name": "Old Delhi Food Walk", "type": "food", "city": "Delhi", "duration_hours": 3, "cost_inr": 1500, "description": "Guided walk through Chandni Chowk sampling paranthas, jalebis, and kebabs"},
    {"name": "Amber Fort Elephant Ride", "type": "culture", "city": "Jaipur", "duration_hours": 2, "cost_inr": 1200, "description": "Ride up to Amber Fort like Rajput royalty"},
    {"name": "Ganga Aarti Ceremony", "type": "culture", "city": "Varanasi", "duration_hours": 1.5, "cost_inr": 0, "description": "Witness the spectacular evening fire ceremony at Dashashwamedh Ghat"},
    {"name": "Spice Plantation Tour", "type": "culture", "city": "Kochi", "duration_hours": 4, "cost_inr": 800, "description": "Walk through cardamom, pepper, and vanilla plantations in Munnar"},
    {"name": "Dudhsagar Falls Trek", "type": "adventure", "city": "Goa", "duration_hours": 6, "cost_inr": 2500, "description": "Trek through the Western Ghats to India's fifth tallest waterfall"},
    {"name": "Yoga Retreat Session", "type": "relaxation", "city": "Rishikesh", "duration_hours": 3, "cost_inr": 600, "description": "Morning yoga and meditation by the Ganges with certified instructors"},
    {"name": "Solang Valley Paragliding", "type": "adventure", "city": "Manali", "duration_hours": 1, "cost_inr": 3500, "description": "Tandem paragliding over the Kullu Valley at 8000 feet"},
    {"name": "Darjeeling Tea Tasting", "type": "food", "city": "Darjeeling", "duration_hours": 2, "cost_inr": 500, "description": "Visit Happy Valley Tea Estate and taste first-flush Darjeeling teas"},
    {"name": "Jodhpur Blue City Walk", "type": "sightseeing", "city": "Jodhpur", "duration_hours": 3, "cost_inr": 900, "description": "Explore the narrow blue-painted lanes of the old Brahmin quarter"},
    {"name": "Backwater Houseboat Cruise", "type": "relaxation", "city": "Kochi", "duration_hours": 8, "cost_inr": 7000, "description": "Overnight cruise through Alleppey backwaters on a traditional kettuvallam"},
]

# Base weather patterns by month (temp_min, temp_max, precip_mm, conditions)
_WEATHER_BY_MONTH = {
    1: (8, 21, 15, "Clear sky"),
    2: (10, 25, 10, "Mainly clear"),
    3: (15, 32, 8, "Partly cloudy"),
    4: (22, 38, 5, "Clear sky"),
    5: (27, 42, 12, "Partly cloudy"),
    6: (28, 40, 80, "Thunderstorm"),
    7: (26, 35, 220, "Heavy rain"),
    8: (25, 34, 200, "Heavy rain"),
    9: (24, 34, 130, "Rain showers"),
    10: (19, 33, 20, "Partly cloudy"),
    11: (12, 28, 5, "Clear sky"),
    12: (7, 22, 8, "Mainly clear"),
}


def _hash_seed(s: str) -> int:
    """Deterministic seed from a string so same query returns same data."""
    return int(hashlib.md5(s.encode()).hexdigest()[:8], 16)


def _generate_daily_forecasts(start_str: str, end_str: str) -> list[dict]:
    """Generate daily weather forecasts for a date range."""
    try:
        start = date.fromisoformat(start_str)
        end = date.fromisoformat(end_str)
    except (ValueError, TypeError):
        start = date.today()
        end = start + timedelta(days=5)

    forecasts = []
    current = start
    while current <= end:
        m = current.month
        base = _WEATHER_BY_MONTH.get(m, (20, 30, 10, "Partly cloudy"))
        seed = _hash_seed(current.isoformat())
        jitter = (seed % 7) - 3  # -3 to +3 variation
        forecasts.append({
            "date": current.isoformat(),
            "temp_min_c": base[0] + jitter,
            "temp_max_c": base[1] + jitter,
            "precipitation_mm": max(0, base[2] + (seed % 20) - 10),
            "precipitation_probability_pct": min(100, base[2] + (seed % 30)),
            "conditions": base[3],
            "wind_speed_kmh": 8 + (seed % 15),
            "humidity_pct": 40 + (seed % 40),
        })
        current += timedelta(days=1)
    return forecasts


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

def _handle_trains(params: dict) -> dict:
    return {"routes": TRAINS, "total": len(TRAINS)}


def _handle_flights(params: dict) -> dict:
    return {"flights": FLIGHTS, "total": len(FLIGHTS)}


def _handle_accommodations(params: dict) -> dict:
    return {"listings": ACCOMMODATIONS, "total": len(ACCOMMODATIONS)}


def _handle_transport_pricing(params: dict) -> dict:
    prices = []
    for t in TRAINS[:4]:
        for cls, fare in t["fare_inr"].items():
            prices.append({"mode": "train", "name": t["name"], "class": cls, "fare_inr": fare, "route": f"{t['from']}-{t['to']}"})
    for f in FLIGHTS[:4]:
        prices.append({"mode": "flight", "name": f"{f['airline']} {f['code']}", "class": "economy", "fare_inr": f["fare_inr"], "route": f"{f['from']}-{f['to']}"})
    prices.append({"mode": "bus", "name": "RSRTC Volvo", "class": "AC", "fare_inr": 950, "route": "Delhi-Jaipur"})
    prices.append({"mode": "car", "name": "Sedan Rental", "class": "standard", "fare_inr": 3500, "route": "per day"})
    return {"prices": prices, "currency": "INR"}


def _handle_accommodation_pricing(params: dict) -> dict:
    prices = []
    for a in ACCOMMODATIONS:
        prices.append({
            "name": a["name"],
            "type": a["type"],
            "city": a["city"],
            "cost_per_night_inr": a["cost_per_night_inr"],
            "rating": a["rating"],
            "tier": "budget" if a["cost_per_night_inr"] < 2000 else "comfort" if a["cost_per_night_inr"] < 10000 else "luxury",
        })
    return {"prices": prices, "currency": "INR"}


def _handle_activity_pricing(params: dict) -> dict:
    prices = [{"name": e["name"], "type": e["type"], "city": e["city"], "cost_inr": e["cost_inr"], "duration_hours": e["duration_hours"]} for e in EXPERIENCES]
    return {"prices": prices, "currency": "INR"}


def _handle_weather(params: dict) -> dict:
    start = params.get("start", date.today().isoformat())
    end = params.get("end", (date.today() + timedelta(days=5)).isoformat())
    forecasts = _generate_daily_forecasts(start, end)
    monsoon_months = {6, 7, 8, 9}
    has_monsoon = any(date.fromisoformat(f["date"]).month in monsoon_months for f in forecasts)
    return {
        "forecasts": forecasts,
        "monsoon_warning": has_monsoon,
        "advisory": "Heavy monsoon rains expected. Carry waterproof gear and check transport status." if has_monsoon else None,
    }


def _handle_tourism(params: dict) -> dict:
    return {"experiences": EXPERIENCES, "total": len(EXPERIENCES)}


# Route table
_ROUTES = {
    "/trains/search": _handle_trains,
    "/flights/search": _handle_flights,
    "/accommodations/search": _handle_accommodations,
    "/pricing/transport": _handle_transport_pricing,
    "/pricing/accommodation": _handle_accommodation_pricing,
    "/pricing/activities": _handle_activity_pricing,
    "/weather/forecast": _handle_weather,
    "/tourism/experiences": _handle_tourism,
}


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------

def handler(event, context):
    path = event.get("path", "") or event.get("rawPath", "")
    params = event.get("queryStringParameters") or {}

    route_handler = _ROUTES.get(path)
    if route_handler is None:
        return _response(404, {"error": f"Unknown route: {path}", "available_routes": list(_ROUTES.keys())})

    data = route_handler(params)
    return _response(200, data)


def _response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
        "body": json.dumps(body),
    }
