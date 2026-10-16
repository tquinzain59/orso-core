"""KAN-96 — statut commercial OPS : ligne d'abonnement choisie par règle, origine lisible,
écarts statut client / abonnement / conteneur signalés.

Les données reproduisent celles du ticket (financia-solutions : 3 lignes ACTIVE, CANCELED,
CANCELED sans identifiant Stripe ; nexis-solutions : 1 ligne CANCELED avec ids Stripe).
"""

from __future__ import annotations

import itertools
from unittest.mock import patch

from olympe.ops_manager import OpsManager
from olympe.subscription_status import (
    build_subscription_origin,
    compute_divergences,
    pick_representative_subscription,
)

FINANCIA_ROWS = [
    {"id": "sub-f1", "status": "ACTIVE", "created_at": "2026-09-28T07:41:00+00:00", "updated_at": "2026-10-03T15:32:00+00:00",
     "stripe_customer_id": None, "stripe_subscription_id": None},
    {"id": "sub-f2", "status": "CANCELED", "created_at": "2026-10-03T12:36:00+00:00", "updated_at": "2026-10-03T15:26:00+00:00",
     "stripe_customer_id": None, "stripe_subscription_id": None},
    {"id": "sub-f3", "status": "CANCELED", "created_at": "2026-10-03T15:27:00+00:00", "updated_at": "2026-10-03T15:36:00+00:00",
     "stripe_customer_id": None, "stripe_subscription_id": None},
]
NEXIS_ROWS = [
    {"id": "sub-n1", "status": "CANCELED", "created_at": "2026-09-27T16:37:00+00:00", "updated_at": "2026-10-03T11:43:00+00:00",
     "stripe_customer_id": "cus_VNBiZ1b73JkcCn", "stripe_subscription_id": "sub_1UMRLA06XM8Z6gbS523z0HNT"},
]


def _tenant(slug, status, instance_status, subs):
    return {
        "id": f"t-{slug}", "slug": slug, "name": slug, "status": status,
        "created_at": "2026-09-27T00:00:00+00:00",
        "profiles": [], "tenant_instances": [{"status": instance_status}],
        "agent_instances": [], "subscriptions": subs,
    }


def _overview(tenants):
    ops = OpsManager(supabase_url="http://supabase.invalid", supabase_key="k", demo_mode=True)
    with patch.object(ops, "_query_supabase", return_value=tenants), \
            patch.object(ops, "_fetch_supabase_auth_users", return_value={}), \
            patch.object(ops, "_db_list_tenants", return_value=[]):
        return {t["slug"]: t for t in ops.get_tenants_overview()}


def test_selection_is_independent_of_input_order():
    """CA1 : toute permutation des lignes donne la même ligne retenue (la plus récente)."""
    picked = {pick_representative_subscription(list(p))["id"] for p in itertools.permutations(FINANCIA_ROWS)}
    assert picked == {"sub-f3"}


def test_selection_handles_missing_dates_and_ties():
    rows = [
        {"id": "b", "created_at": None},
        {"id": "a", "created_at": "garbage"},
        {"id": "c", "created_at": "2026-10-01T00:00:00Z"},
    ]
    assert pick_representative_subscription(rows)["id"] == "c"
    tie = [{"id": "x", "created_at": "2026-10-01T00:00:00Z"}, {"id": "y", "created_at": "2026-10-01T00:00:00Z"}]
    assert pick_representative_subscription(tie)["id"] == pick_representative_subscription(tie[::-1])["id"]
    assert pick_representative_subscription([]) is None


def test_overview_is_stable_across_reads_and_row_order():
    """CA1 : deux lectures successives, lignes dans deux ordres, donnent le même abonnement."""
    forward = _overview([_tenant("financia-solutions", "active", "ready", list(FINANCIA_ROWS))])
    backward = _overview([_tenant("financia-solutions", "active", "ready", FINANCIA_ROWS[::-1])])
    assert forward["financia-solutions"]["subscription"] == backward["financia-solutions"]["subscription"]
    assert forward["financia-solutions"]["subscription"]["id"] == "sub-f3"


def test_financia_status_contradiction_is_stated_with_origin():
    """CA2/CA3/CA5 : client active + abonnement annulé + conteneur en ligne → écarts écrits, origine lisible."""
    sub = _overview([_tenant("financia-solutions", "active", "ready", FINANCIA_ROWS)])["financia-solutions"]["subscription"]
    assert sub["status"] == "canceled"
    origin = sub["origin"]
    assert origin["subscription_id"] == "sub-f3"
    assert origin["created_at"] == "2026-10-03T15:27:00+00:00"
    assert origin["stripe_counterpart"] == "absent"
    assert origin["rows_total"] == 3 and origin["rows_by_status"] == {"active": 1, "canceled": 2}
    codes = {d["code"] for d in sub["divergences"]}
    assert codes == {"tenant_vs_subscription", "container_running_while_canceled"}


def test_nexis_trial_put_to_sleep_by_unbacked_cancellation_is_stated():
    """CA3/CA5 : client trial endormi par une annulation dont les ids Stripe sont seulement enregistrés."""
    sub = _overview([_tenant("nexis-solutions", "trial", "sleeping", NEXIS_ROWS)])["nexis-solutions"]["subscription"]
    assert sub["origin"]["stripe_counterpart"] == "recorded"
    assert sub["origin"]["stripe_subscription_id"] == "sub_1UMRLA06XM8Z6gbS523z0HNT"
    codes = {d["code"] for d in sub["divergences"]}
    assert codes == {"tenant_vs_subscription", "container_sleeping_after_cancellation"}


def test_coherent_client_has_no_divergence():
    row = [{"id": "s", "status": "ACTIVE", "created_at": "2026-10-01T00:00:00Z"}]
    origin = build_subscription_origin(row[0], row)
    assert compute_divergences("active", "active", "ready", origin) == []
    assert compute_divergences("churn", "canceled", "sleeping", origin) == []
