"use client";
/* eslint-disable @next/next/no-img-element */
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

type Destination = {
  name: string;
  intro: string;
  detail: string;
  location: string;
  image: string | null;
  href: string;
};

const DESTINATIONS: Destination[] = [
  {
    name: "Diani",
    intro:
      "Warm water the whole year, a reef close enough to swim to, and hotels small enough to know your name.",
    detail: "The south coast reef",
    location: "Kwale, Kenya",
    image: "/malindi/shallows.jpg",
    href: "/destinations",
  },
  {
    name: "Watamu",
    intro:
      "Mida Creek at low tide, the ruins at Gede in the forest, and the quietest sand on the coast.",
    detail: "Creek, ruins and quiet sand",
    location: "Kilifi, Kenya",
    image: "/malindi/mangroves.jpg",
    href: "/destinations",
  },
  {
    name: "Lamu",
    intro:
      "Coral-stone lanes with no cars, a working dhow harbour, and a pace the tide sets for you.",
    detail: "Old town and the dhow coast",
    location: "Lamu, Kenya",
    image: "/malindi/dhow.jpg",
    href: "/destinations",
  },
  {
    name: "Maasai Mara",
    intro:
      "Open plains and big skies, with the river crossings in the months the herds are moving.",
    detail: "Plains and the migration",
    location: "Narok, Kenya",
    image: null,
    href: "/destinations",
  },
  {
    name: "Rusinga Island",
    intro:
      "Fishing villages on Lake Victoria, sunsets over the water, and the fossil beds where Mary Leakey found Proconsul.",
    detail: "Lake Victoria's islands",
    location: "Homa Bay, Kenya",
    image: null,
    href: "/destinations",
  },
  {
    name: "Mount Kenya",
    intro:
      "Cold mornings at altitude, game drives on private conservancy land, and the mountain over breakfast.",
    detail: "Highlands and conservancy",
    location: "Nanyuki, Kenya",
    image: null,
    href: "/destinations",
  },
  {
    name: "Nanyuki",
    intro:
      "A market town on the equator, and the gate to Ol Pejeta, home to the last two northern white rhinos.",
    detail: "The equator and Ol Pejeta",
    location: "Laikipia, Kenya",
    image: null,
    href: "/destinations",
  },
  {
    name: "Laikipia",
    intro:
      "A high plateau of private ranches and conservancies, with walking safaris, camel treks and wild dogs.",
    detail: "Ranches, walking and wild dogs",
    location: "Laikipia, Kenya",
    image: null,
    href: "/destinations",
  },
  {
    name: "Samburu",
    intro:
      "Dry country along the Ewaso Ng'iro, and the northern species you see nowhere else: Grevy's zebra, gerenuk and reticulated giraffe.",
    detail: "The Ewaso Ng'iro and the north",
    location: "Samburu, Kenya",
    image: null,
    href: "/destinations",
  },
  {
    name: "Turkana",
    intro:
      "The Jade Sea, the largest desert lake in the world, with volcanic islands and the fossil beds of Koobi Fora.",
    detail: "The Jade Sea and the far north",
    location: "Turkana, Kenya",
    image: null,
    href: "/destinations",
  },
];

const PLACEHOLDER = "bg-gradient-to-br from-sea via-panel to-ink";

const CARD_STEP = 265;

