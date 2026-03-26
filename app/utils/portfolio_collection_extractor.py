from .system_prompt_portfolio import veloce_portfolio

def get_collection_detail(user_message: str) -> dict | None:
    """
    Returns the full collection detail based on what the visitor is asking about.
    Returns None if the message is general and the summary is enough.
    """
    msg = user_message.lower()

    apartment_keywords = ["apartment", "residence", "penthouse", "rooftop", "level", "floor", "balcony", "apt"]
    house_land_keywords = ["house", "haven", "solara", "marlow", "ellington", "valen", "aurelia", "storey", "alfresco", "theatre", "scullery", "double garage"]
    terrace_keywords = ["terrace", "greenway", "parkfront", "courtyard signature", "corner signature", "townhouse", "lock and leave", "strata"]
    land_keywords = ["land", "lot", "banksia", "build", "block", "frontage", "titled", "construction"]

    if any(k in msg for k in apartment_keywords):
        return {"matched_collection": "apartments", "detail": veloce_portfolio["ApartmentCollection"]}
    if any(k in msg for k in house_land_keywords):
        return {"matched_collection": "house_and_land", "detail": veloce_portfolio["HouseAndLandCollection"]}
    if any(k in msg for k in terrace_keywords):
        return {"matched_collection": "terraces", "detail": veloce_portfolio["TerraceCollection"]}
    if any(k in msg for k in land_keywords):
        return {"matched_collection": "land", "detail": veloce_portfolio["LandCollection"]}

    return None