/**
 * Horse Racing Nation profile pages for the 2026 Preakness field.
 */
export const PREAKNESS_HORSE_URLS = Object.freeze({
  "TAJ MAHAL": "https://www.horseracingnation.com/horse/Taj_Mahal_4",
  OCELLI: "https://www.horseracingnation.com/horse/Ocelli",
  CRUPPER: "https://www.horseracingnation.com/horse/Crupper",
  ROBUSTA: "https://www.horseracingnation.com/horse/Robusta",
  TALKIN: "https://www.horseracingnation.com/horse/Talkin",
  "CHIP HONCHO": "https://www.horseracingnation.com/horse/Chip_Honcho",
  "THE HELL WE DID": "https://www.horseracingnation.com/horse/The_Hell_We_Did",
  "BULL BY THE HORNS": "https://www.horseracingnation.com/horse/Bull_by_the_Horns",
  "IRON HONOR": "https://www.horseracingnation.com/horse/Iron_Honor",
  "NAPOLEON SOLO": "https://www.horseracingnation.com/horse/Napoleon_Solo",
  "CORONA DE ORO": "https://www.horseracingnation.com/horse/Corona_de_Oro",
  INCREDIBOLT: "https://www.horseracingnation.com/horse/Incredibolt",
  "GREAT WHITE": "https://www.horseracingnation.com/horse/Great_White",
  "PRETTY BOY MIAH": "https://www.horseracingnation.com/horse/Pretty_Boy_Miah",
});

export function normalizeHorseName(s) {
  return String(s ?? "")
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .join(" ")
    .toUpperCase();
}

export function getPreaknessHorseUrl(horseName) {
  return PREAKNESS_HORSE_URLS[normalizeHorseName(horseName)] ?? null;
}
