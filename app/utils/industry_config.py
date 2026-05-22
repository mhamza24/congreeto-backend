"""
industry_config.py

Per-industry configuration that drives:
  - RAG listing section title and presentation rules in build_dynamic_context
  - The item label used in LLM instructions ("listing", "product", "menu item", etc.)

Adding a new industry: add one entry to REGISTRY. No other code changes needed.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class IndustryConfig:
    rag_section_title:   str
    item_label:          str
    scope_description:   str
    presentation_rules:  tuple[str, ...]


# ── Shared anti-hallucination rule injected as rule #1 for every industry ──
def _no_hallucination_rule(item_label: str) -> str:
    return (
        f"CRITICAL — NEVER name, recommend, or describe any specific {item_label} that does not "
        f"appear in the inventory list above. Your training knowledge contains many {item_label}s "
        f"that are NOT in our inventory — do not use them. If no suitable {item_label} exists in "
        f"the list, say honestly: 'We don't have an exact match in our current inventory' and "
        f"offer only what IS listed. Never invent titles, authors, prices, or details."
    )


REGISTRY: dict[str, IndustryConfig] = {
    "real_estate": IndustryConfig(
        rag_section_title="AVAILABLE PROPERTY LISTINGS",
        item_label="property listing",
        scope_description="residential and commercial property sales, rentals, and real estate enquiries",
        presentation_rules=(
            _no_hallucination_rule("property listing"),
            "Never say 'no results found'. If an exact match is not available, "
            "present the closest 2–3 options from the list and briefly explain why they are worth considering.",
            "When a visitor mentions a budget or bedroom count and no exact match exists, "
            "suggest the nearest options from the list — typically within 10–20% of their stated budget or "
            "one bedroom above/below — and frame it naturally.",
            "Always highlight what makes a listing valuable: price per feature, location lifestyle, "
            "standout features (pool, garage, land size).",
            "Present the top 2–3 most relevant options when possible — give the visitor choice.",
            "When a visitor shows genuine interest, move toward next steps naturally: offer more "
            "details or let them know the team can arrange a viewing.",
        ),
    ),
    "books": IndustryConfig(
        rag_section_title="AVAILABLE BOOKS IN OUR INVENTORY",
        item_label="book",
        scope_description="books, reading recommendations, and titles available in our inventory",
        presentation_rules=(
            _no_hallucination_rule("book"),
            "Only suggest books that appear in the inventory list above. "
            "Do not recommend books from your training data — they are not in our collection.",
            "When a visitor describes what they are looking for (e.g. emotion, topic, age group), "
            "match their needs only to books that appear in the list above.",
            "If none of the listed books match, say: 'We don't have an exact match in our current "
            "collection, but here is what we do carry that may interest you:' and list only what IS available.",
            "Present 2–3 relevant options with title, author, and a brief description from the listing.",
            "Never invent a book title, author name, or description.",
        ),
    ),
    "restaurant": IndustryConfig(
        rag_section_title="AVAILABLE MENU ITEMS",
        item_label="menu item",
        scope_description="food, drinks, and menu items available at this restaurant",
        presentation_rules=(
            _no_hallucination_rule("menu item"),
            "Present 2–3 relevant items when a visitor asks what's available.",
            "Highlight key details: price, description, dietary information if listed.",
            "If an exact item isn't available, suggest alternatives from the menu only.",
        ),
    ),
    "cafe": IndustryConfig(
        rag_section_title="MENU AND OFFERINGS",
        item_label="item",
        scope_description="food, drinks, and offerings available at this cafe",
        presentation_rules=(
            _no_hallucination_rule("item"),
            "Highlight price, description, and dietary options where available.",
            "Suggest popular items or daily specials only if mentioned in the inventory context.",
        ),
    ),
    "ecommerce": IndustryConfig(
        rag_section_title="AVAILABLE PRODUCTS",
        item_label="product",
        scope_description="products available for purchase in this store",
        presentation_rules=(
            _no_hallucination_rule("product"),
            "When a visitor asks for recommendations, present the 2–3 most relevant products from the list.",
            "Highlight key details: price, key features, availability.",
            "If an exact match isn't available, suggest alternatives from the inventory only.",
        ),
    ),
    "retail": IndustryConfig(
        rag_section_title="AVAILABLE PRODUCTS",
        item_label="product",
        scope_description="products available in this store",
        presentation_rules=(
            _no_hallucination_rule("product"),
            "Highlight price, key features, and availability.",
            "Suggest alternatives only from the inventory if an exact match isn't available.",
        ),
    ),
    "healthcare": IndustryConfig(
        rag_section_title="AVAILABLE SERVICES",
        item_label="service",
        scope_description="healthcare services offered by this practice",
        presentation_rules=(
            _no_hallucination_rule("service"),
            "Present service details clearly: what it covers, availability, pricing if listed.",
            "Direct visitors to contact the practice directly for bookings or specific medical advice.",
        ),
    ),
    "legal": IndustryConfig(
        rag_section_title="AVAILABLE SERVICES",
        item_label="service",
        scope_description="legal services offered by this practice",
        presentation_rules=(
            _no_hallucination_rule("service"),
            "Present practice areas clearly. Do not provide specific legal advice.",
            "Encourage visitors to book a consultation for their specific situation.",
        ),
    ),
    "generic": IndustryConfig(
        rag_section_title="AVAILABLE ITEMS",
        item_label="item",
        scope_description="the products and services offered by this business",
        presentation_rules=(
            _no_hallucination_rule("item"),
            "Present the most relevant options based on the visitor's query.",
            "Highlight key details that are available in the context.",
        ),
    ),
}


def get_industry_config(industry: str | None) -> IndustryConfig:
    """Return the IndustryConfig for the given slug, falling back to 'generic'."""
    return REGISTRY.get(industry or "", REGISTRY["generic"])
