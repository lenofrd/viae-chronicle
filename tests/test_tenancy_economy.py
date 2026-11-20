from vale.core.config_loader import load_config
from vale.core.event_log import EventLog
from vale.core.world import World
from vale.core.state import HouseholdState, LandParcelState, BuildingState
from vale.modules.tenancy_economy import (
    create_land_lease, settle_land_rent, settle_household_trade,
    deposit_shared_storage, withdraw_shared_storage,
    enqueue_service_request, process_service_queue,
)

def _world():
    cfg = load_config("brookvale-town-001")
    w = World(cfg.world.world_id, EventLog(":memory:"), config=cfg)
    w.state.households["a"] = HouseholdState(household_id="a", member_ids=["a1"], head_id="a1", home_node="common_district", work_node="east_field", formed_tick=0, coin=50, grain=20)
    w.state.households["b"] = HouseholdState(household_id="b", member_ids=["b1"], head_id="b1", home_node="poor_district", work_node="west_field", formed_tick=0, coin=30, grain=5)
    w.state.land_parcels["p"] = LandParcelState(parcel_id="p", spatial_node_id="east_field", land_use="farmland_irrigated", area=1, owner_type="household", owner_id="a", created_tick=0)
    w.state.buildings["s"] = BuildingState(building_id="s", parcel_id="p", building_type="storehouse", owner_type="household", owner_id="a", footprint_area=1, created_tick=0, attributes={"storage_capacity":100, "shared_with_household_ids":["b"]})
    return w

def test_lease_separates_tenure_and_collects_rent():
    w = _world()
    create_land_lease(w, "l1", parcel_id="p", lessor_household_id="a", lessee_household_id="b", rent_per_period=4, deposit=3, period_days=5, duration_days=20)
    assert w.state.land_parcels["p"].owner_id == "a"
    assert w.state.land_parcels["p"].use_rights[0].holder_id == "b"
    assert w.state.households["b"].coin == 27
    w.current_tick = 5
    assert settle_land_rent(w, "l1")
    assert w.state.households["a"].coin == 54
    assert w.state.households["b"].coin == 23

def test_trade_conserves_goods_and_payment():
    w = _world()
    total_g, total_c = w.state.households["a"].grain+w.state.households["b"].grain, w.state.households["a"].coin+w.state.households["b"].coin
    settle_household_trade(w, "t1", seller_household_id="a", buyer_household_id="b", item="grain", quantity=5, unit_price=2)
    assert w.state.households["a"].grain+w.state.households["b"].grain == total_g
    assert w.state.households["a"].coin+w.state.households["b"].coin == total_c

def test_shared_storehouse_respects_depositor_balance():
    w = _world()
    deposit_shared_storage(w, "s", "b", item="grain", quantity=4)
    assert w.state.households["b"].grain == 1
    withdraw_shared_storage(w, "s", "b", item="grain", quantity=2)
    assert w.state.households["b"].grain == 3
    import pytest
    with pytest.raises(ValueError):
        withdraw_shared_storage(w, "s", "a", item="grain", quantity=1)

def test_service_queue_is_fifo_with_wait_estimates():
    w = _world()
    assert enqueue_service_request(w, "r1", node_id="well", service="water", household_id="a", requested_units=2)["position"] == 1
    assert enqueue_service_request(w, "r2", node_id="well", service="water", household_id="b", requested_units=2)["estimated_wait_ticks"] == 1
    w.current_tick = 1
    served = process_service_queue(w, node_id="well", service="water", capacity_units=3)
    assert served[0]["request_id"] == "r1" and served[0]["units"] == 2
    assert served[1]["request_id"] == "r2" and served[1]["units"] == 1
    assert served[1]["wait_ticks"] == 1

def test_arrears_can_be_cured_and_expired_lease_releases_right():
    w = _world()
    w.state.households["b"].coin = 0
    create_land_lease(w, "l2", parcel_id="p", lessor_household_id="a",
                      lessee_household_id="b", rent_per_period=4, deposit=0,
                      period_days=2, duration_days=6)
    w.current_tick = 2
    assert not settle_land_rent(w, "l2")
    assert w.state.land_leases["l2"]["status"] == "arrears"
    w.state.households["b"].coin = 8
    w.current_tick = 4
    assert settle_land_rent(w, "l2")
    assert w.state.land_leases["l2"]["status"] == "active"

