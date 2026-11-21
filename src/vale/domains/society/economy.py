"""Land leasing, household commerce, shared storage and FIFO public queues."""
from __future__ import annotations
from copy import deepcopy
from vale.domains.society.state import LandRightState
from vale.core.world import PHASE_SOCIETY

def _household(world, household_id):
    household = world.state.human.households.get(household_id)
    if household is None:
        raise ValueError(f"unknown household: {household_id}")
    return household

def create_land_lease(world, lease_id, *, parcel_id, lessor_household_id,
                      lessee_household_id, rent_per_period, deposit=0.0,
                      period_days=30, duration_days=360, rent_item="coin",
                      council_decision_id=None, maintenance_responsibility="lessee"):
    """Lease a parcel while preserving ownership; collective land needs council approval."""
    if lease_id in world.state.human.land_leases or rent_item not in {"coin", "grain"}:
        raise ValueError("duplicate lease id or unsupported rent item")
    if rent_per_period < 0 or deposit < 0 or period_days < 1 or duration_days < 1 or maintenance_responsibility not in {"lessor", "lessee", "shared"}:
        raise ValueError("invalid lease terms")
    parcel = world.state.human.land_parcels.get(parcel_id)
    lessee = _household(world, lessee_household_id)
    lessor = None if (parcel is not None and parcel.owner_type == "collective") else _household(world, lessor_household_id)
    if parcel is None or parcel.contested or parcel.owner_type == "protected":
        raise ValueError("parcel is unavailable for lease")
    if lessor_household_id == lessee_household_id:
        raise ValueError("a household cannot lease land to itself")
    if parcel.owner_type == "household" and parcel.owner_id != lessor_household_id:
        raise ValueError("lessor does not own this parcel")
    if parcel.owner_type == "collective":
        if lessor_household_id != "village":
            raise ValueError("collective land rent must be paid to the village treasury")
        decision = world.state.human.council_decisions.get(council_decision_id or "")
        if decision is None or decision.status != "approved" or decision.subject != f"lease:{parcel_id}:{lessee_household_id}":
            raise ValueError("collective lease requires its matching approved council decision")
    elif parcel.owner_type != "household":
        raise ValueError("parcel ownership does not permit leasing")
    if getattr(lessee, rent_item) < deposit:
        raise ValueError("lessee cannot fund the deposit")
    start, end = world.current_tick, world.current_tick + duration_days
    lease = {
        "lease_id": lease_id, "parcel_id": parcel_id,
        "lessor_household_id": lessor_household_id, "lessee_household_id": lessee_household_id,
        "rent_item": rent_item, "rent_per_period": float(rent_per_period),
        "deposit": float(deposit), "period_days": period_days,
        "start_tick": start, "expires_tick": end, "next_due_tick": start + period_days,
        "status": "active", "last_paid_tick": start, "council_decision_id": council_decision_id,
        "maintenance_responsibility": maintenance_responsibility,
    }
    after = round(getattr(lessee, rent_item) - deposit, 2)
    right = LandRightState(
        right_id=f"lease:{lease_id}", holder_type="household", holder_id=lessee_household_id,
        right_type="lease", purpose=parcel.land_use, granted_tick=start, expires_tick=end,
    )
    world.event_log.append(start, "land_lease_created", {
        "lease": lease, "land_right": right.model_dump(mode="json"),
        "lessee_household_id": lessee_household_id, "deposit_item": rent_item,
        "lessee_inventory_after": {rent_item: after},
    })
    setattr(lessee, rent_item, after)
    world.state.human.land_leases[lease_id] = lease
    parcel.use_rights.append(right)
    return lease

