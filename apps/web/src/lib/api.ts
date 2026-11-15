import type { Contact, Experience, Place, Property } from "@/lib/types";

const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";
const V1 = "/api/v1";

export const REVALIDATE = 300;

async function read<T>(path: string, fallback: T): Promise<T> {
  try {
    const res = await fetch(`${API_BASE}${V1}/public/${path}`, {
      next: { revalidate: REVALIDATE },
    });
    if (!res.ok) return fallback;
    return (await res.json()) as T;
  } catch {
    return fallback;
  }
}

export const places = () => read<Place[]>("destinations", []);
export const place = (slug: string) =>
  read<Place | null>(`destinations/${encodeURIComponent(slug)}`, null);

export const properties = (destination?: string) =>
  read<Property[]>(
    destination
      ? `accommodations?destination=${encodeURIComponent(destination)}`
      : "accommodations",
    [],
  );
export const property = (slug: string) =>
  read<Property | null>(`accommodations/${encodeURIComponent(slug)}`, null);

export const experiences = (destination?: string) =>
  read<Experience[]>(
    destination
      ? `activities?destination=${encodeURIComponent(destination)}`
      : "activities",
    [],
  );

const NO_CONTACT: Contact = {
  company_name: "Acacia Tours & Travel",
  contact_email: "",
  contact_phone: "",
  social_line: "",
};

export const contact = () => read<Contact>("contact", NO_CONTACT);
