export type FieldType =
  | "text"
  | "number"
  | "decimal"
  | "boolean"
  | "select"
  | "lookup"
  | "date";

export interface ParentSpec {
  collection: string;
  label: string;
  segment: string;
}

export interface FieldSpec {
  name: string;
  label: string;
  type: FieldType;
  required?: boolean;
  options?: string[];
  lookup?: string;
  lookupUnderParent?: boolean;
  inTable?: boolean;
  inForm?: boolean;
  default?: string | number | boolean;
  placeholder?: string;
}

export interface CatalogueSpec {
  path: string;
  parent?: ParentSpec;
  title: string;
  subtitle: string;
  singular: string;
  readPermission: string;
  managePermission: string;
  fields: FieldSpec[];
}

export interface CatalogueRow {
  id: string;
  name: string;
  slug?: string;
  [key: string]: unknown;
}

export const DESTINATIONS: CatalogueSpec = {
  path: "destinations",
  title: "Destinations",
  subtitle: "Parks, reserves, towns and other places an itinerary can visit.",
  singular: "destination",
  readPermission: "destination:read",
  managePermission: "destination:manage",
  fields: [
    { name: "name", label: "Name", type: "text", required: true },
    {
      name: "type",
      label: "Type",
      type: "select",
      options: ["park", "reserve", "conservancy", "city", "town", "beach", "other"],
      default: "park",
    },
    { name: "country", label: "Country", type: "text", default: "Kenya" },
    { name: "region", label: "Region", type: "text" },
    { name: "is_active", label: "Active", type: "boolean", default: true },
  ],
};

export const ACCOMMODATIONS: CatalogueSpec = {
  path: "accommodations",
  title: "Accommodations",
  subtitle: "Lodges, camps and hotels. Room types and seasonal rates hang off each one.",
  singular: "accommodation",
  readPermission: "accommodation:read",
  managePermission: "accommodation:manage",
  fields: [
    { name: "name", label: "Name", type: "text", required: true },
    {
      name: "destination_id",
      label: "Destination",
      type: "lookup",
      lookup: "destinations",
      required: true,
    },
    {
      name: "category",
      label: "Category",
      type: "select",
      options: ["lodge", "tented_camp", "hotel", "guest_house", "villa", "other"],
      default: "lodge",
    },
    { name: "star_rating", label: "Stars", type: "number" },
    { name: "is_active", label: "Active", type: "boolean", default: true },
  ],
};

export const ACTIVITIES: CatalogueSpec = {
  path: "activities",
  title: "Activities",
  subtitle: "Game drives, balloon safaris, cultural visits and other priced experiences.",
  singular: "activity",
  readPermission: "activity:read",
  managePermission: "activity:manage",
  fields: [
    { name: "name", label: "Name", type: "text", required: true },
    { name: "destination_id", label: "Destination", type: "lookup", lookup: "destinations" },
    { name: "duration_minutes", label: "Duration (min)", type: "number" },
    { name: "is_optional", label: "Optional", type: "boolean", default: true },
    { name: "is_active", label: "Active", type: "boolean", default: true },
  ],
};

export const VEHICLES: CatalogueSpec = {
  path: "vehicles",
  title: "Vehicles",
  subtitle: "Fleet used for transport costing. Fuel economy drives the fuel line on a quote.",
  singular: "vehicle",
  readPermission: "vehicle:read",
  managePermission: "vehicle:manage",
  fields: [
    { name: "name", label: "Name", type: "text", required: true },
    {
      name: "vehicle_type",
      label: "Type",
      type: "select",
      options: ["safari_land_cruiser", "safari_van", "minibus", "saloon", "suv", "other"],
      default: "safari_land_cruiser",
    },
    { name: "registration", label: "Reg.", type: "text" },
    { name: "passenger_capacity", label: "Seats", type: "number", default: 6 },
    { name: "fuel_type", label: "Fuel", type: "text", default: "diesel" },
    {
      name: "fuel_consumption_kmpl",
      label: "km/L",
      type: "decimal",
      required: true,
      placeholder: "7",
    },
    { name: "driver_cost_per_day", label: "Driver/day", type: "decimal", default: "0" },
    { name: "daily_operating_cost", label: "Operating/day", type: "decimal", default: "0" },
    { name: "currency", label: "Currency", type: "text", required: true, default: "USD" },
    { name: "is_active", label: "Active", type: "boolean", default: true },
  ],
};


