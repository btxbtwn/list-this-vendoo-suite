# VENDOO CROSS-LISTING TEMPLATE

Purpose: produce copy/insert-ready field values for Vendoo + eBay + Etsy + Poshmark + Depop from attached photos and any notes.

# **GLOBAL OUTPUT RULES (Hard Constraints)**

* Complete STEP -1 then STEP 0 before any marketplace blocks.  
* Output ONLY the fields in the exact order shown. Do not add extra commentary.  
* One field per line in the format: Field: Value  
* Never combine multiple fields into one line.  
* If unknown or not visible, leave blank after the colon (do not guess).  
* Do not use an em dash in any title or description (use a standard hyphen if needed).  
* Do not add a period after the last tag in any tag list.  
* Pricing MUST follow the canonical formula in `skills/list-this/SKILL.md`: sold-comp median × 1.35, whole dollars only. Auto-accept = listing price minus $2. Minimum offer = listing price minus $4.
* Physical-item descriptions MUST use the Size / Condition / Measurements formula in `SKILL.md`. Do not invent material, garment care, production date, original retail, or vintage status.

# **INPUTS**

***Attach photos. Optionally paste any known details below (leave blank if none).***

**User Notes:** 

**Known Brand (if any):** 

**Known Size (if any):** 

**Known Flaws (if any):** 

Target Platform Overrides (if any): 

STEP -1: PHOTO-TO-DATA EXTRACTION (Facts Only)

Fill these from photos (tags, labels, visible details). Do not include measurements in body text; keep them here only.

**Item Type:**

**Category Guess:**

**Brand:**

**Style/Model Name or Code:**

**Size Tag:**

**Size Type (Regular/Petite/Tall/Plus/Maternity):**

**Department (Women/Men/Unisex/Kids):**

**Primary Color:**

**Secondary Color:**

**Pattern:**

**Material(s) from Tag:**

**Fabric Type/Texture:**

**Closure:**

**Accents:**

**Fit/Silhouette:**

**Era/Aesthetic (2-3):**

**Condition Grade (New w tags/New/Excellent/Good/Fair):**

**Flaws (list):**

**Measurements (if shown):**

**Etsy Vintage Eligible? (Yes/No/Unknown):**

**When Made (Etsy dropdown if vintage):**

# **STEP 0: LIVE DEMAND & PRICING CHECK (Sold Comps)**

Build search strings from {brand + item + color + fit + pattern + era} + synonyms. Use median sold price when exact matches exist.

**Search String (Primary):**

**Search String (Backup):**

**Comps Source (eBay/Poshmark/Depop/Etsy):**

**Market Price (median sold):**

**Listing Price (Market x 1.35):**

**Auto-Accept Offer (Listing - 2):**

**Minimum Offer (Listing - 4):**

# **STANDARDIZED COPY BLOCKS**

Generate once, then reuse across platforms (with Etsy-safe adjustments if needed).

TITLE + DESCRIPTION BLOCKS

 Branded Title (eBay/Poshmark) (80 chars)  
 {BRAND} {SIZE} {VIBE/AESTHETIC} {ITEM} {COLOR} {FIT/SILHOUETTE} {DECADE/TREND}

*line break*

Etsy-Safe Title (Etsy only – no brand) (140 chars)  
 {VIBE/AESTHETIC} {SIZE}  {ITEM} {COLOR} {FIT/SILHOUETTE} {DECADE/TREND} {STYLE KEYWORDS}

*line break*

Universal Description (paste-ready, include line breaks, 200-300 characters) 

{Vibe/era} {decade/trend} {brand} {item} with {key style/feature} in {color/pattern}.​

*line break*

{Fit/silhouette} in {fabric/texture}, styled for {use-case/season}.​

*line break*

Size: {size}

*line break*

Condition: {honest assessment}; Flaws: {specific, only list flaws if you see them in the photos- otherwise do not list flaws}.​ See photos for details.

*line break*

Measurements: {key set} or “See photos for full measurements” if fully legible there.​

*line break*

OFFERS WELCOME! Ships in 1-2 business days. 

*line break*

15% off bundles of 2+ items.

*line break*

QUICK-SWITCH TITLE MATRIX

eBay: Branded Title

Poshmark: Branded Title

Etsy: Etsy-Safe Title (no brand)

Depop: No title field → use Universal Description only

**Keywords/Tags Pool (comma-separated):**

# **FINAL OUTPUTS (COPY/INSERT READY)**

