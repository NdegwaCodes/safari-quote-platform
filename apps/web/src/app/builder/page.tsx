import { Builder } from "@/components/builder";
import { places } from "@/lib/api";
import { canonical } from "@/lib/site";

export const metadata = {
  title: "Safari builder",
  description:
    "Build a trip destination by destination and see a real, currently " +
    "published price for it — not a placeholder.",
  alternates: { canonical: canonical("/builder") },
};

export default async function BuilderPage() {
  const destinations = await places();
  return <Builder destinations={destinations} />;
}