const RATE_TAIL: FieldSpec[] = [
  {
    name: "residence_category_id",
    label: "Residence",
    type: "lookup",
    lookup: "residence-categories",
    required: true,
  },
  { name: "currency", label: "Currency", type: "text", required: true, default: "USD" },
  { name: "effective_from", label: "From", type: "date", required: true },
  { name: "effective_to", label: "To", type: "date", required: true },
  { name: "is_active", label: "Active", type: "boolean", default: true },
];

export const ACCOMMODATION_RATES: CatalogueSpec = {
  path: "rates",
  parent: { collection: "accommodations", label: "Accommodation", segment: "rates" },
  title: "Seasonal rates",
  subtitle: "Per room type, meal plan and residence category, over a season window.",
  singular: "rate",
  readPermission: "accommodation:read",
  managePermission: "accommodation:manage",
  fields: [
    {
      name: "room_type_id",
      label: "Room type",
      type: "lookup",
      lookup: "room-types",
      lookupUnderParent: true,
      required: true,
    },
    {
      name: "meal_plan_id",
      label: "Meal plan",
      type: "lookup",
      lookup: "meal-plans",
      required: true,
    },
    { name: "season_name", label: "Season", type: "text", default: "Standard" },
    { name: "rate_per_night", label: "Per night", type: "decimal", required: true },
    { name: "child_rate", label: "Child", type: "decimal" },
    { name: "single_supplement", label: "Single supp.", type: "decimal" },
    ...RATE_TAIL,
  ],
};

export const PARK_FEES: CatalogueSpec = {
  path: "park-fees",
  parent: { collection: "destinations", label: "Destination", segment: "park-fees" },
  title: "Park & conservation fees",
  subtitle: "Per destination and residence category, with the child-age bounds that classify travellers.",
  singular: "fee",
  readPermission: "park_fee:read",
  managePermission: "park_fee:manage",
  fields: [
    { name: "fee_type", label: "Type", type: "text", default: "park_entry" },
    { name: "adult", label: "Adult", type: "decimal", required: true },
    { name: "child", label: "Child", type: "decimal", required: true },
    { name: "infant", label: "Infant", type: "decimal", default: "0" },
    { name: "child_min_age", label: "Child from age", type: "number", default: 3 },
    { name: "child_max_age", label: "Child to age", type: "number", default: 11 },
    ...RATE_TAIL,
  ],
};

export const ACTIVITY_RATES: CatalogueSpec = {
  path: "rates",
  parent: { collection: "activities", label: "Activity", segment: "rates" },
  title: "Activity rates",
  subtitle: "Effective-dated adult and child prices per residence category.",
  singular: "rate",
  readPermission: "activity:read",
  managePermission: "activity:manage",
  fields: [
    { name: "adult_price", label: "Adult", type: "decimal", required: true },
    { name: "child_price", label: "Child", type: "decimal", required: true },
    ...RATE_TAIL,
  ],
};

export const FUEL_PRICES: CatalogueSpec = {
  path: "fuel-prices",
  title: "Fuel prices",
  subtitle: "Effective-dated price per litre by fuel type. Drives the fuel line on every quote.",
  singular: "fuel price",
  readPermission: "vehicle:read",
  managePermission: "vehicle:manage",
  fields: [
    { name: "fuel_type", label: "Fuel type", type: "text", required: true, default: "diesel" },
    { name: "price_per_litre", label: "Per litre", type: "decimal", required: true },
    { name: "currency", label: "Currency", type: "text", required: true, default: "USD" },
    { name: "effective_from", label: "From", type: "date", required: true },
    { name: "source", label: "Source", type: "text", default: "manual" },
  ],
};