def test_collective_lease_pays_village_treasury():
    w = _world()
    parcel = w.state.land_parcels["p"]
    parcel.owner_type, parcel.owner_id = "collective", "village"
    from vale.core.state import CouncilDecisionState
    w.state.council_decisions["d"] = CouncilDecisionState(
        decision_id="d", subject="lease:p:b", proposer_agent_id="a1",
        status="approved", created_tick=0,
    )
    create_land_lease(w, "public-lease", parcel_id="p", lessor_household_id="village",
                      lessee_household_id="b", rent_per_period=2, deposit=0,
                      period_days=1, duration_days=3, council_decision_id="d")
    w.current_tick = 1
    assert settle_land_rent(w, "public-lease")
    assert w.state.public_treasury["coin"] == 2

def test_rent_arrears_accumulate_by_period_and_are_cleared_when_paid():
    w = _world()
    w.state.households["b"].coin = 0
    create_land_lease(w, "arrears", parcel_id="p", lessor_household_id="a",
                      lessee_household_id="b", rent_per_period=4, period_days=2,
                      duration_days=12)
    w.current_tick = 2
    assert not settle_land_rent(w, "arrears")
    assert w.state.land_leases["arrears"]["arrears_amount"] == 4
    w.current_tick = 4
    assert not settle_land_rent(w, "arrears")
    assert w.state.land_leases["arrears"]["arrears_amount"] == 8
    w.state.households["b"].coin = 12
    w.current_tick = 6
    assert settle_land_rent(w, "arrears")
    assert w.state.households["b"].coin == 0
    assert w.state.households["a"].coin == 62
    assert w.state.land_leases["arrears"]["arrears_amount"] == 0

def test_in_kind_resource_loan_tracks_partial_repayment():
    from vale.modules.tenancy_economy import lend_household_goods, repay_household_goods
    w = _world()
    loan = lend_household_goods(w, "grain-loan", lender_household_id="a",
        borrower_household_id="b", item="grain", quantity=5,
        repayment_quantity=6, due_tick=10)
    assert w.state.households["a"].grain == 15
    assert w.state.households["b"].grain == 10
    repay_household_goods(w, "grain-loan", quantity=2)
    assert loan["repaid"] == 2
    assert loan["status"] == "active"
    repay_household_goods(w, "grain-loan", quantity=4)
    assert loan["status"] == "repaid"
    assert w.state.households["a"].grain == 21
    assert w.state.households["b"].grain == 4

def test_resource_loan_becomes_overdue_once():
    from vale.modules.tenancy_economy import lend_household_goods, settle_due_resource_loans
    w = _world()
    lend_household_goods(w, "late", lender_household_id="a", borrower_household_id="b",
                         item="grain", quantity=2, repayment_quantity=2, due_tick=1)
    w.current_tick = 2
    assert settle_due_resource_loans(w) == ["late"]
    assert settle_due_resource_loans(w) == []
    assert w.state.resource_loans["late"]["status"] == "overdue"

def test_lease_expiry_refunds_escrowed_deposit():
    from vale.modules.tenancy_economy import settle_due_leases
    w = _world()
    create_land_lease(w, "deposit", parcel_id="p", lessor_household_id="a",
                      lessee_household_id="b", rent_per_period=2, deposit=5,
                      period_days=2, duration_days=4)
    assert w.state.households["b"].coin == 25
    w.current_tick = 4
    settle_due_leases(w)
    assert w.state.households["b"].coin == 26
    assert w.state.land_leases["deposit"]["status"] == "expired"
    assert not w.state.land_parcels["p"].use_rights

def test_lease_deposit_offsets_unpaid_rent_on_termination():
    from vale.modules.tenancy_economy import terminate_land_lease
    w = _world()
    create_land_lease(w, "deposit-arrears", parcel_id="p", lessor_household_id="a",
                      lessee_household_id="b", rent_per_period=4, deposit=3,
                      period_days=2, duration_days=10)
    w.state.households["b"].coin = 0
    w.current_tick = 2
    assert not settle_land_rent(w, "deposit-arrears")
    terminate_land_lease(w, "deposit-arrears", reason="default")
    assert w.state.households["b"].coin == 0
    assert w.state.households["a"].coin == 53
    assert w.state.land_leases["deposit-arrears"]["outstanding_arrears"] == 1

def test_lease_renewal_extends_use_right_and_can_reprice():
    from vale.modules.tenancy_economy import renew_land_lease
    w = _world()
    create_land_lease(w, "renew", parcel_id="p", lessor_household_id="a",
                      lessee_household_id="b", rent_per_period=2, period_days=5, duration_days=20)
    renewed = renew_land_lease(w, "renew", additional_days=30, new_rent_per_period=3)
    assert renewed["expires_tick"] == 50
    assert renewed["rent_per_period"] == 3
    assert w.state.land_parcels["p"].use_rights[0].expires_tick == 50
