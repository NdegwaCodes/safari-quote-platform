import type { Image as ApiImage } from "@/lib/types";
import { imageSrc } from "@/lib/site";
import { cn } from "@/lib/utils";

export function Photo({
  image,
  className,
  priority = false,
  sizes,
}: {
  image: ApiImage;
  className?: string;
  priority?: boolean;
  sizes?: string;
}) {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={imageSrc(image.url)}
      alt={image.alt_text ?? ""}
      width={image.width ?? undefined}
      height={image.height ?? undefined}
      loading={priority ? "eager" : "lazy"}
      decoding="async"
      sizes={sizes}
      className={cn("block h-full w-full object-cover", className)}
    />
  );
}

export function lead(images: ApiImage[]): ApiImage | null {
  return images.find((one) => one.is_lead) ?? images[0] ?? null;
}
