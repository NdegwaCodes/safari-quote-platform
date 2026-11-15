import type { MetadataRoute } from "next";
import { places, properties } from "@/lib/api";
import { canonical } from "@/lib/site";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const [allPlaces, allStays] = await Promise.all([places(), properties()]);

  const fixed = ["/", "/destinations", "/stays", "/experiences", "/enquire"];

  return [
    ...fixed.map((path) => ({
      url: canonical(path),
      changeFrequency: "weekly" as const,
      priority: path === "/" ? 1 : 0.7,
    })),
    ...allPlaces.map((one) => ({
      url: canonical(`/destinations/${one.slug}`),
      changeFrequency: "weekly" as const,
      priority: 0.8,
    })),
    ...allStays.map((one) => ({
      url: canonical(`/stays/${one.slug}`),
      changeFrequency: "weekly" as const,
      priority: 0.6,
    })),
  ];
}