***Return TWO things:***
1. **Human Readable Template**: A clean summary for the user to read.
2. **Extension JSON**: The strict JSON block for the Vendoo extension.

## **1. Human Readable Template**

**Title:** {Title}
**Description:** {Description}
**Condition:** {Condition}; {Flaws}.
**Measurements:** See photos for measurements.
**Brand:** {Brand}
**Size:** {Size}
**Color:** {Color}
**Material:** {Material}
**Price:** ${Price}
**Weight:** {Weight} oz
**Tags:** {Tags}

## **2. Extension JSON Structure**

```json
{
  "title": "Fruit of the Loom XL 2012 NHRA Auto Club Finals T-Shirt White Drag Racing Pomona",
  "description": "2012 NHRA Auto Club Finals Fruit of the Loom T-Shirt with Pomona Drag Racing graphic in White.\n\nStandard fit in 100% Cotton, styled for Racing fans.\n\nSize: XL\n\nCondition: Pre-Owned - Fair; Flaws: Small stain on sleeve/shoulder area, small pinhole near bottom hem. See photos for details.\n\nMeasurements: See photos for measurements.\n\nOFFERS WELCOME! Ships in 1-2 business days.\n\n15% off bundles of 2+ items.",
  "price": 15,
  "cost": 5.00,
  "quantity": 1,
  "brand": "Fruit of the Loom",
  "condition": "Good",
  "primaryColor": "White",
  "secondaryColor": "Red",
  "department": "Men",
  "sizeType": "Regular",
  "size": "XL",
  "size_us": "XL",
  "tags": ["Drag Racing", "NHRA", "Pomona", "Auto Club", "Racing", "Streetwear", "Car Guy"],
  "labels": ["To List"],
  "weight_lb": 0,
  "weight_oz": 8,
  "package_dimensions_in": "13x10x3",
  "category_path": "Clothing, Shoes & Accessories > Men > Men's Clothing > Shirts > T-Shirts",
  "zipCode": "70125",
  
  "ebay_specifics": {
    "type": "T-Shirt",
    "department": "Men",
    "sizeType": "Regular",
    "size": "XL",
    "brand": "Fruit of the Loom",
    "color": "White",
    "material": "Cotton",
    "sleeveLength": "Short Sleeve",
    "sleeveType": "Set-In",
    "neckline": "Crew Neck",
    "fit": "Regular",
    "pattern": "Solid",
    "theme": "Racing, Cars, 2010s, Drag Racing",
    "features": "Double-Sided Graphic",
    "strapType": "N/A",
    "character": "N/A",
    "characterFamily": "NHRA",
    "occasion": "Casual",
    "season": "Summer",
    "vintage": "No",
    "countryOfOrigin": "El Salvador",
    "garmentCare": "Machine Washable",
    "handmade": "No",
    "personalize": "No",
    "unitQuantity": "1",
    "unitType": "Unit",
    "yearManufactured": "2010-2019",
    "closure": "Pullover",
    "fabricType": "Knit",
    "accents": "Logo",
    "performanceActivity": "N/A",
    "style": "Graphic Tee",
    "mpn": "Does Not Apply",
    "upc": "Does Not Apply"
  },
  
  "etsy_specifics": {
    "who_made": "Another company or person",
    "what_is": "A finished product",
    "when_made": "2010 - 2019 (Recently)",
    "section": "T-Shirts",
    "materials": ["Cotton"],
    "tags": ["vintage", "racing", "nhra", "graphic tee", "streetwear"],
    "renewalOption": "Automatic",
    "category_specifics": {
      "clothingStyle": "Streetwear",
      "sleeveLength": "Short sleeve",
      "neckline": "Crew",
      "graphic": "Sports & fitness",
      "fabricPattern": "Solid"
    }
  },
  
  "poshmark_specifics": {
    "originalPrice": 0,
    "smartPricing": false,
    "smartPricingMin": "",
    "costPrice": 5.00,
    "otherInfo": ""
  },

  "mercari_specifics": {
    "shippingLabel": "USPS Ground Advantage"
  },

  "depop_specifics": {
    "source": "Preloved",
    "age": "Modern",
    "style": ["Streetwear", "Sportswear", "Graphic"],
    "material": "Cotton",
    "occasion": ["Casual", "Sportswear", "Vacation"],
    "condition": "Used - Fair",
    "location": "New Orleans, LA",
    "shippingMethod": "Depop USPS",
    "parcelSize": "Small"
  }
}
```

### **JSON Field Reference**

