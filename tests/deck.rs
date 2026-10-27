use base64::{engine::general_purpose::STANDARD, Engine};
use hearth_agent::deck::{decode, target_profile};

#[test]
fn user_deck_and_pinned_card_profile_agree() {
    let profile = target_profile();
    let deck = decode(profile["deck_code"].as_str().unwrap()).unwrap();
    assert_eq!(deck.format, "wild");
    assert_eq!(deck.hero_dbf_id, 71062);
    assert_eq!(deck.total_cards, 30);
    assert_eq!(deck.cards.len(), 18);
    assert_eq!(deck.cards.values().filter(|&&n| n == 1).count(), 6);
    for card in profile["cards"].as_array().unwrap() {
        let id = card["dbfId"].as_u64().unwrap() as u32;
        assert_eq!(deck.cards[&id], card["count"].as_u64().unwrap() as u32);
        assert!(!card["required_features"].as_array().unwrap().is_empty());
        assert_eq!(card["simulation_supported"], false);
    }
}

#[test]
fn malformed_or_unsupported_decks_are_rejected_without_guessing() {
    for bytes in [
        vec![], vec![0, 2], // version
        vec![0, 1, 4, 1, 1, 1, 2, 0, 0, 0], // format
        vec![0, 1, 1, 2, 1, 1, 2, 0, 0, 0], // heroes
        vec![0, 1, 1, 1, 1, 1, 2, 1, 2, 0, 0], // duplicate card
        vec![0, 1, 1, 1, 1, 0, 0, 1, 2, 0, 0], // zero copies
        vec![0, 1, 1, 1, 1, 0, 0, 0, 0], // empty
        vec![0, 1, 1, 1, 1, 1, 2, 0, 0, 1], // sideboard
        vec![0, 1, 1, 1, 1, 1, 2, 0, 0, 0, 7], // trailing data
        vec![0, 1, 1, 1, 255, 255, 255, 255, 31], // overflow
        vec![0, 1, 1, 1, 129, 0], // redundant varint
        vec![0, 1, 1, 1, 128], // incomplete varint
    ] {
        assert!(decode(&STANDARD.encode(&bytes)).is_err(), "{bytes:?}");
    }
    assert!(decode("invalid base64").is_err());
    assert!(decode(&"A".repeat(4097)).is_err());
}

#[test]
fn legacy_no_sideboard_flag_and_explicit_empty_flag_match() {
    let legacy = [0, 1, 1, 1, 1, 1, 2, 0, 0];
    let mut explicit = legacy.to_vec();
    explicit.push(0);
    assert_eq!(decode(&STANDARD.encode(legacy)), decode(&STANDARD.encode(explicit)));
}
