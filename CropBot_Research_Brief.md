# CropBot: Research Brief for the CII Post-Harvest Hackathon

Oct 18, 2026 · @Shivaansh Gusain

## TL;DR

CropBot should pitch as a **independent post-harvest decision layer, built entirely in-house**, not as another multilingual farm chatbot. We are in Track 4; the 7-minute pitch video is due 21 Oct 2026, and the Grand Finale is in New Delhi on 18 Dec 2026.

1. **Our current core is already free elsewhere.** Bharat-VISTAAR already offers cited crop Q&A, IMD weather, raw mandi prices, Soil Health Card fertiliser advice, scheme status and pest photo diagnosis. It costs farmers nothing and works in 10 text languages plus a Hindi/English phone (IVR) line.
2. **The post-harvest gap is real and unoccupied.** None of about 40 products checked offers harvest/drying alerts tied to procurement moisture limits, neutral sell/store/pledge advice, mandi ranking by net price, or MSP procurement readiness.
3. **What to build: a "Harvest-to-Sale Planner".** It combines a harvest and drying window with a sell/store/warehouse-loan calculator, plus a best-mandi-by-net-price line and a procurement checklist.
4. **Price information alone does not raise farmer prices** in randomised studies. Storage plus credit does. Our advice must point to a liquidity route: warehouse-receipt loans, KCC interest subvention, or FPO pooling.
5. **Uttarakhand is weak for the warehouse-loan feature.** It has only 12 active registered warehouses and issued no electronic warehouse receipts (e-NWRs, the receipts banks lend against) in FY 2024-25. It is strong for harvest alerts, and for net-price mandi advice in plains mandis such as Dehradun and Haldwani; hill markets lack price data. Demo the loan calculator on an MP or Rajasthan market too.
6. **Stop the Soil Health Card scraping.** It violates the portal's terms. The proxy plan raises legal risk under the IT Act. Use official requests and farmer-entered card values instead.
7. **Business model: shift from "FPOs pay SaaS" to post-harvest transaction fees plus co-funded pilots.** The median FPO earns a 0.27% net margin.
8. **The ask:** a pilot partner (KVK, FPO or warehouse) plus about ₹19–20 lakh for a 12-month, 5,000-farmer pilot. The lean version without team stipends is about ₹11.3 lakh. Incubation and funding talks go through IIT Guwahati TIC, the hackathon's co-organiser.

All figures were gathered between 11 and 17 Oct 2026. Before using any figure on a slide, check it against the "Verify before it goes on a slide" list at the end.

**Acronyms used below:**

