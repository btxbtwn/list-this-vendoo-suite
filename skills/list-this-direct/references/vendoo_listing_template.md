# Vendoo Listing Schema Reference

Reference-only support material for `list-this-direct`.

## Ownership and scope

- `../list-this/SKILL.md` and the current `list-this` output remain the only source of truth for copy, pricing, comps, category reasoning, and marketplace policy.
- Use this file only to confirm Vendoo/marketplace field names, JSON nesting, and allowed dropdown values while mapping already-approved `list-this` data into live forms.
- Do not use this file to generate new titles, descriptions, pricing rules, offer math, trend keywords, or marketplace strategy.

## Example extension JSON shape

Illustrative structure only. Treat the keys and nesting as the reference; treat example values as placeholders, not instructions. If you need live listing values, regenerate them with `list-this` instead of copying from this example.

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
  "labels": [],
  "weight_lb": 0,
  "weight_oz": 8,
  "package_dimensions_in": "13x10x3",
  "category_path": "Clothing, Shoes & Accessories > Men > Men's Clothing > Shirts",
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
    "when_made": "2010-2019",
    "section": "T-Shirts",
    "materials": ["Cotton"],
    "tags": ["vintage", "racing", "nhra", "graphic tee", "streetwear"],
    "renewalOption": "Automatic",
    "processingTime": "1-2 business days",
    "shippingTemplate": "Standard Shipping",
    "category_specifics": {
      "clothingStyle": "Graphic",
      "sleeveLength": "Short Sleeve",
      "neckline": "Crew Neck",
      "graphic": "Racing",
      "occasion": "Everyday",
      "fabric": "Cotton",
      "pattern": "Graphic"
    }
  },
  
  "poshmark_specifics": {
    "originalPrice": 89.00,
    "discountShipping": "",
    "smartPricing": false,
    "smartPricingMin": "",
    "costPrice": 5.00,
    "otherInfo": ""
  },
  
  "depop_specifics": {
    "source": "Preloved",
    "age": "Modern",
    "style": ["Streetwear", "Sportswear", "Graphic"],
    "material": "Cotton",
    "size_grouping": "US",
    "occasion": ["Casual", "Sportswear", "Vacation"],
    "condition": "Used - Fair",
    "location": "New Orleans, LA",
    "shippingMethod": "Depop USPS",
    "parcelSize": "Small (S): Under 12 oz — $6.49"
  }
}
```

## JSON field reference

Populate these fields from `list-this`; this section only describes the expected field names and shapes.

**Main Vendoo Fields:**
- `title` (required): Listing title, max 80 chars
- `description` (required): Multi-line description with line breaks
- `price` (required): Listing price
- `cost`: Cost of goods
- `quantity`: Available quantity (default: 1)
- `brand`: Brand name
- `condition`: Good, Excellent, Fair, New with Tags, etc.
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
- `weight_lb`, `weight_oz`: Package weight
- `package_dimensions_in`: Format "LxWxH"
- `category_path`: Full category path
- `zipCode`: Ship from ZIP code

**eBay Specifics:**
All eBay Item Specifics fields. Use Appendix values.

**Etsy Specifics:**
- `who_made`, `what_is`, `when_made` (required for Etsy)
- `section`: Shop section
- `materials`: Array of materials
- `tags`: Up to 13 tags
- `renewalOption`, `processingTime`, `shippingTemplate`

**Poshmark Specifics:**
- `originalPrice`: MSRP for comparison
- `discountShipping`: Shipping discount option
- `smartPricing`: Enable smart pricing (true/false)

**Depop Specifics:**
- `source`: Preloved, Vintage, Deadstock, etc.
- `age`: Modern, Vintage, Y2K, 90s, etc.
- `style`: Array of 3 styles
- `occasion`: Array of 3 occasions
- `parcelSize`: Shipping size tier

## Appendix: allowed values reference

Use these lists only to choose valid dropdown values when mapping `list-this` output into live Vendoo or marketplace forms.

### eBay optional fields - value lists

* “Show Optional Fields” – REQUIRED  
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

### Etsy optional fields - value lists

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

### Poshmark style tags - master list

* Style Tags (separate with commas, 3 max):  (70s, 80s, 90s, Activewear, Animal Print, Athleisure, Avant Garde, Baggy, Balletcore, Beach, Bodycon, Bohemian, Bow, Bridal, Bridesmaid, Business Casual, Cable Knit, Cashmere, Casual, Chunky, Collegiate, Colorblock, Colorful, Contemporary, Coord Sets, Coquette Girl, Corduroy, Cottagecore, Cozy, Crochet, Cropped, Cruelty-Free, Cut-Out, Drop Waist, Eclectic Grandpa, Embroidered, Fall, Faux Fur, Feminine, Festival, Festive, Flannel, Flare, Floral, Formal, Fringe, Gingham, Girlhoodcore, Gorpcore, Goth, Grunge, Hand Knit, Handmade, Herringbone, Houndstooth, Leather, Leopard Print, Lightweight, Linen, Luxury, Maximalism, Mesh, Metallic, Minimalist, Monochrome, Neutral, Nylon, Office, Oversized, Paisley, Party, Pastel, Patchwork, Peplum, Plaid, Platform, Pleated, Polka Dot, Preppy, Punk, Quiet Luxury, Quilted, Relaxed Fit, Resortwear, Retro, Rosette, Ruffle, Satin, Silk, Sporty, Strapless, Streetwear, Stripes, Suede, Tailored, Tennis Prep, Travel, Tropical, Tweed, Two-Tone, Unisex, Upcycled, Utility, Vacation, Vegan, Velour, Vintage, Waterproof, Wedding, Western, Whimsigoth, Winter, Wool, Woven, Y2K)

### Depop tags + style + parcel sizes

* Tags (separate with commas, up to five): #y2k; #vintage; #90s; #grunge; #coquette; #indie; #preppy; #boho; #streetwear; #cottagecore; #emo; #punk; #retro; #minimalist  
* Condition: Brand new; Like new; Used - Excellent; Used - Good; Used - Fair  
* Primary/Secondary Color  
* Source: Preloved; Vintage  
* Age: 50s; 60s; 70s; 80s; 90s; Y2K; Modern  
* Style (exactly 3): Streetwear; Sportswear; Loungewear; Goth; Boho; Western; Indie; Skater; Rave; Costume; Cosplay; Grunge; Emo; Minimalist; Preppy; Avant Garde; Punk; Glam; Regency; Casual; Utility; Futuristic; Cottage; Fairy; Kidcore; Y2K; Biker; Gorpcore; Twee; Coquette; Whimsygoth; Retro
* “Show Optional Fields” – REQUIRED  
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
* Depop parcel sizes & prices (choose based on weight)  
* Extra extra small (XXS): Under 4 oz — $4.99​  
* Extra small (XS): Under 8 oz — $5.99​  
* Small (S): Under 12 oz — $6.49​  
* Medium (M): Under 1 lb — $7.99​  
* Large (L): Under 2 lb — $11.99​  
* Extra large (XL): Under 10 lb — $13.99​
