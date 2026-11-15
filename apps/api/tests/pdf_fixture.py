from __future__ import annotations


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def make_pdf(rows: list[tuple[float, float, str]], *, size: tuple[int, int] = (612, 792)) -> bytes:
    parts = ["BT", "/F1 9 Tf"]
    for x, y, text in rows:
        parts.append(f"1 0 0 1 {x} {y} Tm ({_escape(text)}) Tj")
    parts.append("ET")
    content = "\n".join(parts).encode("latin-1")

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {size[0]} {size[1]}] "
            f"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
        ).encode("latin-1"),
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


def palmyra_shore_shaped_pdf(
    *, column_without_occupancy: bool = False, marker: str = ""
) -> bytes:
    columns = (40.0, 150.0, 330.0, 400.0, 500.0, 600.0, 700.0, 810.0)
    rows: list[tuple[float, float, str]] = [
        (columns[0], 760.0, "STO RATE AGREEMENT - RESIDENT MARKET 2026 in KES"),
        (columns[3], 720.0, "Standard Room"),
        (columns[5], 720.0, "Superior Room"),
        (columns[2], 700.0, "meal"),
        (columns[3], 700.0, "Single"),
        (columns[4], 700.0, "Double"),
        (columns[5], 700.0, "Single"),
        (columns[6], 700.0, "Double"),
    ]
    body = [
        ("HIGH", "04/01/2026 - 02/04/2026", "BB", "23.920", "31.200", "31.200", "38.480"),
        ("LOW", "07/04/2026 - 30/06/2026", "BB", "19.760", "27.040", "27.040", "34.320"),
        ("PEAK", "23/12/2026 - 03/01/2027", "HB", "42.640", "53.040", "49.920", "60.320"),
    ]
    if column_without_occupancy:
        rows.append((columns[7], 720.0, "CLUB ROOM"))
        body = [
            (*row, club)
            for row, club in zip(body, ("48.880", "44.720", "70.720"), strict=True)
        ]
    y = 675.0
    for season, window, meal, *prices in body:
        rows.append((columns[0], y, season))
        rows.append((columns[1], y, window))
        rows.append((columns[2], y, meal))
        for index, price in enumerate(prices):
            rows.append((columns[3 + index], y, f"{price} KES"))
        y -= 25.0
    if marker:
        rows.append((columns[0], 40.0, marker))
    return make_pdf(rows, size=(1000, 792))


def tamarind_point_shaped_pdf() -> bytes:
    meal_x = (202.0, 245.0, 295.0, 340.0, 397.0, 440.0, 491.0, 538.0)
    price_x = (195.0, 239.0, 285.0, 330.0, 388.0, 435.0, 483.0, 528.0)
    rows: list[tuple[float, float, str]] = [
        (36.0, 760.0, "KSH STO Rates 2027/2028"),
        (36.0, 745.0, "Rates are per room per night, in KSH & inclusive of all taxes."),
        (225.0, 720.0, "HIGH SEASON"),
        (414.0, 720.0, "FESTIVE SEASON"),
        (221.0, 705.0, "11.01.27 - 19.12.27"),
        (413.0, 705.0, "20.12.27 - 10.01.28"),
    ]
    blocks = [
        (
            "CREEK DELUXE",
            [
                ("Single", ("21,600", "24,000", "26,500", "28,400",
                            "30,200", "32,600", "35,100", "37,000")),
                ("Double", ("24,000", "28,900", "33,700", "37,600",
                            "33,600", "38,400", "43,300", "47,200")),
            ],
        ),
        (
            "BOUTIQUE",
            [
                ("Single", ("17,500", "19,900", "22,400", "24,300",
                            "24,500", "26,900", "29,400", "31,300")),
                ("Triple", ("19,400", "26,700", "34,100", "39,900",
                            "27,200", "34,500", "41,800", "47,700")),
            ],
        ),
    ]
    y = 680.0
    for room, data in blocks:
        rows.append((36.0, y, room))
        for index, code in enumerate(("BO", "B&B", "HB", "FB") * 2):
            rows.append((meal_x[index], y, code))
        y -= 25.0
        for label, prices in data:
            rows.append((36.0, y, label))
            for index, price in enumerate(prices):
                rows.append((price_x[index], y, price))
            y -= 25.0
        y -= 15.0
    return make_pdf(rows)
