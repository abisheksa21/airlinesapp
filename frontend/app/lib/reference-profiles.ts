import { AIRPORT_FULL_NAMES, airportDisplayName } from "./airports";
import { CARRIER_NAMES } from "./carriers";

export type ReferenceSource = {
  label: string;
  href: string;
};

export type ReferenceProfile = {
  kind: "carrier" | "airport";
  code: string;
  name: string;
  strapline: string;
  whatItIs: string;
  role: string;
  quickFacts: Array<{ label: string; value: string }>;
  history: string[];
  operationalNotes: string[];
  sources: ReferenceSource[];
};

const WIKIPEDIA = "https://en.wikipedia.org/wiki/";

const CARRIER_REFERENCE: Record<string, Omit<ReferenceProfile, "kind" | "code" | "name">> = {
  AA: {
    strapline: "A large network carrier with a wide domestic and international footprint.",
    whatItIs: "American Airlines is a major U.S. network airline. In this project, AA is the marketing-carrier code used to group the flights sold under the American brand.",
    role: "Network carrier / Oneworld member",
    quickFacts: [
      { label: "Founded", value: "1926" },
      { label: "Headquarters", value: "Fort Worth, Texas" },
      { label: "Alliance", value: "Oneworld" },
      { label: "BTS code", value: "AA" },
    ],
    history: ["1926 — founded as American Airways.", "1936 — began operating under the American Airlines name.", "Today — operates a large hub-and-spoke network across the United States and beyond."],
    operationalNotes: ["A broad network can create very different operating conditions by airport, route, and time of day.", "Read the BTS-derived performance separately from the company history shown here."],
    sources: [{ label: "American Airlines — Wikipedia", href: `${WIKIPEDIA}American_Airlines` }, { label: "BTS on-time data used here", href: "https://www.transtats.bts.gov/ontime/" }],
  },
  DL: {
    strapline: "A major network carrier whose Atlanta hub is one of the largest in the world.",
    whatItIs: "Delta Air Lines is a major U.S. network airline. The DL code identifies flights marketed by Delta in the BTS on-time dataset.",
    role: "Network carrier / SkyTeam member",
    quickFacts: [{ label: "Founded", value: "1925" }, { label: "Headquarters", value: "Atlanta, Georgia" }, { label: "Alliance", value: "SkyTeam" }, { label: "BTS code", value: "DL" }],
    history: ["1925 — began as Huff Daland Dusters, an agricultural aviation operation.", "1929 — started passenger service as Delta Air Service.", "Today — Atlanta is its primary hub and a central connection point in the U.S. network."],
    operationalNotes: ["A hub carrier can look strong overall while still having pressure concentrated at particular connection points.", "The profile’s airport and route breakdowns help locate that pressure."],
    sources: [{ label: "Delta Air Lines — Wikipedia", href: `${WIKIPEDIA}Delta_Air_Lines` }, { label: "BTS on-time data used here", href: "https://www.transtats.bts.gov/ontime/" }],
  },
  UA: {
    strapline: "A global network carrier connecting major U.S. hubs with international markets.",
    whatItIs: "United Airlines is a major U.S. network airline. UA is the marketing-carrier code used by this project when aggregating BTS flight records.",
    role: "Network carrier / Star Alliance member",
    quickFacts: [{ label: "Founded", value: "1926" }, { label: "Headquarters", value: "Chicago, Illinois" }, { label: "Alliance", value: "Star Alliance" }, { label: "BTS code", value: "UA" }],
    history: ["1926 — founded through the early Varney Air Lines network.", "1931 — began operating as United Air Lines.", "Today — maintains major hubs including Chicago, Denver, Newark, San Francisco, and Washington-Dulles."],
    operationalNotes: ["Multiple hubs make the network useful to compare as a set of local operating environments rather than one single average.", "Use the researcher view when you need the route and delay-cause detail."],
    sources: [{ label: "United Airlines — Wikipedia", href: `${WIKIPEDIA}United_Airlines` }, { label: "BTS on-time data used here", href: "https://www.transtats.bts.gov/ontime/" }],
  },
  WN: {
    strapline: "A high-volume low-cost carrier with a primarily domestic network.",
    whatItIs: "Southwest Airlines is a U.S. low-cost airline. WN identifies flights marketed by Southwest in the BTS records used by the lab.",
    role: "Low-cost carrier",
    quickFacts: [{ label: "Founded", value: "1967; service began 1971" }, { label: "Headquarters", value: "Dallas, Texas" }, { label: "Network style", value: "Mostly domestic / point-to-point" }, { label: "BTS code", value: "WN" }],
    history: ["1967 — founded as Air Southwest.", "1971 — began service as Southwest Airlines.", "Today — operates a large domestic network with a distinctive operating model."],
    operationalNotes: ["A point-to-point network can distribute delay exposure differently from a classic hub-and-spoke network.", "Compare WN route and airport patterns before making a system-wide conclusion."],
    sources: [{ label: "Southwest Airlines — Wikipedia", href: `${WIKIPEDIA}Southwest_Airlines` }, { label: "BTS on-time data used here", href: "https://www.transtats.bts.gov/ontime/" }],
  },
  AS: {
    strapline: "A West Coast-focused network carrier with a growing broader footprint.",
    whatItIs: "Alaska Airlines is a U.S. network airline. AS is the marketing-carrier code used in the BTS flight records.",
    role: "Network carrier / Oneworld member",
    quickFacts: [{ label: "Founded", value: "1932" }, { label: "Headquarters", value: "Seattle, Washington" }, { label: "Alliance", value: "Oneworld" }, { label: "BTS code", value: "AS" }],
    history: ["1932 — began as McGee Airways.", "1944 — adopted the Alaska Airlines name.", "2024 — Alaska Air Group completed its acquisition of Hawaiian Airlines; the brands and codes have a changing relationship that matters when interpreting newer records."],
    operationalNotes: ["Recent corporate and coding changes mean the most recent AS/HA records deserve extra care in a longitudinal comparison.", "This reference note is context, not a claim that every record changed code."],
    sources: [{ label: "Alaska Airlines — Wikipedia", href: `${WIKIPEDIA}Alaska_Airlines` }, { label: "BTS on-time data used here", href: "https://www.transtats.bts.gov/ontime/" }],
  },
  B6: {
    strapline: "A low-cost carrier built around major coastal focus cities.",
    whatItIs: "JetBlue Airways is a U.S. low-cost airline. B6 is the marketing-carrier code used for its BTS flight records.",
    role: "Low-cost carrier",
    quickFacts: [{ label: "Founded", value: "1998; service began 2000" }, { label: "Headquarters", value: "Long Island City, New York" }, { label: "Network style", value: "Coastal focus cities" }, { label: "BTS code", value: "B6" }],
    history: ["1998 — founded as New Air.", "2000 — began service as JetBlue Airways.", "Today — known for a low-cost model with a strong presence in New York, Boston, Florida, and other focus markets."],
    operationalNotes: ["Focus-city concentration makes airport-level performance especially useful for understanding the network.", "Separate the airline’s product positioning from measured operating outcomes."],
    sources: [{ label: "JetBlue — Wikipedia", href: `${WIKIPEDIA}JetBlue` }, { label: "BTS on-time data used here", href: "https://www.transtats.bts.gov/ontime/" }],
  },
  NK: {
    strapline: "An ultra-low-cost carrier where the base fare and optional services are deliberately separated.",
    whatItIs: "Spirit Airlines is a U.S. ultra-low-cost airline. NK is the marketing-carrier code used for its BTS records.",
    role: "Ultra-low-cost carrier",
    quickFacts: [{ label: "Founded", value: "1980; Spirit brand from 1992" }, { label: "Headquarters", value: "Miramar, Florida" }, { label: "Network style", value: "Low-fare / point-to-point" }, { label: "BTS code", value: "NK" }],
    history: ["1980 — began as Charter One.", "1992 — adopted the Spirit name.", "Today — uses an unbundled fare model with optional add-ons."],
    operationalNotes: ["The operating data can be compared with other carriers, but the business model is not identical.", "Use like-for-like route or airport comparisons when interpreting differences."],
    sources: [{ label: "Spirit Airlines — Wikipedia", href: `${WIKIPEDIA}Spirit_Airlines` }, { label: "BTS on-time data used here", href: "https://www.transtats.bts.gov/ontime/" }],
  },
  F9: {
    strapline: "An ultra-low-cost carrier with a Denver-centered network and leisure orientation.",
    whatItIs: "Frontier Airlines is a U.S. ultra-low-cost airline. F9 is the marketing-carrier code used by this project.",
    role: "Ultra-low-cost carrier",
    quickFacts: [{ label: "Founded", value: "1994" }, { label: "Headquarters", value: "Denver, Colorado" }, { label: "Network style", value: "Leisure / low-fare" }, { label: "BTS code", value: "F9" }],
    history: ["1994 — founded as a new Frontier Airlines.", "Later years — expanded from its Denver base into a broad U.S. low-fare network.", "Today — uses an unbundled product model and serves many leisure markets."],
    operationalNotes: ["A large number of seasonal or leisure routes can create uneven month-to-month patterns.", "Trend charts are more useful when read alongside volume."],
    sources: [{ label: "Frontier Airlines — Wikipedia", href: `${WIKIPEDIA}Frontier_Airlines` }, { label: "BTS on-time data used here", href: "https://www.transtats.bts.gov/ontime/" }],
  },
  G4: {
    strapline: "A leisure-oriented ultra-low-cost carrier connecting secondary and vacation markets.",
    whatItIs: "Allegiant Air is a U.S. ultra-low-cost carrier focused on leisure travel. G4 is its marketing-carrier code in the BTS data.",
    role: "Ultra-low-cost / leisure carrier",
    quickFacts: [{ label: "Founded", value: "1997" }, { label: "Headquarters", value: "Las Vegas, Nevada" }, { label: "Network style", value: "Small-city to leisure destinations" }, { label: "BTS code", value: "G4" }],
    history: ["1997 — founded as WestJet Express.", "1998 — began operations as Allegiant Air.", "Today — focuses on connecting smaller communities with leisure destinations."],
    operationalNotes: ["Lower-frequency routes can produce noisier percentages, so always check flight counts.", "The volume tile is part of the interpretation, not a footnote."],
    sources: [{ label: "Allegiant Air — Wikipedia", href: `${WIKIPEDIA}Allegiant_Air` }, { label: "BTS on-time data used here", href: "https://www.transtats.bts.gov/ontime/" }],
  },
  HA: {
    strapline: "Hawaii’s long-running airline, with an island-focused network and mainland links.",
    whatItIs: "Hawaiian Airlines is a U.S. airline based in Honolulu. HA is the historical marketing-carrier code represented in the BTS data, although current code relationships require care after the Alaska acquisition.",
    role: "Island network carrier",
    quickFacts: [{ label: "Founded", value: "1929" }, { label: "Headquarters", value: "Honolulu, Hawaii" }, { label: "Network style", value: "Inter-island / mainland links" }, { label: "BTS code", value: "HA" }],
    history: ["1929 — founded as Inter-Island Airways.", "Later years — grew into a major provider of inter-island and Hawaii–mainland service.", "2024 — acquired by Alaska Air Group; interpret the newest records with the code transition in mind."],
    operationalNotes: ["Island operations have a different geography and schedule structure from mainland networks.", "Do not treat a carrier-wide average as a substitute for route-level context."],
    sources: [{ label: "Hawaiian Airlines — Wikipedia", href: `${WIKIPEDIA}Hawaiian_Airlines` }, { label: "BTS on-time data used here", href: "https://www.transtats.bts.gov/ontime/" }],
  },
  VX: {
    strapline: "A historical carrier profile retained to explain legacy records in the warehouse.",
    whatItIs: "Virgin America was a U.S. airline that operated as a separate brand before being acquired by Alaska Airlines. VX is retained here because historical BTS data can contain its records.",
    role: "Historical / retired carrier code",
    quickFacts: [{ label: "Founded", value: "2004; service began 2007" }, { label: "Headquarters", value: "Burlingame, California" }, { label: "Status", value: "Brand retired after Alaska acquisition" }, { label: "BTS code", value: "VX" }],
    history: ["2004 — founded.", "2007 — began passenger service.", "2016–2018 — acquired and integrated into Alaska Airlines; the brand ceased operating separately."],
    operationalNotes: ["VX is a useful example of why a long time range needs business-history context.", "A small or zero recent volume is meaningful here, not a missing-data error."],
    sources: [{ label: "Virgin America — Wikipedia", href: `${WIKIPEDIA}Virgin_America` }, { label: "BTS on-time data used here", href: "https://www.transtats.bts.gov/ontime/" }],
  },
};