def settle_land_rent(world, lease_id):
    lease = world.state.human.land_leases.get(lease_id)
    if lease is None or lease["status"] not in {"active", "arrears"} or world.current_tick < lease["next_due_tick"]:
        return False
    lessee = _household(world, lease["lessee_household_id"])
    lessor = None if lease["lessor_household_id"] == "village" else _household(world, lease["lessor_household_id"])
    item = lease["rent_item"]
    amount = float(lease["rent_per_period"])
    amount_due = round(amount + float(lease.get("arrears_amount", 0.0)), 2)
    paid = getattr(lessee, item) + 1e-9 >= amount_due
    after = dict(lease)
    inventories = {lessee.household_id: {item: round(getattr(lessee, item) - (amount_due if paid else 0), 2)}}
    treasury_after = dict(world.state.human.public_treasury)
    if lessor is not None:
        inventories[lessor.household_id] = {item: round(getattr(lessor, item) + (amount_due if paid else 0), 2)}
    elif paid:
        treasury_after[item] = round(float(treasury_after.get(item, 0.0)) + amount_due, 2)
    if paid:
        after.update(status="active", last_paid_tick=world.current_tick, arrears_amount=0.0,
                     next_due_tick=lease["next_due_tick"] + lease["period_days"])
    else:
        after.update(status="arrears", arrears_amount=amount_due,
                     missed_payments=int(lease.get("missed_payments", 0)) + 1,
                     next_due_tick=min(lease["expires_tick"], lease["next_due_tick"] + lease["period_days"]))
    world.event_log.append(world.current_tick, "land_rent_paid" if paid else "land_rent_missed", {
        "lease_id": lease_id, "lease_after": after, "inventories_after": inventories,
        "amount": amount_due, "item": item, "public_treasury_after": treasury_after,
    })
    for hid, values in inventories.items():
        h = _household(world, hid)
        for field, value in values.items():
            setattr(h, field, value)
    world.state.human.public_treasury = treasury_after
    lease.update(after)
    return paid

def terminate_land_lease(world, lease_id, *, reason="expired"):
    lease = world.state.human.land_leases.get(lease_id)
    if lease is None or lease["status"] not in {"active", "arrears"}:
        raise ValueError("lease is not active")
    parcel = world.state.human.land_parcels[lease["parcel_id"]]
    lessee = _household(world, lease["lessee_household_id"])
    lessor = None if lease["lessor_household_id"] == "village" else _household(world, lease["lessor_household_id"])
    item = lease["rent_item"]
    deposit = float(lease.get("deposit", 0.0))
    arrears = float(lease.get("arrears_amount", 0.0))
    applied = min(deposit, arrears)
    refund = round(deposit - applied, 2)
    inventories = {lessee.household_id: {item: round(getattr(lessee, item) + refund, 2)}}
    treasury_after = dict(world.state.human.public_treasury)
    if applied > 0:
        if lessor is not None:
            inventories[lessor.household_id] = {item: round(getattr(lessor, item) + applied, 2)}
        else:
            treasury_after[item] = round(float(treasury_after.get(item, 0.0)) + applied, 2)
    after = dict(lease, status=("expired" if reason == "expired" else "terminated"),
                 ended_tick=world.current_tick, end_reason=reason,
                 deposit=0.0, deposit_refunded=refund,
                 deposit_applied_to_arrears=applied,
                 outstanding_arrears=round(max(0.0, arrears-applied), 2))
    world.event_log.append(world.current_tick, "land_lease_terminated", {
        "lease_id": lease_id, "parcel_id": parcel.parcel_id,
        "right_id": f"lease:{lease_id}", "lease_after": after,
        "inventories_after": inventories, "public_treasury_after": treasury_after,
    })
    for hid, values in inventories.items():
        h = _household(world, hid)
        for field, value in values.items():
            setattr(h, field, value)
    world.state.human.public_treasury = treasury_after
    parcel.use_rights = [r for r in parcel.use_rights if r.right_id != f"lease:{lease_id}"]
    lease.update(after)
    return lease


def renew_land_lease(world, lease_id, *, additional_days, new_rent_per_period=None, council_decision_id=None):
    """Renew an unexpired lease; collective land requires a matching council approval."""
    lease = world.state.human.land_leases.get(lease_id)
    if lease is None or lease["status"] != "active" or world.current_tick >= lease["expires_tick"]:
        raise ValueError("only an active, unexpired lease can be renewed")
    if additional_days < 1 or (new_rent_per_period is not None and new_rent_per_period < 0):
        raise ValueError("invalid renewal terms")
    parcel = world.state.human.land_parcels[lease["parcel_id"]]
    if lease["lessor_household_id"] == "village":
        decision = world.state.human.council_decisions.get(council_decision_id or "")
        expected = f"lease:{parcel.parcel_id}:{lease['lessee_household_id']}"
        if decision is None or decision.status != "approved" or decision.subject != expected:
            raise ValueError("collective lease renewal requires matching council approval")
    after = dict(lease, expires_tick=int(lease["expires_tick"])+int(additional_days),
                 renewal_count=int(lease.get("renewal_count", 0))+1)
    if new_rent_per_period is not None:
        after["rent_per_period"] = float(new_rent_per_period)
    world.event_log.append(world.current_tick, "land_lease_renewed", {
        "lease_id": lease_id, "lease_after": after, "council_decision_id": council_decision_id,
    })
    lease.update(after)
    for right in parcel.use_rights:
        if right.right_id == f"lease:{lease_id}":
            right.expires_tick = after["expires_tick"]
    return lease