**Main Vendoo Fields:**
- `title` (required): Listing title, max 80 chars
- `description` (required): Multi-line description with line breaks
- `price` (required): Listing price
- `cost`: Cost of goods
- `quantity`: Available quantity (default: 1)
- `brand`: Brand name
- `condition`: Vendoo general form values only. See `references/vendoo-dropdown-options.md` — each marketplace uses a different condition vocabulary.
- `primaryColor`: Main color (MUST be basic color: Red, Blue, Green, Yellow, Orange, Purple, Pink, Brown, Gray, Black, White, Beige, Navy)
- `secondaryColor`: Accent color (MUST be basic color: Red, Blue, Green, Yellow, Orange, Purple, Pink, Brown, Gray, Black, White, Beige, Navy)
- `department`: Men, Women, Unisex, Kids

**Color Standardization Rules:**
- **ALWAYS use basic colors** for primaryColor and secondaryColor
- **Map specific shades to basics**:
  - Teal, Turquoise, Aqua → **Blue**
  - Burgundy, Maroon, Wine → **Red**
  - Charcoal, Slate → **Gray**
  - Mint, Sage, Olive → **Green**
  - Coral, Salmon, Peach → **Orange**
  - Lavender, Lilac, Mauve → **Purple**
  - Cream, Ivory, Off-White → **White**
  - Tan, Khaki, Camel → **Beige**
  - Mustard, Gold → **Yellow**
  - Rust, Copper, Bronze → **Brown**
  - Indigo, Cobalt, Royal → **Blue**
  - Fuchsia, Magenta, Hot Pink → **Pink**
  - For multicolor items: primaryColor = "Multi", secondaryColor = blank or most prominent color
- `sizeType`: Regular, Petite, Tall, Plus, Maternity
- `size`: Size value (S, M, L, XL, numeric)
- `size_us`: US size for consistency
- `tags`: Array of keywords
- `labels`: Array of Vendoo labels
- `weight_lb`, `weight_oz`: Packaged shipping weight. Estimate from item type/size when the seller did not provide a scale weight (do not ask). Example: a women's M graphic tee is often `0` lb / `8`–`12` oz packaged.
- `package_dimensions_in`: Format "LxWxH". Use a reasonable poly-mailer / packaging estimate for the item unless the seller provided dimensions.
- `category_path`: Full category path
- `category_path` must end at a selectable Vendoo General leaf. Use `Clothing, Shoes & Accessories > Women > Women's Clothing > Tops` for women's shirts and T-shirts; `Shirts & Blouses` is not a valid Vendoo General segment. For men's T-shirts, use `Clothing, Shoes & Accessories > Men > Men's Clothing > Shirts > T-Shirts`.
- `zipCode`: Ship from ZIP code

**eBay Specifics:**
All eBay Item Specifics fields. Use Appendix values.

**Etsy Specifics:**
- `who_made`, `what_is`, `when_made` (required for Etsy). `when_made` must be an exact Etsy dropdown value from `vendoo-dropdown-options.json`, such as `2010 - 2019 (Recently)`, not `2010s` or `2010-2019`.
- `section`: Shop section
- `materials`: Array of materials
- `tags`: Up to 13 tags
- `renewalOption`
- Shipping profile, processing time, and return policy are account-level Etsy settings — leave them out
- `category_specifics`: T-shirt optional fields after Show Optional Fields. Use live Etsy dropdown values from `vendoo-dropdown-options.json` (`clothingStyle`, `sleeveLength`, `neckline`, `closure`, `graphic`, `fabricPattern`). Fill every applicable row. Use Does Not Apply only for `graphic` / `collarStyle` / `occasion` / `holiday` / `sustainability` when they literally do not apply.

**Poshmark Specifics:**
- `originalPrice`: MSRP for comparison
- `smartPricing`: Enable smart pricing (true/false)
- Shipping discount and return policy are account-level Poshmark settings — leave them out

**Depop Specifics:**
- `source`: Preloved, Vintage, Deadstock, etc.
- `age`: Modern, Vintage, Y2K, 90s, etc.
- `style`: Array of 3 styles
- `occasion`: Array of 3 occasions
- `parcelSize`: Exact Depop dropdown value (`Extra extra small`, `Extra small`, `Small`, `Medium`, `Large`, `Extra large`). Do not include weight or price notes. Pick the tier that matches `weight_lb`/`weight_oz`: under 4oz Extra extra small, under 8oz Extra small, under 12oz Small, under 1lb Medium, under 2lb Large, otherwise Extra large.

