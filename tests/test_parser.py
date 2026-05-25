from __future__ import annotations

import unittest

from pedalbom.parser import parse_text


SAMPLE_TEXT = """
Unless otherwise noted, the footprints on the PCB support 5mm film
caps, 2.5mm electrolytic caps, and 1/4w resistors.
The pedal should be powered by a regulated, screened and isolated
power supply, delivering 9v DC tip negative, at a minimum of 100mA

Bill of Materials
Resistors
Part ID Value  Count total  Note
R1 10r 1
R2 390r 1 Sets max brightness
for LED. Adjust to taste
R3 B20k trim
3362 bourns
1 LED brightness,
adjust to taste up to
100k

Capacitors
Part ID Value  Count total  Note
C3, C4, C5, C6, C7, C8 10uF 5 16v min.
C3 10uF NP 1 If use polar, insert
opposite way to
silkscreen

Potentiometers
Part ID Value  Count total  Note
Swell/Fuzz/Octave "OFS" A1M 1

Semiconductors
Part ID Value  Count total  Note
D1 1n5817 1 Reverse polarity
D3, D4, D5, D6, D7, D8, D9,
D10, D11, D12, D13, D14
1n4148 12
Q2 BC547b NPN 1  Sub 2n2222a /
BC548
Q4 2N5088 1 Sub BC549c

Other
Part ID Value  Count total  Note
Footswitch 3PDT 1 Standard part, orient
90 degrees(!)
Sourcing Parts
"""

STRAYLIGHT_TEXT = """
STRAYLIGHT CHORUS/VIBE
5
PARTS LIST
PART VALUE TYPE NOTES
R32 4k7 Metal film resistor, 1/4W
STRAYLIGHT CHORUS/VIBE
6
C15 1uF Film capacitor, 7.2 x 3.5mm See build notes (pg. 14) for alternatives if these are out of stock.
D7 3mm LED LED, 3mm, red diffused Part of the rate indicator mod. See build notes.
REG 78L15 Regulator, +15V , TO-92
IC1-S DIP-8 socket IC socket, DIP-8
LDR1 PDV-P9203 LDR, 10-30k light, 5M dark See build notes for possible LDR substitutes.
SPEED A 100kC dual 16mm dual pot, right angle
CH/VIBE SPDT on-on T oggle switch, SPDT on-on
CANCEL SPDT on-on T oggle switch, SPDT on-on
DC 2.1mm DC jack, 2.1mm panel mount Lumberg NEB/J 21 C or equivalent.
GAIN 500R trimmer Trimmer, 10%, 1/4" Bourns 3362P
ENCLOSURE 1590BBS Enclosure, die-cast aluminum
BUILD NOTES
"""


class ParserTests(unittest.TestCase):
    def test_multiline_rows_and_notes_are_extracted(self) -> None:
        document = parse_text(SAMPLE_TEXT)
        items = {(item.section, item.part_id): item for item in document.items}

        self.assertEqual(items[("resistors", "R3")].value, "B20k trim 3362 bourns")
        self.assertEqual(items[("resistors", "R3")].quantity, 1)
        self.assertEqual(
            items[("semiconductors", "D3, D4, D5, D6, D7, D8, D9, D10, D11, D12, D13, D14")].quantity,
            12,
        )
        self.assertEqual(items[("semiconductors", "Q2")].notes, "Sub 2n2222a / BC548")
        self.assertEqual(items[("semiconductors", "Q4")].value, "2N5088")

    def test_ambiguous_duplicate_designators_are_flagged(self) -> None:
        document = parse_text(SAMPLE_TEXT)
        capacitor_rows = [item for item in document.items if item.section == "capacitors"]

        warnings = " ".join("; ".join(item.warnings) for item in capacitor_rows)
        self.assertIn("Designator count (6) does not match quantity (5)", warnings)
        self.assertIn("C3 also appears", warnings)

    def test_generic_parts_list_format_is_extracted(self) -> None:
        document = parse_text(STRAYLIGHT_TEXT)
        items = {item.part_id: item for item in document.items}

        self.assertEqual(len(document.items), 12)
        self.assertEqual(items["R32"].notes, "Metal film resistor, 1/4W")
        self.assertEqual(items["REG"].section, "semiconductors")
        self.assertEqual(items["IC1-S"].value, "DIP-8 socket")
        self.assertEqual(items["LDR1"].section, "semiconductors")
        self.assertEqual(items["SPEED A"].section, "potentiometers")
        self.assertEqual(items["CH/VIBE"].section, "other")
        self.assertEqual(items["CH/VIBE"].notes, "Toggle switch, SPDT on-on")
        self.assertEqual(items["DC"].section, "other")
        self.assertEqual(items["GAIN"].notes, 'Trimmer, 10%, 1/4" Bourns 3362P')


if __name__ == "__main__":
    unittest.main()