def settle_due_leases(world):
    results = []
    for lease_id in sorted(world.state.human.land_leases):
        lease = world.state.human.land_leases[lease_id]
        if lease["status"] not in {"active", "arrears"}:
            continue
        if world.current_tick >= lease["expires_tick"]:
            while lease["status"] in {"active", "arrears"} and lease["next_due_tick"] <= lease["expires_tick"] and world.current_tick >= lease["next_due_tick"]:
                results.append(settle_land_rent(world, lease_id))
            results.append(terminate_land_lease(world, lease_id))
        elif world.current_tick >= lease["next_due_tick"]:
            results.append(settle_land_rent(world, lease_id))
    return results

def settle_household_trade(world, trade_id, *, seller_household_id, buyer_household_id,
                           item, quantity, unit_price, payment_item="coin"):
    seller, buyer = _household(world, seller_household_id), _household(world, buyer_household_id)
    goods = {"grain", "meat", "fish", "vegetable", "cloth", "firewood", "herbs", "hardwood"}
    if seller_household_id == buyer_household_id or item not in goods or payment_item not in {"coin", "grain"} or item == payment_item:
        raise ValueError("invalid trade parties or commodities")
    if quantity <= 0 or unit_price < 0:
        raise ValueError("quantity must be positive and price non-negative")
    total = round(quantity * unit_price, 2)
    if getattr(seller, item) + 1e-9 < quantity or getattr(buyer, payment_item) + 1e-9 < total:
        raise ValueError("insufficient inventory to settle trade")
    inventories = {
        seller_household_id: {item: round(getattr(seller, item)-quantity, 2), payment_item: round(getattr(seller, payment_item)+total, 2)},
        buyer_household_id: {item: round(getattr(buyer, item)+quantity, 2), payment_item: round(getattr(buyer, payment_item)-total, 2)},
    }
    world.event_log.append(world.current_tick, "household_trade_settled", {
        "trade_id": trade_id, "seller_household_id": seller_household_id,
        "buyer_household_id": buyer_household_id, "item": item, "quantity": quantity,
        "payment_item": payment_item, "total_paid": total, "inventories_after": inventories,
    })
    for hid, values in inventories.items():
        h = _household(world, hid)
        for field, value in values.items():
            setattr(h, field, value)
    return {"trade_id": trade_id, "quantity": quantity, "total_paid": total}

def _storage_access(building, household_id):
    return ((building.owner_type == "household" and building.owner_id == household_id)
            or household_id in building.attributes.get("shared_with_household_ids", []))

def deposit_shared_storage(world, building_id, household_id, *, item, quantity):
    building, household = world.state.human.buildings.get(building_id), _household(world, household_id)
    if building is None or building.building_type != "storehouse" or building.status not in {"active", "occupied"} or not _storage_access(building, household_id):
        raise ValueError("active storehouse access is required")
    goods = {"grain", "meat", "fish", "vegetable", "cloth", "firewood", "herbs", "hardwood"}
    if item not in goods or quantity <= 0 or getattr(household, item) + 1e-9 < quantity:
        raise ValueError("invalid deposit or insufficient household inventory")
    stored = dict(building.stored_inventory)
    balances = dict(building.depositor_balances)
    capacity = float(building.attributes.get("storage_capacity", 120.0))
    if sum(float(v) for v in stored.values()) + quantity > capacity + 1e-9:
        raise ValueError("storehouse capacity exceeded")
    stored[item] = round(float(stored.get(item, 0))+quantity, 2)
    key = f"{household_id}:{item}"
    balances[key] = round(float(balances.get(key, 0))+quantity, 2)
    inv = {item: round(getattr(household, item)-quantity, 2)}
    world.event_log.append(world.current_tick, "shared_storage_deposit", {
        "building_id": building_id, "household_id": household_id, "stored_inventory_after": stored,
        "depositor_balances_after": balances, "household_inventory_after": inv,
    })
    building.stored_inventory, building.depositor_balances = stored, balances
    setattr(household, item, inv[item])
    return stored[item]

