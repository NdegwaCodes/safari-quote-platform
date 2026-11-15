export type Image = {
  id: string;
  url: string;
  alt_text: string | null;
  width: number | null;
  height: number | null;
  is_lead: boolean;
};

export type Place = {
  name: string;
  slug: string;
  type: string;
  country: string;
  region: string | null;
  latitude: string | null;
  longitude: string | null;
  description: string | null;
  images: Image[];
  stays: string[];
  activities: string[];
};

export type Property = {
  name: string;
  slug: string;
  category: string;
  star_rating: number | null;
  latitude: string | null;
  longitude: string | null;
  check_in_time: string | null;
  check_out_time: string | null;
  description: string | null;
  destination: string;
  destination_slug: string;
  rooms: string[];
  images: Image[];
};

export type Experience = {
  name: string;
  slug: string;
  description: string | null;
  duration_minutes: number | null;
  destination: string;
  destination_slug: string;
};

export type Contact = {
  company_name: string;
  contact_email: string;
  contact_phone: string;
  social_line: string;
};

export type LegEstimate = {
  destination: string;
  tier: string;
  nights: number;
  property_name: string | null;
  room_type: string | null;
  meal_plan: string | null;
  currency: string | null;
  per_person: string | null;
  group_total: string | null;
  refused: string | null;
};

export type Estimate = {
  legs: LegEstimate[];
  currency: string | null;
  per_person: string | null;
  group_total: string | null;
  note: string;
};
