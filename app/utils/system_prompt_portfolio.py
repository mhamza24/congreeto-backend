# vilara_portfolio_prompt.py
# ─────────────────────────────────────────────────────────────────────────────
# ARIA — Veloce Property Portfolio Prompt
# Vilara Park | All Four Collections (inc. Banksia Grove Land)
# Version 1.1 — Listing URLs added to all properties
# ─────────────────────────────────────────────────────────────────────────────
# USAGE NOTE:
# This prompt is injected alongside the ARIA system prompt at runtime.
# ARIA uses this data to match visitors to listings, present options with
# authority, and guide conversations toward viewings and consultations.
# In production, replace with real-time database/embedding lookups.
# LINK RULE: When presenting any property to a visitor, always include the
# listing URL inline so the visitor can view it directly. Never mention a
# property without its link. Include the full URL including https:// so
# the platform renders a clickable preview.
# ─────────────────────────────────────────────────────────────────────────────


veloce_portfolio_summary =  {
    "note": "Full portfolio summary. Use this to make cross-collection recommendations. When a visitor shows interest in a specific collection, the full detail for that collection is also provided below.",
    "apartments": {
        "collection": "Vilara Park Residences — Boutique Apartments",
        "availability": "Limited — over 50% sold",
        "listings": [
            {"id": "VIL-APT-102", "name": "Residence 102", "price": "From $915,000", "beds": 2, "type": "Ground floor garden apartment", "url": "https://getveloce.com/landingpage/categories/apartments/residence-102"},
            {"id": "VIL-APT-201", "name": "Residence 201", "price": "From $932,000", "beds": 2, "type": "Park-facing balcony", "url": "https://getveloce.com/landingpage/categories/apartments/residence-201"},
            {"id": "VIL-APT-302", "name": "Residence 302", "price": "From $968,000", "beds": 2, "type": "Corner apartment with study", "url": "https://getveloce.com/landingpage/categories/apartments/residence-302"},
            {"id": "VIL-APT-401", "name": "Residence 401", "price": "From $1,125,000", "beds": 3, "type": "Elevated park outlook", "url": "https://getveloce.com/landingpage/categories/apartments/residence-401"},
            {"id": "VIL-APT-502", "name": "Residence 502", "price": "From $1,185,000", "beds": 3, "type": "Executive with retreat", "url": "https://getveloce.com/landingpage/categories/apartments/residence-502"},
            {"id": "VIL-APT-601", "name": "The Penthouse", "price": "Price on application", "beds": 4, "type": "Entire top floor", "url": "https://getveloce.com/landingpage/categories/apartments/residence-601"},
        ]
    },
    "house_and_land": {
        "collection": "Vilara Park Signature House and Land",
        "listings": [
            {"id": "VIL-HL-HAVEN", "name": "The Haven", "price": "From $699,000", "beds": 3, "storeys": 1, "url": "https://getveloce.com/landingpage/categories/home-land-packages/the-haven"},
            {"id": "VIL-HL-SOLARA", "name": "The Solara", "price": "From $749,000", "beds": 4, "storeys": 1, "url": "https://getveloce.com/landingpage/categories/home-land-packages/the-solara"},
            {"id": "VIL-HL-MARLOW", "name": "The Marlow", "price": "From $779,000", "beds": 4, "storeys": 1, "url": "https://getveloce.com/landingpage/categories/home-land-packages/the-marlow"},
            {"id": "VIL-HL-ELLINGTON", "name": "The Ellington", "price": "From $815,000", "beds": 4, "storeys": 1, "url": "https://getveloce.com/landingpage/categories/home-land-packages/the-ellington"},
            {"id": "VIL-HL-VALEN", "name": "The Valen", "price": "From $899,000", "beds": 4, "storeys": 2, "url": "https://getveloce.com/landingpage/categories/home-land-packages/the-valen"},
            {"id": "VIL-HL-AURELIA", "name": "The Aurelia", "price": "From $949,000", "beds": 5, "storeys": 2, "url": "https://getveloce.com/landingpage/categories/home-land-packages/the-aurelia"},
        ]
    },
    "terraces": {
        "collection": "Vilara Park Terrace Collection",
        "availability": "Only 4 remaining from 10",
        "listings": [
            {"id": "VIL-TER-01", "name": "The Greenway Terrace", "price": "From $599,000", "beds": 2, "url": "https://getveloce.com/landingpage/categories/terraces/the-greenway-terrace"},
            {"id": "VIL-TER-02", "name": "The Parkfront Terrace", "price": "From $619,000", "beds": 2, "url": "https://getveloce.com/landingpage/categories/terraces/the-parkfront-terrace"},
            {"id": "VIL-TER-03", "name": "The Corner Signature Terrace", "price": "From $639,000", "beds": 2, "url": "https://getveloce.com/landingpage/categories/terraces/the-corner-signature-terrace"},
            {"id": "VIL-TER-04", "name": "The Courtyard Signature Terrace", "price": "From $649,000", "beds": 2, "url": "https://getveloce.com/landingpage/categories/terraces/the-courtyard-signature-terrace"},
        ]
    },
    "land": {
        "collection": "Banksia Grove Estate Final Land Release",
        "availability": "12 lots remaining, all titled and ready to build",
        "price_range": "$345,000 to $389,000",
        "lot_size": "360m2 all lots",
        "standout_lots": ["Lot 104 corner $379K", "Lot 108 wide frontage $365K", "Lot 111 park facing $372K", "Lot 112 premium $389K", "Lot 107 entry $345K"],
        "all_lot_urls": {
            "lot-101": "https://getveloce.com/landingpage/categories/land-final-release/lot-101",
            "lot-102": "https://getveloce.com/landingpage/categories/land-final-release/lot-102",
            "lot-103": "https://getveloce.com/landingpage/categories/land-final-release/lot-103",
            "lot-104": "https://getveloce.com/landingpage/categories/land-final-release/lot-104",
            "lot-105": "https://getveloce.com/landingpage/categories/land-final-release/lot-105",
            "lot-106": "https://getveloce.com/landingpage/categories/land-final-release/lot-106",
            "lot-107": "https://getveloce.com/landingpage/categories/land-final-release/lot-107",
            "lot-108": "https://getveloce.com/landingpage/categories/land-final-release/lot-108",
            "lot-109": "https://getveloce.com/landingpage/categories/land-final-release/lot-109",
            "lot-110": "https://getveloce.com/landingpage/categories/land-final-release/lot-110",
            "lot-111": "https://getveloce.com/landingpage/categories/land-final-release/lot-111",
            "lot-112": "https://getveloce.com/landingpage/categories/land-final-release/lot-112",
        }
    },
    "location_and_lifestyle": {
        "suburb": "Ellenbrook, Perth, Western Australia",
        "cbd_distance": "25 to 30 minutes via Tonkin Highway",
        "swan_valley": "15 minutes",
        "ellenbrook_central": "5 minutes — Coles, Woolworths, cafes, retail",
        "schools": "Close to primary and secondary schools and childcare",
        "train_station": "Ellenbrook Train Station nearby",
        "parkland": "All Vilara Park properties directly opposite landscaped parkland and walking trails",
        "beach": "No beach proximity — nearest beaches are approx 45 to 60 minutes. Be honest if asked.",
    }
}