def withdraw_shared_storage(world, building_id, household_id, *, item, quantity):
    building, household = world.state.human.buildings.get(building_id), _household(world, household_id)
    if building is None or building.building_type != "storehouse" or building.status not in {"active", "occupied"} or not _storage_access(building, household_id):
        raise ValueError("active storehouse access is required")
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    stored = dict(building.stored_inventory)
    balances = dict(building.depositor_balances)
    key = f"{household_id}:{item}"
    if item not in stored or float(balances.get(key, 0)) + 1e-9 < quantity or float(stored[item]) + 1e-9 < quantity:
        raise ValueError("withdrawal exceeds this household's deposit")
    stored[item] = round(float(stored[item])-quantity, 2)
    balances[key] = round(float(balances[key])-quantity, 2)
    inv = {item: round(getattr(household, item)+quantity, 2)}
    world.event_log.append(world.current_tick, "shared_storage_withdrawal", {
        "building_id": building_id, "household_id": household_id, "stored_inventory_after": stored,
        "depositor_balances_after": balances, "household_inventory_after": inv,
    })
    building.stored_inventory, building.depositor_balances = stored, balances
    setattr(household, item, inv[item])
    return inv[item]

def enqueue_service_request(world, request_id, *, node_id, service, household_id, requested_units=1.0):
    _household(world, household_id)
    if requested_units <= 0:
        raise ValueError("requested_units must be positive")
    key = f"{node_id}:{service}"
    queue = deepcopy(world.state.human.service_queues.get(key) or {
        "node_id": node_id, "service": service, "requests": [], "served_units": 0.0,
    })
    if any(r["request_id"] == request_id for r in queue["requests"]):
        raise ValueError("duplicate service request")
    entry = {"request_id": request_id, "household_id": household_id,
             "requested_units": float(requested_units), "queued_tick": world.current_tick}
    queue["requests"].append(entry)
    world.event_log.append(world.current_tick, "service_request_queued", {"queue_key": key, "queue_after": queue, "request": entry})
    world.state.human.service_queues[key] = queue
    return {"position": len(queue["requests"]), "estimated_wait_ticks": len(queue["requests"])-1}

def process_service_queue(world, *, node_id, service, capacity_units):
    if capacity_units < 0:
        raise ValueError("capacity_units must be non-negative")
    key = f"{node_id}:{service}"
    queue = deepcopy(world.state.human.service_queues.get(key) or {
        "node_id": node_id, "service": service, "requests": [], "served_units": 0.0,
    })
    remaining, served = float(capacity_units), []
    for request in queue["requests"]:
        if remaining <= 1e-9:
            break
        amount = min(float(request["requested_units"]), remaining)
        request["requested_units"] = round(float(request["requested_units"])-amount, 4)
        remaining = round(remaining-amount, 4)
        if amount > 0:
            served.append({"request_id": request["request_id"], "household_id": request["household_id"], "units": amount,
                           "wait_ticks": world.current_tick-int(request["queued_tick"])})
    queue["requests"] = [r for r in queue["requests"] if float(r["requested_units"]) > 1e-9]
    queue["served_units"] = round(float(queue.get("served_units", 0))+sum(x["units"] for x in served), 4)
    world.event_log.append(world.current_tick, "service_queue_processed", {"queue_key": key, "queue_after": queue, "served": served})
    world.state.human.service_queues[key] = queue
    return served

class TenancyEconomyModule:
    """Daily settlement hook for leases and configured service queues."""
    name = "tenancy_economy"
    phase = PHASE_SOCIETY
    depends_on = []

    def step(self, world):
        settle_due_leases(world)
        settle_due_resource_loans(world)
        tuning = getattr(getattr(world.config, "agents", None), "tuning", None)
        capacities = getattr(getattr(tuning, "environment", None), "service_capacity_by_node", {}) or {}
        for key in sorted(world.state.human.service_queues):
            queue = world.state.human.service_queues[key]
            node_id, service = queue.get("node_id"), queue.get("service")
            capacity = (capacities.get(node_id) or {}).get(service)
            if capacity is not None and queue.get("requests"):
                process_service_queue(world, node_id=node_id, service=service, capacity_units=float(capacity))

