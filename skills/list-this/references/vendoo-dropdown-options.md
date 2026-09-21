# Vendoo marketplace dropdown options

Scraped live from `https://web.vendoo.co` on **2026-09-08**.

Machine-readable copy: `vendoo-dropdown-options.json`.

**Category used for category-specific fields:** Clothing, Shoes & Accessories > Men > Men's Clothing > Shirts > T-Shirts (eBay 15687, Poshmark Men > Shirts > Tees - Short Sleeve, Depop `menswear_shirts`, Etsy 449). Other categories will expose different specifics.

Brand, tags, Character, Country of Origin, Model, and similar open-ended fields were skipped.

## Condition (fill-critical)

Each marketplace has its own vocabulary. Filling Vendoo general `condition` into marketplace overrides will miss unless the filler maps these strings.

| Marketplace | Options |
|---|---|
| **Vendoo general** | New With Tags/Box · New Without Tags/Box · New With Imperfections · Pre-Owned - Excellent · Pre-Owned - Good · Pre-Owned - Fair · Poor (Major flaws) |
| **eBay** | New with tags · New without tags · New with imperfections · Pre-owned - Excellent · Pre-owned - Good · Pre-owned - Fair |
| **Poshmark** | New With Tags (NWT) · Like New · Good · Fair |
| **Mercari** | New (New with tags) · Like new (New without tags) · Good (Gently used) · Fair (Used) · Poor (Major flaws) |
| **Depop** | Brand new · Like new · Used - Excellent · Used - Good · Used - Fair |
| Etsy / Facebook / Shopify / Vinted / Whatnot | No condition dropdown on the Vendoo form |

Poshmark help text: NWT = tags/packaging; Like New = new without tags; Good = gently used; Fair = visible wear.

Depop help text: Brand new = unused with tags; Like new = mint pre-owned or new without tags; Used - Excellent/Good/Fair = increasing wear.

eBay has no Poor option. Casing differs from Vendoo (`Pre-owned` vs `Pre-Owned`).

The Studio extension maps Vendoo general condition → marketplace labels before filling:

| Vendoo general | eBay | Poshmark | Mercari | Depop |
|---|---|---|---|---|
| New With Tags/Box | New with tags | New With Tags (NWT) | New (New with tags) | Brand new |
| New Without Tags/Box | New without tags | Like New | Like new (New without tags) | Like new |
| New With Imperfections | New with imperfections | Good | Good (Gently used) | Used - Good |
| Pre-Owned - Excellent | Pre-owned - Excellent | Like New | Like new (New without tags) | Used - Excellent |
| Pre-Owned - Good | Pre-owned - Good | Good | Good (Gently used) | Used - Good |
| Pre-Owned - Fair | Pre-owned - Fair | Fair | Fair (Used) | Used - Fair |
| Poor (Major flaws) | Pre-owned - Fair | Fair | Poor (Major flaws) | Used - Fair |

## Colors

| Marketplace | Options |
|---|---|
| **Vendoo / eBay** | Beige, Black, Blue, Brown, Cream, Gold, Gray, Green, Orange, Multicolor, Pink, Purple, Red, Silver, Yellow, Tan, White |
| **Etsy** | Same list **without** Multicolor |
| **Poshmark** | Same list **without** Beige and Multicolor |
| **Depop** | Black, Grey, White, Brown, Tan, Cream, Yellow, Red, Burgundy, Orange, Pink, Purple, Blue, Navy, Green, Khaki, Multi, Silver, Gold |

Depop uses **Grey** (not Gray) and **Multi** (not Multicolor), plus Burgundy, Navy, Khaki.

The Studio extension maps Vendoo general colors before filling. When Multicolor has no marketplace option, secondary is promoted to primary so the required field is not left blank:

| Incoming / Vendoo | eBay | Etsy | Poshmark | Depop |
|---|---|---|---|---|
| Gray / Grey | Gray | Gray | Gray | Grey |
| Multicolor / Multi | Multicolor | *skipped* → use secondary | *skipped* → use secondary | Multi |
| Beige | Beige | Beige | Tan | Tan |
| Navy | Blue | Blue | Blue | Navy |
| Burgundy | Red | Red | Red | Burgundy |
| Khaki | Beige | Beige | Tan | Khaki |

## Vendoo general

- **US Size** (after T-Shirt category): 2XS–8XL, combos (S/M, M/L, L/XL, XS/S), numeric 28–62, Big 1X–6X, ST–6XLT, One Size, IT/EU/FR 42–60.
- Size Type (`#generalDetails.size.scale.value`) is **gone**. Size is labeled US Size.

## eBay (T-Shirt 15687)

