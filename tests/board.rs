use hearth_agent::board::BoardView;
use hearth_agent::export::board_json;
use hearth_agent::replay::{Entity, Game};

fn entity(id: u32, card_id: Option<&str>, tags: &[(&str, &str)]) -> Entity {
    Entity { id, card_id: card_id.map(str::to_string),
        tags: tags.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect() }
}

fn game() -> Game {
    let mut game = Game { game_entity: Some(1), ..Game::default() };
    game.players.insert(1, 2);
    game.players.insert(2, 3);
    game.entities.insert(1, entity(1, None, &[("TURN", "7")]));
    game.entities.insert(2, entity(2, None, &[("CURRENT_PLAYER", "1"), ("RESOURCES", "4")]));
    game.entities.insert(3, entity(3, None, &[("CURRENT_PLAYER", "0")]));
    game
}

#[test]
fn hidden_zones_never_export_cached_card_identity_or_stats() {
    let mut game = game();
    for (id, zone) in [(10, "HAND"), (11, "DECK"), (12, "SECRET")] {
        game.entities.insert(id, entity(id, Some("PRIVATE_CARD"), &[
            ("ZONE", zone), ("CONTROLLER", "1"), ("CARDTYPE", "SPELL"),
            ("ATK", "999"), ("COST", "888"), ("ZONE_POSITION", "2")]));
    }
    let board = BoardView::from_game(&game);
    let player = &board.players[0];
    assert_eq!(player.hand[0].position, Some(2));
    assert!(!player.hand[0].public_zone);
    assert_eq!(player.hand[0].card_type, None);
    assert_eq!(player.hand[0].cost, None);
    assert_eq!(player.observed_deck_count, 1);
    assert_eq!(player.observed_secret_count, 1);
    let json = board_json(&board);
    assert!(!json.contains("PRIVATE_CARD"));
    assert!(!json.contains("999"));
    assert!(!json.contains("888"));
}

#[test]
fn public_entities_are_ordered_with_unknown_positions_last() {
    let mut game = game();
    for (id, position) in [(10, "3"), (11, "1"), (12, "0"), (13, "1")] {
        game.entities.insert(id, entity(id, Some("PUBLIC_CARD"), &[
            ("ZONE", "PLAY"), ("CONTROLLER", "2"), ("CARDTYPE", "MINION"),
            ("ATK", "4"), ("HEALTH", "5"), ("ZONE_POSITION", position)]));
    }
    let board = BoardView::from_game(&game);
    let cards = &board.players[1].in_play;
    assert_eq!(cards.iter().map(|c| c.entity_id).collect::<Vec<_>>(), [11, 13, 10, 12]);
    assert_eq!(cards[0].attack, Some(4));
    assert_eq!(cards[0].health, Some(5));
    assert_eq!(cards[0].damage, None);
    assert_eq!(cards[0].exhausted, None);
    assert_eq!(cards[0].card_id, Some("PUBLIC_CARD"));
    assert!(board.players[0].in_play.is_empty());
}

#[test]
fn missing_and_invalid_numbers_remain_unknown_instead_of_zero() {
    let mut game = game();
    game.entities.get_mut(&2).unwrap().tags.insert("RESOURCES_USED".into(), "-1".into());
    game.entities.get_mut(&3).unwrap().tags.insert("RESOURCES".into(), "4294967296".into());
    let board = BoardView::from_game(&game);
    assert_eq!(board.players[0].resources, Some(4));
    assert_eq!(board.players[0].resources_used, None);
    assert_eq!(board.players[0].temporary_resources, None);
    assert_eq!(board.players[1].resources, None);
    assert_eq!(board.invalid_fields, 2);
    assert_eq!(board.turn, Some(7));
}

#[test]
fn hero_reference_requires_matching_owner_type_and_zone() {
    let mut game = game();
    game.entities.get_mut(&2).unwrap().tags.insert("HERO_ENTITY".into(), "10".into());
    game.entities.insert(10, entity(10, Some("HERO_01"), &[
        ("ZONE", "PLAY"), ("CONTROLLER", "1"), ("CARDTYPE", "HERO")]));
    assert_eq!(BoardView::from_game(&game).players[0].hero_entity, Some(10));
    for (tag, value) in [("CONTROLLER", "2"), ("CARDTYPE", "MINION"), ("ZONE", "HAND")] {
        let old = game.entities.get_mut(&10).unwrap().tags.insert(tag.into(), value.into()).unwrap();
        let board = BoardView::from_game(&game);
        assert_eq!(board.players[0].hero_entity, None);
        assert_eq!(board.invalid_fields, 1);
        game.entities.get_mut(&10).unwrap().tags.insert(tag.into(), old);
    }
    game.entities.get_mut(&10).unwrap().tags.insert("ZONE".into(), "GRAVEYARD".into());
    assert_eq!(BoardView::from_game(&game).players[0].hero_entity, Some(10));
}

#[test]
fn active_player_requires_unique_and_fully_observed_flags() {
    let mut game = game();
    assert_eq!(BoardView::from_game(&game).active_player, Some(1));
    for value in ["1", "2", "unknown"] {
        game.entities.get_mut(&3).unwrap().tags.insert("CURRENT_PLAYER".into(), value.into());
        assert_eq!(BoardView::from_game(&game).active_player, None);
    }
    game.entities.get_mut(&3).unwrap().tags.remove("CURRENT_PLAYER");
    assert_eq!(BoardView::from_game(&game).active_player, None);
}

#[test]
fn moving_public_card_to_hand_removes_identity_from_projection() {
    use hearth_agent::watch::StreamState;
    let mut stream = StreamState::default();
    for text in ["CREATE_GAME", "Player EntityID=2 PlayerID=1",
        "FULL_ENTITY - Creating ID=10 CardID=REVEALED_CARD", "tag=ZONE value=PLAY",
        "tag=CONTROLLER value=1", "tag=COST value=5"] {
        stream.feed(format!("D 00:00:00 GameState.DebugPrintPower() - {text}\n").as_bytes()).unwrap();
    }
    assert!(board_json(&BoardView::from_game(&stream.game().unwrap())).contains("REVEALED_CARD"));
    stream.feed(b"D 00:00:00 GameState.DebugPrintPower() - TAG_CHANGE Entity=10 tag=ZONE value=HAND\n").unwrap();
    let game = stream.game().unwrap();
    assert_eq!(game.entities[&10].card_id.as_deref(), Some("REVEALED_CARD"));
    let json = board_json(&BoardView::from_game(&game));
    assert!(!json.contains("REVEALED_CARD"));
    assert!(json.contains("\"cost\":null"));
}
