from __future__ import annotations

import os
import sys

# Ensure imports work when this script is executed directly or as a Kaggle raw agent.
sys.path.insert(0, os.getcwd())

import player1

EARLY_GAME_TURNS = 80
MID_GAME_TURNS = 250
TERMINAL_PHASE_START = 440


def _nearest_enemy_distance(obs) -> float:
    if not bool(obs.owned.any()):
        return float("inf")
    enemy_planets = obs.is_enemy
    if not bool(enemy_planets.any()):
        return float("inf")

    my_x = obs.x[obs.owned].unsqueeze(-1)
    my_y = obs.y[obs.owned].unsqueeze(-1)
    enemy_x = obs.x[enemy_planets].unsqueeze(0)
    enemy_y = obs.y[enemy_planets].unsqueeze(0)
    dx = my_x - enemy_x
    dy = my_y - enemy_y
    dist = (dx * dx + dy * dy).sqrt()
    return float(dist.min().item())


def _enemy_fleet_threat(obs) -> tuple[int, float]:
    enemy_fleets = obs.f_alive & (obs.f_owner >= 0.0) & (obs.f_owner != float(obs.player_id))
    if not bool(enemy_fleets.any()):
        return 0, 0.0
    count = int(enemy_fleets.sum().item())
    ships = float(obs.f_ships[enemy_fleets].sum().item())
    return count, ships


def _config_for_state(player_count: int, obs) -> player1.ProducerLiteConfig:
    base = player1.CONFIG_4P if int(player_count) >= 4 else player1.ProducerLiteConfig()
    if obs is None:
        return base

    alive_planets = obs.alive
    my_ships = float(obs.ships[obs.owned & alive_planets].sum().item())
    total_ships = float(obs.ships[alive_planets].sum().item())
    my_share = my_ships / max(total_ships, 1.0)

    neutral_planets = int(obs.is_neutral[alive_planets].sum().item())
    enemy_planets = int(obs.is_enemy[alive_planets].sum().item())
    owned_planets = int(obs.owned[alive_planets].sum().item())
    enemy_fleets, enemy_fleet_ships = _enemy_fleet_threat(obs)
    enemy_distance = _nearest_enemy_distance(obs)

    step = int(obs.step.item())
    early_game = step < EARLY_GAME_TURNS
    terminal_phase = step >= TERMINAL_PHASE_START
    strong_lead = my_share > 0.62 or owned_planets >= enemy_planets + 2
    behind = my_share < 0.32 or owned_planets + 1 < enemy_planets
    many_neutrals = neutral_planets >= 6
    enemy_force = enemy_fleet_ships > my_ships * 0.3

    if early_game:
        base = player1.dataclasses.replace(
            base,
            roi_threshold=0.92,
            max_waves_per_turn=16,
            max_offensive_targets=16,
            max_defensive_targets=4,
            min_ships_to_launch=1.4,
            max_sources_per_lane=14,
            regroup_pressure_norm="none",
        )
    elif terminal_phase:
        base = player1.dataclasses.replace(
            base,
            roi_threshold=1.25,
            max_waves_per_turn=16,
            max_offensive_targets=16,
            max_defensive_targets=3,
            min_ships_to_launch=1.0,
            enable_regroup=False,
            max_sources_per_lane=14,
        )
    elif strong_lead:
        base = player1.dataclasses.replace(
            base,
            roi_threshold=2.0,
            max_waves_per_turn=14,
            max_offensive_targets=14,
            max_defensive_targets=4,
            min_ships_to_launch=3.0,
            regroup_pressure_norm="none",
        )
    elif behind:
        base = player1.dataclasses.replace(
            base,
            roi_threshold=1.0,
            max_waves_per_turn=16,
            max_offensive_targets=14,
            max_defensive_targets=8,
            min_ships_to_launch=1.2,
            regroup_pressure_norm="l2",
            regroup_time_penalty_weight=5e-4,
            max_sources_per_lane=14,
        )
    else:
        base = player1.dataclasses.replace(
            base,
            roi_threshold=1.05,
            max_waves_per_turn=14,
            max_offensive_targets=14,
            max_defensive_targets=5,
            min_ships_to_launch=1.6,
            max_sources_per_lane=14,
        )

    if many_neutrals and early_game:
        base = player1.dataclasses.replace(
            base,
            roi_threshold=0.9,
            max_offensive_targets=16,
            max_waves_per_turn=16,
            min_ships_to_launch=1.2,
        )

    if enemy_planets >= owned_planets and neutral_planets < 3:
        base = player1.dataclasses.replace(
            base,
            max_defensive_targets=max(base.max_defensive_targets, 8),
            roi_threshold=max(base.roi_threshold, 1.05),
            min_ships_to_launch=max(base.min_ships_to_launch, 1.6),
        )

    if enemy_force and enemy_distance < 18.0:
        base = player1.dataclasses.replace(
            base,
            max_defensive_targets=max(base.max_defensive_targets, 9),
            min_ships_to_launch=max(base.min_ships_to_launch, 1.4),
            regroup_pressure_norm="l2",
            regroup_time_penalty_weight=5e-4,
        )

    if my_share > 0.65 and not terminal_phase:
        base = player1.dataclasses.replace(
            base,
            roi_threshold=max(base.roi_threshold, 2.2),
            max_offensive_targets=max(base.max_offensive_targets, 14),
            max_waves_per_turn=max(base.max_waves_per_turn, 16),
            min_ships_to_launch=max(base.min_ships_to_launch, 3.0),
        )

    return base


# Patch player1 so its runtime uses this adaptive config function.
player1._config_for_state = _config_for_state


def agent(obs):
    player1._config_for_state = _config_for_state
    return player1.agent(obs)
