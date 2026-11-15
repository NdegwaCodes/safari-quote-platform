from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.documents.fonts import font_stack

DOCUMENT_SETTINGS_KEY = "document"

_FONT_STACK = re.compile(r"[A-Za-z0-9 '\"_.,-]{1,200}")


class DocumentConfig(BaseModel):

    model_config = ConfigDict(extra="ignore")

    company_name: str = Field(default="Acacia Tours & Travel")
    contact_email: str = Field(default="info@example.com")
    contact_phone: str = Field(default="+254 700 000 000")
    social_line: str = Field(default="DM us directly through our social platforms")
    tagline_lines: list[str] = Field(
        default_factory=lambda: [
            "Curated Journeys.",
            "Authentic Experiences.",
            "Exceptional Service.",
        ]
    )

    proposal_kind: str = Field(default="Corporate Travel Proposal")
    welcome_eyebrow: str = Field(default="Welcome")
    why_us_heading: str = Field(default="Why Acacia Tours?")
    why_us_points: list[str] = Field(
        default_factory=lambda: [
            "Curated accommodation selection",
            "Private group transportation",
            "Flexible accommodation options",
            "End-to-end travel planning",
            "Dedicated trip coordination",
            "Supplier coordination",
            "Professional pre-trip support",
        ]
    )
    coordination_heading: str = Field(default="Included in our coordination")
    coordination_points: list[str] = Field(
        default_factory=lambda: [
            "Accommodation sourcing",
            "Group transportation coordination",
            "Supplier liaison",
            "Group logistics",
            "Room allocation",
            "Trip planning",
            "Pre-trip communication",
            "On-trip coordination",
        ]
    )
    next_steps_heading: str = Field(default="Let's Create Your Experience")
    next_steps_body: str = Field(
        default=(
            "Once your preferred accommodation option has been selected, our team "
            "will proceed with availability confirmation, room allocation, transport "
            "scheduling and final itinerary coordination."
        )
    )

    exclusions_heading: str = Field(default="What the quoted price excludes")
    exclusions: list[str] = Field(
        default_factory=lambda: [
            "Travel insurance",
            "Airport taxes, visa fees and travel documentation",
            "Meals and drinks beyond the stated meal plan",
            "Personal expenses — laundry, telephone, minibar and shopping",
            "Optional activities and excursions not listed as included",
            "Tips and gratuities",
        ]
    )
    exclusions_note: str = Field(
        default=(
            "Anything not listed as included in your selected option is not "
            "covered by the quoted price. We are glad to quote separately for "
            "any of it."
        )
    )

    availability_notice_heading: str = Field(
        default="Accommodation availability & booking"
    )
    availability_notice: str = Field(
        default=(
            "All accommodation options and quoted rates are subject to availability "
            "at the time of booking. We strongly recommend confirming your preferred "
            "accommodation as early as possible to secure availability and ensure a "
            "smooth experience, especially for group bookings. Rates may be subject "
            "to change where supplier rates or availability change prior to "
            "confirmation."
        )
    )
    closing_disclaimer: str = Field(
        default=(
            "All prices quoted are inclusive of VAT and are based on the current "
            "group requirements and supplier quotations available at the time of "
            "preparation. Accommodation and related services remain subject to "
            "availability and final confirmation at the time of booking."
        )
    )
    vat_note: str = Field(default="All prices inclusive of 16% VAT")

    font_display: str = Field(default=font_stack("Cormorant Garamond"))
    font_body: str = Field(default=font_stack("Libre Franklin"))
    fonts_are_placeholders: bool = Field(default=False)

    @field_validator("font_display", "font_body")
    @classmethod
    def _css_safe_font_stack(cls, value: str) -> str:
        if not _FONT_STACK.fullmatch(value):
            raise ValueError(
                "A font stack may contain only letters, digits, spaces, quotes, "
                "hyphens, underscores, dots and commas."
            )
        return value

    page_size: str = Field(default="A4", pattern="^(A4|Letter)$")