const AIRPORT_ROLE: Record<string, { role: string; description: string; hub?: string }> = {
  ATL: { role: "Global hub", description: "A very high-volume connecting airport serving the Atlanta region and a central Delta network hub.", hub: "Delta Air Lines" },
  DFW: { role: "Large connecting hub", description: "A major North Texas airport with a large domestic and international network, especially important to American Airlines.", hub: "American Airlines" },
  DEN: { role: "Mountain-region hub", description: "A large airport serving the Denver region and a major connecting point for several U.S. carriers.", hub: "United Airlines" },
  ORD: { role: "Major urban hub", description: "A high-volume Chicago airport serving a dense domestic and international market.", hub: "United Airlines / American Airlines" },
  LAX: { role: "International gateway", description: "A major West Coast gateway with substantial origin-destination traffic and international connectivity.", hub: "Multiple carriers" },
  JFK: { role: "International gateway", description: "A major New York international gateway with a carrier mix that changes by route and terminal.", hub: "Multiple carriers" },
  SEA: { role: "Pacific Northwest hub", description: "A major Pacific Northwest airport and an important Alaska Airlines network center.", hub: "Alaska Airlines" },
  MIA: { role: "International gateway", description: "A major South Florida gateway with strong links to Latin America and the Caribbean.", hub: "American Airlines" },
  CLT: { role: "Connecting hub", description: "A high-volume Southeastern U.S. airport with a strong connecting role in the American network.", hub: "American Airlines" },
  MSP: { role: "Upper Midwest hub", description: "A major Minneapolis–Saint Paul airport and an important Delta connection point.", hub: "Delta Air Lines" },
  HNL: { role: "Island gateway", description: "Hawaii’s primary international gateway and a central airport for inter-island and mainland service.", hub: "Hawaiian Airlines / Alaska Airlines" },
  SFO: { role: "Bay Area gateway", description: "A major San Francisco Bay Area airport with strong domestic and trans-Pacific connectivity.", hub: "United Airlines" },
};