# **APPENDIX: ALLOWED VALUES REFERENCES (Do not copy into outputs)**

Use these lists only to select valid dropdown values. Outputs should still be the clean one-line Field: Value format.

## **eBay Optional Fields - Value Lists**

* “Show Optional Fields” – REQUIRED  
* Fill every applicable optional row. Use Does Not Apply only when the attribute literally does not apply (MPN, UPC, Character, Theme, Strap Type, Fabric Weight, Accents, Country of Origin, Sleeve Type). Never leave Features, Neckline, Season, Fit, Pattern, Occasion, Closure, Unit Quantity, or Unit Type blank.  
* Accents: Beaded, Bow, Button, Crochet, Embroidered, Fringe, Fur Trim, Glitter, Jewel, Logo, Pleated, Quilted, Rhinestone, Ruffle, Sequin, Strap, Studded, Tasseled, Zipper  
* Character: (if applicable) Disney, Marvel, Band name, etc.  
* Closure: Zip, Button, Snap, Tie, Pullover, Hook & Eye, Elastic, Toggle, Velcro, Drawstring, Clasp, Lace-up, Magnetic  
* Collar Style: Band, Button-Down, Point, Sailor, Shawl, Spread, Stand-Up, Wing  
* Country/Region of Manufacture: USA, China, Vietnam, Mexico, India, Bangladesh, Italy, etc.  
* Fabric Type: Canvas, Chiffon, Corduroy, Crochet, Denim, Flannel, Fleece, Jersey, Knit, Lace, Microfiber, Rayon, Satin, Tweed, Twill, Velvet  
* Features: 1/2 Zip, 1/4 Zip, Adjustable, All Seasons, Belted, Breathable, Buckle, Collarless, Full Zip, Graphic Print, Heavyweight, Hooded, Insulated, Lightweight, Lined, Moisture Wicking, Open, Oversized, Pockets, Preshrunk, Reflective, Reversible, Ring Spun, Sheer, Shoulder Pads, Stretch, Tagless, Taped Seams, Thermal, Waterproof, Water Resistant  
* Fit: Athletic, Classic, Extra-Slim, Regular, Relaxed, Slim​  
* Garment Care: Machine Washable, Hand Wash Only, Dry Clean Only, Tumble Dry Low, Line Dry, Do Not Bleach, Iron Low  
* Handmade: Yes / No  
* Jacket/Coat Length: Short, Mid-Length, Long, Extra Long  
* Knit Style: Cable-Knit, Chunky-Knit, Open-Knit, Tight-Knit, Waffle-Knit  
* Material: Cotton, Polyester, Spandex, Nylon, Rayon, Linen, Silk, Wool, Acrylic, Denim, Leather, Suede, Cashmere, Modal, Viscose, Bamboo, Hemp  
* Neckline: Boat Neck, Collared, Cowl Neck, Crew Neck, High Neck, Mock Neck, Round Neck, Scoop Neck, Square Neck, Turtleneck, V-Neck  
* Occasion (Only these options): Casual; Travel; Business; Formal; Party/Cocktail; Workwear  
* Performance/Activity: Baseball; Basketball; Bodybuilding; CrossFit; Cross Training; Cycling; Dance; Football; Golf; Gym & Training; Hiking; Hockey; Hunting; Lacrosse; Pilates; Racing; Riding; Rugby; Running & Jogging; Skateboarding; Skiing; Soccer; Squash; Tennis; Track & Field; Volleyball; Walking; Weightlifting; Wrestling; Yoga  
* Pattern: Solid, Striped, Floral, Plaid, Polka Dot, Animal Print, Geometric, Abstract, Paisley, Tie-Dye, Camo, Color Block, Graphic Print  
* Personalize: Yes / No  
* Season: Spring, Summer, Fall, Winter  
* Sleeve Length: Sleeveless, Cap Sleeve, Short Sleeve, 3/4 Sleeve, Long Sleeve  
* Sleeve Type: Asymmetrical Sleeve, Balloon Sleeve, Bell Sleeve, Cap Sleeve, Cold Shoulder Sleeve, Dolman Sleeve, Flared Sleeve, Flutter Sleeve, Kimono Sleeve, Puff Sleeve, Raglan Sleeve, Roll Tab Sleeve, Slit Sleeve, Strappy Sleeve  
* Strap Type (if applicable): Adjustable, Convertible, Spaghetti, Tank, Halter, Strapless, Racerback, Crisscross  
* Style (choose 1): Basic, Camisole, Cropped, Jersey, Kimono, Ringer, Tunic  
* Theme: 80s; 90s; Animals; Anime; Army; Art; Aztec; Beach; Beer; Biker; Bird; Bohemian; Butterfly; Cars; Cartoon; Cat; Christmas; City; Classic; Coins; College; Colorful; Comics; Countries; Cowboy; Dad; Designer; Dog; Fish; Flag; Flower; Funny; Geek; Gothic; Grunge; Halloween; Hawaiian; Heart; Hip Hop; Hippie; Hipster; Holiday; Horror; Horse; Indian; Italian; Korean; Leopard; London; Love; Marine; Metal; Money; Moon; Motorcycle; Movie; Music; Nature; Nautical; Nerd; Outdoor; Owl; Paris; Patriotic; Peasant; Preppy; Princess; Punk; Quotes; Rainbow; Retro; Rock; School; Shell; Ski; Skull; Snake; Southwestern; Space; Sports; Stars; Steampunk; Tattoo; Teacher; Tortoise; Transportation; Tribal; Tropical; Unicorn; University; USA; Wedding; Western; Zebra  
* Unit Quantity: 1; Unit Type: Unit; Vintage: Yes / No; MPN: Does Not Apply; UPC: Does Not Apply