- **Department:** Men, Teens, Unisex Adults
- **Size Type:** Regular, Big & Tall (must set Size Type before Size populates)
- **Size** (after Regular): 2XS–2XL, combos, 28–50, One Size, IT/EU/FR 42–60 (no Big & Tall extras until Size Type is Big & Tall)
- **Pricing format:** Auction Style, Fixed Price
- **Duration:** displayed **Good 'Til Cancelled** on Fixed Price (menu did not open)
- **Type:** ----, T-Shirt
- **Fit:** ----, Athletic, Classic, Extra-Slim, Regular, Relaxed, Slim
- **Handmade / Personalize / Vintage:** ----, Yes, No
- **Sleeve Length:** ----, Sleeveless, Short Sleeve, 3/4 Sleeve, Long Sleeve
- **Neckline:** ----, Collared, Crew Neck, Henley, High Neck, Mock Neck, Round Neck, Square Neck, Turtleneck, V-Neck
- **Pattern:** ----, Animal Print, Argyle/Diamond, Camouflage, Check, Colorblock, Fair Isle, Floral, Geometric, Graphic Print, Herringbone, Paisley, Plaid, Polka Dot, Solid, Striped
- **Style:** ----, Basic, Cropped, Ringer
- **Season:** Fall, Spring, Summer, Winter
- **Garment Care:** ----, Dry Clean Only, Hand Wash Only, Machine Washable
- **Unit Type:** ----, Unit, oz, lb, fl oz, gal, ft, ft², ft³
- **Year Manufactured:** ----, 2020-2029 … Pre-1900s
- Accents, Features, Material, Fabric Type, Theme: see JSON (19 / 43 / 58 / 21 / 113 values)

## Poshmark

- **Category top-level:** Electronics, Home, Kids, Men, Pets, Women
- Nested picker, not a flat dropdown. Current path: Men > Shirts > Tees - Short Sleeve
- **Shirts children:** Casual Button Down Shirts, Dress Shirts, Jerseys, Polos, Sweatshirts & Hoodies, Tank Tops, Tees - Long Sleeve, Tees - Short Sleeve, None
- **Discounted Shipping:** disabled without an active Poshmark connection

## Mercari

- **Delivery method:** Standard shipping, Ship on your own
- **Who pays:** Buyer pays, I'll pay
- **Shipping Label:** disabled on this draft (needs Mercari connection and/or package weight)

## Depop

Source, age, style, material, and occasion on the live form **do not match** the old Studio enums.

- **Source:** Vintage, Preloved, Reworked, Custom, Handmade, Deadstock, Designer, Repaired
- **Age:** Modern, y2k, 90s, 80s, 70s, 60s, 50s, Antique
- **Style (32):** Streetwear, Sportswear, Loungewear, Goth, Retro, Boho, Western, Indie, Skater, Rave, Costume, Cosplay, Grunge, Emo, Minimalist, Preppy, Avant Garde, Punk, Glam, Regency, Casual, Utility, Futuristic, Cottage, Fairy, Kidcore, Y2K, Biker, Gorpcore, Twee, Coquette, Whimsygoth
- **Size:** 3XS, XXS, XS, S, M, L, XL, XXL, 3XL, 4XL, 5XL, 6XL, One size, Other
- **Body fit:** Maternity, Petite, Plus size, Tall
- **Material (33):** Acrylic … Wool (includes Cotton - Organic/Recycled, Elastane / Lycra / Spandex; no Satin)
- **Occasion:** Casual, Festival, Gifting, Going out, Outdoors, Party, Relaxation, School, Ski, Special Occasion, Summer, Vacation, Winter, Work, Workout
- **Shipping:** Depop Shipping (USPS), Other
- **Parcel size:** Extra extra small (under 4oz $1.99) … Extra large (under 10lb $5.99)

Material, occasion, and body fit appear after **Show Optional Fields**.

## Etsy

- **Who made:** Another company or person, A member of my shop, I did
- **What is it:** A finished product, A supply or tool to make things
- **When made:** Made To Order (Not Yet Made), 2020-2026 (Recently) … Before 1700 (Vintage)
- **Listing type:** Physical Item, Digital Item
- **Renewal:** Automatic, Manual
- **Listing state:** Draft Listing, Live Listing, Inactive
- Shipping / processing / return profiles are **account-specific**
- T-shirt category specifics (after Show Optional Fields): clothing style, sleeve length, neckline, graphic, occasion, holiday, sustainability, fabric pattern — see JSON

## Other marketplaces

| Marketplace | Closed dropdowns captured |
|---|---|
| **Facebook** | Delivery method: Shipping only. Shipping option: Use a prepaid shipping label |
| **Shopify** | No condition dropdown. Location and Collections are account-specific |
| **Vinted** | BETA; Title, Description, Quantity, Category, Price only on this draft |
| **Whatnot** | Hazmat: No Hazardous Materials, Contains Hazardous Materials, Contains Lithium Batteries. Sales format: Buy It Now, Anytime Auction |