export function getCarrierReference(code: string): ReferenceProfile {
  const upper = code.toUpperCase();
  const base = CARRIER_REFERENCE[upper];
  if (base) return { kind: "carrier", code: upper, name: CARRIER_NAMES[upper] ?? upper, ...base };
  return {
    kind: "carrier", code: upper, name: CARRIER_NAMES[upper] ?? upper,
    strapline: "A carrier profile assembled around the records available in the BTS warehouse.",
    whatItIs: "This carrier is identified by its marketing-carrier code in the BTS on-time dataset. Curated historical context has not yet been added for this code.",
    role: "BTS marketing-carrier code",
    quickFacts: [{ label: "BTS code", value: upper }],
    history: ["The data profile is available; the reference narrative is still being curated."],
    operationalNotes: ["Treat the measured statistics as data-derived and avoid filling gaps with assumptions."],
    sources: [{ label: "Search Wikipedia for this carrier", href: `https://en.wikipedia.org/w/index.php?search=${encodeURIComponent(CARRIER_NAMES[upper] ?? upper)}` }, { label: "BTS on-time data used here", href: "https://www.transtats.bts.gov/ontime/" }],
  };
}

export function getAirportReference(code: string, city?: string | null, state?: string | null): ReferenceProfile {
  const upper = code.toUpperCase();
  const name = airportDisplayName(upper, city, state);
  const role = AIRPORT_ROLE[upper];
  return {
    kind: "airport", code: upper, name,
    strapline: role?.description ?? "An airport profile combining measured BTS activity with plain-language reference context.",
    whatItIs: `${name} is identified in this project by the IATA code ${upper}. The performance figures come from BTS flight records; the description here is contextual reference material, not a BTS measurement.`,
    role: role?.role ?? "Airport in the BTS network",
    quickFacts: [
      { label: "IATA code", value: upper },
      ...(city && state ? [{ label: "Location", value: `${city}, ${state}` }] : []),
      ...(role?.hub ? [{ label: "Reference network role", value: role.hub }] : []),
      { label: "Measured by", value: "BTS on-time records" },
    ],
    history: role ? ["This airport’s reference role is presented as context for interpreting its measured traffic and reliability.", `Network note — ${role.hub ?? "the airport has multiple operators"}.`] : ["A fuller historical narrative is not yet curated for this airport.", "The measured profile remains available from the BTS warehouse."],
    operationalNotes: ["Busy airports can have high flight counts and still show different patterns by carrier, direction, and hour.", "Use the researcher view to inspect those operating conditions instead of relying on one airport-wide average."],
    sources: [{ label: `${name} — Wikipedia search`, href: `https://en.wikipedia.org/w/index.php?search=${encodeURIComponent(name)}` }, { label: "BTS on-time data used here", href: "https://www.transtats.bts.gov/ontime/" }],
  };
}

export function allAirportCodes(): string[] {
  return Object.keys(AIRPORT_FULL_NAMES);
}