veloce_portfolio = {
    "Project": {
        "Name": "Vilara Park Residences",
        "Location": "Ellenbrook, Perth, Western Australia",
        "Overview": (
            "Vilara Park is a boutique, architecturally designed development in Ellenbrook, "
            "positioned directly opposite open parkland and tree-lined walking paths. "
            "The project comprises four distinct collections: boutique luxury apartments, "
            "a signature house and land collection, a curated terrace collection, "
            "and the Banksia Grove Estate land release. "
            "Over 50% already sold. Limited residences remain."
        ),
        "KeySellingPoints": [
            "Boutique scale — only 12 apartments, limited house and land packages, 4 remaining terraces, and 12 land lots",
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
                "URL": "https://getveloce.com/landingpage/categories/apartments/residence-102",
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
                "URL": "https://getveloce.com/landingpage/categories/apartments/residence-201",
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
                "URL": "https://getveloce.com/landingpage/categories/apartments/residence-302",
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
                "URL": "https://getveloce.com/landingpage/categories/apartments/residence-401",
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
                "URL": "https://getveloce.com/landingpage/categories/apartments/residence-502",
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
                "URL": "https://getveloce.com/landingpage/categories/apartments/residence-601",
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
                "URL": "https://getveloce.com/landingpage/categories/home-land-packages/the-haven",
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
                "URL": "https://getveloce.com/landingpage/categories/home-land-packages/the-solara",
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
                "URL": "https://getveloce.com/landingpage/categories/home-land-packages/the-marlow",
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
                "URL": "https://getveloce.com/landingpage/categories/home-land-packages/the-ellington",
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
                "URL": "https://getveloce.com/landingpage/categories/home-land-packages/the-valen",
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
                "URL": "https://getveloce.com/landingpage/categories/home-land-packages/the-aurelia",
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
            "Ducted reverse cycle air conditioning",
        ],
        "Lifestyle": (
            "Parkland directly opposite for morning jogs, dog walks, and evening strolls. "
            "5 minutes to Ellenbrook Central. Close to schools, childcare, and Ellenbrook Train Station. "
            "Perth CBD approx 25–30 minutes. Swan Valley approx 15 minutes."
        ),
        "Listings": [
            {
                "ListingID": "VIL-TER-01",
                "Title": "The Greenway Terrace",
                "URL": "https://getveloce.com/landingpage/categories/terraces/the-greenway-terrace",
                "SubTitle": "Terrace Residence 1",
                "Bedrooms": 2,
                "Bathrooms": 2,
                "Study": False,
                "Garage": "Secure rear-access garage",
                "Courtyard": True,
                "Type": "Terrace",
                "PriceFrom": 599000,
                "PriceDisplay": "From $599,000",
                "Availability": "Available",
                "Features": [
                    "Private landscaped courtyard",
                    "Secure rear-access garage",
                    "Open-plan living flowing to courtyard",
                    "Stone kitchen surfaces and engineered timber flooring",
                    "Smart home capability",
                    "Premium finishes throughout",
                    "Directly opposite Vilara Park greenspace",
                    "Strata maintained common landscaping",
                ],
                "Ideal_For": [
                    "First home buyers entering the market strategically",
                    "Professionals wanting lock-and-leave convenience",
                    "Downsizers seeking simplicity with style",
                ],
                "KeyPitch": (
                    "The entry point to the Terrace Collection — but it doesn't feel like one. "
                    "Refined finishes, parkside address, and a price that makes sense for first home buyers."
                ),
                "FirstHomeBuyerNote": (
                    "WA first home buyers may be eligible for the First Home Owner Grant "
                    "and stamp duty concessions. Speak to our finance team early."
                ),
            },
            {
                "ListingID": "VIL-TER-02",
                "Title": "The Parkfront Terrace",
                "URL": "https://getveloce.com/landingpage/categories/terraces/the-parkfront-terrace",
                "SubTitle": "Terrace Residence 2",
                "Bedrooms": 2,
                "Bathrooms": 2,
                "Study": True,
                "Garage": "Secure rear-access double garage",
                "Courtyard": True,
                "Type": "Terrace",
                "PriceFrom": 619000,
                "PriceDisplay": "From $619,000",
                "Availability": "Available",
                "Features": [
                    "Direct park frontage with open green outlook",
                    "Private rear courtyard — fully landscaped, ready for entertaining",
                    "Secure rear-access double garage",
                    "Stone benchtops, premium European appliances (Miele or equivalent)",
                    "Soft-close cabinetry and designer tapware",
                    "Engineered timber flooring through living zone",
                    "High ceilings throughout",
                    "Smart home integration — lighting and climate control",
                    "Ducted reverse cycle air conditioning",
                    "NBN ready",
                    "Well-lit, pedestrian-friendly streetscape",
                    "Strata maintained common landscaping",
                ],
                "Ideal_For": [
                    "Professionals commuting to Perth CBD",
                    "First home buyers wanting park-facing living",
                    "Downsizers seeking security and low maintenance",
                ],
                "KeyPitch": (
                    "Opening your front door to open green space instead of traffic changes the feel of daily life. "
                    "Direct park frontage, double garage, and premium finishes — hard to match at this price point."
                ),
                "FirstHomeBuyerNote": (
                    "WA first home buyers may be eligible for the First Home Owner Grant "
                    "and stamp duty concessions."
                ),
            },
            {
                "ListingID": "VIL-TER-03",
                "Title": "The Corner Signature Terrace",
                "URL": "https://getveloce.com/landingpage/categories/terraces/the-corner-signature-terrace",
                "SubTitle": "Terrace Residence 3",
                "Bedrooms": 2,
                "Bathrooms": 2,
                "Study": True,
                "Garage": "Secure rear-access garage",
                "Courtyard": True,
                "Type": "Terrace",
                "PriceFrom": 639000,
                "PriceDisplay": "From $639,000",
                "Availability": "Available",
                "Features": [
                    "Corner position — natural light from multiple angles",
                    "Park views from balcony across Vilara Park greenery",
                    "Enclosed study — genuine work-from-home flexibility",
                    "Private rear courtyard — fully landscaped and functional",
                    "Secure rear-access garage",
                    "Stone benchtops and premium European appliances",
                    "Engineered timber flooring",
                    "High ceilings throughout",
                    "Smart lighting and climate control",
                    "Ducted reverse cycle air conditioning",
                    "NBN ready",
                    "Trellised walkways and safe, well-lit boulevard",
                    "Strata maintained common areas",
                ],
                "Ideal_For": [
                    "Professionals commuting to the CBD who need WFH flexibility",
                    "Couples wanting lifestyle balance and architectural distinction",
                    "Buyers prioritising light, privacy and corner presence",
                ],
                "KeyPitch": (
                    "Corner position means more light and more presence. "
                    "The enclosed study makes WFH actually work — it's not an afterthought, it's a genuine room."
                ),
            },
            {
                "ListingID": "VIL-TER-04",
                "Title": "The Courtyard Signature Terrace",
                "URL": "https://getveloce.com/landingpage/categories/terraces/the-courtyard-signature-terrace",
                "SubTitle": "Terrace Residence 4",
                "Bedrooms": 2,
                "Bathrooms": 2,
                "Study": True,
                "Garage": "Secure rear-access garage",
                "Courtyard": True,
                "CourtyardExtended": True,
                "Type": "Terrace",
                "PriceFrom": 649000,
                "PriceDisplay": "From $649,000",
                "Availability": "Available",
                "Features": [
                    "Extended private courtyard — room for dining table, lounge setting and greenery",
                    "Secure rear-access garage",
                    "Open-plan living with timber flooring flowing to courtyard",
                    "Stone benchtops and premium European appliances",
                    "Smart home integration — adjust lighting and temperature remotely",
                    "Master suite — elegant and calming",
                    "Main bathroom with freestanding bath",
                    "High ceilings throughout",
                    "Ducted reverse cycle air conditioning",
                    "NBN ready",
                    "Landscaped, safe and well-lit boulevard",
                    "Strata maintained external landscaping",
                ],
                "Ideal_For": [
                    "Downsizers wanting a private garden retreat without maintenance overhead",
                    "Professionals and couples who entertain outdoors",
                    "Buyers building their future in a boutique parkside setting",
                ],
                "KeyPitch": (
                    "The extended courtyard is the standout — genuine entertaining space, not just a token outdoor area. "
                    "If outdoor living matters, this is the one in the collection."
                ),
            },
        ],
        "TerraceNote": (
            "Only 4 remaining from a collection of 10 — genuinely scarce. "
            "Individual terrace pricing ranges from $599,000 to $649,000. "
            "WA first home buyers may be eligible for the First Home Owner Grant and stamp duty concessions. "
            "Finance support available through accredited partners."
        ),
    },

    # ─────────────────────────────────────────────────────────────────────────
    # COLLECTION 4 — BANKSIA GROVE ESTATE (LAND)
    # ─────────────────────────────────────────────────────────────────────────
    "LandCollection": {
        "CollectionName": "Banksia Grove Estate — Final Stage Land Release",
        "Location": "Ellenbrook, Western Australia",
        "Availability": "Final stage release — limited to 12 premium lots. All titled and ready to build.",
        "Overview": (
            "An exclusive final-stage land release in the thriving community of Ellenbrook. "
            "Thoughtfully designed for modern living, this boutique release offers a limited collection "
            "of 12 fully titled residential lots ideal for families, first-home buyers, and investors "
            "looking to secure land in one of Perth's fastest-growing corridors. "
            "Surrounded by established amenities, parks, and schools, Banksia Grove Estate provides "
            "the perfect balance between peaceful suburban living and everyday convenience."
        ),
        "KeyStats": {
            "TotalLots": 12,
            "LotSize": "360m² (consistent across all lots)",
            "Status": "100% titled and ready for immediate construction",
            "DistanceToCBD": "Approx 35 minutes via Tonkin Highway",
            "PriceRange": "$345,000 – $389,000",
        },
        "EstateFeatures": [
            "Underground power and utilities connected",
            "NBN ready on every lot",
            "Level blocks designed for easy construction",
            "Close to parks and playgrounds",
            "Minutes to quality schools",
            "Near Ellenbrook Central Shopping Centre (Coles, Woolworths, cafés, retail)",
            "Easy access to Tonkin Highway and Perth CBD",
            "Short drive to Swan Valley wineries and restaurants",
            "All lots fully titled — build immediately, no delays",
        ],
        "Listings": [
            {
                "ListingID": "BGE-LOT-101",
                "LotNumber": "Lot 101",
                "URL": "https://getveloce.com/landingpage/categories/land-final-release/lot-101",
                "Address": "14 Banksia Terrace, Ellenbrook",
                "LandSize": "360m²",
                "Frontage": "12m",
                "Price": 355000,
                "PriceDisplay": "$355,000",
                "Status": "Available",
                "Tags": [],
                "KeyPitch": "Well-proportioned 12m frontage block — ideal for a wide range of single or double-storey modern home designs.",
            },
            {
                "ListingID": "BGE-LOT-102",
                "LotNumber": "Lot 102",
                "URL": "https://getveloce.com/landingpage/categories/land-final-release/lot-102",
                "Address": "16 Banksia Terrace, Ellenbrook",
                "LandSize": "360m²",
                "Frontage": "12m",
                "Price": 357000,
                "PriceDisplay": "$357,000",
                "Status": "Available",
                "Tags": [],
                "KeyPitch": "Solid 12m frontage in the heart of the estate — balanced streetscape and convenient access to nearby parklands.",
            },
            {
                "ListingID": "BGE-LOT-103",
                "LotNumber": "Lot 103",
                "URL": "https://getveloce.com/landingpage/categories/land-final-release/lot-103",
                "Address": "18 Banksia Terrace, Ellenbrook",
                "LandSize": "360m²",
                "Frontage": "10.5m",
                "Price": 349000,
                "PriceDisplay": "$349,000",
                "Status": "Available",
                "Tags": [],
                "KeyPitch": (
                    "Most affordable block in the collection. Efficient 10.5m frontage suits compact modern home designs — "
                    "popular with first-home buyers, investors, and downsizers."
                ),
            },
            {
                "ListingID": "BGE-LOT-104",
                "LotNumber": "Lot 104",
                "URL": "https://getveloce.com/landingpage/categories/land-final-release/lot-104",
                "Address": "1 Jacaranda Lane, Ellenbrook",
                "LandSize": "360m²",
                "Frontage": "15m",
                "Price": 379000,
                "PriceDisplay": "$379,000",
                "Status": "Available",
                "Tags": ["Corner Lot"],
                "KeyPitch": (
                    "Premium corner position — wider 15m frontage, greater design flexibility, and increased street presence. "
                    "Corner blocks are highly sought after and typically attract stronger resale value."
                ),
            },
            {
                "ListingID": "BGE-LOT-105",
                "LotNumber": "Lot 105",
                "URL": "https://getveloce.com/landingpage/categories/land-final-release/lot-105",
                "Address": "20 Banksia Terrace, Ellenbrook",
                "LandSize": "360m²",
                "Frontage": "12.5m",
                "Price": 362000,
                "PriceDisplay": "$362,000",
                "Status": "Available",
                "Tags": [],
                "KeyPitch": "Slightly wider 12.5m frontage allows more flexibility in home design — great for families wanting open-plan living with a proper outdoor zone.",
            },
            {
                "ListingID": "BGE-LOT-106",
                "LotNumber": "Lot 106",
                "URL": "https://getveloce.com/landingpage/categories/land-final-release/lot-106",
                "Address": "22 Banksia Terrace, Ellenbrook",
                "LandSize": "360m²",
                "Frontage": "12m",
                "Price": 359000,
                "PriceDisplay": "$359,000",
                "Status": "Available",
                "Tags": [],
                "KeyPitch": "Regular 12m frontage — efficient, cost-effective to build on, suits double garages, open-plan living and outdoor entertaining.",
            },
            {
                "ListingID": "BGE-LOT-107",
                "LotNumber": "Lot 107",
                "URL": "https://getveloce.com/landingpage/categories/land-final-release/lot-107",
                "Address": "3 Jacaranda Lane, Ellenbrook",
                "LandSize": "360m²",
                "Frontage": "10m",
                "Price": 345000,
                "PriceDisplay": "$345,000",
                "Status": "Available",
                "Tags": [],
                "KeyPitch": (
                    "Entry price point in the estate at $345K. Compact 10m frontage ideal for space-efficient modern homes — "
                    "particularly appealing for first-home buyers and investors."
                ),
            },
            {
                "ListingID": "BGE-LOT-108",
                "LotNumber": "Lot 108",
                "URL": "https://getveloce.com/landingpage/categories/land-final-release/lot-108",
                "Address": "24 Banksia Terrace, Ellenbrook",
                "LandSize": "360m²",
                "Frontage": "13m",
                "Price": 365000,
                "PriceDisplay": "$365,000",
                "Status": "Available",
                "Tags": ["Wide Frontage"],
                "KeyPitch": (
                    "Wider 13m frontage with strong design freedom — suits larger living areas, expanded garages, "
                    "or homes with enhanced street-facing architecture."
                ),
                "Note": "Listed as $385,000 in some source materials; confirmed price is $365,000. Verify at enquiry.",
            },
            {
                "ListingID": "BGE-LOT-109",
                "LotNumber": "Lot 109",
                "URL": "https://getveloce.com/landingpage/categories/land-final-release/lot-109",
                "Address": "26 Banksia Terrace, Ellenbrook",
                "LandSize": "360m²",
                "Frontage": "12m",
                "Price": 358000,
                "PriceDisplay": "$358,000",
                "Status": "Available",
                "Tags": [],
                "KeyPitch": "Well-proportioned block surrounded by landscaped streets — ideal for a comfortable family home with double garage and outdoor entertaining.",
            },
            {
                "ListingID": "BGE-LOT-110",
                "LotNumber": "Lot 110",
                "URL": "https://getveloce.com/landingpage/categories/land-final-release/lot-110",
                "Address": "5 Jacaranda Lane, Ellenbrook",
                "LandSize": "360m²",
                "Frontage": "11m",
                "Price": 352000,
                "PriceDisplay": "$352,000",
                "Status": "Available",
                "Tags": [],
                "KeyPitch": "Practical 11m frontage in a quiet street setting — flexible for modern single or double-storey designs at an accessible price.",
            },
            {
                "ListingID": "BGE-LOT-111",
                "LotNumber": "Lot 111",
                "URL": "https://getveloce.com/landingpage/categories/land-final-release/lot-111",
                "Address": "7 Jacaranda Lane, Ellenbrook",
                "LandSize": "360m²",
                "Frontage": "12.5m",
                "Price": 372000,
                "PriceDisplay": "$372,000",
                "Status": "Available",
                "Tags": ["Park Facing"],
                "KeyPitch": (
                    "Park-facing position — wake up to green space instead of rooftops. "
                    "Park-facing lots hold lifestyle and resale appeal above standard street-facing blocks."
                ),
            },
            {
                "ListingID": "BGE-LOT-112",
                "LotNumber": "Lot 112",
                "URL": "https://getveloce.com/landingpage/categories/land-final-release/lot-112",
                "Address": "28 Banksia Terrace, Ellenbrook",
                "LandSize": "360m²",
                "Frontage": "15m",
                "Price": 389000,
                "PriceDisplay": "$389,000",
                "Status": "Available",
                "Tags": ["Premium Lot"],
                "KeyPitch": (
                    "The finest block in the estate — widest 15m frontage, premium position, strong street presence. "
                    "Ideal for buyers building a standout home. Expect strong demand."
                ),
            },
        ],
        "LandNote": (
            "All 12 lots are 360m², fully titled, and ready for immediate construction — no delays. "
            "Prices range from $345,000 (Lot 107) to $389,000 (Lot 112). "
            "Standout lots: Lot 104 (corner, $379K), Lot 108 (wide frontage, $365K), "
            "Lot 111 (park facing, $372K), Lot 112 (premium, $389K). "
            "WA first home buyers may be eligible for the First Home Owner Grant and stamp duty concessions. "
            "Finance and construction loan support available through accredited partners."
        ),
        "FirstHomeBuyerNote": (
            "Purchasing land and building a new home may qualify WA first home buyers for the First Home Owner Grant "
            "and stamp duty concessions. Speak to the finance team early to understand eligibility and structure."
        ),
    },

    # ─────────────────────────────────────────────────────────────────────────
    # PORTFOLIO GUIDANCE — FOR ARIA USE
    # ─────────────────────────────────────────────────────────────────────────
    "PortfolioGuidance": {
        "LinkRule": (
            "CRITICAL — Every time ARIA presents or mentions a specific property, she must include the "
            "listing URL from that property's URL field inline in her message. Always use the full URL "
            "including https:// so the platform renders a clickable link preview. "
            "Never mention a property by name without including its URL. "
            "Example: 'The Solara is the one — big kitchen, big alfresco, built for entertaining. "
            "Have a look: https://getveloce.com/landingpage/categories/home-land-packages/the-solara'"
        ),
        "BudgetMatching": {
            "Under_400K": (
                "Banksia Grove Estate land lots start from $345,000 (Lot 107). "
                "All 12 lots are titled and ready to build — ideal for buyers who want to choose their own builder. "
                "Entry lots range from $345K–$365K; premium and park-facing lots reach $372K–$389K."
            ),
            "AUD_345K_to_400K": (
                "Banksia Grove Estate is the right conversation. "
                "Lot 107 ($345K, 10m frontage) and Lot 103 ($349K, 10.5m) are the entry points. "
                "Lot 104 ($379K, corner) and Lot 112 ($389K, premium wide frontage) are the standouts at the top of this range."
            ),
            "Under_650K": (
                "The Greenway Terrace starts from $599K — refined finishes, 2 bed/2 bath, private courtyard. "
                "Ideal entry point, especially for WA first home buyers eligible for FHOG. "
                "The Parkfront Terrace (from $619K) and Corner Signature Terrace (from $639K) also fall here. "
                "Alternatively, land lots at Banksia Grove Estate range from $345K–$389K for buyers wanting to build."
            ),
            "AUD_650K_to_700K": (
                "The Courtyard Signature Terrace (from $649K) is the standout — extended courtyard, study, premium finishes. "
                "The Haven house and land (from $699K) is also reachable — 3 bed, 2 bath, study nook, full standard inclusions."
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
        "ListingURLs": {
            "VIL-APT-102": "https://getveloce.com/landingpage/categories/apartments/residence-102",
            "VIL-APT-201": "https://getveloce.com/landingpage/categories/apartments/residence-201",
            "VIL-APT-302": "https://getveloce.com/landingpage/categories/apartments/residence-302",
            "VIL-APT-401": "https://getveloce.com/landingpage/categories/apartments/residence-401",
            "VIL-APT-502": "https://getveloce.com/landingpage/categories/apartments/residence-502",
            "VIL-APT-601": "https://getveloce.com/landingpage/categories/apartments/residence-601",
            "VIL-HL-HAVEN": "https://getveloce.com/landingpage/categories/home-land-packages/the-haven",
            "VIL-HL-SOLARA": "https://getveloce.com/landingpage/categories/home-land-packages/the-solara",
            "VIL-HL-MARLOW": "https://getveloce.com/landingpage/categories/home-land-packages/the-marlow",
            "VIL-HL-ELLINGTON": "https://getveloce.com/landingpage/categories/home-land-packages/the-ellington",
            "VIL-HL-VALEN": "https://getveloce.com/landingpage/categories/home-land-packages/the-valen",
            "VIL-HL-AURELIA": "https://getveloce.com/landingpage/categories/home-land-packages/the-aurelia",
            "VIL-TER-01": "https://getveloce.com/landingpage/categories/terraces/the-greenway-terrace",
            "VIL-TER-02": "https://getveloce.com/landingpage/categories/terraces/the-parkfront-terrace",
            "VIL-TER-03": "https://getveloce.com/landingpage/categories/terraces/the-corner-signature-terrace",
            "VIL-TER-04": "https://getveloce.com/landingpage/categories/terraces/the-courtyard-signature-terrace",
            "BGE-LOT-101": "https://getveloce.com/landingpage/categories/land-final-release/lot-101",
            "BGE-LOT-102": "https://getveloce.com/landingpage/categories/land-final-release/lot-102",
            "BGE-LOT-103": "https://getveloce.com/landingpage/categories/land-final-release/lot-103",
            "BGE-LOT-104": "https://getveloce.com/landingpage/categories/land-final-release/lot-104",
            "BGE-LOT-105": "https://getveloce.com/landingpage/categories/land-final-release/lot-105",
            "BGE-LOT-106": "https://getveloce.com/landingpage/categories/land-final-release/lot-106",
            "BGE-LOT-107": "https://getveloce.com/landingpage/categories/land-final-release/lot-107",
            "BGE-LOT-108": "https://getveloce.com/landingpage/categories/land-final-release/lot-108",
            "BGE-LOT-109": "https://getveloce.com/landingpage/categories/land-final-release/lot-109",
            "BGE-LOT-110": "https://getveloce.com/landingpage/categories/land-final-release/lot-110",
            "BGE-LOT-111": "https://getveloce.com/landingpage/categories/land-final-release/lot-111",
            "BGE-LOT-112": "https://getveloce.com/landingpage/categories/land-final-release/lot-112",
        },
        "BuyerTypeMatching": {
            "FirstHomeBuyer": [
                "BGE-LOT-107 — Lot 107 from $345K. Entry land price, titled and ready to build. FHOG eligible.",
                "BGE-LOT-103 — Lot 103 from $349K. Efficient 10.5m block, great value entry. FHOG eligible.",
                "VIL-TER-01 — The Greenway Terrace from $599K. Refined entry, FHOG eligible, lock-and-leave.",
                "VIL-TER-02 — The Parkfront Terrace from $619K. Park-facing, premium, FHOG eligible.",
                "VIL-HL-HAVEN — The Haven from $699K. Premium inclusions, manageable size, FHOG eligible.",
            ],
            "Family": [
                "VIL-HL-SOLARA — The Solara. 4 bed, theatre, big alfresco. Lives brilliantly.",
                "VIL-HL-ELLINGTON — The Ellington. Dual living zones, scullery, perfect for active families.",
                "VIL-HL-VALEN — The Valen. Double storey, retreat, guest suite.",
                "VIL-HL-AURELIA — The Aurelia. 5 bed, theatre, guest suite. The legacy home.",
                "VIL-APT-401 — Residence 401. 3-bed apartment for families wanting boutique living.",
                "BGE-LOT-104 — Lot 104 corner block. Build your own family home with design freedom.",
                "BGE-LOT-112 — Lot 112 premium wide frontage. The best block to build on in the estate.",
            ],
            "Professional": [
                "VIL-APT-201 — Residence 201. Park views, balcony, rooftop amenities. Lock-and-leave.",
                "VIL-APT-302 — Residence 302. Corner apartment with study zone. WFH-ready.",
                "VIL-APT-502 — Residence 502. Executive layout with retreat and top-floor views.",
                "VIL-TER-03 — Corner Signature Terrace. WFH study, park views, corner light.",
                "VIL-TER-02 — Parkfront Terrace. Low maintenance, parkside, direct highway access.",
            ],
            "Downsizer": [
                "VIL-APT-102 — Residence 102. Private garden apartment — outdoor space without maintenance.",
                "VIL-APT-401 — Residence 401. 3 bedrooms, space without a big garden.",
                "VIL-TER-04 — Courtyard Signature Terrace. Extended courtyard, own front door, strata handles the rest.",
                "VIL-TER-01 — Greenway Terrace. Elegance without upkeep, parkside calm.",
            ],
            "Investor": [
                "BGE-LOT-107 — Lot 107 from $345K. Lowest entry in the portfolio. Strong rental demand from owner-builders.",
                "BGE-LOT-103 — Lot 103 from $349K. Compact efficient block, low land cost for build-to-rent strategy.",
                "BGE-LOT-111 — Lot 111 park facing from $372K. Park-facing scarcity drives rental and resale premium.",
                "VIL-APT-201 — Residence 201. Strong rental appeal, park facing, rooftop amenities.",
                "VIL-APT-302 — Residence 302. Corner position, study zone, broad renter appeal.",
                "VIL-HL-HAVEN — The Haven. Entry-level pricing, rental demand from first-home aspirants.",
                "VIL-TER-01 to VIL-TER-04 — Terraces. Scarcity and boutique appeal in tight rental market.",
            ],
            "LuxuryPrestige": [
                "VIL-APT-502 — Residence 502. Executive layout, treetop views, exclusive.",
                "VIL-APT-601 — The Penthouse. Entire top floor. Panoramic views. Price on application.",
                "VIL-HL-AURELIA — The Aurelia. 5-bed legacy family home.",
                "BGE-LOT-112 — Lot 112. Widest frontage, premium position — build a standout prestige home.",
            ],
            "LandBuyer": [
                "BGE-LOT-104 — Lot 104, Corner, $379K. Best design flexibility in the estate.",
                "BGE-LOT-111 — Lot 111, Park Facing, $372K. Best lifestyle position in the estate.",
                "BGE-LOT-112 — Lot 112, Premium Wide Frontage, $389K. Best block in the estate.",
                "BGE-LOT-108 — Lot 108, Wide Frontage, $365K. Strong design freedom at a mid-range price.",
                "BGE-LOT-107 — Lot 107, $345K. Best entry price in the portfolio.",
            ],
        },
        "ARIANotes": (
            "Always present 1–2 listings max — never a full list dump. "
            "Lead with the strongest match and explain in one sentence why it fits what the visitor told you. "
            "ALWAYS include the listing URL when presenting any property — use the URL field from each listing. "
            "Include the full https:// URL so the platform renders a preview. "
            "If budget is slightly short, pivot warmly: acknowledge it positively and show the closest fit. "
            "If a visitor's preferred type has no match, guide them to the most similar option and explain the lifestyle crossover. "
            "Penthouse enquiries: always offer a private consultation rather than stating price in chat. "
            "Terrace pricing: ranges from $599K–$649K — name the specific terrace and its price naturally. "
            "Frame terrace scarcity naturally ('only 4 left from a collection of 10'). "
            "Land lots: all 12 are 360m², titled and ready to build. Prices $345K–$389K. "
            "Frame land lot scarcity naturally ('final stage release — only 12 lots'). "
            "Highlight standout lots by tag: Corner (Lot 104), Wide Frontage (Lot 108), Park Facing (Lot 111), Premium (Lot 112). "
            "For land buyers, always mention construction loan and FHOG eligibility naturally. "
            "Finance options are available across all collections — introduce naturally when appropriate."
        ),
    },
}