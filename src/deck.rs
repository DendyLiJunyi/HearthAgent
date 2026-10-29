//! Bounded version-1 deckstring decoding. Format and card identity are metadata,
//! not proof that a deck is legal for the installed rules version.
use std::collections::BTreeMap;
use base64::{engine::general_purpose::STANDARD, Engine};
use serde::Serialize;

/// Reviewed ordinary attack sources for the first deck. An arbitrary in-play
/// minion POWER option may be an activated ability (for example a Titan).
pub const TARGET_ATTACK_SOURCES: &[&str] = &[
    "LOOT_412", "TID_078",
];
pub const TARGET_HERO_PREFIX: &str = "HERO_03";

#[derive(Debug, PartialEq, Eq, Serialize)]
pub struct Deck {
    pub format: &'static str,
    pub hero_dbf_id: u32,
    pub cards: BTreeMap<u32, u32>,
    pub total_cards: u32,
}

struct Reader<'a> { bytes: &'a [u8], cursor: usize }
impl Reader<'_> {
    fn uint(&mut self) -> Result<u32, String> {
        let mut value = 0u32;
        for shift in (0..35).step_by(7) {
            let byte = *self.bytes.get(self.cursor).ok_or("truncated deckstring")?;
            self.cursor += 1;
            if shift == 28 && byte > 15 { return Err("deckstring integer overflow".into()); }
            value |= u32::from(byte & 127) << shift;
            if byte & 128 == 0 {
                if shift != 0 && byte == 0 { return Err("noncanonical deckstring integer".into()); }
                return Ok(value);
            }
        }
        Err("deckstring integer overflow".into())
    }
}

pub fn decode(code: &str) -> Result<Deck, String> {
    let code = code.trim();
    if code.is_empty() || code.len() > 4096 { return Err("deckstring must contain 1..4096 bytes".into()); }
    let bytes = STANDARD.decode(code).map_err(|_| "invalid deckstring base64")?;
    let mut reader = Reader { bytes: &bytes, cursor: 0 };
    if reader.uint()? != 0 || reader.uint()? != 1 { return Err("unsupported deckstring header/version".into()); }
    let format = match reader.uint()? {
        1 => "wild", 2 => "standard", _ => return Err("unsupported deck format".into()),
    };
    if reader.uint()? != 1 { return Err("exactly one hero is supported".into()); }
    let hero_dbf_id = reader.uint()?;
    if hero_dbf_id == 0 { return Err("invalid hero ID".into()); }
    let mut cards = BTreeMap::new();
    let mut total_cards = 0;
    for fixed_count in [Some(1), Some(2), None] {
        let entries = reader.uint()?;
        if entries > 100 { return Err("too many deck entries".into()); }
        for _ in 0..entries {
            let id = reader.uint()?;
            let count = match fixed_count { Some(count) => count, None => reader.uint()? };
            if id == 0 || count == 0 || count > 100 || cards.insert(id, count).is_some() {
                return Err("invalid or duplicate deck card entry".into());
            }
            total_cards += count;
            if total_cards > 100 { return Err("deck exceeds 100-card parsing limit".into()); }
        }
    }
    // Legacy exports omit the sideboard flag. Explicit empty is also accepted.
    if reader.cursor < bytes.len() && reader.uint()? != 0 {
        return Err("sideboards are not supported yet".into());
    }
    if reader.cursor != bytes.len() { return Err("unexpected trailing deckstring data".into()); }
    if total_cards == 0 { return Err("deck contains no cards".into()); }
    Ok(Deck { format, hero_dbf_id, cards, total_cards })
}

pub fn target_profile() -> serde_json::Value {
    serde_json::from_str(include_str!("../config/decks/wild-rogue.json")).expect("validated target deck profile")
}

/// Explicit variants keep historical corpus identity separate from new decks.
pub fn profile_for_code(code: &str) -> Option<serde_json::Value> {
    let original = target_profile();
    let variant: serde_json::Value = serde_json::from_str(include_str!(
        "../config/decks/wild-rogue-nzoth-2026-10-29.json")).expect("validated Rogue variant");
    [original, variant].into_iter().find(|p| p["deck_code"].as_str() == Some(code.trim()))
}
