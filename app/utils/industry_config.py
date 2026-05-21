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
    rag_section_title:  str
    item_label:         str
    presentation_rules: tuple[str, ...]


REGISTRY: dict[str, IndustryConfig] = {
    "real_estate": IndustryConfig(
        rag_section_title="AVAILABLE PROPERTY LISTINGS",
        item_label="listing",
        presentation_rules=(
            "Never say 'no results found'. If an exact match is not available, "
            "present the closest 2–3 options and briefly explain why they are worth considering.",
            "When a visitor mentions a budget or bedroom count and no exact match exists, "
            "suggest the nearest options — typically within 10–20% of their stated budget or "
            "one bedroom above/below — and frame it naturally.",
            "Always highlight what makes a listing valuable: price per feature, location lifestyle, "
            "standout features (pool, garage, land size).",
            "Present the top 2–3 most relevant options when possible — give the visitor choice.",
            "When a visitor shows genuine interest, move toward next steps naturally: offer more "
            "details or let them know the team can arrange a viewing.",
        ),
    ),
    "restaurant": IndustryConfig(
        rag_section_title="AVAILABLE MENU ITEMS",
        item_label="menu item",
        presentation_rules=(
            "Only reference menu items that appear in the context below. Do not invent dishes or prices.",
            "Present 2–3 relevant items when a visitor asks what's available.",
            "Highlight key details: price, description, dietary information if listed.",
            "If an exact item isn't available, suggest alternatives that may suit the visitor's preference.",
        ),
    ),
    "cafe": IndustryConfig(
        rag_section_title="MENU AND OFFERINGS",
        item_label="item",
        presentation_rules=(
            "Only reference items that appear in the context below. Do not invent items or prices.",
            "Highlight price, description, and dietary options where available.",
            "Suggest popular items or daily specials if mentioned in the context.",
        ),
    ),
    "ecommerce": IndustryConfig(
        rag_section_title="AVAILABLE PRODUCTS",
        item_label="product",
        presentation_rules=(
            "Only reference products that appear in the context below. Do not invent products or prices.",
            "When a visitor asks for recommendations, present the 2–3 most relevant products.",
            "Highlight key details: price, key features, availability.",
            "If an exact match isn't available, suggest alternatives.",
        ),
    ),
    "retail": IndustryConfig(
        rag_section_title="AVAILABLE PRODUCTS",
        item_label="product",
        presentation_rules=(
            "Only reference products that appear in the context below.",
            "Highlight price, key features, and availability.",
            "Suggest alternatives if an exact match isn't available.",
        ),
    ),
    "healthcare": IndustryConfig(
        rag_section_title="AVAILABLE SERVICES",
        item_label="service",
        presentation_rules=(
            "Only reference services that appear in the context below.",
            "Present service details clearly: what it covers, availability, pricing if listed.",
            "Direct visitors to contact the practice directly for bookings or specific medical advice.",
        ),
    ),
    "legal": IndustryConfig(
        rag_section_title="AVAILABLE SERVICES",
        item_label="service",
        presentation_rules=(
            "Only reference services that appear in the context below.",
            "Present practice areas clearly. Do not provide specific legal advice.",
            "Encourage visitors to book a consultation for their specific situation.",
        ),
    ),
    "generic": IndustryConfig(
        rag_section_title="AVAILABLE ITEMS",
        item_label="item",
        presentation_rules=(
            "Only reference items that appear in the context below. Do not invent or hallucinate information.",
            "Present the most relevant options based on the visitor's query.",
            "Highlight key details that are available in the context.",
        ),
    ),
}


def get_industry_config(industry: str | None) -> IndustryConfig:
    """Return the IndustryConfig for the given slug, falling back to 'generic'."""
    return REGISTRY.get(industry or "", REGISTRY["generic"])