## **Etsy Optional Fields - Value Lists**

* “Show Optional Fields” – REQUIRED  
* Fill every applicable optional row. Use Does Not Apply only when the attribute literally does not apply (Graphic, Collar style, Holiday, Occasion, Sustainability). Always fill Clothing style, Sleeve length, Neckline, Closure, and Fabric pattern.  
* Clothing Style (up to 1): ---- ; Western & cowboy ; Minimalist ; Boho & hippie ; Gothic ; Harajuku ; Lolita ; Military ; Mod ; Preppy ; Rave ; Pin-up & rockabilly ; Rocker ; Menswear  
* Closure (up to 3): Zipper; Buttons; Tie; Pullover; Elastic; Hook & eye; Snap; Drawstring; Lace-up; Toggle; Velcro  
* Jacket Style: ----; Motorcycle; Bomber; Cape; Jean; Overcoat; Parka; Peacoat; Puffer; Raincoat; Track; Trench; Windbreaker; Nehru; Sherwani  
* Sleeve Length: Sleeveless; Short sleeve; 3/4 sleeve; Long sleeve  
* Neckline: Crew; V-Neck; Collared; Scoop; Off-Shoulder; Sweetheart; Boat; Cowl; Square; Halter; High neck; Turtleneck  
* Collar Style (up to 1): Band; Bertha; Bow; Butterfly; Cape; Cutaway; Funnel; High neck; Jabot; Peter Pan; Rolled; Ruffle; Sailor; Shawl; Straight; Tab; Wing tip  
* Occasion (up to 1): Bachelorette party; Birthday; Engagement; Graduation; Wedding; LGBTQ pride  
* Holiday (up to 1): Lunar New Year; Christmas; Easter; Halloween; Hanukkah; Independence Day; Kwanzaa; New Year’s; St Patrick’s Day; Thanksgiving; Valentine’s Day  
* Season: Spring, Summer, Fall, Winter  
* Size: From list  
* Sustainability (up to 3): Eco‑friendly; Organic; Recycled; Upcycled; Handmade; Made to order  
* Pattern: Abstract; Animal print; Camouflage; Check; Floral; Geometric; Herringbone; Houndstooth; Ikat; Paisley; Plaid; Polka dot; Solid; Striped; Tie dye; Patchwork; Southwestern

## **Poshmark Style Tags - Master List**

* Style Tags (separate with commas, 3 max):  (70s, 80s, 90s, Activewear, Animal Print, Athleisure, Avant Garde, Baggy, Balletcore, Beach, Bodycon, Bohemian, Bow, Bridal, Bridesmaid, Business Casual, Cable Knit, Cashmere, Casual, Chunky, Collegiate, Colorblock, Colorful, Contemporary, Coord Sets, Coquette Girl, Corduroy, Cottagecore, Cozy, Crochet, Cropped, Cruelty-Free, Cut-Out, Drop Waist, Eclectic Grandpa, Embroidered, Fall, Faux Fur, Feminine, Festival, Festive, Flannel, Flare, Floral, Formal, Fringe, Gingham, Girlhoodcore, Gorpcore, Goth, Grunge, Hand Knit, Handmade, Herringbone, Houndstooth, Leather, Leopard Print, Lightweight, Linen, Luxury, Maximalism, Mesh, Metallic, Minimalist, Monochrome, Neutral, Nylon, Office, Oversized, Paisley, Party, Pastel, Patchwork, Peplum, Plaid, Platform, Pleated, Polka Dot, Preppy, Punk, Quiet Luxury, Quilted, Relaxed Fit, Resortwear, Retro, Rosette, Ruffle, Satin, Silk, Sporty, Strapless, Streetwear, Stripes, Suede, Tailored, Tennis Prep, Travel, Tropical, Tweed, Two-Tone, Unisex, Upcycled, Utility, Vacation, Vegan, Velour, Vintage, Waterproof, Wedding, Western, Whimsigoth, Winter, Wool, Woven, Y2K)