def lend_household_goods(world, loan_id, *, lender_household_id, borrower_household_id,
                         item, quantity, repayment_quantity, due_tick):
    """Transfer goods as a tracked in-kind loan, not an unrecorded gift."""
    lender, borrower = _household(world, lender_household_id), _household(world, borrower_household_id)
    goods = {"grain", "meat", "fish", "vegetable", "cloth", "firewood", "herbs", "hardwood"}
    if loan_id in world.state.human.resource_loans or lender_household_id == borrower_household_id:
        raise ValueError("duplicate loan id or identical households")
    if item not in goods or quantity <= 0 or repayment_quantity < quantity or due_tick <= world.current_tick:
        raise ValueError("invalid in-kind loan terms")
    if getattr(lender, item) + 1e-9 < quantity:
        raise ValueError("lender lacks the goods")
    inventories = {
        lender_household_id: {item: round(getattr(lender, item)-quantity, 2)},
        borrower_household_id: {item: round(getattr(borrower, item)+quantity, 2)},
    }
    loan = {
        "loan_id": loan_id, "lender_household_id": lender_household_id,
        "borrower_household_id": borrower_household_id, "item": item,
        "principal": float(quantity), "repayment_due": float(repayment_quantity),
        "repaid": 0.0, "due_tick": int(due_tick), "status": "active",
        "created_tick": world.current_tick,
    }
    world.event_log.append(world.current_tick, "resource_loan_created", {
        "loan": loan, "inventories_after": inventories,
    })
    for hid, values in inventories.items():
        h = _household(world, hid)
        for field, value in values.items():
            setattr(h, field, value)
    world.state.human.resource_loans[loan_id] = loan
    return loan

def repay_household_goods(world, loan_id, *, quantity):
    """Repay an in-kind loan partially or fully; lender receives actual goods."""
    loan = world.state.human.resource_loans.get(loan_id)
    if loan is None or loan["status"] not in {"active", "overdue"}:
        raise ValueError("resource loan is not outstanding")
    if quantity <= 0:
        raise ValueError("repayment quantity must be positive")
    borrower = _household(world, loan["borrower_household_id"])
    lender = _household(world, loan["lender_household_id"])
    remaining = round(float(loan["repayment_due"])-float(loan["repaid"]), 2)
    if quantity > remaining + 1e-9 or getattr(borrower, loan["item"]) + 1e-9 < quantity:
        raise ValueError("repayment exceeds outstanding balance or borrower inventory")
    inventories = {
        borrower.household_id: {loan["item"]: round(getattr(borrower, loan["item"])-quantity, 2)},
        lender.household_id: {loan["item"]: round(getattr(lender, loan["item"])+quantity, 2)},
    }
    after = dict(loan, repaid=round(float(loan["repaid"])+quantity, 2))
    after["status"] = "repaid" if after["repaid"] + 1e-9 >= after["repayment_due"] else ("overdue" if world.current_tick > loan["due_tick"] else "active")
    world.event_log.append(world.current_tick, "resource_loan_repaid", {
        "loan_id": loan_id, "loan_after": after, "inventories_after": inventories,
        "quantity": quantity,
    })
    for hid, values in inventories.items():
        h = _household(world, hid)
        for field, value in values.items():
            setattr(h, field, value)
    loan.update(after)
    return loan


def settle_due_resource_loans(world):
    """Mark overdue in-kind obligations once, without repeatedly emitting events."""
    changed = []
    for loan_id in sorted(world.state.human.resource_loans):
        loan = world.state.human.resource_loans[loan_id]
        if loan["status"] == "active" and world.current_tick > int(loan["due_tick"]):
            after = dict(loan, status="overdue", overdue_tick=world.current_tick)
            world.event_log.append(world.current_tick, "resource_loan_overdue", {
                "loan_id": loan_id, "loan_after": after,
            })
            loan.update(after)
            changed.append(loan_id)
    return changed