export function Hero() {
  const [active, setActive] = useState(0);
  const [maxOffset, setMaxOffset] = useState(0);
  const viewportRef = useRef<HTMLDivElement>(null);
  const trackRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const id = setTimeout(() => {
      setActive((prev) => (prev + 1) % DESTINATIONS.length);
    }, 5500);
    return () => clearTimeout(id);
  }, [active]);

  useEffect(() => {
    const viewport = viewportRef.current;
    const track = trackRef.current;
    if (!viewport || !track) return;
    const measure = () => setMaxOffset(Math.max(0, track.scrollWidth - viewport.clientWidth));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(viewport);
    return () => observer.disconnect();
  }, []);

  const current = DESTINATIONS[active];
  if (!current) return null;
  const offset = Math.min(active * CARD_STEP, maxOffset);

  return (
    <section className="relative isolate flex min-h-[90vh] flex-col justify-end overflow-hidden">
      {DESTINATIONS.map((dest, index) => (
        <div
          key={dest.name}
          className={`absolute inset-0 -z-20 transition-opacity duration-1000 ${
            index === active ? "opacity-100" : "opacity-0"
          }`}
        >
          {dest.image ? (
            <img src={dest.image} alt="" className="h-full w-full object-cover" />
          ) : (
            <div className={`h-full w-full ${PLACEHOLDER}`} />
          )}
        </div>
      ))}
      <div className="absolute inset-0 -z-10 bg-gradient-to-t from-black/90 via-black/55 to-black/30" />

      <div className="mx-auto w-full max-w-6xl px-6 pt-16 lg:px-[72px] lg:pt-14">
        <span className="inline-flex items-center gap-2 rounded-pill border border-white/25 bg-white/10 px-4 py-1.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-white backdrop-blur">
          <span className="h-1.5 w-1.5 rounded-full bg-gold-soft" />
          Where we go
        </span>
        <h1 className="mt-5 max-w-[18ch] font-display text-5xl font-medium leading-[1.03] text-white sm:text-6xl lg:text-7xl">
          Two coasts, one country, <span className="text-gold-soft">built to order</span>
        </h1>
      </div>

      <div className="mx-auto mt-10 grid w-full max-w-6xl grid-cols-1 items-end gap-10 px-6 pb-14 lg:grid-cols-[minmax(0,24rem)_minmax(0,1fr)] lg:gap-12 lg:px-[72px] lg:pb-12">
        <div key={active} className="hero-fade">
          <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-gold-soft">
            Featured destination
          </p>
          <h2 className="mt-2 font-display text-4xl font-medium text-white">
            {current.name}
          </h2>
          <p className="mt-3 max-w-sm text-[15px] leading-relaxed text-white/85">
            {current.intro}
          </p>
          <p className="mt-3 inline-flex items-center gap-1.5 text-[13px] text-white/75">
            <svg viewBox="0 0 24 24" className="h-4 w-4 fill-gold-soft" aria-hidden="true">
              <path d="M12 2a7 7 0 0 0-7 7c0 5 7 13 7 13s7-8 7-13a7 7 0 0 0-7-7zm0 9.5A2.5 2.5 0 1 1 12 6.5a2.5 2.5 0 0 1 0 5z" />
            </svg>
            {current.location}
          </p>

          <div className="mt-7 flex flex-wrap items-center gap-4">
            <Link
              href="/enquire"
              className="rounded-pill bg-gold-bright px-7 py-3.5 text-[12px] font-bold uppercase tracking-[0.1em] text-ink shadow-xl transition duration-200 hover:-translate-y-0.5 hover:bg-gold-deep hover:text-white"
            >
              Request a custom trip
            </Link>
            <Link
              href="/builder"
              className="rounded-pill border border-white/45 bg-white/5 px-7 py-3.5 text-[12px] font-semibold uppercase tracking-[0.1em] text-white backdrop-blur transition duration-200 hover:-translate-y-0.5 hover:bg-white/15"
            >
              Build your own trip
            </Link>
          </div>

          <div className="mt-6 inline-flex items-center gap-2.5 rounded-pill bg-white/10 px-4 py-2 text-[12px] font-medium text-white/85 backdrop-blur">
            <span className="h-1.5 w-1.5 rounded-full bg-gold-soft" />
            Real, itemised prices. Never a fake discount.
          </div>
        </div>

        <div className="hidden min-w-0 lg:block">
          <div
            ref={viewportRef}
            className="overflow-hidden py-1"
            onScroll={(event) => {
              event.currentTarget.scrollLeft = 0;
            }}
          >
            <div
              ref={trackRef}
              className="flex items-end gap-5 px-1 transition-transform duration-500 ease-out"
              style={{ transform: `translateX(-${offset}px)` }}
            >
              {DESTINATIONS.map((dest, index) => (
                <button
                  key={dest.name}
                  type="button"
                  onClick={() => setActive(index)}
                  onFocus={() => setActive(index)}
                  aria-label={`Show ${dest.name}`}
                  className={`relative shrink-0 overflow-hidden rounded-3xl text-left transition-all duration-500 ${
                    index === active
                      ? "h-[340px] w-[245px] ring-2 ring-gold-bright"
                      : "h-[300px] w-[245px] opacity-80 hover:opacity-100"
                  }`}
                >
                  {dest.image ? (
                    <img src={dest.image} alt="" className="absolute inset-0 h-full w-full object-cover" />
                  ) : (
                    <div className={`absolute inset-0 ${PLACEHOLDER}`} />
                  )}
                  <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent" />
                  <div className="absolute inset-x-0 bottom-0 p-5">
                    <p className="font-display text-xl text-white">{dest.name}</p>
                    <p className="mt-1 text-[12px] leading-snug text-white/80">{dest.detail}</p>
                    <p className="mt-2 inline-flex items-center gap-1 text-[11px] text-white/70">
                      <svg viewBox="0 0 24 24" className="h-3 w-3 fill-gold-soft" aria-hidden="true">
                        <path d="M12 2a7 7 0 0 0-7 7c0 5 7 13 7 13s7-8 7-13a7 7 0 0 0-7-7zm0 9.5A2.5 2.5 0 1 1 12 6.5a2.5 2.5 0 0 1 0 5z" />
                      </svg>
                      {dest.location}
                    </p>
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="mx-auto mb-8 flex w-full max-w-6xl gap-2 px-6 lg:px-[72px]">
        {DESTINATIONS.map((dest, index) => (
          <button
            key={dest.name}
            type="button"
            onClick={() => setActive(index)}
            aria-label={`Show ${dest.name}`}
            className={`h-1.5 rounded-full transition-all duration-300 ${
              index === active ? "w-10 bg-gold-bright" : "w-5 bg-white/35 hover:bg-white/60"
            }`}
          />
        ))}
      </div>
    </section>
  );
}
