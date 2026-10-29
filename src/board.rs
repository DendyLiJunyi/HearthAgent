//! Typed last-observed tags. No legal moves or fresh/complete state are inferred.
//! Only an identified local player's hand may expose observed card information.
use crate::replay::{Entity, Game};

/// Last-observed combat tags, not a reconstructed rules engine. In particular,
/// missing flags are unknown and silence does not synthesize other flag values.
#[derive(Default, Debug, PartialEq, Eq, serde::Serialize)]
pub struct CombatView {
    pub taunt: Option<bool>,
    pub divine_shield: Option<bool>,
    pub stealth: Option<bool>,
    pub frozen: Option<bool>,
    pub charge: Option<bool>,
    pub rush: Option<bool>,
    pub windfury: Option<bool>,
    pub poisonous: Option<bool>,
    pub lifesteal: Option<bool>,
    pub silenced: Option<bool>,
    pub cant_be_damaged: Option<bool>,
    pub cant_attack: Option<bool>,
    pub cant_attack_heroes: Option<bool>,
    pub attacks_this_turn: Option<u32>,
}

#[derive(Debug, PartialEq, Eq)]
pub struct CardView<'a> {
    pub entity_id: u32,
    pub position: Option<u32>,
    pub public_zone: bool,
    pub card_id: Option<&'a str>,
    pub card_type: Option<&'static str>,
    pub cost: Option<u32>,
    pub cost_resource: Option<&'static str>,
    pub attack: Option<u32>,
    pub health: Option<u32>,
    pub damage: Option<u32>,
    pub armor: Option<u32>,
    pub durability: Option<u32>,
    pub exhausted: Option<bool>,
    pub combat: CombatView,
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
    pub perspective: Option<u32>,
    pub perspective_source: Option<&'static str>,
    pub perspective_conflicting: bool,
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

pub(crate) fn card<'a>(entity: &'a Entity, public_zone: bool, visible: bool, invalid: &mut usize) -> CardView<'a> {
    let mut view = CardView {
        entity_id: entity.id,
        position: number(entity, "ZONE_POSITION", invalid).filter(|p| *p > 0),
        public_zone,
        card_id: None, card_type: None, cost: None, cost_resource: None, attack: None, health: None,
        damage: None, armor: None, durability: None, exhausted: None,
        combat: CombatView::default(),
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
        view.cost_resource = match entity.tag("CARD_ALTERNATE_COST") {
            None => None,
            Some("0") => Some("mana"), Some("1") => Some("health"),
            Some("2") => Some("armor"), Some("3") => Some("corpses"),
            Some("4") => Some("opponents_health"), Some("5") => Some("alt_tavern_coin"),
            Some(_) => { *invalid += 1; None },
        };
        view.attack = number(entity, "ATK", invalid);
        view.health = number(entity, "HEALTH", invalid);
        view.damage = number(entity, "DAMAGE", invalid);
        view.armor = number(entity, "ARMOR", invalid);
        view.durability = number(entity, "DURABILITY", invalid);
        view.exhausted = flag(entity, "EXHAUSTED", invalid);
        view.combat = CombatView {
            taunt: flag(entity, "TAUNT", invalid),
            divine_shield: flag(entity, "DIVINE_SHIELD", invalid),
            stealth: flag(entity, "STEALTH", invalid),
            frozen: flag(entity, "FROZEN", invalid),
            charge: flag(entity, "CHARGE", invalid),
            rush: flag(entity, "RUSH", invalid),
            windfury: flag(entity, "WINDFURY", invalid),
            poisonous: flag(entity, "POISONOUS", invalid),
            lifesteal: flag(entity, "LIFESTEAL", invalid),
            silenced: flag(entity, "SILENCED", invalid),
            cant_be_damaged: flag(entity, "CANT_BE_DAMAGED", invalid),
            cant_attack: flag(entity, "CANT_ATTACK", invalid),
            cant_attack_heroes: flag(entity, "CANT_ATTACK_HEROES", invalid),
            attacks_this_turn: number(entity, "NUM_ATTACKS_THIS_TURN", invalid),
        };
    }
    view
}

impl<'a> BoardView<'a> {
    pub fn from_game(game: &'a Game) -> Self {
        let perspective = game.perspective.player_id();
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
                Some("PLAY") => player.in_play.push(card(entity, true, true, &mut invalid)),
                Some("HAND") => {
                    let visible = perspective == Some(player.player_id)
                        && entity.card_id.as_deref().is_some_and(|id| !id.is_empty());
                    player.hand.push(card(entity, false, visible, &mut invalid));
                },
                Some("GRAVEYARD") => player.graveyard.push(card(entity, true, true, &mut invalid)),
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
        Self { perspective, perspective_source: game.perspective.source(), perspective_conflicting: game.perspective.conflicting,
            players, active_player, turn, invalid_fields: invalid }
    }
}