## **Depop Tags + Style + Parcel Sizes**

* Tags (separate with commas, up to five): #y2k; #vintage; #90s; #grunge; #coquette; #indie; #preppy; #boho; #streetwear; #cottagecore; #emo; #punk; #retro; #minimalist  
* Condition: Brand new; Like new; Used - Excellent; Used - Good; Used - Fair  
* Primary/Secondary Color  
* Source: Preloved; Vintage  
* Age: 50s; 60s; 70s; 80s; 90s; Y2K; Modern  
* Style (exactly 3): Streetwear; Sportswear; Loungewear; Goth; Boho; Western; Indie; Skater; Rave; Costume; Cosplay; Grunge; Emo; Minimalist; Preppy; Avant Garde; Punk; Glam; Regency; Casual; Utility; Futuristic; Cottage; Fairy; Kidcore; Y2K; Biker; Gorpcore; Twee; Coquette; Whimsygoth; Retro
* “Show Optional Fields” – REQUIRED  
* Fill every applicable Depop optional row. Omit Size Grouping for Regular sizing (it does not apply). Always fill Source, Age, Style (3), Occasion (3), and Parcel Size. Material only from tag evidence.  
* Size Grouping (1): Maternity; Petite; Plus Size; Tall  
* Type (up to 2): Blazer, Bomber, Cape, Duster, Lightweight, Poncho, Puffer, Shacket, Varsity, Windbreaker  
* Material (up to 4): Cotton; Polyester; Spandex; Silk; Wool; Leather; Denim; Nylon; Rayon; Linen; Acrylic; Velvet; Corduroy; Fleece; Satin  
* Type (up to 2): Blazer, Bomber, Cape, Duster, Lightweight, Poncho, Puffer, Shacket, Varsity, Windbreaker  
* Occasion (exactly 3): Casual; Party; Festival; Gifting; Going out; Outdoors; Relaxation; School; Ski; Special Occasion; Summer; Vacation; Winter; Workout; Beach; Date night; Work  
* Qty: 1  
* Category: exact  
* Brand: from list or “Other”  
* Location: New Orleans, LA  
* Shipping: Depop USPS  
* Depop parcel sizes (use these exact dropdown values; weight notes are not part of the value)  
* Extra extra small — Under 4oz  
* Extra small — Under 8oz  
* Small — Under 12oz  
* Medium — Under 1lb  
* Large — Under 2lb  
* Extra large — Under 10lb

# **2026 STRATEGY UPDATES (Daily Protocol)**

* **BOLO Brands 2026 (Price Aggressively):**
    * **Women:** Lululemon, Alo Yoga, Vuori, Nike, Gymshark, Quince, Everlane, Halara, Sezane, House of CB.
    * **Men:** Kuhl, Carhartt, Patagonia, Chrome Hearts, Ralph Lauren, Vuori, Outdoor Research.
    * **Target:** Wild Fable, A New Day (flip fast).
* **Trend Keywords (Inject into Title/Tags):**
    * **Aesthetics:** "Gorpcore" (outdoor/hiking), "Y2K" (90s/00s), "Coquette" (bows/lace), "Silent Luxury" (basics/neutrals).
    * **Styles:** Wide-Leg/Flare (Jeans), Skorts, Oversized Hoodies, Graphic Tees (Single-stitch).
* **Platform Strategy:**
    * **eBay:** Maximize Item Specifics (Sleeve, Fit, Theme).
    * **Depop:** Use "Punchy" descriptions + Aesthetic tags (#y2k #grunge).
    * **Poshmark:** Use NWT toggle if applicable + 3 Style Tags.
* **Pricing Rule:** Always check sold comps + live listings. If brand is on BOLO list, aim for upper range of comps.
