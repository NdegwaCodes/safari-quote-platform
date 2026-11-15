import { Chrome } from "@/components/chrome";
import { TripProvider } from "@/components/trip-provider";

export default function TripLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <TripProvider>
      <Chrome>{children}</Chrome>
    </TripProvider>
  );
}
