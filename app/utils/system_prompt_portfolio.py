# vilara_portfolio_prompt.py
# ─────────────────────────────────────────────────────────────────────────────
# ARIA — Veloce Property Portfolio Prompt
# Vilara Park | All Three Collections
# ─────────────────────────────────────────────────────────────────────────────
# USAGE NOTE:
# This prompt is injected alongside the ARIA system prompt at runtime.
# ARIA uses this data to match visitors to listings, present options with
# authority, and guide conversations toward viewings and consultations.
# In production, replace with real-time database/embedding lookups.
# ─────────────────────────────────────────────────────────────────────────────

veloce_portfolio = {
    "Project": {
        "Name": "Vilara Park Residences",
        "Location": "Ellenbrook, Perth, Western Australia",
        "Overview": (
            "Vilara Park is a boutique, architecturally designed development in Ellenbrook, "
            "positioned directly opposite open parkland and tree-lined walking paths. "
            "The project comprises three distinct collections: boutique luxury apartments, "
            "a signature house and land collection, and a curated terrace collection. "
            "Over 50% already sold. Limited residences remain."
        ),
        "KeySellingPoints": [
            "Boutique scale — only 12 apartments, limited house and land packages, and 4 remaining terraces",
            "Directly opposite landscaped parkland and walking trails",
            "Ground-floor café (Café Vilara) within the building",
            "Resort-style rooftop amenities: heated pool, outdoor dining, gym, cinema, residents' lounge",
            "Strong rental demand and investment appeal in Ellenbrook's growth corridor",
            "Approx 25–30 minutes to Perth CBD via Tonkin Highway",
            "Approx 15 minutes to Swan Valley wineries and restaurants",
            "5 minutes to Ellenbrook Central — Coles, Woolworths, cafés, retail",
            "Close to primary and secondary schools, childcare, and Ellenbrook Train Station",
        ],
        "FinanceOptions": (
            "Structured lending options available through accredited finance partners. "
            "First home buyer eligibility, government grant guidance, deposit strategies, "
            "construction finance, investment loan structures, and pre-approval support all available. "
            "Bespoke finance structuring available for prestige buyers."
        ),
    },

    # ─────────────────────────────────────────────────────────────────────────
    # COLLECTION 1 — VILARA PARK APARTMENTS
    # ─────────────────────────────────────────────────────────────────────────
    "ApartmentCollection": {
        "CollectionName": "Vilara Park Residences — Boutique Apartments",
        "TotalApartments": 12,
        "Availability": "Limited — over 50% sold. Penthouses remain available.",
        "Architecture": (
            "Curved balconies wrap each level, layered with lush planting. "
            "Floor-to-ceiling glazing. Engineered timber flooring. Carrara marble benchtops. "
            "Premium European appliances. Designer tapware and brushed finishes. "
            "Ducted reverse cycle air conditioning. Smart building access and security."
        ),
        "SharedAmenities": [
            "Heated rooftop swimming pool with sun loungers and private cabanas",
            "Outdoor dining terrace and built-in BBQ kitchen",
            "Fully equipped private gym",
            "Boutique residents' cinema (seats up to 10, bookable)",
            "Residents' lounge with dining, entertainment and pool table",
            "Secure foyer and reception with statement finishes",
            "Undercover basement parking with lift connectivity",
            "Smart building access and intercom",
            "Ground-floor Café Vilara",
        ],
        "Listings": [
            {
                "ListingID": "VIL-APT-102",
                "Title": "Residence 102 — Private Garden Apartment",
                "Level": 1,
                "Bedrooms": 2,
                "Bathrooms": 2,
                "CarBays": 1,
                "Type": "Apartment — Ground-Level Garden Residence",
                "PriceFrom": 915000,
                "PriceDisplay": "From $915,000",
                "Availability": "Available",
                "Highlights": [
                    "Private landscaped courtyard via full-height sliding doors",
                    "Carrara stone island bench",
                    "Premium 900mm integrated appliances",
                    "Soft-close cabinetry with warm timber detailing",
                    "Master suite with garden outlook, walk-in robe and spa ensuite",
                    "Full-height tiling and brushed fixtures throughout",
                    "Ducted reverse cycle air conditioning",
                    "Secure basement parking",
                    "Smart building access",
                ],
                "Ideal_For": [
                    "Downsizers wanting outdoor space without maintenance",
                    "Professionals valuing outdoor privacy",
                    "Owner-occupiers seeking boutique apartment living",
                ],
                "KeyPitch": (
                    "One of the few ground-level offerings in a boutique building of just 12. "
                    "Private courtyard, high-end finishes, and the convenience of apartment living — rare combination."
                ),
            },
            {
                "ListingID": "VIL-APT-201",
                "Title": "Residence 201 — Park-Facing Balcony",
                "Level": 2,
                "Bedrooms": 2,
                "Bathrooms": 2,
                "CarBays": 1,
                "Type": "Apartment",
                "PriceFrom": 932000,
                "PriceDisplay": "From $932,000",
                "Availability": "Available",
                "Highlights": [
                    "Curved park-facing balcony with open green outlook",
                    "Carrara stone surfaces in kitchen and bathrooms",
                    "Premium integrated appliances",
                    "Master suite with walk-in robe and ensuite with freestanding bath",
                    "Double-glazed windows",
                    "Secure basement car bay",
                    "Full access to rooftop pool, gym and cinema",
                ],
                "Ideal_For": [
                    "Young professionals",
                    "Investors seeking strong rental appeal",
                    "Lifestyle buyers wanting parkside living",
                ],
                "KeyPitch": (
                    "Elevated above street level with open park views and a curved balcony — "
                    "the kind of morning outlook that makes the commute worth it."
                ),
            },
            {
                "ListingID": "VIL-APT-302",
                "Title": "Residence 302 — Corner Residence",
                "Level": 3,
                "Bedrooms": 2,
                "Bathrooms": 2,
                "Study": True,
                "CarBays": 1,
                "Type": "Apartment — Corner Layout",
                "PriceFrom": 968000,
                "PriceDisplay": "From $968,000",
                "Availability": "Available",
                "Highlights": [
                    "Corner dual-aspect layout with enhanced privacy and airflow",
                    "Dedicated study zone — ideal for work-from-home",
                    "Oversized balcony with architectural curved framing",
                    "Waterfall stone island in kitchen",
                    "Premium appliance package",
                    "Master suite with walk-in robe and elegant ensuite",
                    "Designer lighting and cabinetry",
                    "Secure parking",
                ],
                "Ideal_For": [
                    "Executive buyers wanting location and design integrity",
                    "Professionals needing work-from-home flexibility",
                    "Buyers prioritising light, privacy and cross-ventilation",
                ],
                "KeyPitch": (
                    "Corner position means more light, more privacy, and better airflow — "
                    "plus a dedicated study that actually works, not an afterthought."
                ),
            },
            {
                "ListingID": "VIL-APT-401",
                "Title": "Residence 401 — Elevated Park Outlook",
                "Level": 4,
                "Bedrooms": 3,
                "Bathrooms": 2,
                "CarBays": 2,
                "Type": "Apartment",
                "PriceFrom": 1125000,
                "PriceDisplay": "From $1,125,000",
                "Availability": "Available",
                "Highlights": [
                    "Three full bedrooms — rare in a boutique building",
                    "Sweeping park views from curved balcony",
                    "Open-plan living — expansive yet intimate",
                    "Carrara stone kitchen with premium 900mm appliances and integrated cabinetry",
                    "Double vanity ensuite",
                    "Two secure car bays",
                    "Smart building automation",
                    "Residents-only rooftop amenity access",
                ],
                "Ideal_For": [
                    "Families wanting apartment living with more space",
                    "Downsizers needing a third bedroom for guests or home office",
                    "Investors seeking larger format premium stock",
                ],
                "KeyPitch": (
                    "Scale rarely found in boutique developments — three bedrooms, two car bays, "
                    "park views, and resort amenities. Serious value at this level."
                ),
            },
            {
                "ListingID": "VIL-APT-502",
                "Title": "Residence 502 — Executive Residence",
                "Level": 5,
                "Bedrooms": 3,
                "Bathrooms": 2,
                "Retreat": True,
                "CarBays": 2,
                "Type": "Apartment — Executive Layout",
                "PriceFrom": 1185000,
                "PriceDisplay": "From $1,185,000",
                "Availability": "Available",
                "Highlights": [
                    "Private bedroom wing separate from main living zone",
                    "Dedicated retreat — ideal as media lounge, reading room or children's zone",
                    "Extended curved balcony with treetop and skyline views",
                    "Premium finishes throughout",
                    "Two secure car bays",
                    "Boutique building — only 12 residences total",
                    "Full rooftop amenity access",
                ],
                "Ideal_For": [
                    "Executives valuing privacy and entertaining space",
                    "Families wanting flexibility within apartment living",
                    "Buyers who entertain regularly",
                ],
                "KeyPitch": (
                    "The retreat zone changes how the whole home functions — "
                    "it's not just space, it's flexibility. One of the standout layouts in the building."
                ),
            },
            {
                "ListingID": "VIL-APT-601",
                "Title": "Residence 601 — The Penthouse",
                "Level": 6,
                "Bedrooms": 4,
                "Bathrooms": 3,
                "CarBays": 2,
                "Type": "Penthouse — Entire Top Floor",
                "PriceFrom": None,
                "PriceDisplay": "Price Upon Application",
                "Availability": "Available",
                "Highlights": [
                    "Entire top floor — complete privacy and presence",
                    "Panoramic park and skyline views from expansive curved balcony",
                    "Upgraded stone selections and bespoke cabinetry throughout",
                    "Expansive glazing across all aspects",
                    "Master suite with freestanding bath, double vanity, full-height tiling and dressing zone",
                    "Smart home automation",
                    "Two secure car bays",
                    "Exclusive access to full rooftop resort amenity deck",
                    "Bespoke finance structuring available",
                ],
                "Ideal_For": [
                    "Prestige buyers seeking architectural distinction",
                    "Executive families wanting hotel-inspired boutique living",
                    "Buyers for whom privacy and views are non-negotiable",
                ],
                "KeyPitch": (
                    "The crown of Vilara. Entire top floor, panoramic views, resort amenities below. "
                    "Penthouse opportunities in boutique buildings are rare — this is one of them."
                ),
                "Note": "Enquire directly for pricing. Private finance consultation available.",
            },
        ],
    },

    # ─────────────────────────────────────────────────────────────────────────
    # COLLECTION 2 — SIGNATURE HOUSE & LAND
    # ─────────────────────────────────────────────────────────────────────────
    "HouseAndLandCollection": {
        "CollectionName": "Vilara Park — Signature House & Land Collection",
        "Availability": "Limited release — select packages already sold. Enquire for current availability.",
        "Overview": (
            "Architecturally curated house and land packages within the Vilara Park masterplanned estate. "
            "Premium standard inclusions across all homes: stone benchtops, 900mm cooking appliances, "
            "designer tapware, ducted reverse cycle air conditioning, freestanding baths in master suites, "
            "fully landscaped gardens from day one, and smart-home capability."
        ),
        "StandardInclusions": [
            "Engineered stone benchtops throughout",
            "Premium 900mm oven, cooktop and canopy rangehood",
            "Soft-close cabinetry and designer tapware",
            "Ducted reverse cycle air conditioning",
            "High ceilings to main living areas",
            "Freestanding standalone bath in master suite",
            "Fully landscaped front garden with irrigation",
            "Covered alfresco under main roof",
            "Exposed aggregate driveway",
            "NBN ready and smart-home capable",
            "Secure double garage",
        ],
        "Listings": [
            {
                "ListingID": "VIL-HL-HAVEN",
                "Title": "The Haven — Single Storey",
                "Storeys": 1,
                "Bedrooms": 3,
                "Bathrooms": 2,
                "Study": True,
                "Type": "House & Land",
                "PriceFrom": 699000,
                "PriceDisplay": "From $699,000",
                "Availability": "Available — enquire for land lots",
                "Highlights": [
                    "Open-plan kitchen with stone benchtops and 900mm appliances",
                    "Dedicated study nook — great for remote work or homework",
                    "High ceilings with natural light throughout living zone",
                    "Landscaped backyard — low maintenance but functional",
                    "Master suite with freestanding bath and premium finishes",
                    "Secure double garage",
                ],
                "Ideal_For": [
                    "First home buyers wanting premium inclusions",
                    "Young couples stepping into the market confidently",
                    "Investors targeting first-home buyer rental demand",
                ],
                "KeyPitch": (
                    "Entry point to the collection — but it doesn't feel like one. "
                    "Premium inclusions, smart layout, and a price that works for first home buyers."
                ),
                "FirstHomeBuyerNote": (
                    "Eligible WA first home buyers may qualify for the First Home Owner Grant "
                    "and potential stamp duty concessions. Speak to our finance team early."
                ),
            },
            {
                "ListingID": "VIL-HL-SOLARA",
                "Title": "The Solara — Single Storey",
                "Storeys": 1,
                "Bedrooms": 4,
                "Bathrooms": 2,
                "Theatre": True,
                "Type": "House & Land",
                "PriceFrom": 749000,
                "PriceDisplay": "From $749,000",
                "Availability": "Available — enquire for land lots",
                "Highlights": [
                    "Oversized stone island — the centrepiece of the home",
                    "Premium 900mm cooktop, oven and rangehood",
                    "High ceilings lifting main living zone",
                    "Expansive sliding doors to covered alfresco under main roof",
                    "Master suite at front — private retreat with freestanding bath and WIR",
                    "Theatre room with acoustic privacy",
                    "Fully landscaped front and rear gardens from day one",
                    "Exposed aggregate driveway",
                ],
                "Ideal_For": [
                    "Families who live in the kitchen and entertain regularly",
                    "Upsizers wanting space, flow and lifestyle",
                    "Buyers wanting a home that feels premium from day one",
                ],
                "KeyPitch": (
                    "Designed for families who live out loud — big kitchen, big alfresco, private master. "
                    "One of the most popular layouts in the collection for good reason."
                ),
            },
            {
                "ListingID": "VIL-HL-MARLOW",
                "Title": "The Marlow — Single Storey",
                "Storeys": 1,
                "Bedrooms": 4,
                "Bathrooms": 2,
                "Type": "House & Land",
                "PriceFrom": 779000,
                "PriceDisplay": "From $779,000",
                "Availability": "Available — enquire for land lots",
                "Highlights": [
                    "Flowing open-plan kitchen, dining and living",
                    "Stone benchtops and 900mm stainless steel appliances",
                    "High ceilings with sliding doors to alfresco and landscaped garden",
                    "Master suite with freestanding bath and walk-in robe",
                    "Double garage",
                    "Fully landscaped front and rear yard",
                ],
                "Ideal_For": [
                    "Buyers who value simplicity done beautifully",
                    "Families wanting flow and outdoor connection",
                    "Those who want lifestyle without complexity",
                ],
                "KeyPitch": (
                    "Clean lines, great proportions, flows beautifully inside and out. "
                    "The kind of home that photographs well and lives even better."
                ),
            },
            {
                "ListingID": "VIL-HL-ELLINGTON",
                "Title": "The Ellington — Single Storey",
                "Storeys": 1,
                "Bedrooms": 4,
                "Bathrooms": 2,
                "Theatre": True,
                "Activity": True,
                "Type": "House & Land",
                "PriceFrom": 815000,
                "PriceDisplay": "From $815,000",
                "Availability": "Available — enquire for land lots",
                "Highlights": [
                    "Dual living zones — theatre room and separate activity space",
                    "Oversized stone island bench",
                    "Walk-in scullery — keeps entertaining seamless",
                    "High ceilings throughout",
                    "Covered alfresco and fully landscaped backyard — ready from move-in",
                    "Double vanity ensuite",
                    "Freestanding bath in master",
                    "Smart home capability",
                ],
                "Ideal_For": [
                    "Growing families needing multiple zones",
                    "Buyers who want flexibility for kids, work and entertaining",
                    "Upsizers who've outgrown their current home",
                ],
                "KeyPitch": (
                    "Two living zones changes everything — theatre for movie nights, "
                    "activity room for kids or study. The scullery keeps the kitchen clean while you entertain. "
                    "Built for family life, not just family size."
                ),
            },
            {
                "ListingID": "VIL-HL-VALEN",
                "Title": "The Valen — Double Storey",
                "Storeys": 2,
                "Bedrooms": 4,
                "Bathrooms": 3,
                "Study": True,
                "Retreat": True,
                "Type": "House & Land — Double Storey",
                "PriceFrom": 899000,
                "PriceDisplay": "From $899,000",
                "Availability": "Available — enquire for land lots",
                "Highlights": [
                    "Striking double storey façade with architectural presence",
                    "Downstairs guest bedroom and full bathroom",
                    "Expansive stone kitchen flowing to alfresco",
                    "900mm premium appliances",
                    "Upstairs retreat lounge creating separation before master suite",
                    "Master suite with freestanding bath, dual vanities and premium finishes",
                    "Optional balcony",
                    "Fully landscaped gardens",
                    "Smart-home capable",
                ],
                "Ideal_For": [
                    "Families ready to step up to a prestige layout",
                    "Multi-generational buyers needing downstairs guest accommodation",
                    "Buyers who want architectural presence and internal separation",
                ],
                "KeyPitch": (
                    "The retreat upstairs creates real separation — master suite feels like its own wing. "
                    "Downstairs guest bed with full bath is a genuine feature, not an afterthought."
                ),
            },
            {
                "ListingID": "VIL-HL-AURELIA",
                "Title": "The Aurelia — Double Storey",
                "Storeys": 2,
                "Bedrooms": 5,
                "Bathrooms": 3,
                "Theatre": True,
                "GuestSuite": True,
                "Type": "House & Land — Double Storey",
                "PriceFrom": 949000,
                "PriceDisplay": "From $949,000",
                "Availability": "Available — enquire for land lots",
                "Highlights": [
                    "5 bedrooms — the largest layout in the collection",
                    "Butler-style pantry off main kitchen",
                    "Expansive open-plan living flowing to covered alfresco",
                    "Theatre room downstairs",
                    "Self-contained guest suite downstairs",
                    "Four bedrooms and retreat upstairs",
                    "Master suite with freestanding bath, dual vanities and full-height tiling",
                    "Ducted reverse cycle air conditioning",
                    "Covered alfresco and landscaped gardens",
                ],
                "Ideal_For": [
                    "Large families who refuse to compromise on space",
                    "Multi-generational households",
                    "Buyers building a long-term family home",
                ],
                "KeyPitch": (
                    "Five bedrooms, butler pantry, theatre, guest suite — this home is built for a life well lived. "
                    "It's the one you grow into, not out of."
                ),
            },
        ],
    },

    # ─────────────────────────────────────────────────────────────────────────
    # COLLECTION 3 — THE TERRACE COLLECTION
    # ─────────────────────────────────────────────────────────────────────────
    "TerraceCollection": {
        "CollectionName": "Vilara Park — The Terrace Collection",
        "TotalTerraces": 10,
        "Sold": 6,
        "Remaining": 4,
        "Availability": "Only 4 remaining — final release.",
        "Overview": (
            "Curated terrace homes positioned directly opposite Vilara Park's landscaped green. "
            "Architectural façades with high-quality materials, rear-access garages keeping the street clean, "
            "trellised walkways and landscaped verges. "
            "Lock-and-leave by design — strata manages common landscaping and shared external elements. "
            "Each terrace has its own private courtyard, front door and street presence."
        ),
        "Finishes": [
            "High ceilings creating openness",
            "Engineered timber flooring",
            "Stone benchtops and premium European appliances",
            "Designer tapware and freestanding baths",
            "Smart home capability — lighting and climate control",
            "NBN connectivity",
        ],
        "Lifestyle": (
            "Parkland directly opposite for morning jogs, dog walks, and evening strolls. "
            "5 minutes to Ellenbrook Central. Close to schools, childcare, and Ellenbrook Train Station. "
            "Perth CBD approx 25–30 minutes. Swan Valley approx 15 minutes."
        ),
        "Listings": [
            {
                "ListingID": "VIL-TER-01",
                "Title": "Terrace Residence 1",
                "Bedrooms": 2,
                "Bathrooms": 2,
                "Garage": "Secure rear-access garage",
                "Courtyard": True,
                "Type": "Terrace",
                "PriceDisplay": "Enquire for pricing",
                "Availability": "Available",
                "Features": [
                    "Private landscaped courtyard",
                    "Secure rear-access garage",
                    "Smart home readiness",
                    "Premium finishes throughout",
                    "Directly opposite Vilara Park greenspace",
                ],
                "Ideal_For": [
                    "Professionals and young couples",
                    "First home buyers stepping into the market",
                    "Downsizers wanting elegance without maintenance",
                ],
            },
            {
                "ListingID": "VIL-TER-02",
                "Title": "Terrace Residence 2",
                "Bedrooms": 2,
                "Bathrooms": 2,
                "Garage": "Secure rear-access garage",
                "Courtyard": True,
                "Type": "Terrace",
                "PriceDisplay": "Enquire for pricing",
                "Availability": "Available",
                "Features": [
                    "Private landscaped courtyard",
                    "Secure rear-access garage",
                    "Smart home readiness",
                    "Premium finishes throughout",
                    "Directly opposite Vilara Park greenspace",
                ],
                "Ideal_For": [
                    "Professionals and young couples",
                    "First home buyers stepping into the market",
                    "Downsizers wanting elegance without maintenance",
                ],
            },
            {
                "ListingID": "VIL-TER-03",
                "Title": "Terrace Residence 3",
                "Bedrooms": 2,
                "Bathrooms": 2,
                "Garage": "Secure rear-access garage",
                "Courtyard": True,
                "Type": "Terrace",
                "PriceDisplay": "Enquire for pricing",
                "Availability": "Available",
                "Features": [
                    "Private landscaped courtyard",
                    "Secure rear-access garage",
                    "Smart home readiness",
                    "Premium finishes throughout",
                    "Directly opposite Vilara Park greenspace",
                ],
                "Ideal_For": [
                    "Professionals and young couples",
                    "First home buyers stepping into the market",
                    "Downsizers wanting elegance without maintenance",
                ],
            },
            {
                "ListingID": "VIL-TER-04",
                "Title": "Terrace Residence 4",
                "Bedrooms": 2,
                "Bathrooms": 2,
                "Garage": "Secure rear-access garage",
                "Courtyard": True,
                "Type": "Terrace",
                "PriceDisplay": "Enquire for pricing",
                "Availability": "Available",
                "Features": [
                    "Private landscaped courtyard",
                    "Secure rear-access garage",
                    "Smart home readiness",
                    "Premium finishes throughout",
                    "Directly opposite Vilara Park greenspace",
                ],
                "Ideal_For": [
                    "Professionals and young couples",
                    "First home buyers stepping into the market",
                    "Downsizers wanting elegance without maintenance",
                ],
            },
        ],
        "TerraceNote": (
            "Individual terrace pricing is available on enquiry. "
            "With only 4 remaining from a collection of 10, these are genuinely scarce. "
            "WA first home buyers may be eligible for the First Home Owner Grant and stamp duty concessions."
        ),
    },

    # ─────────────────────────────────────────────────────────────────────────
    # PORTFOLIO GUIDANCE — FOR ARIA USE
    # ─────────────────────────────────────────────────────────────────────────
    "PortfolioGuidance": {
        "BudgetMatching": {
            "Under_700K": (
                "The Haven house and land package starts from $699K — premium inclusions, "
                "3 bedrooms and study nook. Great entry point. "
                "Terrace collection pricing also available on enquiry and may suit this range."
            ),
            "AUD_700K_to_800K": (
                "The Solara (from $749K) and The Marlow (from $779K) are the sweet spot here. "
                "Both are 4-bedroom single storey homes with outstanding standard inclusions. "
                "Solara suits entertainers; Marlow suits those wanting elegant simplicity."
            ),
            "AUD_800K_to_950K": (
                "The Ellington (from $815K) is ideal for growing families needing dual living zones. "
                "The Valen (from $899K) steps it up to double storey with a guest suite. "
                "Apartment Residence 201 (from $932K) and 302 (from $968K) also fall in this range — "
                "good for buyers wanting apartment convenience over a house."
            ),
            "AUD_950K_to_1_2M": (
                "The Aurelia (from $949K) is the flagship house and land — 5 bed, 3 bath, butler pantry. "
                "Apartment Residence 401 (from $1.125M) for 3-bedroom apartment buyers with park views."
            ),
            "AUD_1_2M_plus": (
                "Residence 502 Executive Apartment from $1.185M. "
                "The Penthouse (Residence 601) is price upon application — enquire for private consultation."
            ),
        },
        "BuyerTypeMatching": {
            "FirstHomeBuyer": [
                "VIL-HL-HAVEN — The Haven from $699K. Premium inclusions, manageable size, eligible for FHOG.",
                "VIL-TER-01 to VIL-TER-04 — Terraces. Lock-and-leave convenience, parkside lifestyle.",
            ],
            "Family": [
                "VIL-HL-SOLARA — The Solara. 4 bed, theatre, big alfresco. Lives brilliantly.",
                "VIL-HL-ELLINGTON — The Ellington. Dual living zones, scullery, perfect for active families.",
                "VIL-HL-VALEN — The Valen. Double storey, retreat, guest suite.",
                "VIL-HL-AURELIA — The Aurelia. 5 bed, theatre, guest suite. The legacy home.",
                "VIL-APT-401 — Residence 401. 3-bed apartment for families wanting boutique living.",
            ],
            "Professional": [
                "VIL-APT-201 — Residence 201. Park views, balcony, rooftop amenities. Lock-and-leave.",
                "VIL-APT-302 — Residence 302. Corner apartment with study zone. WFH-ready.",
                "VIL-APT-502 — Residence 502. Executive layout with retreat and top-floor views.",
                "VIL-TER-01 to VIL-TER-04 — Terraces. Low maintenance, parkside, close to highway.",
            ],
            "Downsizer": [
                "VIL-APT-102 — Residence 102. Private garden apartment — outdoor space without maintenance.",
                "VIL-APT-401 — Residence 401. 3 bedrooms, space without a big garden.",
                "VIL-TER-01 to VIL-TER-04 — Terraces. Own front door, own courtyard, strata handles the rest.",
            ],
            "Investor": [
                "VIL-APT-201 — Residence 201. Strong rental appeal, park facing, rooftop amenities.",
                "VIL-APT-302 — Residence 302. Corner position, study zone, broad renter appeal.",
                "VIL-HL-HAVEN — The Haven. Entry-level pricing, rental demand from first-home aspirants.",
                "VIL-TER-01 to VIL-TER-04 — Terraces. Scarcity and boutique appeal in tight rental market.",
            ],
            "LuxuryPrestige": [
                "VIL-APT-502 — Residence 502. Executive layout, treetop views, exclusive.",
                "VIL-APT-601 — The Penthouse. Entire top floor. Panoramic views. Price on application.",
                "VIL-HL-AURELIA — The Aurelia. 5-bed legacy family home.",
            ],
        },
        "ARIANotes": (
            "Always present 1–2 listings max — never a full list dump. "
            "Lead with the strongest match and explain in one sentence why it fits what the visitor told you. "
            "If budget is slightly short, pivot warmly: acknowledge it positively and show the closest fit. "
            "If a visitor's preferred type has no match, guide them to the most similar option and explain the lifestyle crossover. "
            "Penthouse enquiries: always offer a private consultation rather than stating price in chat. "
            "Terrace pricing: available on enquiry — frame scarcity naturally ('only 4 left from a collection of 10'). "
            "Finance options are available across all collections — introduce naturally when appropriate."
        ),
    },
}
