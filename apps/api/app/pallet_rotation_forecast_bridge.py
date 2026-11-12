"""Bridge historical hourly profiles into product-specific pallet portfolio inputs.

This module is deliberately pure: it derives planning evidence but does not query
inventory, reserve pallets, create tasks, or move stock.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from app.pallet_rotation_windows import recommend_low_traffic_window


def enrich_pallet_candidates_with_hourly_profiles(
    candidates: Iterable[Mapping[str, Any]],
    profiles_by_product: Mapping[int, list[Mapping[str, Any]]],
    *,
    current_hour: int,
    duration_hours: int = 1,
    minimum_observed_days: int = 7,
) -> dict[str, Any]:
    """Attach SKU-specific low-traffic and consumption evidence to each pallet.

    Candidates must contain product_id and residual_base_units. Profiles are
    keyed by product_id and must contain the full 24-hour historical profile.
    Incomplete evidence is preserved as UNKNOWN/None; it is never treated as 0.
    """
    enriched = []
    excluded = 0
    for candidate in candidates:
        row = dict(candidate)
        product_id = row.get("product_id")
        residual = row.get("residual_base_units")
        if isinstance(product_id, bool) or not isinstance(product_id, int) or product_id <= 0:
            row["traffic_level"] = "UNKNOWN"
            row["forecast_consumption_until_low_traffic"] = None
            row["planning_reason"] = "INVALID_PRODUCT_ID"
            excluded += 1
            enriched.append(row)
            continue
        profile = profiles_by_product.get(product_id)
        if profile is None:
            row["traffic_level"] = "UNKNOWN"
            row["forecast_consumption_until_low_traffic"] = None
            row["planning_reason"] = "HOURLY_PROFILE_MISSING"
            excluded += 1
            enriched.append(row)
            continue
        try:
            decision = recommend_low_traffic_window(
                profile,
                current_hour=current_hour,
                duration_hours=duration_hours,
                residual_base_units=residual,
                minimum_observed_days=minimum_observed_days,
            )
        except (TypeError, ValueError):
            row["traffic_level"] = "UNKNOWN"
            row["forecast_consumption_until_low_traffic"] = None
            row["planning_reason"] = "HOURLY_PROFILE_INVALID"
            excluded += 1
            enriched.append(row)
            continue

        row["planning_recommendation"] = decision.recommendation
        row["planning_reason"] = decision.reason_code
        row["recommended_window_start_hour"] = decision.start_hour
        if decision.recommendation == "INSUFFICIENT_DATA":
            row["traffic_level"] = "UNKNOWN"
            row["forecast_consumption_until_low_traffic"] = None
            row["current_hour_average_customers"] = None
            row["daily_hourly_average_customers"] = None
            row["planning_evidence"] = {
                "observed_sales_days_min": decision.observed_sales_days_min,
                "observed_traffic_days_min": decision.observed_traffic_days_min,
                "historical_profile_only": True,
            }
            excluded += 1
            enriched.append(row)
            continue

        traffic_by_hour = {
            int(item["hour_of_day"]): float(item["average_customers"])
            for item in profile
        }
        traffic_values = list(traffic_by_hour.values())
        current_traffic = traffic_by_hour[current_hour]
        daily_hourly_average = sum(traffic_values) / len(traffic_values)
        row["traffic_level"] = (
            "LOW" if current_traffic <= daily_hourly_average
            else "HIGH"
        )
        row["current_hour_average_customers"] = current_traffic
        row["daily_hourly_average_customers"] = round(daily_hourly_average, 3)
        row["forecast_consumption_until_low_traffic"] = (
            decision.projected_consumption_through_window
        )
        row["planning_evidence"] = {
            "observed_sales_days_min": decision.observed_sales_days_min,
            "observed_traffic_days_min": decision.observed_traffic_days_min,
            "historical_profile_only": True,
        }
        if row["forecast_consumption_until_low_traffic"] is None:
            excluded += 1
        enriched.append(row)

    return {
        "candidates": enriched,
        "candidate_count": len(enriched),
        "without_sufficient_profile": excluded,
        "source": "HISTORICAL_PRODUCT_HOURLY_SALES_AND_STORE_TRAFFIC",
        "automatic_stock_movement_allowed": False,
    }