- FPO = Farmer Producer Organisation
- KVK = Krishi Vigyan Kendra (district farm extension centre)
- KCC = Kisan Credit Card (subsidised farm loan)
- MSP = Minimum Support Price
- FCI = Food Corporation of India
- WDRA = Warehousing Development and Regulatory Authority
- e-NWR = electronic Negotiable Warehouse Receipt (a receipt for stored crop that a bank can lend against)
- e-KUN = e-Kisan Upaj Nidhi (the government's warehouse-receipt loan portal)
- UCF = Uttarakhand Cooperative Federation
- IVR = phone menu line
- DPDP = Digital Personal Data Protection law
- CBBO = Cluster-Based Business Organisation (agencies that support FPOs)

## The hackathon

The [CII Post-Harvest Hackathon](https://unstop.com/competitions/crp-cii-post-harvest-hackathon-cii-confederation-of-indian-industry-1700604) is about reducing post-harvest losses. A mostly pre-harvest pitch will look off-brief.

| Item | Detail |
| --- | --- |
| Organisers | CII–FACE (Food and Agriculture Centre of Excellence) with IIT Guwahati Technology Incubation Centre |
| Focus | Post-harvest management, storage, logistics, processing, waste use, value generation |
| Tracks | 1 Smart Food Loss Reduction · 2 Food Traceability & Transparency · 3 Digital Market Ecosystem for Farmers · 4 AI-Powered Agriculture · 5 Waste Collection & Value Generation · 6 Open Innovation |
| Our track | Track 4 (AI-Powered Agriculture), confirmed by email |
| Judging | Innovation, feasibility, scalability, relevance/impact; the pitch round adds "implementation approach" |
| Past rounds | Idea submission and concept pitch closed 31 Jul 2026; mentorship session 7 Aug 2026 |
| Grand Finale | 18 Dec 2026, New Delhi, before industry leaders |
| Rewards | CII certificates, mentorship, investor and policymaker access, **pilot implementation through the CII industry network**. No cash prize is listed. |

**Confirmed by email:** we are in **Track 4 (AI-Powered Agriculture)**, and the 7-minute Zoom pitch video is due Oct 21, 2026. The scoring rubric is still not public; ask the organisers for it.

Because the main reward is a pilot, our ask should name a pilot partner first and money second.

## Where we stand today

The repo has Soil Health Card scrapers and a graph-extraction prototype. The scrapers and graph prototype sit in one initial commit, and there is no post-harvest code.

### Code

- **Soil Health Card scrapers** (`state_retrival.py` → `village_retrival.py`, `data_scraper.py`). These walk the soilhealth4.dac.gov.in GraphQL API from state to village. The data is only village-level counts of High/Medium/Low N, P and K. It is not a farmer's own soil values, so it cannot drive the fertiliser-dose formulas in the crop guides.
- **Graph prototype** (`Graph_Rag_try.py`):
  - Uses llama3.2 with an unconstrained `LLMGraphTransformer` on 10 chunks, which gives an inconsistent graph.
  - Re-splits Docling's chunks with a second text splitter, which cuts tables in half.
  - Imports from the unmaintained `langchain_experimental`.
  - Has the Neo4j password hardcoded, so it is now in git history; rotate it and move it to an environment variable.
- **Source book in the repo:** the TNAU Crop Production Guide 2020 (460 pages, Tamil Nadu only). Variety tables are transposed and multi-column. Page 7 uses a legacy Tamil font that extracts as garbage.

### Legal and data risks

- **Soil Health Card scraping breaks the portal's terms of service.** The terms forbid robots, impersonation and commercial reuse without permission. The notes propose a spoofed browser User-Agent and rotating residential proxies to evade the firewall. That deliberate evasion raises exposure under IT Act s.43(b). A dishonest or fraudulent act under s.43 becomes a criminal offence under s.66. This is not legal advice. **Stop it.** Instead:
  - request data officially from MoA\&FW;
  - use the data.gov.in datasets under the Government Open Data License (GODL);
  - let farmers type in or photograph their own card.
- **Book licensing.** ICAR Kharif 2025 is non-commercial only. The ICAR portal, PAU and TNAU require permission. The agrimoon and weebly PDFs are re-hosts of unclear origin. Storing extracted facts with citations is lower risk than serving copied text, but get legal confirmation before going commercial.
- **Personal data.** India's DPDP Rules were notified on 13 Nov 2025, with most obligations from about May 2027. Phone numbers, locations and card photos need consent notices now.

### Deck critique (12 slides)

- **No numbers anywhere.** There is no loss figure, farmer count, rupee impact, cost or funding figure.
- **"Hallucination-free" is an overclaim.** Replace it with a measured error rate and a "cites its source or declines" rule.
- **The competition slide leaves out our real competitors.** It omits Bharat-VISTAAR, Kisan e-Mitra and e-NAM.
- **The business model does not add up.** 250 FPOs × \~650 members ≈ 160,000 farmers, not 500,000. FPO ability to pay is not shown.
- **No post-harvest content and no demo.** Two slides are also numbered "02".

## Competitors

Bharat-VISTAAR is free and broad but shallow: generic advice, raw prices, and no post-harvest decision support. Position CropBot as complementary to it.

### Bharat-VISTAAR, checked against its public code

Its backend is open source ([bharat-oan-api](https://github.com/OpenAgriNet/bharat-oan-api), last commit 15 Oct 2026). That let us check what it actually does, not just what press releases claim.

| Aspect | What we found |
| --- | --- |
| Launch and budget | Announced in Budget 2026-27 (₹150 cr). Phase 1 launched in Jaipur on 17 Feb 2026 ([PIB](https://www.pib.gov.in/PressReleasePage.aspx?PRID=2228842)). |
| Channels | IVR 155261 (works on feature phones), "Bharati" voice/text bot, web chat, Android app, embedded in PM-KISAN and PMFBY apps. **No WhatsApp.** |
| Languages | IVR is still **Hindi and English only**. Text works in 10 languages ([Lok Sabha USQ 1497, 28 Jul 2026](https://sansad.in/getFile/lsapps/loksabhaquestions/annex/188/AU1497_GAaTNq.docx?source=lsapps)). |
| Personalisation | The code receives only the query, language and GPS coordinates. It uses no Farmer ID, land record, crop sown or plot data. Soil Health Card fertiliser advice works only by looking up the farmer's registered mobile number. NITI's claim of land-record personalisation is not in the public code; production may differ. |
| Knowledge and model | Document search over ICAR crop guides, IMD Mausamgram, Agmarknet prices, and pest image diagnosis (NPSS, the national pest surveillance system). Azure GPT-4.1 by default, Bhashini for speech. Answers carry "Source:" lines. No knowledge graph found. |
| Post-harvest | The mandi tool returns raw prices near a place, with no distance, transport or net-price logic. **Zero tools for MSP, procurement, warehouse loans or moisture.** Post-harvest suggestion buttons exist but are switched off. |
| Usage | 3 lakh+ farmers and 72 lakh+ queries (Parliament, Jul 2026). The app has 10K+ installs and a 3.7 rating, and has not been updated since 18 Feb 2026. |
| Critiques | Barely promoted; unclear accountability for wrong advice; no published accuracy evaluation ([The Secretariat](https://thesecretariat.in/article/ai-in-agriculture-bharat-vistaar-faces-triple-test-of-credibility-market-risk-accountability), [CSTEP](https://cstep.in/?p=240771)). |
| Open to partners | OpenAgriNet lets outside services join VISTAAR's network through the Beckn protocol ([docs](https://docs.openagrinet.global/llms.txt)). We are not using this; CropBot stays fully independent. |

### Capability matrix

Y = yes, P = partial, N = no or not found.

| Player | WhatsApp | Farm-level personalisation | Mandi prices | Sell/store advice | Warehouse-loan link | Harvest/drying alerts | Business model |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Bharat-VISTAAR | N | N (GPS only) | Raw | N | N | N | Free, government |
| MahaVISTAAR (Maharashtra) | N (requested) | Y (AgriStack + memory) | Y (stale per reviews) | N | P (warehouse locator) | N | Free, state |
| Kisan e-Mitra | N | Account only | N | N | N | N | Free; schemes only |
| e-NAM / Agmarknet | N | N | Y | N | P (e-NWR trade) | N | Free; prices and trading |
| Farmer.Chat (Digital Green) | Earlier; now app/web | P | N | N | N | N | Free; grant-funded |
| Plantix / AgroStar | N | Low | AgroStar only | N | N | N | Input sales; biased advice |
| DeHaat / ITC MAARS | ? | Y / P | Y | N (they buy the crop) | N | N | Inputs + buying produce |
| Arya.ag / StarAgri | N | Own stock only | P | Conflicted | Y (own lending) | N | Storage fees + interest |
| **CropBot (planned)** | Planned | Y | Net of costs | **Y** | **Navigator** | **Y** | Free for farmers |

Other notes:

- **No Uttarakhand state AI farm advisor exists.**
- **BharatAgri shut down in Nov 2025.** It could not raise funding against high acquisition costs and low repeat use.
- **A Digital Green fine-tuning study built on Farmer.Chat found harvest timing was the weakest topic** (44.6% average F1) ([arXiv](https://arxiv.org/html/2603.03294v1)).
- **ICAR-IIOR's Oilseeds Kisaan Mitra** is a free WhatsApp bot with ICAR content, but it covers oilseeds only.

### Do not pitch these as unique

All of these are already free from the government: cited crop Q&A, weather, Soil Health Card advice, raw mandi prices, scheme information, and pest photo diagnosis. Government WhatsApp advice exists only for oilseeds (ICAR-IIOR), so WhatsApp is a channel advantage for us, but not the headline.

## Post-harvest strategy

Build one **Harvest-to-Sale Planner** that carries on from our pre-harvest advice. We already know the farmer's crop, sowing date and location, so we can plan the harvest and the sale.

### Why this, backed by evidence

- **The problem is large.** Post-harvest losses are about **₹1.53 lakh crore a year** ([NABCONS 2022 via ICRIER](https://icrier.org/pdf/Policy_Brief_20.pdf)). Loss rates by crop group:
  - cereals 3.89–5.92%
  - pulses up to 6.74%
  - fruits 6.02–15.05%
  - vegetables 4.87–11.61%
- **Most farm losses happen at harvest, not in storage.** For paddy: harvesting 1.42%, threshing 0.97%, drying 0.33%, against farm storage 0.40%. Cereal farm-storage loss is only about 0.3–0.4%.
- **Price information alone does not raise farmer prices.** Two randomised studies found no average effect:
  - Reuters Market Light SMS in Maharashtra ([Fafchamps & Minten 2012](https://ideas.repec.org/a/oup/wbecrv/v26y2012i3p383-414.html));
  - price information for West Bengal potato farmers ([Mitra et al. 2018](https://people.bu.edu/dilipm/wkpap/MitraMookherjeeToreroVisariaAug2016_Paper.pdf)).
- **Liquidity is what lets farmers wait.** Harvest loans in Kenya let farmers store and sell later, for roughly 28–29% return ([Burke et al., QJE 2019](https://www.nber.org/papers/w24476)).
- **India's warehouse-loan system is underused by smallholders.**
  - e-Kisan Upaj Nidhi had only **62 farmer applicants and ₹25.44 lakh disbursed** as of 13 Jul 2025 ([Lok Sabha AU671](https://eparlib.sansad.in/bitstream/123456789/2997246/1/AU671_uUZM4D.pdf)).
  - The average warehouse receipt is about 23 tonnes, far above one smallholder's harvest.
  - Support exists: KCC interest subvention covers 6 months post-harvest for small and marginal farmers storing in registered warehouses. A ₹1,000 cr credit guarantee scheme charges farmers a 0.4% fee ([WDRA AR 2024-25](https://wdra.gov.in/documents/d/wdra/wdra_englsih-an_24-25-final-to-print-compressed)).

### Features, ranked

| # | Feature | What it does | Hard for VISTAAR to copy? | Ready by 18 Dec? |
| --- | --- | --- | --- | --- |
| 1 | Harvest and drying window | Sowing date + crop duration + rain forecast → "harvest by X, dry below 17% (paddy) / 12% (wheat, ragi)". These are FCI procurement limits: for wheat, the older RMS spec buys 12–14% at a discount and rejects grain above 14% (verify the 2026-27 notice; demo on paddy first). | Medium: VISTAAR stores no crop or sowing date per farmer | Yes. Rule-based; most demo-able |
| 2 | Sell / store / pledge calculator | Seasonal price range from mandi history, minus storage fee, interest (after subvention), quality loss and transport. Then nearest registered warehouse and loan route (the e-Kisan Upaj Nidhi portal, a bank, or FPO pooling). | High: a government bot advising "hold your crop" raises liability and herding concerns | Medium. Backtest first |
| 3 | Best mandi by net price | Modal price minus transport, mandi fee and commission, with price-date freshness | Low: the easiest for VISTAAR to copy | Yes. data.gov.in API |
| 4 | MSP / procurement readiness | Registration deadlines, nearest centre, moisture and quality self-check, MSP vs net market price | Medium: fragmented per state and season | Yes, for 1–2 states and 2 crops |
| 5 | Storage coach | Moisture, hermetic bags, pest-safe storage | Low: it is content | Yes, but only for soybean, pulses and perishables |

**Skip for now:** FPO buyer-matching (needs real FPOs and buyers; e-NAM, ONDC and DeHaat already do it) and crop-residue connectors. Put both on the roadmap slide.

### Limits we must state openly

- **Hill markets have almost no price data.** On 16 Oct 2026 the live feed returned Uttarakhand prices only from plains mandis. Chamoli had 37 records in a year. There were none for mandua, rajma or jhangora.
  - The sell/store feature therefore covers **plains crops**: wheat, paddy, potato, tomato, and apple at Dehradun and Haldwani.
  - Hill millets use the fixed UCF price (mandua ₹52.05/kg, 250 centres; *unverified*). That fits feature 4.
- **Forecasts are uncertain.** Published Indian price forecasts are typically off by 9–15% on average (mean absolute percentage error). That is about as large as the price rise a farmer gains by storing, so a single-number forecast could point the wrong way. Always show a range and a confidence level, never a single number.
- **Uttarakhand has very few warehouses** (12 active registered ones as of 31 Mar 2025, and no e-NWRs). Backtest and demo feature 2 on an MP or Rajasthan market as well.

## Knowledge graph and tech stack

Store facts as typed text with stable IDs, and use multilingual embeddings only to find them. Stay on Neo4j for now. Self-host Sarvam-30B on our GX10 (the team's ASUS Ascent GX10 workstation: NVIDIA GB10, 128 GB memory), with Sarvam's API as fallback.

### "Embeddings, not words": keep the instinct, change the design

- **Embeddings are right for search across languages.** BGE-M3 and Qwen3-Embedding match a Hindi question to an English passage without translating the knowledge base.
- **Embeddings are wrong for storing facts.** In one benchmark (EmbedNum-1K), 13 embedding models matched numbers at roughly chance accuracy. Doses like "120:40:40 kg NPK/ha", variety codes (ADT 53 vs CO 51) and "do not spray" negations get blurred. You also cannot cite a vector or correct one fact in it.
- **Our notes said embeddings save compute; that is half right.** The LLM reads text, so the text must be stored anyway. But a text graph built by an LLM costs more to index than plain vector search. Parsing tables with code cuts most of that cost.
- **Every serious graph-RAG system stores text entities and adds embeddings on top.** That includes Microsoft GraphRAG, LightRAG, HippoRAG 2 and Neo4j GraphRAG.

**Design:**

1. Canonical English facts with language-neutral IDs. AGROVOC has Indian labels only in Hindi and Telugu, so we build most local-language labels ourselves.
2. Every number is a typed field: value, unit, basis (per ha, per kg seed), original text, and source page.
3. An alias layer: dhaan / nel / paddy all point to rice.
4. A vector layer with dense plus sparse matching, so exact tokens like "ADT 53" still match.
5. Every fact carries applicability: state, agro-climatic zone, season, irrigated or rainfed, and purpose. The TNAU book gives rice NPK of 150:50:50 in one section and 150:50:60/80 for seed production.
6. Conflicts between books stay as separate claims. Filter them by the farmer's location and never average them.

### Docling

- **Our notes called Docling a "2 GB model"; that is really the install size.** The models themselves are small: layout 172 MB, table model 146–213 MB, Granite-Docling 515 MB. Our `.venv` is 5.4 GB.
- **Speed:** about 8 pages/s on a GPU without OCR, so a 460-page book takes minutes.
- **Tables are the hard part.** Rotate the transposed variety tables and stitch page-split tables in code. Validate each table against the rendered page.
- **Store data in layers:**
  - L0: the original PDF;
  - L1: Docling's lossless JSON export;
  - L2: per-crop JSON validated with Pydantic;
  - L3: the graph and embeddings, built from L2.

  The database then becomes a rebuildable index.
- **OCR for Tamil and Hindi needs explicit setup.** Our environment currently falls back to a Chinese/English OCR model.

### Graph database

- **Do not build on Kuzu.** Its repo was archived on 10 Oct 2025 after Apple bought the company. **LadybugDB** is the active fork (MIT licence); its LangChain adapter has a single maintainer.
- **The "128× faster than Neo4j" claim from our notes has no source.** The closest public benchmark, run on one laptop, showed 0.54× to 374× depending on the query.
- **Database speed doesn't matter at our scale** (tens of thousands of chunks). The LLM takes seconds; the database takes milliseconds.
- **Stay on Neo4j Community.** It runs from a tarball with no Docker needed, has vector and full-text indexes, and has maintained LangChain support. From version 2026.08 it defaults to 1-bit vector compression; set it to scalar or none.

### LLM and voice

- **Sarvam-30B** is 32B total parameters with 2.4B active, Apache 2.0. Stored at 8-bit precision (FP8, about 32 GB), it fits easily in the GX10's memory. Estimated 45–60 tokens/s for one user; benchmark it yourself.
  - vLLM support was merged upstream on 7 Mar 2026, but the Hugging Face model card still describes a patch.
- **It is Sarvam-105B, not "104B".**
- **The hosted API now lists sarvam-105b** at ₹15 input / ₹60 output per 1M tokens ([pricing](https://docs.sarvam.ai/api/pricing)).
- **Voice costs more than the LLM.** Speech-to-text is ₹30 per audio hour and text-to-speech ₹3 per 1,000 characters (Bulbul v3). That is about ₹2 per voice query, against ₹0.06 for the LLM.
- **Language coverage differs.** The hosted chat model and TTS cover about 11 languages; speech-to-text covers 22. Test a low-resource language before claiming "22 languages".
- **Free alternatives:** AI4Bharat IndicTrans2 (translation, MIT) and IndicConformer (speech-to-text, MIT) can be self-hosted.

## Data sources and licensing

Most live data we need is free for a hackathon. Several sources become paid or permission-only once we are a commercial startup.

| Source | Gives us | Access | Commercial use |
| --- | --- | --- | --- |
| [Open-Meteo](https://open-meteo.com/en/terms) | Forecast (16 days), ERA5 history from 1940, evapotranspiration, soil moisture, seasonal and ensemble forecasts | Free API, under 10,000 calls/day | **Non-commercial only on the free tier.** Needs a paid plan or a self-hosted copy (AGPL). CC BY attribution. |
| [IMD API](https://api.imd.gov.in/public/api_reference.html) | District warnings (days 1–5), nowcast, district rainfall departure, city forecast, station data | IP whitelisting via the nodal officer named in IMD's API document | **Free for non-commercial use only** (IMD RTI reply, 11 Sep 2025; linked in Sources). Ask in writing about startup terms. |
| NASA POWER, IMD Pune 0.25° rainfall grids | Climatology and rainfall normals | Free | CC BY (NASA); IMD grids have no stated licence |
| [data.gov.in mandi prices](https://www.data.gov.in/resource/current-daily-price-various-commodities-various-markets-mandi) | Daily prices per mandi; a variety-wise history dataset | Free API key | GODL (commercial use allowed with attribution). History sampled only from Nov 2025, so confirm depth. |
| Agmarknet 2.0 portal | Prices, 4,367 mandis | No public API | Scraping is legally grey; use data.gov.in |
| e-NAM | 1,656 mandis, prices, e-NWR trading | No public developer API | n/a |
| WDRA warehouses, e-NWR | 7,660 active warehouses (30 Jun 2026; counts differ by date) | Website and mWDRA app only | Curate by hand |
| MSP and procurement specs | MSP rates; FCI moisture limits (paddy 17% and ragi 12% for KMS 2026-27; wheat 12% per an older RMS spec, to verify) | PIB / DFPD PDFs | Public; enter manually each season |
| Soil Health Card | Farmer card values | Ask the farmer, or an official data request | Portal terms forbid bots and commercial reuse |
| Crop guides (TNAU, ICAR, PAU, HPKV) | Practices, varieties, doses | PDFs | Mostly non-commercial or permission-required; ask ICAR's DKMA and individual universities |

### Weather notes

- **Always pass `timezone=Asia/Kolkata`.** Open-Meteo returns daily values in GMT by default.
- **Weather models disagree, especially in the hills.** In Dehradun, models differed on one day's maximum temperature by 3.6 °C. Hill districts need altitude correction.
- **IMD forecasts take priority.** Open-Meteo has no Indian models, so IMD district warnings always win when the two disagree.
- **Weather stays out of the graph.** It is a cached live tool. The graph holds rules such as "don't spray if rain is due within 24 h".
- **IMD closed its 199 district agromet units on 1 Mar 2024,** so block-level farm advisories may no longer exist.

### Source priority for the knowledge base

1. Current-season state agricultural university package of practices, and ICAR state advisories.
2. ICAR crop-institute bulletins and KVK district guides.
3. National handbooks, for principles.
4. Textbooks, for explanations only, never for doses or dates.

For Uttarakhand: request the GBPUAT Pantnagar and VPKAS Almora guides directly, since we found none online.

## Business model, costs and funding

Stay free for farmers. Earn from post-harvest transactions and co-funded pilots, not FPO software subscriptions. A 12-month, one-district pilot costs about ₹19–20 lakh.

### Why "FPOs pay SaaS" is weak

- **Most FPOs cannot pay.** The median Farmer Producer Company makes a 0.27% net margin, and only 43–49% keep operating after support ends ([TCI-BIRD 2026](https://tci.cornell.edu/wp-content/uploads/2026/02/TCI-BIRD-The-State-of-FPOs-in-India-2026.pdf)). A ₹50 lakh-turnover FPO earns about ₹13,500 a year in profit, so a ₹50,000 fee is out of reach. Only about 1,135 scheme FPOs turn over more than ₹1 crore.
- **No precedent for states buying this.** We found no public example of a state paying a startup per farmer for an advisory chatbot. Government agri-AI here is open public infrastructure, philanthropy-funded, or tendered.
- **Farmers won't pay for advice.** In the Avaaj Otalo trial, average willingness to pay was about ₹107 for 9 months. BharatAgri's paid advisory shut down in Nov 2025.

### A model with better evidence

- **Referral or origination fees from post-harvest services:** registered warehouses, warehouse-receipt lenders, and FPO aggregation. Arya.ag, which combines storage, warehouse-receipt finance and trading, reported ₹447 cr net revenue and ₹43 cr profit before tax in FY25 (company-reported). That is evidence that storage-plus-finance can be profitable.
- **A success fee from larger FPOs,** set below the extra price they demonstrably earn. Sell through FPO support agencies (CBBOs) and FPO lenders.
- **Co-funded pilots** with a KVK or university plus a philanthropic or state partner.
- **Keep input-selling out.** Plantix, a free diagnosis app, ended up owned by a pesticide trader. Our "no selling pressure" stance is a strength.

### Costs

The pilot budget assumes 500 → 1,500 → 3,000 → 5,000 farmers by quarter, 8 queries per farmer per month, and 30% voice queries.

| Line item (12 months) | ₹ |
| --- | --- |
| Speech-to-text and text-to-speech | 1,41,600 |
| LLM (GX10 power + API fallback) | 15,000 |
| WhatsApp messages + platform fee | 80,300 |
| Cloud hosting, Open-Meteo plan, broadband/UPS | 94,000 |
| Agronomist validator, 1 FTE | 3,60,000 |
| Team stipends, 4 × ₹15k/month | 7,20,000 |
| Field operations (KVK/FPO demos, travel) | 2,40,000 |
| Baseline/endline impact survey | 60,000 |
| Legal, DPDP compliance, incorporation | 40,000 |
| 10% contingency | 1,75,090 |
| **Total** | **≈ 19,26,000** |

- **About 56% of the budget is staff (agronomist + stipends), about 72% with field work and the survey;** technology is about ₹3.3 lakh (₹3.6 lakh with contingency).
- **Lean version** without stipends: about ₹11.3 lakh.
- **The GX10 (about ₹4.5 lakh) is in-kind,** not part of the ask.
- **At the deck's Year-3 target of 500,000 farmers (not yet backed by a growth plan),** the optimised cost is about **₹55 per farmer per year**. That assumes 5 queries per farmer per month, short spoken replies (about ₹0.65 per voice query) and a 10-person team. It is below the \~$0.94 per user per year average of Precision Development (PxD), a large farmer-advisory non-profit. It supports the line "personalised voice advice at public-extension cost".
- **Self-hosting the LLM saves little at scale.** The GX10 breaks even with the API at about 2 lakh queries per month. Its value is zero marginal cost in Year 1, data sovereignty and offline demos. The real savings are in shorter voice replies.
- **WhatsApp:** from 1 Oct 2026 only the first 1,000 service messages per number per month are free, then about ₹0.13 each. Re-verify on Meta's rate card.

### Incubation and funding

Funding is not a separate problem for us right now. IIT Guwahati's Technology Incubation Centre (IITG-TIC) co-organises the hackathon, so incubation and funding conversations go through them and the CII network. The budget above is the ask we state in the pitch.

## The 7-minute pitch (video due 21 Oct)

Show the solution and the evidence, not the implementation. Spend about 10% of the time on technology and let a live demo carry it.

**For the 21 Oct video:** there is no time to build the post-harvest features first. Demo what works today (the PWA advisory) plus a scripted mock-up of the Harvest-to-Sale Planner, clearly labelled as a prototype. On the Evidence slide, show targets and how we will measure them, not results.

| Time | Section | Content |
| --- | --- | --- |
| 0:00–0:30 | Hook | One real Uttarakhand farmer: rain at harvest, or a forced sale at harvest. One number. |
| 0:30–1:15 | Problem | ₹1.53 lakh crore lost a year; losses happen mostly at harvest; farmers sell at harvest because they need cash. |
| 1:15–2:45 | **Live demo** (longest section) | A Hindi voice question: "Rain in 3 days, should I harvest my paddy, how do I dry it, sell or store?" Show the harvest window, the moisture target, the sell/store/loan comparison in ₹ per quintal, and the cited source. Show the loan comparison on an MP or Rajasthan market, since Uttarakhand has only 12 registered warehouses. |
| 2:45–3:30 | How it works | One diagram: knowledge graph, live data, model on our own hardware, "cite or decline" rule, agronomist review. |
| 3:30–4:15 | Evidence | Backtest result (₹ per quintal, hit rate), accuracy on 100–200 agronomist-checked questions vs a plain-LLM baseline (all pending: see Actions), farmers tested, letters of intent. |
| 4:15–4:50 | Landscape | VISTAAR, Kisan e-Mitra, e-NAM, Farmer.Chat, Plantix, and "do nothing" (the input dealer). CropBot as the independent post-harvest layer. |
| 4:50–5:45 | Model and costs | Free for farmers; transaction fees and co-funded pilots; ₹55 per farmer per year at scale. |
| 5:45–6:20 | Impact and roadmap | A district target with a conservative formula (farmers × produce value × loss reduction × adoption) and a comparison group. |
| 6:20–7:00 | Team and ask | A pilot partner plus ₹19–20 lakh in milestone instalments. One-line vision. |

### Rules for what we say

- **Never disparage Bharat-VISTAAR.** Say CropBot is complementary: VISTAAR answers general questions, while CropBot, built entirely in-house, handles the post-harvest decision.
- **Don't claim VISTAAR lacks location or Soil Health Card features** unless we have tested it ourselves by calling 155261.
- **Don't present Soil Health Card or IMD integrations as live** if they are not. Say "access requested" only after we have actually sent the requests.
- **Replace "hallucination-free"** with a measured error rate.
- **Claim the district target, not ₹1.5 lakh crore.** Mobile advisory has raised yields by about 4–6% on average in studies, so don't promise more.
- **Keep the competition table honest.** Include VISTAAR, Kisan e-Mitra, e-NAM, Farmer.Chat, Plantix and the input dealer.

## Next steps to 18 Dec

The pitch video is due 21 Oct 2026, three days away; the finale is on 18 Dec, about 9 weeks away. Evidence beats features: a backtest, 15–30 farmers and one letter of intent will matter more than extra code.

### Actions

- [ ] By 21 Oct · Akhil + team: rebuild the deck to the pitch structure above; record, review and submit the 7-minute video
- [ ] This week · Suryansh: stop the Soil Health Card scraper; send official data requests (MoA&FW, and the IMD whitelisting form)
- [ ] This week · whole team: contact KVK Dehradun, a UCF centre or an FPO for the farmer test
- [ ] By 8 Nov · Suryansh: confirm how far data.gov.in price history goes back; if it starts in Nov 2025, find older series
- [ ] By 8 Nov · Sandeep: build the harvest-and-drying window (feature 1) on Open-Meteo plus FCI moisture limits, starting with paddy
- [ ] By 22 Nov · Sandeep + Suryansh: build the sell/store calculator (feature 2); backtest wheat, paddy, potato and tomato against "sell at harvest" (all crops) and "sell at MSP" (wheat and paddy only)
- [ ] By 22 Nov · Suryansh: build best mandi by net price (feature 3) on the data.gov.in API
- [ ] By 22 Nov · Shivaansh: build MSP/procurement readiness (feature 4) for Uttarakhand wheat, paddy and UCF mandua
- [ ] By 22 Nov · Sandeep: backtest feature 1: how often did rain fall inside the computed harvest window in past seasons?
- [ ] By 29 Nov · Shivaansh: build an evaluation set of 100–200 farmer questions with agronomist-checked answers; measure accuracy against a plain-LLM baseline
- [ ] By 29 Nov · whole team: run 15–30 farmers through KVK Dehradun or a UCF collection centre
- [ ] By 29 Nov · whole team: get 1–3 letters of intent (FPO, warehouse, KVK)
- [ ] By 29 Nov · Akhil: call 155261 and try the VISTAAR app with our own test questions

### Open questions for the team

1. Answered: Track 4 is confirmed, and the 7-minute video is due 21 Oct 2026.
2. Who can reach KVK Dehradun, a UCF centre or an FPO this month?
3. Plains crops or hill crops first? The sell/store feature only works where price data exists.
4. Have the Soil Health Card and IMD access requests actually been sent?

### Verify before it goes on a slide

- The RMS 2026-27 wheat moisture limit, and the Uttarakhand procurement portal and rules
- Whether production VISTAAR uses AgriStack data that its public code does not show
- Warehouse counts, which conflict by date (6,166 / 10,727 / 7,660), so always cite the date
- The KCC interest-subvention loan limit (₹3 lakh or ₹5 lakh)
- Meta's live INR rate card and the 1 Oct 2026 service-message rule
- Current prices for Open-Meteo plans and the GX10
- Our own Sarvam-30B benchmark on the GX10
- The UCF mandua price and the hill-market data gaps

### Sources

- [CII Post-Harvest Hackathon (Unstop)](https://unstop.com/competitions/crp-cii-post-harvest-hackathon-cii-confederation-of-indian-industry-1700604)
- [Bharat-VISTAAR backend code](https://github.com/OpenAgriNet/bharat-oan-api) · [OpenAgriNet docs](https://docs.openagrinet.global/llms.txt) · [PIB launch](https://www.pib.gov.in/PressReleasePage.aspx?PRID=2228842) · [Lok Sabha USQ 1497](https://sansad.in/getFile/lsapps/loksabhaquestions/annex/188/AU1497_GAaTNq.docx?source=lsapps) · [NITI Frontier Tech](https://frontiertech.niti.gov.in/story/how-bharat-vistaar-is-connecting-140m-farmers-to-smarter-agriculture/)
- [The Secretariat](https://thesecretariat.in/article/ai-in-agriculture-bharat-vistaar-faces-triple-test-of-credibility-market-risk-accountability) · [CSTEP](https://cstep.in/?p=240771) · [MahaVISTAAR (World Bank)](https://www.worldbank.org/en/news/feature/2026/08/27/small-ai-transforms-farming-in-india)
- [NABCONS loss study (archived)](https://web.archive.org/web/20260512064941/https://mofpi.gov.in/sites/default/files/study_report_of_post_harvest_losses.pdf) · [ICRIER Policy Brief 20](https://icrier.org/pdf/Policy_Brief_20.pdf)
- [WDRA Annual Report 2024-25](https://wdra.gov.in/documents/d/wdra/wdra_englsih-an_24-25-final-to-print-compressed) · [WDRA bulletin Apr–Jun 2026](https://wdra.gov.in/documents/d/wdra/wdra-bulletin-april-26-to-june-26-1) · [e-KUN, Lok Sabha AU671](https://eparlib.sansad.in/bitstream/123456789/2997246/1/AU671_uUZM4D.pdf)
- [DFPD KMS 2026-27 specifications](https://www.foododisha.in/Download/uniform-specification-of-paddy-rice-and-coarse-grains.pdf) · [data.gov.in mandi prices](https://www.data.gov.in/resource/current-daily-price-various-commodities-various-markets-mandi)
- [Fafchamps & Minten 2012](https://ideas.repec.org/a/oup/wbecrv/v26y2012i3p383-414.html) · [Mitra et al. 2018](https://people.bu.edu/dilipm/wkpap/MitraMookherjeeToreroVisariaAug2016_Paper.pdf) · [Burke et al. 2019](https://www.nber.org/papers/w24476) · [Farmer.Chat accuracy paper](https://arxiv.org/html/2603.03294v1)
- [TCI-BIRD State of FPOs 2026](https://tci.cornell.edu/wp-content/uploads/2026/02/TCI-BIRD-The-State-of-FPOs-in-India-2026.pdf) · [PRS budget analysis](https://prsindia.org/files/budget/budget_parliament/2026/DfG_Analysis_2026-27-Agriculture.pdf) · [PxD 2024 report](https://precisiondev.org/wp-content/uploads/2025/05/2024-PxD-Annual-Report_270525.pdf) · [Arya.ag FY25](https://entrackr.com/fintrackr/aryaag-reports-rs-447-cr-revenue-in-fy25-profits-spike-70-9048421) · [Plantix (FERN)](https://thefern.org/2024/10/this-app-set-out-to-fight-pesticides-once-vc-stepped-in-the-app-helped-sell-them)
- [Sarvam pricing](https://docs.sarvam.ai/api/pricing) · [Sarvam-30B model card](https://huggingface.co/sarvamai/sarvam-30b) · [Kuzu repo (archived)](https://github.com/kuzudb/kuzu) · [LadybugDB](https://github.com/LadybugDB/ladybug)
- [Open-Meteo terms](https://open-meteo.com/en/terms) · [IMD API reference](https://api.imd.gov.in/public/api_reference.html)
- [Uttarakhand Startup Policy](https://startuputtarakhand.uk.gov.in/attachments/16831085833.pdf) · [RKVY guidelines](https://agristartup.gov.in/LetterAndCircular/OperationalGuidelineRKVY.pdf) · [Startup India playbook 2026](https://www.startupindia.gov.in/content/dam/startupindia/homebanners/Startup-Schemes-Playbook-June-2026.pdf)

IMD access: [RTI reply on non-commercial use](https://internal.imd.gov.in/section/rti/rticases/20260112_rti_211.pdf) · [IP whitelisting request form](https://city.imd.gov.in/citywx/api_request.php).
