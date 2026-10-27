//! A neutral, typed projection of last-observed tags. No legal moves are inferred.
//! Hidden-zone cards are opaque even when an earlier reveal left cached tags.
use crate::replay::{Entity, Game};

#[derive(Debug, PartialEq, Eq)]
pub struct CardView<'a> {
    pub entity_id: u32,
    pub position: Option<u32>,
    pub public_zone: bool,
    pub card_id: Option<&'a str>,
    pub card_type: Option<&'static str>,
    pub cost: Option<u32>,
    pub attack: Option<u32>,
    pub health: Option<u32>,
    pub damage: Option<u32>,
    pub armor: Option<u32>,
    pub durability: Option<u32>,
    pub exhausted: Option<bool>,
}

#[derive(Debug, PartialEq, Eq)]
pub struct PlayerView<'a> {
    pub player_id: u32,
    pub entity_id: u32,
    pub current_player: Option<bool>,
    pub hero_entity: Option<u32>,
    pub resources: Option<u32>,
    pub resources_used: Option<u32>,
    pub temporary_resources: Option<u32>,
    pub in_play: Vec<CardView<'a>>,
    pub hand: Vec<CardView<'a>>,
    pub graveyard: Vec<CardView<'a>>,
    pub observed_deck_count: usize,
    pub observed_secret_count: usize,
}

#[derive(Debug, PartialEq, Eq)]
pub struct BoardView<'a> {
    pub players: Vec<PlayerView<'a>>,
    pub active_player: Option<u32>,
    pub turn: Option<u32>,
    pub invalid_fields: usize,
}

fn number(entity: &Entity, key: &str, invalid: &mut usize) -> Option<u32> {
    let value = entity.tag(key)?;
    match value.parse() {
        Ok(value) => Some(value),
        Err(_) => { *invalid += 1; None },
    }
}

fn flag(entity: &Entity, key: &str, invalid: &mut usize) -> Option<bool> {
    match entity.tag(key)? {
        "0" => Some(false),
        "1" => Some(true),
        _ => { *invalid += 1; None },
    }
}

fn card<'a>(entity: &'a Entity, visible: bool, invalid: &mut usize) -> CardView<'a> {
    let mut view = CardView {
        entity_id: entity.id,
        position: number(entity, "ZONE_POSITION", invalid).filter(|p| *p > 0),
        public_zone: visible,
        card_id: None, card_type: None, cost: None, attack: None, health: None,
        damage: None, armor: None, durability: None, exhausted: None,
    };
    if visible {
        view.card_id = entity.card_id.as_deref();
        view.card_type = match entity.tag("CARDTYPE") {
            Some("HERO") => Some("HERO"), Some("MINION") => Some("MINION"),
            Some("SPELL") => Some("SPELL"), Some("WEAPON") => Some("WEAPON"),
            Some("HERO_POWER") => Some("HERO_POWER"), Some("LOCATION") => Some("LOCATION"),
            Some("ENCHANTMENT") => Some("ENCHANTMENT"), _ => None,
        };
        view.cost = number(entity, "COST", invalid);
        view.attack = number(entity, "ATK", invalid);
        view.health = number(entity, "HEALTH", invalid);
        view.damage = number(entity, "DAMAGE", invalid);
        view.armor = number(entity, "ARMOR", invalid);
        view.durability = number(entity, "DURABILITY", invalid);
        view.exhausted = flag(entity, "EXHAUSTED", invalid);
    }
    view
}

impl<'a> BoardView<'a> {
    pub fn from_game(game: &'a Game) -> Self {
        let mut invalid = 0;
        let turn = game.game_entity.and_then(|id| game.entities.get(&id))
            .and_then(|entity| number(entity, "TURN", &mut invalid));
        let mut players = Vec::new();
        for (&player_id, &entity_id) in &game.players {
            let entity = game.entities.get(&entity_id);
            let hero = entity.and_then(|e| number(e, "HERO_ENTITY", &mut invalid));
            let hero_entity = hero.filter(|id| {
                let valid = game.entities.get(id).is_some_and(|e|
                    e.tag("CARDTYPE") == Some("HERO") && matches!(e.tag("ZONE"), Some("PLAY" | "GRAVEYARD"))
                    && e.tag("CONTROLLER").and_then(|v| v.parse::<u32>().ok()) == Some(player_id));
                if !valid { invalid += 1; }
                valid
            });
            players.push(PlayerView {
                player_id, entity_id, hero_entity,
                current_player: entity.and_then(|e| flag(e, "CURRENT_PLAYER", &mut invalid)),
                resources: entity.and_then(|e| number(e, "RESOURCES", &mut invalid)),
                resources_used: entity.and_then(|e| number(e, "RESOURCES_USED", &mut invalid)),
                temporary_resources: entity.and_then(|e| number(e, "TEMP_RESOURCES", &mut invalid)),
                in_play: Vec::new(), hand: Vec::new(), graveyard: Vec::new(),
                observed_deck_count: 0, observed_secret_count: 0,
            });
        }
        for entity in game.entities.values() {
            let controller = number(entity, "CONTROLLER", &mut invalid);
            let Some(player) = players.iter_mut().find(|p| Some(p.player_id) == controller) else { continue; };
            match entity.tag("ZONE") {
                Some("PLAY") => player.in_play.push(card(entity, true, &mut invalid)),
                Some("HAND") => player.hand.push(card(entity, false, &mut invalid)),
                Some("GRAVEYARD") => player.graveyard.push(card(entity, true, &mut invalid)),
                Some("DECK") => player.observed_deck_count += 1,
                Some("SECRET") => player.observed_secret_count += 1,
                _ => {},
            }
        }
        for player in &mut players {
            // Unknown positions sort after known positions; ties resolve by stable entity ID.
            for cards in [&mut player.in_play, &mut player.hand, &mut player.graveyard] {
                cards.sort_by_key(|c| (c.position.is_none(), c.position, c.entity_id));
            }
        }
        let current: Vec<_> = players.iter().filter(|p| p.current_player == Some(true)).collect();
        let active_player = if current.len() == 1 && players.iter().all(|p| p.current_player.is_some()) {
            Some(current[0].player_id)
        } else { None };
        Self { players, active_player, turn, invalid_fields: invalid }
    }
}
